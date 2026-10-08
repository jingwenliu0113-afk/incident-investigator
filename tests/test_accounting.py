"""Loss accounting of a raw export (decision 008 §6) from the collector's own counters and the SDKs' error counters."""

import json

import yaml

from collect.accounting import RAW_RECEIVERS, account, collector_snapshots, sdk_error_series
from env.lock import PROJECT_DIR
from env.soak import RAW_CONFIG

S = 10**9
T0 = 1791461133 * S  # 2026-10-08T12:05:33Z, the collector's first self-telemetry export in soak #3
START = T0 + 30 * S


def kv(**attrs):
    return [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()]


def export(service, t, counters, *, start=T0 - 60 * S, scope="go.opentelemetry.io/collector/service"):
    """One self-telemetry export: {(metric, ((attr, value), ...)): value}; points a few µs apart like the real ones."""
    metrics = [{"name": name, "sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": [
        {"attributes": kv(**dict(attrs)), "startTimeUnixNano": str(start), "timeUnixNano": str(t + i * 1000),
         "asInt": str(value)}]}} for i, ((name, attrs), value) in enumerate(counters.items())]
    return json.dumps({"resourceMetrics": [{"resource": {"attributes": kv(**{"service.name": service})},
                                            "scopeMetrics": [{"scope": {"name": scope}, "metrics": metrics}]}]})


def counters(spans, *, refused=0, sent=None, failed_export=0, ml_in=None, ml_out=None, logs=0, points=0):
    c = {
        ("otelcol_receiver_accepted_spans", (("receiver", "otlp"), ("transport", "grpc"))): spans,
        ("otelcol_receiver_refused_spans", (("receiver", "otlp"), ("transport", "grpc"))): refused,
        ("otelcol_exporter_sent_spans", (("exporter", "file/raw_traces"),)): spans if sent is None else sent,
        ("otelcol_exporter_sent_spans", (("exporter", "otlp_grpc/jaeger"),)): spans,  # not the raw path
        ("otelcol_receiver_accepted_log_records", (("receiver", "otlp"), ("transport", "http"))): logs,
        ("otelcol_exporter_sent_log_records", (("exporter", "file/raw_logs"),)): logs,
        ("otelcol_exporter_send_failed_log_records", (("exporter", "opensearch"),)): 7,  # ambient (decision 005)
        ("otelcol_receiver_accepted_metric_points", (("receiver", "docker_stats"), ("transport", ""))): points,
        ("otelcol_receiver_accepted_metric_points", (("receiver", "span_metrics"), ("transport", ""))): 999 + points,  # not raw
        ("otelcol_exporter_sent_metric_points", (("exporter", "file/raw_metrics"),)): points,
        ("otelcol_processor_incoming_items", (("otel.signal", "traces"), ("processor", "memory_limiter"))):
            2 * spans if ml_in is None else ml_in,
        ("otelcol_processor_outgoing_items", (("otel.signal", "traces"), ("processor", "memory_limiter"))):
            2 * spans if ml_out is None else ml_out,
        ("otelcol_process_uptime", ()): 60,  # not a counter accounting uses
    }
    if failed_export:
        c[("otelcol_exporter_send_failed_spans", (("exporter", "file/raw_traces"),))] = failed_export
    return c


def write(tmp_path, lines):
    p = tmp_path / "metrics.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return p


def scan(items, duplicates=0):
    return {"items": items, "duplicates": duplicates}


SCANS = {"traces": scan(400), "logs": scan(50), "metrics": scan(90)}


def test_raw_receivers_match_the_locked_raw_config():
    pipelines = yaml.safe_load((PROJECT_DIR / RAW_CONFIG).read_text())["service"]["pipelines"]
    assert {sig: tuple(pipelines[f"{sig}/raw"]["receivers"]) for sig in ("traces", "metrics", "logs")} == RAW_RECEIVERS


def test_snapshots_group_one_export_of_the_collector_and_ignore_other_services(tmp_path):
    p = write(tmp_path, [export("otelcol-contrib", T0, counters(100)),
                         export("jaeger", T0, counters(5)),  # jaeger is built on the collector: same metric names
                         export("otelcol-contrib", T0 + 60 * S, counters(250)),
                         "{broken"])
    snaps = collector_snapshots(p)
    assert [s["t"] for s in snaps] == [T0, T0 + 60 * S]
    assert snaps[1]["values"]["otelcol_exporter_sent_spans{exporter=file/raw_traces}"] == 250
    assert "otelcol_process_uptime{}" not in snaps[0]["values"]
    assert snaps[0]["start"] == T0 - 60 * S


def snaps_for(tmp_path, *exports):
    return collector_snapshots(write(tmp_path, [export("otelcol-contrib", t, c) for t, c in exports]))


