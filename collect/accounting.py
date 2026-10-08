"""Loss accounting of one raw export (decision 008 §6), from counters that are themselves in the raw metrics file.

collector_snapshots(): the collector's own counters (service.name otelcol-contrib, pushed every 60 s), one entry per export.
sdk_error_series(): the SDKs' self-observability counters that carry an error.type (telemetry lost before the collector).
account(): deltas over a window, bracketed by the last export at or before its start and the first at or after its end
(a counter exported after the end still covers the end), and the flags that make the raw export incomplete.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

COLLECTOR_SERVICE = "otelcol-contrib"
# receivers of traces/raw, metrics/raw and logs/raw in env/otelcol-config-raw.yml (tests/test_accounting.py checks they match)
RAW_RECEIVERS = {
    "traces": ("otlp",),
    "metrics": ("docker_stats", "http_check/frontend-proxy", "host_metrics", "nginx", "otlp", "redis", "postgresql",
                "kafkametrics"),
    "logs": ("otlp",),
}
ITEMS = {"traces": "spans", "metrics": "metric_points", "logs": "log_records"}
EXPORT_GAP_NS = 5 * 10**9  # points of one export are microseconds apart; exports are 60 s apart
_KEEP = re.compile(r"otelcol_(receiver_(accepted|refused|failed)_|exporter_(sent|send_failed)_|processor_(incoming|outgoing)_items$"
                   r"|processor_memory_limiter_refused_)")


def _attrs(items: list | None) -> dict[str, str]:
    return {a["key"]: str(next(iter((a.get("value") or {"": ""}).values()), "")) for a in items or []}


def _points(path: Path):
    """(service.name, metric name, point) for every sum / gauge point; unparsable lines are skipped (scan_raw_file reports them)."""
    with Path(path).open("rb") as f:
        for raw in f:
            try:
                doc = json.loads(raw)
            except ValueError:
                continue
            for rm in (doc.get("resourceMetrics") or []) if isinstance(doc, dict) else []:
                service = _attrs((rm.get("resource") or {}).get("attributes")).get("service.name")
                for sm in rm.get("scopeMetrics") or []:
                    for m in sm.get("metrics") or []:
                        for kind in ("sum", "gauge"):
                            for pt in (m.get(kind) or {}).get("dataPoints") or []:
                                yield service, m.get("name", ""), pt


def _value(pt: dict) -> float:
    v = pt.get("asInt", pt.get("asDouble", 0))
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def counter_key(name: str, attrs: dict[str, str]) -> str:
    """One counter series: JSON of [name, sorted attribute pairs] (attribute values may hold any character)."""
    return json.dumps([name, sorted(attrs.items())], separators=(",", ":"))


def collector_snapshots(path: Path, service: str = COLLECTOR_SERVICE) -> list[dict]:
    """[{t, start, values: {"metric{attr=value,...}": value}}] in time order, one per self-telemetry export."""
    points = sorted((int(pt.get("timeUnixNano") or 0), int(pt.get("startTimeUnixNano") or 0), counter_key(name, _attrs(pt.get("attributes"))),
                     _value(pt))
                    for svc, name, pt in _points(path) if svc == service and _KEEP.match(name))
    snaps: list[dict] = []
    for t, start, key, value in points:
        if not snaps or t - snaps[-1]["last"] > EXPORT_GAP_NS:
            snaps.append({"t": t, "start": start, "values": {}, "last": t})
        snaps[-1]["values"][key] = value
        snaps[-1]["last"] = t
        snaps[-1]["start"] = min(snaps[-1]["start"], start) if start else snaps[-1]["start"]
    return [{k: v for k, v in s.items() if k != "last"} for s in snaps]


def sdk_error_series(path: Path) -> dict:
    """{"errors": points of otel.sdk.* counters with a non-empty error.type (decision 008 §6: any of them is loss),
    "exports": {service: times of its otel.sdk.* exports}} -- the exports bracket the window, not the error points."""
    errors, exports = [], {}
    for svc, name, pt in _points(path):
        if not name.startswith("otel.sdk."):
            continue
        t = int(pt.get("timeUnixNano") or 0)
        exports.setdefault(svc, set()).add(t)
        attrs = _attrs(pt.get("attributes"))
        if attrs.get("error.type"):
            errors.append({"t": t, "service": svc, "metric": name, "component": attrs.get("otel.component.name", ""),
                           "error_type": attrs["error.type"], "value": _value(pt)})
    return {"exports": {svc: sorted(ts) for svc, ts in sorted(exports.items(), key=lambda kv: str(kv[0]))},
            "errors": sorted(errors, key=lambda r: r["t"])}


def _sum(values: dict[str, float], metric: str, **match: str | tuple[str, ...]) -> float:
    total = 0.0
    for key, v in values.items():
        name, pairs = json.loads(key)
        if name != metric:
            continue
        attrs = dict(pairs)
        if all(attrs.get(k) in (allowed if isinstance(allowed, tuple) else (allowed,)) for k, allowed in match.items()):
            total += v
    return total


def _bracket(times: list[int], start_ns: int, end_ns: int) -> tuple[int | None, int | None]:
    base = max((i for i, t in enumerate(times) if t <= start_ns), default=None, key=lambda i: times[i])
    final = min((i for i, t in enumerate(times) if t >= end_ns), default=None, key=lambda i: times[i])
    return base, final


def account(snapshots: list[dict], sdk: dict, scans: dict[str, dict | None], *, start_ns: int, end_ns: int) -> dict:
    """decision 008 §6 over [start_ns, end_ns]. Flags make the raw export incomplete; SDK errors are reported only."""
    flags: list[str] = []
    b, f = _bracket([s["t"] for s in snapshots], start_ns, end_ns)
    base = snapshots[b] if b is not None else {"t": None, "start": None, "values": {}}  # counters start at 0
    final = snapshots[f] if f is not None else None
    restarted = final is not None and base["start"] is not None and base["start"] != final["start"]
    if final is None or restarted:
        flags.append("accounting_unavailable")  # nothing exported after the window, or the counters were reset
    signals = {}
    if final is not None and not restarted:
        for sig, items in ITEMS.items():
            def delta(metric: str, **match) -> float:
                return _sum(final["values"], metric, **match) - _sum(base["values"], metric, **match)

            recv, exp = {"receiver": RAW_RECEIVERS[sig]}, {"exporter": f"file/raw_{sig}"}
            ml = {"processor": "memory_limiter", "otel.signal": sig}
            row = {"accepted": delta(f"otelcol_receiver_accepted_{items}", **recv),
                   "refused": delta(f"otelcol_receiver_refused_{items}", **recv),
                   "failed": delta(f"otelcol_receiver_failed_{items}", **recv),
                   "sent": delta(f"otelcol_exporter_sent_{items}", **exp),
                   "send_failed": delta(f"otelcol_exporter_send_failed_{items}", **exp),
                   "memory_limiter_dropped": max(0, delta("otelcol_processor_incoming_items", **ml)
                                                 - delta("otelcol_processor_outgoing_items", **ml),
                                                 delta(f"otelcol_processor_memory_limiter_refused_{items}")),
                   "file_items": (scans.get(sig) or {}).get("items", 0) + (scans.get(sig) or {}).get("duplicates", 0),
                   "final_sent": _sum(final["values"], f"otelcol_exporter_sent_{items}", **exp)}
            signals[sig] = {k: int(v) for k, v in row.items()}
            if row["memory_limiter_dropped"] > 0 and "memory_limiter_refused" not in flags:
                flags.append("memory_limiter_refused")
            if row["send_failed"] > 0 and "exporter_rejected" not in flags:
                flags.append("exporter_rejected")  # the file exporter could not write a batch
            balanced = row["accepted"] <= row["sent"] <= row["accepted"] + row["refused"] + row["failed"]
            if not balanced or row["file_items"] < row["final_sent"]:
                flags.append(f"accounting_mismatch:{sig}")

    groups: dict[tuple, list[dict]] = {}
    for r in (sdk or {}).get("errors", []):
        groups.setdefault((r["service"], r["metric"], r["component"], r["error_type"]), []).append(r)
    lost_by_service: dict[str, dict[str, int]] = {}
    for (svc, metric, _, error_type), rows in sorted(groups.items(), key=lambda kv: str(kv[0])):
        def value_at(t: int) -> float:  # the series' value at the export at t (0 when that export did not carry it)
            return max((r for r in rows if r["t"] <= t + EXPORT_GAP_NS), key=lambda r: r["t"], default={"value": 0})["value"]

        exports = (sdk or {}).get("exports", {}).get(svc, [])
        final_t = min((t for t in exports if t >= end_ns), default=None)
        before = max((r for r in rows if r["t"] <= start_ns), key=lambda r: r["t"], default={"value": 0})["value"]
        lost = (value_at(final_t) if final_t is not None else rows[-1]["value"]) - before
        if lost > 0:
            per = lost_by_service.setdefault(svc, {})
            per[f"{metric} {error_type}"] = per.get(f"{metric} {error_type}", 0) + int(lost)
    sdk_lost = lost_by_service

    return {"accounting_version": 1, "window_ns": [start_ns, end_ns],
            "snapshots": {"base": base["t"], "final": final["t"] if final else None},
            "signals": signals, "sdk_errors": sdk_lost, "flags": flags}
