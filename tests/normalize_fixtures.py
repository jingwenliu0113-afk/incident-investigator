"""Synthetic raw OTLP JSON for normalize tests (decision 011): every rule gets a positive and a negative case."""

from __future__ import annotations

import json
from pathlib import Path

T0 = 1791460000_000000000  # data-clock ns; the incident window below is [T0 + 60 s, T0 + 600 s)
S = 10**9
HOST_START, HOST_END = "2026-10-08T11:47:40Z", "2026-10-08T11:56:40Z"  # host clock
OFFSETS = [0.0, 0.0]


def kv(d: dict) -> list:
    out = []
    for k, v in d.items():
        if isinstance(v, bool):
            val = {"boolValue": v}
        elif isinstance(v, int):
            val = {"intValue": str(v)}
        elif isinstance(v, float):
            val = {"doubleValue": v}
        else:
            val = {"stringValue": v}
        out.append({"key": k, "value": val})
    return out


def res(service: str | None, **extra) -> dict:
    attrs = ({"service.name": service} if service else {}) | extra
    return {"attributes": kv(attrs)}


def span(tid: str, sid: str, start: int, name: str = "GET /api", parent: str | None = None, attrs: dict | None = None,
         status: dict | None = None, events: list | None = None) -> dict:
    s = {"traceId": tid, "spanId": sid, "name": name, "kind": 2, "startTimeUnixNano": str(start),
         "endTimeUnixNano": str(start + 5_000_000), "attributes": kv(attrs or {}), "status": status or {}}
    if parent:
        s["parentSpanId"] = parent
    if events:
        s["events"] = events
    return s


def traces_line(resource: dict, spans: list, scope: str = "io.opentelemetry.sdk") -> str:
    return json.dumps({"resourceSpans": [{"resource": resource, "scopeSpans": [{"scope": {"name": scope}, "spans": spans}]}]})


def log(t: int, body: str, attrs: dict | None = None, event_name: str | None = None, severity: int = 9) -> dict:
    r = {"timeUnixNano": str(t), "severityNumber": severity, "body": {"stringValue": body}, "attributes": kv(attrs or {})}
    if event_name:
        r["eventName"] = event_name
    return r


def logs_line(resource: dict, records: list, scope: str = "app") -> str:
    return json.dumps({"resourceLogs": [{"resource": resource, "scopeLogs": [{"scope": {"name": scope}, "logRecords": records}]}]})


def gauge_line(resource: dict, name: str, points: list, scope: str = "app", kind: str = "gauge") -> str:
    metric = {"name": name, "unit": "1", kind: {"dataPoints": points}}
    if kind == "sum":
        metric[kind].update(aggregationTemporality=2, isMonotonic=True)
    return json.dumps({"resourceMetrics": [{"resource": resource, "scopeMetrics": [{"scope": {"name": scope}, "metrics": [metric]}]}]})


def pt(t: int, value: int = 1, attrs: dict | None = None, **extra) -> dict:
    return {"startTimeUnixNano": str(T0), "timeUnixNano": str(t), "asInt": str(value), "attributes": kv(attrs or {}), **extra}


TID, TID2, TID3 = "1" * 32, "2" * 32, "3" * 32


