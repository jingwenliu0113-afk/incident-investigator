"""Statistical rule baseline v2 (SPEC Core §7 #3, decision 014 and its revision 1): per-service robust anomaly scores.

Reference = the first 10 minutes of the window (the one framing sentence every method gets); each feature scores the
largest increase after it as a robust z. Fixed rules turn the scores into a decision-013 prediction.
"""

from __future__ import annotations

import time
from statistics import median

from collect.derive import container_minute_stats, service_minute_stats

METHOD = {"name": "stat-anomaly", "version": "2"}
REFERENCE_MINUTES = 10
# decision 014 revision 1: max(3, the largest z of any SUT service on the fault-free calibration snapshots of soak #3
# and soak #5), rounded up to 0.1; fixed here, never recomputed
NULL_THRESHOLDS = {"error_ratio": 3.0, "p95_latency_ms": 45.0, "warn_logs": 3.0, "cpu": 3.6, "memory": 34.0}
MAX_CANDIDATES = 5
MIN_REFERENCE_POINTS = 3
USER_FACING = ("frontend-proxy", "frontend")
FEATURE_FAULT = {"error_ratio": "error_response", "p95_latency_ms": "added_latency", "cpu": "cpu_saturation",
                 "memory": "memory_leak", "warn_logs": None}
MiB = 2**20


def _floor(feature: str, ref_median: float) -> float:
    return {"error_ratio": 0.01, "warn_logs": 1.0, "cpu": 0.02,
            "p95_latency_ms": max(0.1 * ref_median, 1.0), "memory": max(0.02 * ref_median, MiB)}[feature]


def robust_scores(features: dict, reference_minutes: int = REFERENCE_MINUTES) -> dict[str, dict[str, float]]:
    """{service: {feature: z}}: (largest value after the reference - reference median) / max(1.4826 MAD, floor), >= 0."""
    out: dict[str, dict[str, float]] = {}
    for svc, feats in features.items():
        out[svc] = {}
        for name, series in feats.items():
            ref = [v for m, v in series.items() if m < reference_minutes and v is not None]
            check = [v for m, v in series.items() if m >= reference_minutes and v is not None]
            if len(ref) < MIN_REFERENCE_POINTS or not check:
                continue
            med = median(ref)
            scale = max(1.4826 * median(abs(v - med) for v in ref), _floor(name, med))
            out[svc][name] = max(0.0, (max(check) - med) / scale)
    return out


def features(snapshot) -> dict[str, dict[str, dict[int, float]]]:
    """{service: {feature: {minute since window start: value}}} for the snapshot's SUT services (collect.derive views)."""
    spans = service_minute_stats(snapshot)["services"]
    containers = container_minute_stats(snapshot)["services"]
    out = {}
    for svc in snapshot.services:
        s, c = spans.get(svc, {}), containers.get(svc, {})
        out[svc] = {
            "error_ratio": {m: v["error_spans"] / v["spans"] for m, v in s.items() if v["spans"]},
            "p95_latency_ms": {m: v["p95_server_ms"] for m, v in s.items() if v["p95_server_ms"] is not None},
            "warn_logs": {m: v["warn_logs"] for m, v in s.items()},
            "cpu": {m: v["cpu"] for m, v in c.items() if v.get("cpu") is not None},
            "memory": {m: v["memory"] for m, v in c.items() if v.get("memory") is not None},
        }
    return out


def predict_from_features(feats: dict, *, incident_id: str, evidence: list[dict] | None = None) -> dict:
    z = robust_scores(feats)
    units = {svc: {k: v / NULL_THRESHOLDS[k] for k, v in f.items()} for svc, f in z.items()}  # 1 = the feature's threshold
    score = {svc: max(f.values(), default=0.0) for svc, f in units.items()}
    ranked = sorted((s for s in score if score[s] > 0), key=lambda s: (-score[s], s))
    candidates = ranked[:MAX_CANDIDATES]
    affected = [s for s in ranked if score[s] >= 1] or candidates[:1]
    fault_type = None
    if candidates and score[candidates[0]] >= 1:
        top_feature = max(units[candidates[0]].items(), key=lambda kv: (kv[1], kv[0]))[0]
        fault_type = FEATURE_FAULT[top_feature]
    kinds = [kind for kind, feature in (("errors", "error_ratio"), ("latency", "p95_latency_ms"))
             if any(units.get(s, {}).get(feature, 0.0) >= 1 for s in USER_FACING)] or ["none"]
    return {"prediction_version": 1, "incident_id": incident_id, "method": dict(METHOD),
            "fault": {"fault_type": fault_type, "fault_family": None}, "origin_candidates": candidates,
            "affected_services": affected, "user_symptom": {"kinds": kinds}, "evidence": evidence or [],
            "usage": {"tokens_in": None, "tokens_out": None, "proxy_tokens": None, "tool_calls": 0, "retrievals": 0,
                      "latency_s": None, "cost_usd": 0}}


def _evidence(snapshot, feats: dict, pred: dict) -> list[dict]:
    """Up to 5 spans of the top service in the minute of its top feature (error or latency features only)."""
    if not pred["origin_candidates"]:
        return []
    top = pred["origin_candidates"][0]
    z = {k: v / NULL_THRESHOLDS[k] for k, v in robust_scores({top: feats[top]})[top].items()}
    feature = max(z.items(), key=lambda kv: (kv[1], kv[0]))[0] if z else None
    if feature not in ("error_ratio", "p95_latency_ms"):
        return []
    series = feats[top][feature]
    minute = max((m for m in series if m >= REFERENCE_MINUTES), key=lambda m: (series[m], -m))
    origin = snapshot.window["start_ns"]
    in_minute = [s for s in snapshot.spans() if s["service"] == top
                 and (s["start_time_unix_nano"] - origin) // 60_000_000_000 == minute]
    if feature == "error_ratio":
        chosen = sorted((s for s in in_minute if s["status_code"] == "error"), key=lambda s: s["start_time_unix_nano"])
    else:
        chosen = sorted((s for s in in_minute if s["kind"] == "server" and s["end_time_unix_nano"] is not None),
                        key=lambda s: s["start_time_unix_nano"] - s["end_time_unix_nano"])
    return [{"id": s["id"]} for s in chosen[:5]]


def predict(snapshot, incident_id: str) -> dict:
    t0 = time.monotonic()
    feats = features(snapshot)
    pred = predict_from_features(feats, incident_id=incident_id)
    pred["evidence"] = _evidence(snapshot, feats, pred)
    pred["usage"]["latency_s"] = round(time.monotonic() - t0, 3)
    return pred
