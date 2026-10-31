"""The Vertex AI Gemini adapter (decision 032, exploratory only): the model interface of decision 020 §6 over the Google Gen
AI SDK. A scripted `call` stands in for Vertex AI; no test reaches the network or spends anything."""

import json

import pytest
from google.genai import errors, types

from agent.harness import CallError
from eval.runner import RETRYABLE
from ollama_fixtures import ANSWER

MODEL = "gemini-test"
VERSION = "gemini-test-001"
SIG = "c2lnbmF0dXJl"  # base64 of b"signature"


def part_call(name, args, *, sig=None, call_id=None):
    part = {"function_call": {"name": name, "args": args, **({"id": call_id} if call_id else {})}}
    return {**part, **({"thought_signature": sig} if sig else {})}


def response(*parts, finish="STOP", prompt=1000, cached=0, candidates=20, thoughts=50, version=VERSION, **extra):
    usage = {"prompt_token_count": prompt, "candidates_token_count": candidates, "thoughts_token_count": thoughts,
             "total_token_count": prompt + candidates + thoughts, **({"cached_content_token_count": cached} if cached else {})}
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}, "finish_reason": finish}],
            "usage_metadata": usage, "model_version": version, **extra}


class Scripted:
    """Answers each request with the next scripted reply; an exception in the script is raised instead."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, request):
        self.requests.append(request)
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item(request) if callable(item) else item


def model(call, **kw):
    from agent.gemini import GeminiModel

    settings = {"thinking_level": "LOW", "temperature": 0, "seed": 42, "max_output_tokens": 32_768,
                "sleep": lambda s: None}
    return GeminiModel(MODEL, call=call, **{**settings, **kw})


TOOL = {"name": "search_spans", "description": "find spans", "input_schema": {"type": "object", "properties": {}}}
USER = [{"role": "user", "content": [{"type": "text", "text": "task"}]}]


def test_messages_become_gemini_contents_with_signatures_ids_and_function_responses():
    from agent.gemini import to_gemini_contents

    messages = [
        {"role": "user", "content": [{"type": "text", "text": "task"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "look", "thought_signature": SIG},
            {"type": "tool_use", "id": "toolu_000_0", "name": "search_spans", "input": {"status": "error"}, "call_id": "c1"},
            {"type": "tool_use", "id": "toolu_000_1", "name": "list_services", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_000_0", "content": "3 spans"},
            {"type": "tool_result", "tool_use_id": "toolu_000_1", "is_error": True, "content": "error: no more tool calls"},
            {"type": "text", "text": "submit now"}]},
        {"role": "user", "content": "plain string"},
    ]
    assert to_gemini_contents(messages) == [
        {"role": "user", "parts": [{"text": "task"}]},
        {"role": "model", "parts": [
            {"text": "look", "thought_signature": SIG},
            {"function_call": {"name": "search_spans", "args": {"status": "error"}, "id": "c1"}},
            {"function_call": {"name": "list_services", "args": {}}}]},
        {"role": "user", "parts": [  # consecutive user messages are one turn
            {"function_response": {"name": "search_spans", "response": {"output": "3 spans"}, "id": "c1"}},
            {"function_response": {"name": "list_services", "response": {"error": "error: no more tool calls"}}},
            {"text": "submit now"}, {"text": "plain string"}]},
    ]
    with pytest.raises(ValueError, match="unknown tool_use id"):
        to_gemini_contents([{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": ""}]}])


def test_an_empty_reply_leaves_no_empty_model_turn():
    """A reply without parts (a malformed function call) is kept in the transcript as an empty assistant message, but
    Gemini refuses a turn without parts: it is left out and the user turns around it become one."""
    from agent.gemini import to_gemini_contents

    messages = [*USER, {"role": "assistant", "content": []},
                {"role": "user", "content": [{"type": "text", "text": "Continue"}]}]
    assert to_gemini_contents(messages) == [{"role": "user", "parts": [{"text": "task"}, {"text": "Continue"}]}]


def test_tools_become_function_declarations_with_the_json_schema_as_given():
    from agent.gemini import to_function_declarations
    from agent.harness import api_tools

    assert to_function_declarations([TOOL]) == [{"name": "search_spans", "description": "find spans",
                                                 "parameters_json_schema": {"type": "object", "properties": {}}}]
    submit = next(t for t in api_tools() if t["name"] == "submit_diagnosis")
    assert to_function_declarations([submit])[0]["parameters_json_schema"] == submit["input_schema"]  # unchanged


def test_the_request_is_valid_for_the_sdk_and_carries_the_settings():
    from agent.harness import api_tools

    m = model(Scripted())
    request = m.request("system text", USER, api_tools())
    assert request["model"] == MODEL
    config = request["config"]
    assert config["system_instruction"] == "system text"
    assert (config["temperature"], config["seed"], config["max_output_tokens"]) == (0, 42, 32_768)
    assert config["thinking_config"] == {"thinking_level": "LOW"}
    assert config["automatic_function_calling"] == {"disable": True}  # the harness runs the tools, never the SDK
    assert [d["name"] for d in config["tools"][0]["function_declarations"]] == [t["name"] for t in api_tools()]
    types.GenerateContentConfig.model_validate(config)  # the shapes the SDK accepts (no network)
    for content in request["contents"]:
        types.Content.model_validate(content)
    unset = model(Scripted(), temperature=None, seed=None).request("", USER, [])["config"]
    assert "temperature" not in unset and "seed" not in unset and "tools" not in unset  # None: the model's default


def test_a_reply_becomes_content_blocks_with_deterministic_ids_and_usage():
    call = Scripted(response({"text": "looking", "thought_signature": SIG},
                             part_call("search_spans", {"status": "error"}, sig=SIG, call_id="c9"),
                             part_call("submit_diagnosis", ANSWER),
                             prompt=1200, cached=1000, candidates=30, thoughts=70))
    out = model(call).complete("sys", USER, [TOOL])
    assert out["content"] == [
        {"type": "text", "text": "looking", "thought_signature": SIG},
        {"type": "tool_use", "id": "toolu_000_0", "name": "search_spans", "input": {"status": "error"},
         "thought_signature": SIG, "call_id": "c9"},
        {"type": "tool_use", "id": "toolu_000_1", "name": "submit_diagnosis", "input": ANSWER}]
    assert out["stop_reason"] == "tool_use"
    assert out["usage"] == {"input_tokens": 1200, "output_tokens": 100}  # output = answer + thinking tokens
    assert out["gemini"] == {"model_version": VERSION, "finish_reason": "STOP", "prompt": 1200, "cached": 1000,
                             "candidates": 30, "thoughts": 70}


def test_thought_parts_become_thinking_blocks_and_round_trip():
    from agent.gemini import to_gemini_contents

    out = model(Scripted(response({"text": "plan", "thought": True, "thought_signature": SIG}, {"text": "answer"})))\
        .complete("", USER, [])
    assert out["content"] == [{"type": "thinking", "thinking": "plan", "thought_signature": SIG},
                              {"type": "text", "text": "answer"}]
    assert out["stop_reason"] == "end_turn"
    back = to_gemini_contents([*USER, {"role": "assistant", "content": out["content"]}])[1]
    assert back == {"role": "model", "parts": [{"text": "plan", "thought": True, "thought_signature": SIG},
                                               {"text": "answer"}]}


def test_turn_numbers_follow_the_assistant_messages():
    messages = [*USER, {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
                {"role": "user", "content": [{"type": "text", "text": "go on"}]}]
    out = model(Scripted(response(part_call("search_spans", {})))).complete("", messages, [TOOL])
    assert out["content"][0]["id"] == "toolu_001_0"


def test_stop_reasons_for_the_output_limit_and_a_malformed_call():
    m = model(Scripted(response({"text": "partial"}, finish="MAX_TOKENS"), response(finish="MALFORMED_FUNCTION_CALL")))
    first = m.complete("", USER, [TOOL])
    assert (first["content"], first["stop_reason"]) == ([{"type": "text", "text": "partial"}], "max_tokens")
    second = m.complete("", USER, [TOOL])  # no valid call: an empty reply the harness answers like any other
    assert (second["content"], second["stop_reason"]) == ([], "end_turn")
    assert [c["finish_reason"] for c in m.calls] == ["MAX_TOKENS", "MALFORMED_FUNCTION_CALL"]


@pytest.mark.parametrize("reply", [
    response({"text": "x"}, finish="SAFETY"),
    response(finish="PROHIBITED_CONTENT"),
    {"prompt_feedback": {"block_reason": "SAFETY"}, "usage_metadata": {"prompt_token_count": 10}, "model_version": VERSION},
])
def test_a_blocked_prompt_or_reply_is_a_model_failure_that_is_never_retried(reply):
    from agent.gemini import BLOCKED

    m = model(Scripted(reply))
    with pytest.raises(CallError) as e:
        m.complete("", USER, [])
    assert e.value.reason == BLOCKED and BLOCKED not in RETRYABLE
    assert len(m.calls) == 1  # the blocked call is in the ledger: its tokens are billed


def api_error(code, status="X"):
    return errors.APIError(code, {"error": {"code": code, "message": f"m{code}", "status": status}})


def test_rate_limits_and_server_errors_are_retried_within_the_call_then_reported():
    slept = []
    m = model(Scripted(api_error(429, "RESOURCE_EXHAUSTED"), api_error(503), response({"text": "ok"})),
              sleep=slept.append)
    assert m.complete("", USER, [])["content"] == [{"type": "text", "text": "ok"}]
    assert len(slept) == 2 and m.calls[-1]["retries"] == 2
    from agent.gemini import CALL_RETRIES

    m = model(Scripted(*[api_error(500)] * (CALL_RETRIES + 1)))
    with pytest.raises(CallError) as e:
        m.complete("", USER, [])
    assert e.value.reason == "api_error" and "500" in e.value.detail
    assert m.calls == []  # no reply came back: nothing billed


def test_a_bad_request_stops_at_once_and_is_not_retryable():
    m = model(Scripted(api_error(400, "INVALID_ARGUMENT")))
    with pytest.raises(CallError) as e:
        m.complete("", USER, [])
    assert e.value.reason == "bad_request" and "bad_request" not in RETRYABLE


def test_auth_errors_are_api_errors_without_waiting():
    slept = []
    m = model(Scripted(api_error(403, "PERMISSION_DENIED")), sleep=slept.append)
    with pytest.raises(CallError) as e:
        m.complete("", USER, [])
    assert e.value.reason == "api_error" and slept == []


def test_connection_failures_are_transport_errors_and_timeouts_are_not_waited_for_again():
    import httpx

    m = model(Scripted(ConnectionResetError("reset"), response({"text": "ok"})))
    assert m.complete("", USER, [])["content"][0]["text"] == "ok"
    slept = []
    m = model(Scripted(httpx.ReadTimeout("slow")), sleep=slept.append)
    with pytest.raises(CallError) as e:
        m.complete("", USER, [])
    assert e.value.reason == "transport_error" and slept == []


def test_the_model_version_is_pinned():
    from agent.gemini import PIN_MISMATCH

    m = model(Scripted(response({"text": "a"}), response({"text": "b"}, version="gemini-test-002")))
    m.complete("", USER, [])
    assert m.model_version == VERSION
    with pytest.raises(CallError) as e:
        m.complete("", USER, [])
    assert e.value.reason == PIN_MISMATCH and PIN_MISMATCH not in RETRYABLE
    m = model(Scripted(response({"text": "a"})), expected_version="gemini-test-000")
    with pytest.raises(CallError, match="gemini-test-000"):
        m.complete("", USER, [])
    m = model(Scripted(response({"text": "a"}, version=None)))
    with pytest.raises(CallError) as e:
        m.complete("", USER, [])
    assert e.value.reason == PIN_MISMATCH  # a reply that does not say its version cannot be shown to be pinned


def test_call_cost_separates_cached_input_and_counts_thinking_as_output():
    from agent.gemini import call_cost

    price = {"input": 2.0, "cached_input": 0.1, "output": 10.0}
    usage = {"prompt": 1_000_000, "cached": 800_000, "candidates": 100_000, "thoughts": 100_000}
    assert call_cost(usage, price) == pytest.approx(0.2 * 2.0 + 0.8 * 0.1 + 0.2 * 10.0)


def test_the_harness_runs_an_investigation_through_the_adapter(tmp_path):
    from agent.harness import investigate
    from test_agent_tools import Snap

    def answer(request):
        names = [d["name"] for d in request["config"]["tools"][0]["function_declarations"]]
        assert "submit_diagnosis" in names
        if any("function_response" in p for c in request["contents"] for p in c["parts"]):
            return response(part_call("submit_diagnosis", ANSWER, sig=SIG))
        return response(part_call("search_spans", {"status": "error", "limit": 5}, sig=SIG))

    call = Scripted(answer, answer)
    pred, transcript = investigate(Snap(), "INC-001", model(call), cache_root=tmp_path,
                                   method={"name": "agent", "version": "1"}, max_turns=5)
    assert transcript["stop_reason"] == "submitted"
    assert pred["origin_candidates"] == ["payment", "checkout"]
    second = call.requests[1]["contents"]
    assert second[1]["parts"][0]["thought_signature"] == SIG  # the model's signature goes back unchanged
    assert json.dumps(transcript)  # the transcript stays JSON
