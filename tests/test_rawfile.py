"""Streaming scan of raw OTLP JSON Lines files written by the collector's file exporter (decision 008)."""

import hashlib
import json

import pytest

from collect.rawfile import scan_raw_file

T0 = 1791453665_000000000  # 2026-10-08T10:01:05Z in unix nanos
MIN = 60 * 10**9


def res(service, extra=()):
    return {"attributes": [{"key": "service.name", "value": {"stringValue": service}}, *extra]}


def span(trace, span_id, start, name="GET"):
    # OTLP JSON: hex ids, int64 as decimal strings, zero values omitted
    return {"traceId": trace, "spanId": span_id, "name": name, "kind": 2,
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(start + 5_000_000), "status": {}}


def traces_line(service, spans):
    return json.dumps({"resourceSpans": [{"resource": res(service), "scopeSpans": [{"scope": {"name": "s"}, "spans": spans}]}]})


def metrics_line(service, points, name="http.server.duration", kind="sum"):
    metric = {"name": name, kind: {"dataPoints": points, **({"aggregationTemporality": 2, "isMonotonic": True} if kind == "sum" else {})}}
    return json.dumps({"resourceMetrics": [{"resource": res(service), "scopeMetrics": [{"scope": {"name": "m"}, "metrics": [metric]}]}]})


def point(t, value=1, attrs=()):
    return {"startTimeUnixNano": str(T0 - MIN), "timeUnixNano": str(t), "asInt": str(value), "attributes": list(attrs)}


def logs_line(service, records):
    return json.dumps({"resourceLogs": [{"resource": res(service), "scopeLogs": [{"scope": {}, "logRecords": records}]}]})


def write(tmp_path, name, lines, *, trailing_newline=True):
    p = tmp_path / name
    p.write_text("\n".join(lines) + ("\n" if trailing_newline else ""))
    return p


def test_traces_counts_items_services_times_and_minutes(tmp_path):
    p = write(tmp_path, "traces.jsonl", [
        traces_line("checkout", [span("a" * 32, "b" * 16, T0), span("a" * 32, "c" * 16, T0 + MIN)]),
        traces_line("frontend", [span("d" * 32, "e" * 16, T0 + 2 * MIN)]),
    ])
    s = scan_raw_file(p, "traces")
    assert s["signal"] == "traces" and s["format"] == "otlp-json-lines"
    assert s["lines"] == 2 and s["parse_errors"] == 0 and s["wrong_signal_lines"] == 0
    assert s["items"] == 3 and s["duplicates"] == 0
    assert s["by_service"] == {"checkout": 2, "frontend": 1}
    assert s["min_time"] == "2026-10-08T10:01:05Z" and s["max_time"] == "2026-10-08T10:03:05Z"
    assert s["minutes"] == ["2026-10-08T10:01", "2026-10-08T10:02", "2026-10-08T10:03"]
    assert s["bytes"] == p.stat().st_size
    assert s["sha256"] == "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    assert s["last_line_truncated"] is False


def test_resent_batches_are_counted_as_duplicates_not_items(tmp_path):
    line = traces_line("checkout", [span("a" * 32, "b" * 16, T0)])
    s = scan_raw_file(write(tmp_path, "t.jsonl", [line, line]), "traces")
    assert s["items"] == 1 and s["duplicates"] == 1  # dedupe key (traceId, spanId)


def test_metrics_count_data_points_and_dedupe_by_series_and_time(tmp_path):
    attrs = [{"key": "http.route", "value": {"stringValue": "/api/cart"}}]
    p = write(tmp_path, "m.jsonl", [
        metrics_line("cart", [point(T0, attrs=attrs), point(T0 + MIN, attrs=attrs)]),
        metrics_line("cart", [point(T0, attrs=attrs)]),  # resent
        metrics_line("cart", [point(T0, attrs=[{"key": "http.route", "value": {"stringValue": "/x"}}])]),  # other series
        metrics_line("docker", [{"timeUnixNano": str(T0), "asDouble": "NaN"}], name="container.cpu", kind="gauge"),
        metrics_line("x", [{"timeUnixNano": str(T0), "count": "3", "bucketCounts": ["1", "2"], "explicitBounds": [1.0]}],
                     name="h", kind="histogram"),
    ])
    s = scan_raw_file(p, "metrics")
    assert s["items"] == 5 and s["duplicates"] == 1
    assert s["by_service"] == {"cart": 3, "docker": 1, "x": 1}


def test_logs_use_timestamp_then_observed_timestamp_and_dedupe_by_content(tmp_path):
    rec = {"timeUnixNano": str(T0), "severityText": "INFO", "body": {"stringValue": "hello"}}
    no_ts = {"observedTimeUnixNano": str(T0 + MIN), "body": {"stringValue": "hello"}}
    same_text_other_time = {"timeUnixNano": str(T0 + 2 * MIN), "body": {"stringValue": "hello"}}
    p = write(tmp_path, "l.jsonl", [logs_line("cart", [rec, no_ts, same_text_other_time]), logs_line("cart", [rec])])
    s = scan_raw_file(p, "logs")
    assert s["items"] == 3 and s["duplicates"] == 1  # identical normal logs at other times are NOT duplicates
    assert s["minutes"] == ["2026-10-08T10:01", "2026-10-08T10:02", "2026-10-08T10:03"]


def test_broken_lines_are_reported_with_their_numbers(tmp_path):
    good = traces_line("checkout", [span("a" * 32, "b" * 16, T0)])
    p = write(tmp_path, "t.jsonl", [
        good,
        good[:-1] + traces_line("checkout", [span("a" * 32, "f" * 16, T0)]),  # two objects glued on one line
        metrics_line("cart", [point(T0)]),  # other signal in this file
        "",
        good[: len(good) // 2],  # truncated last line (SIGKILL mid-write)
    ], trailing_newline=False)
    s = scan_raw_file(p, "traces")
    assert s["lines"] == 5 and s["empty_lines"] == 1
    assert s["parse_errors"] == 2 and s["parse_error_lines"] == [2, 5]
    assert s["wrong_signal_lines"] == 1
    assert s["last_line_truncated"] is True
    assert s["items"] == 1


def test_empty_file_and_unknown_signal(tmp_path):
    s = scan_raw_file(write(tmp_path, "e.jsonl", [], trailing_newline=False), "logs")
    assert s["lines"] == 0 and s["items"] == 0 and s["min_time"] is None and s["minutes"] == []
    with pytest.raises(ValueError):
        scan_raw_file(tmp_path / "e.jsonl", "profiles")
