"""Agent harness v1 (decision 020): task text, tool-use loop, checked submission, usage and transcript; a scripted model."""

import re

import pytest

from agent.harness import SUBMIT_SPEC, investigate
from agent.prompt import FRAMING, task_prompt
from collect.policy import load_policy
from eval.score import check_prediction
from test_agent_tools import Snap, hexid

ANSWER = {"fault": {"fault_type": "error_response", "fault_family": "error"}, "origin_candidates": ["payment", "checkout"],
          "affected_services": ["payment", "checkout"], "user_symptom": {"kinds": ["errors"]},
          "evidence": [{"id": hexid("s", 2)}]}


class Scripted:
    """A model that answers from a script; records what it was sent."""

    def __init__(self, *turns):
        self.turns, self.calls = list(turns), []

    def complete(self, system, messages, tools):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        content = self.turns.pop(0) if self.turns else [{"type": "text", "text": "thinking"}]
        return {"content": content, "usage": {"input_tokens": 100, "output_tokens": 10}}


def tool(name, args, i="t1"):
    return {"type": "tool_use", "id": i, "name": name, "input": args}


def run(tmp_path, model, **kw):
    return investigate(Snap(), "INC-001", model, cache_root=tmp_path / "cache", method={"name": "agent", "version": "1"}, **kw)


def test_a_tool_call_then_a_submission_gives_a_checked_prediction_with_usage_and_a_transcript(tmp_path):
    model = Scripted([{"type": "text", "text": "look at errors"}, tool("search_spans", {"status": "error"})],
                     [tool("submit_diagnosis", ANSWER, "t2")])
    pred, transcript = run(tmp_path, model, price_per_mtok={"input": 3.0, "output": 15.0})
    assert check_prediction(pred) == [] and pred["origin_candidates"] == ["payment", "checkout"]
    assert pred["incident_id"] == "INC-001" and pred["method"] == {"name": "agent", "version": "1"}
    assert pred["usage"]["tokens_in"] == 200 and pred["usage"]["tokens_out"] == 20 and pred["usage"]["tool_calls"] == 1
    assert pred["usage"]["proxy_tokens"] > 0 and pred["usage"]["retrievals"] == 0
    assert pred["usage"]["cost_usd"] == pytest.approx((200 * 3.0 + 20 * 15.0) / 1e6)
    assert transcript["stop_reason"] == "submitted" and transcript["exposure"] == [hexid("s", 2), "t-" + "a" * 32, hexid("s", 3), "t-" + "b" * 32]
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "t1" and "2 spans match" in result["content"]
    assert {t["name"] for t in model.calls[0]["tools"]} >= {"search_spans", "submit_diagnosis"}


def test_an_invalid_submission_is_returned_for_correction_and_repeated_failure_abstains(tmp_path):
    bad = {**ANSWER, "origin_candidates": ["load-generator"]}
    pred, transcript = run(tmp_path, Scripted([tool("submit_diagnosis", bad)], [tool("submit_diagnosis", ANSWER, "t2")]))
    assert pred["origin_candidates"] == ["payment", "checkout"] and transcript["stop_reason"] == "submitted"
    assert "unknown service" in transcript["messages"][2]["content"][0]["content"]
    pred, transcript = run(tmp_path, Scripted(*[[tool("submit_diagnosis", bad, f"t{i}")] for i in range(3)]))
    assert transcript["stop_reason"] == "invalid_submission" and pred["origin_candidates"] == [] and check_prediction(pred) == []


def test_at_the_turn_limit_the_model_is_asked_to_submit_once_and_otherwise_abstains(tmp_path):
    looping = [[tool("list_services", {}, f"t{i}")] for i in range(10)]
    model = Scripted(*looping)
    pred, transcript = run(tmp_path, model, max_turns=3)
    assert transcript["stop_reason"] == "turn_limit" and pred["fault"]["fault_type"] is None and pred["affected_services"] == []
    assert len(model.calls) == 4  # three turns, then one last chance after "submit now"
    assert "submit_diagnosis now" in model.calls[3]["messages"][-1]["content"][-1]["text"]

    model = Scripted(*looping[:3], [tool("submit_diagnosis", ANSWER, "last")])
    pred, transcript = run(tmp_path, model, max_turns=3)
    assert transcript["stop_reason"] == "submitted_after_limit" and pred["origin_candidates"][0] == "payment"


