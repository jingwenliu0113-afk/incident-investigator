"""Dump-all and retrieval baselines (decision 021) with a scripted model: packing, retrieval, shared submission rules."""

import re

import pytest

from baselines.dump_all import dump_all, pack
from baselines.retrieval import retrieval, search
from collect.snapshot import proxy_tokens
from eval.score import check_prediction
from test_agent_harness import ANSWER, Scripted, tool
from test_agent_tools import Snap, hexid

METHOD = {"name": "m", "version": "1"}


def test_the_dump_puts_the_overview_then_error_groups_then_a_time_sample_within_the_budget():
    text, stats = pack(Snap(), "INC-001", budget=100_000)
    overview, errors, sample = text.index("## Per service and minute"), text.index("## Error-level records"), text.index("## Sample")
    assert overview < errors < sample
    assert "payment +011:00 spans=2 errors=1" in text
    group = text[errors:sample]
    assert "1 x payment span" in group and hexid("s", 2) in group and hexid("l", 6) in group  # spans with error, logs >= WARN
    assert hexid("s", 1) not in group and hexid("s", 1) in text[sample:]  # other records only in the sample
    assert stats["proxy_tokens"] == proxy_tokens(text) and stats["records"] >= 4
    small, s2 = pack(Snap(), "INC-001", budget=300)
    assert s2["proxy_tokens"] <= 300 and "## Sample" not in small  # cut from the end, never over the budget
    assert pack(Snap(), "INC-001", budget=100_000) == (text, stats)  # deterministic


def test_dump_all_is_one_call_with_only_the_submit_tool(tmp_path):
    model = Scripted([tool("submit_diagnosis", ANSWER)])
    pred, transcript = dump_all(Snap(), "INC-001", model, method=METHOD, budget=100_000)
    assert check_prediction(pred) == [] and transcript["stop_reason"] == "submitted" and len(model.calls) == 1
    assert [t["name"] for t in model.calls[0]["tools"]] == ["submit_diagnosis"]
    assert "## Error-level records" in model.calls[0]["messages"][0]["content"][0]["text"]
    assert pred["usage"]["tool_calls"] == 0 and pred["usage"]["retrievals"] == 0 and pred["usage"]["proxy_tokens"] > 0
    lazy = Scripted([{"type": "text", "text": "it is payment"}])
    pred, transcript = dump_all(Snap(), "INC-001", lazy, method=METHOD, budget=100_000)
    assert transcript["stop_reason"] == "no_submission" and pred["origin_candidates"] == []


def test_retrieval_ranks_by_bm25_and_filters(tmp_path):
    hits = search(Snap(), tmp_path / "cache", "payment failed", k=3)
    assert hits[0] == hexid("s", 2) or hits[0] == hexid("l", 6)  # the records with both words come first
    assert set(hits[:2]) == {hexid("s", 2), hexid("l", 6)}
    assert search(Snap(), tmp_path / "cache", "payment", service="cart", k=5) == []
    assert search(Snap(), tmp_path / "cache", "cache", k=5) == [hexid("l", 5)]
    assert set(search(Snap(), tmp_path / "cache", "payment", t0=600, t1=703, k=10)) == {hexid("s", 2), hexid("s", 4)}
    assert search(Snap(), tmp_path / "cache", "\"(*", k=5) == []  # operators are not passed to FTS5


def test_retrieval_asks_for_queries_then_answers_from_what_they_found(tmp_path):
    model = Scripted([tool("propose_queries", {"queries": [{"text": "failed"}, {"text": "cache", "service": "cart"}]})],
                     [tool("submit_diagnosis", ANSWER, "t2")])
    pred, transcript = retrieval(Snap(), "INC-001", model, method=METHOD, cache_root=tmp_path / "cache", q=8, k=5)
    assert check_prediction(pred) == [] and transcript["stop_reason"] == "submitted"
    assert [t["name"] for t in model.calls[0]["tools"]] == ["propose_queries"]
    assert [t["name"] for t in model.calls[1]["tools"]] == ["submit_diagnosis"]
    found = model.calls[1]["messages"][-1]["content"][0]["content"]
    assert re.findall(r"^([sl]-[0-9a-f]{16}) ", found, re.MULTILINE) == [hexid("l", 5), hexid("s", 2), hexid("l", 6)]  # by time
    assert pred["usage"]["retrievals"] == 2 and pred["usage"]["tool_calls"] == 0
    assert transcript["exposure"] == ["stats:*", hexid("l", 5), hexid("s", 2), hexid("l", 6)]
    many = {"queries": [{"text": f"q{i}"} for i in range(12)]}
    pred, _ = retrieval(Snap(), "INC-001", Scripted([tool("propose_queries", many)], [tool("submit_diagnosis", ANSWER, "x")]),
                        method=METHOD, cache_root=tmp_path / "cache", q=8, k=5)
    assert pred["usage"]["retrievals"] == 8  # at most q