def test_a_clean_window_has_no_flags_and_counts_deltas_between_the_bracketing_exports(tmp_path):
    snaps = snaps_for(tmp_path, (T0, counters(100, logs=10, points=20)), (T0 + 60 * S, counters(250, logs=30, points=50)),
                      (T0 + 120 * S, counters(400, logs=50, points=90)))
    acc = account(snaps, [], SCANS, start_ns=START, end_ns=T0 + 90 * S)
    assert acc["flags"] == []
    assert acc["snapshots"] == {"base": T0, "final": T0 + 120 * S}  # last export <= start, first export >= end
    assert acc["signals"]["traces"] == {"accepted": 300, "refused": 0, "failed": 0, "sent": 300, "send_failed": 0,
                                        "memory_limiter_dropped": 0, "file_items": 400, "final_sent": 400}
    assert acc["signals"]["metrics"]["accepted"] == 70  # docker_stats only: span_metrics is not in metrics/raw


def test_memory_limiter_drops_and_raw_exporter_failures_are_flagged(tmp_path):
    snaps = snaps_for(tmp_path, (T0, counters(100)), (T0 + 120 * S, counters(400, ml_in=800, ml_out=790, failed_export=3)))
    acc = account(snaps, [], SCANS, start_ns=START, end_ns=T0 + 90 * S)
    assert "memory_limiter_refused" in acc["flags"] and "exporter_rejected" in acc["flags"]
    assert acc["signals"]["traces"]["memory_limiter_dropped"] == 10


def test_raw_path_must_balance_with_the_receiver_and_the_file(tmp_path):
    # sent below accepted: items accepted but never written
    snaps = snaps_for(tmp_path, (T0, counters(100)), (T0 + 120 * S, counters(400, sent=390)))
    assert "accounting_mismatch:traces" in account(snaps, [], SCANS, start_ns=START, end_ns=T0 + 90 * S)["flags"]
    # a refused batch the raw pipeline still wrote (another pipeline failed): sent within accepted + refused
    snaps = snaps_for(tmp_path, (T0, counters(100)), (T0 + 120 * S, counters(400, refused=5, sent=405)))
    acc = account(snaps, [], dict(SCANS, traces=scan(400, duplicates=5)), start_ns=START, end_ns=T0 + 90 * S)
    assert acc["flags"] == [] and acc["signals"]["traces"]["refused"] == 5
    # the file holds fewer items than the exporter reported sent
    snaps = snaps_for(tmp_path, (T0, counters(100)), (T0 + 120 * S, counters(400)))
    acc = account(snaps, [], dict(SCANS, traces=scan(399)), start_ns=START, end_ns=T0 + 90 * S)
    assert "accounting_mismatch:traces" in acc["flags"]


def test_no_export_after_the_window_end_means_the_window_cannot_be_accounted(tmp_path):
    snaps = snaps_for(tmp_path, (T0, counters(100)), (T0 + 60 * S, counters(250)))
    acc = account(snaps, [], SCANS, start_ns=START, end_ns=T0 + 90 * S)
    assert "accounting_unavailable" in acc["flags"]
    assert "accounting_unavailable" in account([], [], SCANS, start_ns=START, end_ns=T0 + 90 * S)["flags"]


def sdk_line(service, t, value, *, error_type="java.net.UnknownHostException"):
    point = {"attributes": kv(**{"otel.component.name": "otlp_http_log_exporter/0", "error.type": error_type}),
             "timeUnixNano": str(t), "asInt": str(value)}
    ok = {"attributes": kv(**{"otel.component.name": "otlp_http_log_exporter/0"}), "timeUnixNano": str(t), "asInt": "99"}
    metric = {"name": "otel.sdk.exporter.log.exported", "sum": {"dataPoints": [point, ok]}}
    return json.dumps({"resourceMetrics": [{"resource": {"attributes": kv(**{"service.name": service})},
                                            "scopeMetrics": [{"scope": {"name": "io.opentelemetry.sdk.logs"},
                                                              "metrics": [metric]}]}]})


def test_sdk_errors_count_only_inside_the_window_and_are_reported_not_flagged(tmp_path):
    # soak #3: kafka failed one export of 160 log records at start-up (collector not resolvable yet), never again
    p = write(tmp_path, [sdk_line("kafka", T0, 160), sdk_line("kafka", T0 + 120 * S, 160),
                         sdk_line("ad", T0, 0), sdk_line("ad", T0 + 120 * S, 12)])
    series = sdk_error_series(p)
    assert {s["service"] for s in series} == {"kafka", "ad"}
    snaps = snaps_for(tmp_path, (T0, counters(100)), (T0 + 120 * S, counters(400)))
    acc = account(snaps, series, SCANS, start_ns=START, end_ns=T0 + 90 * S)
    assert acc["sdk_errors"] == {"ad": {"otel.sdk.exporter.log.exported java.net.UnknownHostException": 12}}
    assert acc["flags"] == []


def test_a_collector_restart_inside_the_window_resets_the_counters_and_cannot_be_accounted(tmp_path):
    p = write(tmp_path, [export("otelcol-contrib", T0, counters(100)),
                         export("otelcol-contrib", T0 + 120 * S, counters(40), start=T0 + 70 * S)])  # restarted at +70 s
    acc = account(collector_snapshots(p), [], SCANS, start_ns=START, end_ns=T0 + 90 * S)
    assert acc["flags"] == ["accounting_unavailable"] and acc["signals"] == {}  # no negative deltas
