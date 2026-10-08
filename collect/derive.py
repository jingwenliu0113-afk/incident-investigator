"""Derived views over a snapshot, shared by every method so they all see the same numbers (decision 011 §2, §5).

Nothing here is stored in the snapshot: analysis choices stay versioned code, not frozen data.
"""

from __future__ import annotations

from collections import defaultdict

DERIVE_VERSION = 2  # 2: non-monotonic cumulative sums may go down (only a new start time resets)
WARN_SEVERITY = 13  # OTLP severity_number: WARN and above


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-95 * len(ordered) // 100) - 1)]


def service_minute_stats(snapshot) -> dict:
    """Per service and per minute since the window start: spans, server spans, error spans, p95 server latency, WARN+ logs."""
    origin = snapshot.window["start_ns"]
    stats: dict = defaultdict(lambda: defaultdict(lambda: {"spans": 0, "server_spans": 0, "error_spans": 0,
                                                            "server_ms": [], "warn_logs": 0}))
    for s in snapshot.spans():
        m = stats[s["service"]][(s["start_time_unix_nano"] - origin) // 60_000_000_000]
        m["spans"] += 1
        m["error_spans"] += s["status_code"] == "error"
        if s["kind"] == "server" and s["end_time_unix_nano"] is not None:
            m["server_spans"] += 1
            m["server_ms"].append((s["end_time_unix_nano"] - s["start_time_unix_nano"]) / 1e6)
    for r in snapshot.logs():
        t = r["time_unix_nano"] if r["time_unix_nano"] is not None else r["observed_time_unix_nano"]
        if r["severity_number"] >= WARN_SEVERITY:
            stats[r["service"]][(t - origin) // 60_000_000_000]["warn_logs"] += 1
    out = {}
    for svc, minutes in stats.items():
        out[svc] = {}
        for minute, m in sorted(minutes.items()):
            out[svc][minute] = {k: v for k, v in m.items() if k != "server_ms"} | {"p95_server_ms": _p95(m["server_ms"])}
    return {"version": DERIVE_VERSION, "services": out}


def point_deltas(points: list[dict], monotonic: bool) -> list[dict]:
    """Deltas of one cumulative sum series in time order (pass the series' `monotonic`). A new start time is a reset,
    and for a monotonic series so is a drop in value (the delta is then the new value). The first point in the window
    only anchors: its interval spans the window edge (decision 008 §7)."""
    out, prev = [], None
    for p in sorted(points, key=lambda p: p["time_unix_nano"]):
        value = p.get("value")
        if not isinstance(value, (int, float)):
            prev = None
            continue
        if prev is not None and not p.get("first_in_window"):
            reset = (p.get("start_time_unix_nano") != prev.get("start_time_unix_nano")
                     or (monotonic and value < prev["value"]))
            out.append({"time_unix_nano": p["time_unix_nano"], "delta": value if reset else value - prev["value"], "reset": reset})
        prev = p
    return out