def test_a_spent_tool_budget_also_asks_for_the_answer(tmp_path):
    model = Scripted([tool("list_services", {}, "a")], [tool("list_services", {}, "b")], [tool("submit_diagnosis", ANSWER, "s")])
    pred, transcript = run(tmp_path, model, max_tool_calls=2, max_turns=20)
    assert pred["usage"]["tool_calls"] == 2 and transcript["stop_reason"] == "submitted_after_limit"
    assert "submit_diagnosis now" in model.calls[2]["messages"][-1]["content"][-1]["text"]
    model = Scripted(*[[tool("list_services", {}, f"t{i}")] for i in range(4)])
    assert run(tmp_path, model, max_tool_calls=2, max_turns=20)[1]["stop_reason"] == "tool_budget"


def test_the_task_text_is_the_same_framing_for_every_method_and_says_nothing_about_the_collection():
    text = task_prompt(Snap())
    assert FRAMING == ("The system was healthy during the first 10 minutes of the time window; "
                       "at some point after that a fault may have started.")
    assert FRAMING in text and "+030:00.000" in text  # the window as render v1 writes times
    for word in ("cart", "checkout", "payment", "error_response", "unreachable_dependency", "degraded_feature"):
        assert word in text
    assert load_policy().lexicon_hit(text) == 0
    assert not re.search(r"flag|inject|chaos|run group|seed|10 minutes long|fault window", text, re.IGNORECASE)
    assert SUBMIT_SPEC["name"] == "submit_diagnosis" and load_policy().lexicon_hit(str(SUBMIT_SPEC)) == 0


def test_impossible_evidence_times_are_a_correctable_problem_not_a_crash(tmp_path):
    bad = {**ANSWER, "evidence": [{"id": "m-" + "c" * 16, "t0": "1e400", "t1": float("inf")}]}
    pred, transcript = run(tmp_path, Scripted([tool("submit_diagnosis", bad)], [tool("submit_diagnosis", ANSWER, "t2")]))
    assert transcript["stop_reason"] == "submitted" and pred["evidence"] == [{"id": hexid("s", 2)}]


def test_every_tool_use_in_a_turn_gets_its_own_result(tmp_path):
    # the Messages API rejects a request whose previous turn has a tool_use without a tool_result
    from agent.harness import submit_round

    model = Scripted([tool("submit_diagnosis", {**ANSWER, "origin_candidates": ["nope"]}, "a"),
                      tool("submit_diagnosis", {**ANSWER, "origin_candidates": ["nope"]}, "b")],
                     [tool("submit_diagnosis", ANSWER, "c"), tool("submit_diagnosis", ANSWER, "d")])
    messages = [{"role": "user", "content": [{"type": "text", "text": "go"}]}]
    pred, stop = submit_round(model, "sys", messages, Snap(), "INC-001", {"name": "m", "version": "1"}, {"input": 0, "output": 0})
    assert stop == "submitted" and pred["origin_candidates"] == ["payment", "checkout"]
    for i, m in enumerate(messages):
        if m["role"] == "assistant":
            uses = {b["id"] for b in m["content"] if b.get("type") == "tool_use"}
            answered = {b["tool_use_id"] for b in messages[i + 1]["content"] if b.get("type") == "tool_result"}
            assert uses == answered
    _, transcript = run(tmp_path, Scripted([tool("submit_diagnosis", ANSWER, "x"), tool("submit_diagnosis", ANSWER, "y")]))
    last = transcript["messages"][-1]["content"]
    assert {b["tool_use_id"] for b in last} == {"x", "y"}
