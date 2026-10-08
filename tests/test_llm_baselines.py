"""Dump-all and retrieval baselines (decision 021) with a scripted model: packing, retrieval, shared submission rules."""

import re

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