def raw_lines() -> dict[str, list[str]]:
    w = T0 + 120 * S  # inside the window
    checkout, payment = res("checkout"), res("payment")
    traces = [
        # kept: a checkout server span with a flag attribute (X5 strips the key) and a privacy attribute (X9)
        traces_line(checkout, [span(TID, "a" * 16, w, "oteldemo.CheckoutService/PlaceOrder",
                                    attrs={"feature_flag.key": "paymentFailure", "user.email": "x@y.z",
                                           "rpc.service": "oteldemo.CheckoutService"},
                                    status={"code": 2, "message": "failed to charge card: paymentFailure on"},
                                    events=[{"timeUnixNano": str(w + 1), "name": "feature_flag.evaluation",
                                             "attributes": kv({"feature_flag.key": "paymentFailure"})},
                                            {"timeUnixNano": str(w + 2), "name": "message",
                                             "attributes": kv({"message.type": "SENT"})}])]),
        # X4 root: checkout's client span to flagd, and its child (a SUT span below it) go with it
        traces_line(checkout, [span(TID, "b" * 16, w + 10, "flagd.evaluation.v1.Service/ResolveBoolean", parent="a" * 16,
                                    attrs={"rpc.service": "flagd.evaluation.v1.Service", "server.address": "flagd"})]),
        traces_line(payment, [span(TID, "c" * 16, w + 20, "child of flagd call", parent="b" * 16)]),
        # child before parent in the file, and the root outside the window: still closed over
        traces_line(payment, [span(TID3, "d" * 16, w, "late child", parent="e" * 16)]),
        traces_line(checkout, [span(TID3, "e" * 16, T0, "flagd call before the window", attrs={"server.address": "flagd:8013"})]),
        # X1: load-generator span dropped, but its SUT child is NOT (no cascade from X1)
        traces_line(res("load-generator"), [span(TID2, "f" * 16, w, "GET /")]),
        traces_line(res("frontend-proxy"), [span(TID2, "9" * 16, w + 5, "ingress", parent="f" * 16,
                                                 attrs={"url.path": "/api/products/1"})]),
        # X6: denied scope
        traces_line(checkout, [span(TID2, "8" * 16, w, "provider init")], scope="dev.openfeature.contrib.hooks.otel"),
        # duplicate (SDK resend): dropped by dedupe
        traces_line(payment, [span(TID2, "7" * 16, w, "Charge")]),
        traces_line(payment, [span(TID2, "7" * 16, w, "Charge")]),
        # out of window
        traces_line(payment, [span(TID2, "6" * 16, T0 + 700 * S, "after the window")]),
    ]
    logs = [
        logs_line(payment, [log(w, "Payment request failed. Invalid token. demo.user_context.loyalty_level=gold")]),
        logs_line(res("ad"), [log(w, "Triggering a manual garbage collection, next one in 10 seconds.")]),  # X7
        logs_line(res("product-catalog"), [log(w, "Error: Product Catalog Fail Feature Flag Enabled")]),  # X8 tokens
        logs_line(res("shipping"), [log(w, "evaluated", event_name="shipping.feature_flag.evaluated")]),  # X5 event
        logs_line(res("flagd"), [log(w, "flag set updated")]),  # X1
        logs_line(res("recommendation"), [log(w, "get_product_list: cache hit")]),  # Class B: kept
        logs_line(checkout, [{"observedTimeUnixNano": str(w + 3), "body": {"stringValue": "no event time"}}]),
        logs_line(checkout, [log(T0 + 10 * S, "before the window")]),
        # emitted inside the removed flagd call (span b): goes with its span (X4)
        logs_line(checkout, [{**log(w + 11, "resolving with provider"), "traceId": TID, "spanId": "b" * 16}]),
    ]
    metrics = [
        gauge_line(res("cart"), "app.cart.items", [pt(w), pt(w + 60 * S, 2)], kind="sum"),
        gauge_line(res("cart"), "feature_flag.evaluation_requests_total", [pt(w)]),  # X5 metric name
        gauge_line(res("cart"), "http.client.duration", [pt(w, attrs={"feature_flag.key": "cartFailure"})]),  # X5 point attr
        gauge_line(res("checkout"), "otel.sdk.span.processed", [pt(w)]),  # X3
        gauge_line(res(None, **{"container.name": "checkout"}), "container.cpu.utilization", [pt(w)],
                   scope="github.com/open-telemetry/opentelemetry-collector-contrib/receiver/dockerstatsreceiver"),
        gauge_line(res(None, **{"container.name": "flagd"}), "container.cpu.utilization", [pt(w)],
                   scope="github.com/open-telemetry/opentelemetry-collector-contrib/receiver/dockerstatsreceiver"),  # X1
        gauge_line(res(None, **{"process.command_line": "docker exec x python -c ofrep paymentFailure"}),
                   "process.cpu.time", [pt(w)],
                   scope="github.com/open-telemetry/opentelemetry-collector-contrib/receiver/hostmetricsreceiver/internal/scraper/processscraper"),  # X2
        gauge_line(res(None, **{"postgresql.database.name": "otel"}), "postgresql.backends", [pt(w)],
                   scope="github.com/open-telemetry/opentelemetry-collector-contrib/receiver/postgresqlreceiver"),
        gauge_line(res("cart"), "no.value", [pt(w, flags=1)]),  # X10 NoRecordedValue
    ]
    return {"traces": traces, "metrics": metrics, "logs": logs}


def write_raw(raw_dir: Path) -> dict[str, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for sig, lines in raw_lines().items():
        p = raw_dir / f"{sig}.jsonl"
        p.write_text("\n".join(lines) + "\n")
        out[sig] = p
    return out
