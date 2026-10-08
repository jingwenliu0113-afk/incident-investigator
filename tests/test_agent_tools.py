"""Agent tools v1 (decisions 011 §5, 019): data access over the frozen snapshot, metered, with an exposure log."""

import re

import pytest

from agent.tools import MAX_LIMIT, TOOL_SPECS, ToolSession, build_index
from collect.policy import load_policy
from collect.snapshot import proxy_tokens

S = 10**9
W0 = 1_791_460_000 * S
SCOPE = {"name": "github.com/open-telemetry/opentelemetry-collector-contrib/receiver/dockerstatsreceiver"}


def hexid(kind, i):
    return f"{kind}-{i:016x}"


def span(i, t, service, name="GET /x", status="unset", dur_ms=10, trace="a" * 32, message=None, kind="server"):
    return {"id": hexid("s", i), "trace_id": trace, "span_id": f"{i:016x}", "service": service, "name": name, "kind": kind,
            "start_time_unix_nano": W0 + t * S, "end_time_unix_nano": W0 + t * S + dur_ms * 10**6,
            "status_code": status, "status_message": message, "events": []}


def log(i, t, service, body, severity=9):
    return {"id": hexid("l", i), "service": service, "time_unix_nano": W0 + t * S, "observed_time_unix_nano": None,
            "severity_number": severity, "body": body, "event_name": None}


class Snap:
    def __init__(self, sha="sha256:" + "1" * 64):
        self.meta = {"content_sha256": sha, "window": {"start_ns": W0, "end_ns": W0 + 1800 * S},
                     "services": ["cart", "checkout", "payment"]}
        self._spans = [span(1, 30, "payment"), span(2, 700, "payment", status="error", message="Payment Request Failed"),
                       span(3, 701, "checkout", name="PlaceOrder", status="error", dur_ms=900, trace="b" * 32),
                       span(4, 702, "payment", name="Charge", dur_ms=5, trace="b" * 32, kind="internal")]
        self._logs = [log(5, 40, "cart", "cache hit"), log(6, 705, "payment", "charge failed: invalid token", severity=17)]
        self._series = [{"id": "m-" + "c" * 16, "service": "payment", "metric": "container.cpu.usage.total", "kind": "sum",
                         "unit": "ns", "scope": SCOPE, "monotonic": True, "temporality": "cumulative", "attributes": {}},
                        {"id": "m-" + "d" * 16, "service": "cart", "metric": "app.cart.items", "kind": "gauge", "unit": "1",
                         "scope": {"name": "app"}, "monotonic": None, "temporality": None, "attributes": {}}]
        self._points = [{"id": hexid("p", 10 + k), "series_id": "m-" + "c" * 16, "service": "payment",
                         "metric": "container.cpu.usage.total", "kind": "sum", "start_time_unix_nano": W0,
                         "time_unix_nano": W0 + k * 30 * S, "value": k * 3 * S, "first_in_window": k == 0} for k in range(4)]
        self.builds = 0

    @property
    def window(self):
        return self.meta["window"]

    @property
    def services(self):
        return self.meta["services"]

    def spans(self):
        self.builds += 1
        return iter(self._spans)

    def logs(self):
        return iter(self._logs)

    def series(self):
        return iter(self._series)

    def points(self):
        return iter(self._points)


@pytest.fixture
def session(tmp_path):
    return ToolSession(Snap(), cache_root=tmp_path / "cache")


def ids(text):
    """The record ids that start the lines of a tool answer (render v1 puts the id first)."""
    return re.findall(r"^([slmp]-[0-9a-f]{16}) ", text, re.MULTILINE)


def test_the_index_is_cached_by_content_digest_and_rebuilt_when_it_differs(tmp_path):
    snap = Snap()
    path = build_index(snap, tmp_path / "cache")
    assert path == tmp_path / "cache" / ("1" * 64) / "index.sqlite" and path.exists()
    before = snap.builds
    assert build_index(snap, tmp_path / "cache") == path and snap.builds == before  # cached
    other = Snap(sha="sha256:" + "2" * 64)
    assert build_index(other, tmp_path / "cache") != path


