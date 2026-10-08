"""Failure taxonomy v1 (SPEC Core §10, decision 022). Ground-truth side: it reads the label and the method's exposure.

A failure = origin_top1 or fault_type wrong. Each failure gets the first matching category of CATEGORIES.
"""

from __future__ import annotations

from collect.normalize import host_to_data_ns


GRACE_S = 60  # the same tail as decision 017's temporal weak label
MINUTE = 60 * 10**9
CATEGORIES = ("no_answer", "coverage", "mechanism", "not_seen", "seen_misread", "rule_limit")
SUBMITTED = ("submitted", "submitted_after_limit")


def _ns(ts: str, offset_s: float) -> int:
    return host_to_data_ns(ts, offset_s)  # exactly as normalize maps the window (clock audit)


def origin_evidence_seen(exposure: list[str], snapshot, label: dict, *, clock_offset_s: float = 0.0) -> bool:
    """Did the method look at the origin in the fault period (a record, a metric series or its minute statistics)?"""
    origin = label["origin_service"]
    on = _ns(label["fault_start"], clock_offset_s)
    end = _ns(label["fault_end"], clock_offset_s) + GRACE_S * 10**9
    start = snapshot.window["start_ns"]
    first_minute, last_minute = (on - start) // MINUTE, (end - start) // MINUTE
    for e in exposure:
        if e == "stats:*":
            return True
        if e.startswith("stats:"):
            _, svc, span = e.split(":")
            m0, m1 = (int(x) for x in span.split("-"))
            if svc == origin and m0 <= last_minute and m1 >= first_minute:
                return True
            continue
        rec = snapshot.resolve(e)
        if rec is None or rec.get("service") != origin:
            continue
        kind = e[:2]
        if kind == "m-":
            return True
        t = (rec.get("start_time_unix_nano") if kind == "s-" else
             rec.get("time_unix_nano") if rec.get("time_unix_nano") is not None else rec.get("observed_time_unix_nano"))
        if t is not None and on <= t <= end:
            return True
    return False


def classify(pred: dict, label: dict, score: dict, transcript: dict | None, snapshot, *,
             clock_offset_s: float = 0.0) -> str | None:
    if score["origin_top1"] == 1 and score["fault_type"] == 1:
        return None
    if not pred["origin_candidates"] or (transcript is not None and transcript.get("stop_reason") not in SUBMITTED):
        return "no_answer"
    if (label.get("labeling", {}).get("method") == "catalog+review"
            and all(v != "origin" for v in label["telemetry_coverage"].values())):
        return "coverage"
    if score["origin_top1"] == 1:
        return "mechanism"
    if transcript is None:
        return "rule_limit"
    seen = origin_evidence_seen(transcript.get("exposure") or [], snapshot, label, clock_offset_s=clock_offset_s)
    return "seen_misread" if seen else "not_seen"