def test_retrieval_answers_every_tool_use_survives_bad_numbers_and_rebuilds_a_broken_cache(tmp_path):
    two = Scripted([tool("propose_queries", {"queries": [{"text": "failed", "t1": 1e12}]}, "a"),
                    tool("propose_queries", {"queries": [{"text": "cache", "t0": float("inf")}, {"text": "cache"}]}, "b")],
                   [tool("submit_diagnosis", ANSWER, "c")])
    pred, transcript = retrieval(Snap(), "INC-001", two, method=METHOD, cache_root=tmp_path / "cache", q=8, k=5)
    reply = transcript["messages"][2]["content"]
    assert {b["tool_use_id"] for b in reply if b.get("type") == "tool_result"} == {"a", "b"}
    assert "skipped" in reply[0]["content"]  # bad time bounds: the query is not run, and the model is told
    assert pred["usage"]["retrievals"] == 1 and hexid("l", 5) in transcript["exposure"]  # queries of both calls count
    broken = tmp_path / "broken"
    (broken / ("1" * 64)).mkdir(parents=True)
    (broken / ("1" * 64) / "retrieval.sqlite").write_text("not a database")  # a derived cache: rebuilt, never "0 found"
    assert search(Snap(), broken, "cache", k=5) == [hexid("l", 5)]


def test_dump_all_exposure_claims_only_the_overview_rows_that_were_packed():
    model = Scripted([tool("submit_diagnosis", ANSWER)])
    _, full = dump_all(Snap(), "INC-001", model, method=METHOD, budget=100_000)
    assert full["exposure"][0] == "stats:*"
    model = Scripted([tool("submit_diagnosis", ANSWER)])
    _, cut = dump_all(Snap(), "INC-001", model, method=METHOD, budget=200)  # 60 before 021's Pilot revision (longer head)
    assert "stats:*" not in cut["exposure"] and cut["exposure"] == ["stats:checkout:11-11", "stats:payment:0-1"]
    assert all(e.startswith("stats:") and e.count(":") == 2 for e in cut["exposure"])


def _model_facing_text(calls: list[dict]) -> str:
    """Everything a model was sent: system, tool names / descriptions / schemas, and every text and tool result."""
    parts = []
    for c in calls:
        parts.append(str(c.get("system", "")))
        parts += [str(t) for t in c["tools"]]
        for m in c["messages"]:
            for b in m["content"]:
                parts.append(str(b.get("text", b.get("content", ""))))
    return "\n".join(parts)


def test_every_text_the_llm_baselines_send_passes_the_lexicon_and_says_nothing_about_the_collection(tmp_path):
    # decision 015 §6: any prompt or tool description passes the lexicon check and does not describe the collection
    from collect.policy import load_policy

    dumped = Scripted([tool("submit_diagnosis", ANSWER)])
    dump_all(Snap(), "INC-001", dumped, method=METHOD, budget=100_000)
    asked = Scripted([tool("propose_queries", {"queries": [{"text": "failed"}, {"text": "q", "t1": 1e12}]})],
                     [{"type": "text", "text": "no"}], [tool("submit_diagnosis", ANSWER, "t2")])
    retrieval(Snap(), "INC-001", asked, method=METHOD, cache_root=tmp_path / "cache", q=8, k=5)
    for model in (dumped, asked):
        text = _model_facing_text(model.calls)
        assert load_policy().lexicon_hit(text) == 0
        assert not re.search(r"flag|inject|chaos|run group|seed|fault window", text, re.IGNORECASE)