def test_search_spans_filters_orders_by_time_and_pages(session):
    out = session.call("search_spans", {"service": "payment"})
    assert out.splitlines()[0] == "3 spans match; showing 1-3" and ids(out) == [hexid("s", 1), hexid("s", 2), hexid("s", 4)]
    assert ids(session.call("search_spans", {"status": "error"})) == [hexid("s", 2), hexid("s", 3)]
    assert ids(session.call("search_spans", {"min_duration_ms": 100})) == [hexid("s", 3)]
    assert ids(session.call("search_spans", {"t0": 600, "t1": 701})) == [hexid("s", 2)]  # [t0, t1) in seconds from the start
    assert ids(session.call("search_spans", {"text": "payment request"})) == [hexid("s", 2)]  # case-insensitive, on the line
    page = session.call("search_spans", {"limit": 1, "offset": 1})
    assert page.splitlines()[0] == "4 spans match; showing 2-2" and ids(page) == [hexid("s", 2)]
    assert "+011:40.000" in session.call("search_spans", {"status": "error", "limit": 1})  # times as render v1 writes them


def test_logs_traces_series_points_and_services(session):
    assert ids(session.call("search_logs", {"min_severity": 13})) == [hexid("l", 6)]
    assert ids(session.call("search_logs", {"text": "CACHE"})) == [hexid("l", 5)]
    assert ids(session.call("search_logs", {"text": "invalid_token"})) == []  # _ is literal, not a wildcard
    assert ids(session.call("search_logs", {"text": "charge failed: invalid"})) == [hexid("l", 6)]
    assert ids(session.call("get_trace", {"trace_id": "b" * 32})) == [hexid("s", 3), hexid("s", 4)]
    assert ids(session.call("list_series", {"text": "cpu"})) == ["m-" + "c" * 16]
    assert ids(session.call("get_points", {"series_id": "m-" + "c" * 16, "t0": 30, "t1": 90})) == [hexid("p", 11), hexid("p", 12)]
    services = session.call("list_services", {})
    assert "payment spans=3 logs=1 series=1" in services and "cart spans=0 logs=1 series=1" in services


def test_service_minute_stats_is_one_service_per_call_with_the_derived_definitions(session):
    out = session.call("service_minute_stats", {"service": "payment"})
    lines = out.splitlines()
    assert lines[0].startswith("payment per minute")
    assert any(line.startswith("+011:00 spans=2 errors=1") for line in lines)
    assert any("cpu_cores=0.1" in line for line in lines)  # 3 s of CPU per 30 s
    assert "error: service" in session.call("service_minute_stats", {})


def test_limits_bad_arguments_and_the_budget(tmp_path):
    s = ToolSession(Snap(), cache_root=tmp_path / "cache", max_calls=3)
    assert MAX_LIMIT == 50
    assert s.call("search_spans", {"limit": 500}).splitlines()[0] == "4 spans match; showing 1-4"  # capped, not refused
    assert s.call("nope", {}).startswith("error: unknown tool")
    assert s.call("search_spans", {"status": "broken"}).startswith("error:")
    assert s.call("search_spans", {}).startswith("error: budget")  # unknown tools and bad arguments still count as calls
    assert s.usage["tool_calls"] == 3

    s = ToolSession(Snap(), cache_root=tmp_path / "cache", max_proxy_tokens=10)
    first = s.call("search_spans", {})
    assert s.usage["proxy_tokens"] == proxy_tokens(first) > 10
    assert s.call("search_logs", {}).startswith("error: budget") and s.usage["tool_calls"] == 1  # a refusal is not a call


def test_the_exposure_log_lists_each_shown_record_once_in_order(session):
    session.call("search_spans", {"status": "error"})
    session.call("search_spans", {"service": "payment"})
    session.call("get_trace", {"trace_id": "b" * 32})
    assert session.exposure == [hexid("s", 2), hexid("s", 3), hexid("s", 1), hexid("s", 4)]


def test_tool_descriptions_do_not_describe_the_collection_and_pass_the_lexicon():
    policy = load_policy()
    names = {t["name"] for t in TOOL_SPECS}
    assert names == {"list_services", "search_spans", "search_logs", "get_trace", "list_series", "get_points",
                     "service_minute_stats"}
    for t in TOOL_SPECS:
        text = t["description"] + str(t["parameters"])
        assert policy.lexicon_hit(text) == 0, t["name"]
        assert not re.search(r"flag|inject|chaos|anomal|rank", text, re.IGNORECASE), t["name"]