def test_dump_all_and_retrieval_attach_the_usage_so_far_to_a_failed_call(tmp_path):
    from agent.harness import CallError
    from test_agent_harness import Failing

    try:
        dump_all(Snap(), "INC-001", Failing(1), method=METHOD, budget=100_000)
    except CallError as e:
        assert e.usage["tokens_in"] == 0 and e.usage["cost_usd"] is None
    else:
        raise AssertionError("no CallError")
    model = Failing(2, [tool("propose_queries", {"queries": [{"text": "failed"}]})], reason="transport_error")
    try:
        retrieval(Snap(), "INC-001", model, method=METHOD, cache_root=tmp_path / "cache", q=8, k=5,
                  price_per_mtok={"input": 1.0, "output": 1.0})
    except CallError as e:
        assert e.reason == "transport_error" and e.usage["tokens_in"] == 100 and e.usage["tokens_out"] == 10
        assert e.usage["cost_usd"] == pytest.approx(110 / 1e6)
    else:
        raise AssertionError("no CallError")


def test_no_text_any_llm_method_sends_names_the_incident_id(tmp_path):
    # decision 023 §4: ids are assigned in collection order and slots.json is committed, so the id never reaches a model
    from agent.harness import investigate

    dumped = Scripted([tool("submit_diagnosis", ANSWER)])
    dump_all(Snap(), "INC-042", dumped, method=METHOD, budget=100_000)
    asked = Scripted([tool("propose_queries", {"queries": [{"text": "failed"}]})], [tool("submit_diagnosis", ANSWER, "t2")])
    retrieval(Snap(), "INC-042", asked, method=METHOD, cache_root=tmp_path / "cache", q=8, k=5)
    agent = Scripted([tool("search_spans", {"status": "error"})], [tool("submit_diagnosis", ANSWER, "t2")])
    investigate(Snap(), "INC-042", agent, cache_root=tmp_path / "cache", method=METHOD)
    for model in (dumped, asked, agent):
        text = _model_facing_text(model.calls)
        assert "INC-042" not in text


# ---------------------------------------------------------------- decision 021, Pilot revision (user decision 2026-10-11)

MiB = 2**20
AGENT_INPUTS_SHA256 = "2e45e45a17fd586ac90e5e1632461db59612f98d39ac8543337dcb2e479a4a82"  # before the revision, on Snap()


def _overview_before_the_revision(snapshot) -> str:
    """baselines/overview.py as it was for the original Pilot run (commit a268211), verbatim: the rows must not change."""
    from collect.derive import container_minute_stats, service_minute_stats

    def _num(x, fmt=".3f"):
        return "-" if x is None else format(x, fmt)

    spans, containers = service_minute_stats(snapshot)["services"], container_minute_stats(snapshot)["services"]
    lines = ["## Per service and minute (spans, error spans, p95 of server spans in ms, logs at WARN or above, "
             "CPU cores used, memory MiB)"]
    for svc in snapshot.services:
        s, c = spans.get(svc, {}), containers.get(svc, {})
        for minute in sorted(set(s) | set(c)):
            a, b = s.get(minute, {}), c.get(minute, {})
            mem = b.get("memory")
            lines.append(f"{svc} +{minute:03d}:00 spans={a.get('spans', 0)} errors={a.get('error_spans', 0)} "
                         f"p95_ms={_num(a.get('p95_server_ms'))} warn_logs={a.get('warn_logs', 0)} "
                         f"cpu_cores={_num(b.get('cpu'))} memory_mib={_num(None if mem is None else mem / MiB, '.1f')}")
    return "\n".join(lines)


def _synthetic_snapshot():
    from pathlib import Path

    from collect.layout import DataLayout
    from collect.snapshot import open_snapshot

    layout = DataLayout(Path(__file__).resolve().parent.parent / "data/samples/synthetic")
    return open_snapshot(layout.incident_dir("INC-000") / "normalized", layout)


def test_the_overview_says_its_rows_are_not_records_and_keeps_every_row_as_it_was():
    from baselines.overview import NOTE, overview

    for snap in (Snap(), _synthetic_snapshot()):
        old, new = _overview_before_the_revision(snap).splitlines(), overview(snap).splitlines()
        assert new == [old[0], NOTE, *old[1:]]  # the header and the rows, content and order, unchanged
    for words in ("aggregates", "not records", "no id", "cannot be cited", "s-...", "l-...", "trace_id", "m-...", "p-..."):
        assert words in NOTE
    assert "\n" not in NOTE and not re.search(r"fault|error|latency|slow|cpu|memory", NOTE, re.IGNORECASE)  # says nothing about any fault
    assert not re.search(r"[slmpt]-[0-9a-f]{16}", NOTE)  # names no id


def test_dump_all_and_retrieval_both_send_the_statement_before_the_rows(tmp_path):
    from baselines.overview import NOTE

    dumped = Scripted([tool("submit_diagnosis", ANSWER)])
    dump_all(Snap(), "INC-001", dumped, method=METHOD, budget=100_000)
    asked = Scripted([tool("propose_queries", {"queries": [{"text": "failed"}]})], [tool("submit_diagnosis", ANSWER, "t2")])
    retrieval(Snap(), "INC-001", asked, method=METHOD, cache_root=tmp_path / "cache", q=8, k=5)
    for model in (dumped, asked):
        text = model.calls[0]["messages"][0]["content"][0]["text"]
        assert text.index("## Per service and minute") < text.index(NOTE) < text.index("checkout +011:00")
        assert text.count(NOTE) == 1


def test_a_cut_dump_keeps_the_statement_with_the_header_and_claims_only_rows():
    from baselines.overview import NOTE

    full, _ = pack(Snap(), "INC-001", budget=100_000)
    for budget in range(1, proxy_tokens(full) + 50, 7):
        text, stats = pack(Snap(), "INC-001", budget=budget)
        assert stats["proxy_tokens"] <= budget
        assert ("## Per service and minute" in text) == (NOTE in text)  # the header never goes in without the statement
        assert NOTE not in stats["overview_rows"] and all(r.split(" ", 1)[0] in Snap().services for r in stats["overview_rows"])
    text, stats = pack(Snap(), "INC-001", budget=proxy_tokens(full))
    assert stats["overview_complete"] and len(stats["overview_rows"]) == 4  # the four rows; the statement is not a row
    small, cut = pack(Snap(), "INC-001", budget=150)
    assert NOTE in small and 0 < len(cut["overview_rows"]) < 4 and not cut["overview_complete"]


def test_the_agent_prompt_and_tools_are_unchanged_by_the_revision(tmp_path):
    import hashlib
    import json
    from pathlib import Path

    from agent.harness import api_tools, investigate
    from agent.prompt import SYSTEM, task_prompt
    from baselines.overview import NOTE

    agent_inputs = SYSTEM + "\n" + task_prompt(Snap()) + "\n" + json.dumps(api_tools(), sort_keys=True)
    assert hashlib.sha256(agent_inputs.encode()).hexdigest() == AGENT_INPUTS_SHA256
    for path in sorted((Path(__file__).resolve().parent.parent / "agent").glob("*.py")):
        assert "overview" not in path.read_text(), path  # the Agent never sees the overview block (decision 021 §1)
    agent = Scripted([tool("service_minute_stats", {})], [tool("submit_diagnosis", ANSWER, "t2")])
    investigate(Snap(), "INC-001", agent, cache_root=tmp_path / "cache", method=METHOD)
    assert NOTE not in _model_facing_text(agent.calls)


def test_the_revised_methods_say_their_version_and_the_agent_keeps_its_own(tmp_path):
    from eval.runner import run_llm

    config = {"budgets": {"dump_all_proxy_tokens": 100_000, "retrieval_queries": 8, "retrieval_k": 5,
                          "agent_max_turns": 30, "agent_max_tool_calls": 40, "agent_max_proxy_tokens": 100_000}}
    scripts = {"dump-all": [[tool("submit_diagnosis", ANSWER)]],
               "retrieval": [[tool("propose_queries", {"queries": [{"text": "failed"}]})], [tool("submit_diagnosis", ANSWER, "t2")]],
               "agent": [[tool("submit_diagnosis", ANSWER)]]}
    versions = {kind: run_llm(kind, Snap(), "INC-001", Scripted(*turns), config, cache_root=tmp_path / "cache")[0]["method"]
                for kind, turns in scripts.items()}
    assert versions == {"dump-all": {"name": "dump-all", "version": "2"}, "retrieval": {"name": "retrieval", "version": "2"},
                        "agent": {"name": "agent", "version": "1"}}
