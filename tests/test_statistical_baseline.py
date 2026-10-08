"""Statistical rule baseline v1 (SPEC Core §7 #3, decision 014): per-service robust anomaly scores on the snapshot."""

import pytest

from baselines.statistical import NULL_THRESHOLDS, REFERENCE_MINUTES, predict_from_features, robust_scores
from eval.score import check_prediction


def flat(value, minutes=25, **at):
    """A feature series: `value` every minute, overridden at the given minutes (m12=..., m13=...)."""
    out = {m: value for m in range(minutes)}
    out.update({int(k[1:]): v for k, v in at.items()})
    return out


def quiet(svc_minutes=25):
    return {"error_ratio": flat(0.0, svc_minutes), "p95_latency_ms": flat(20.0, svc_minutes),
            "warn_logs": flat(0, svc_minutes), "cpu": flat(0.05, svc_minutes), "memory": flat(50 * 2**20, svc_minutes)}


def test_robust_z_uses_the_first_ten_minutes_as_reference_and_only_increases():
    assert REFERENCE_MINUTES == 10
    f = {"payment": {**quiet(), "error_ratio": flat(0.0, m14=1.0, m15=1.0)},
         "cart": {**quiet(), "p95_latency_ms": flat(20.0, m3=500.0, m16=10.0)}}  # a spike in the reference, a drop later
    z = robust_scores(f)
    assert z["payment"]["error_ratio"] == pytest.approx(1.0 / 0.01)  # (max - median) / floor 0.01
    assert z["cart"]["p95_latency_ms"] == 0.0  # drops never score; a reference spike only widens nothing (median)
    assert all(v == 0.0 for k, v in z["cart"].items())


def test_features_without_enough_reference_or_check_minutes_do_not_score():
    f = {"email": {**quiet(), "memory": {12: 10.0, 13: 2.0**31}}}  # no reference minutes at all
    assert "memory" not in robust_scores(f)["email"]
    f = {"email": {**quiet(), "cpu": {m: 0.05 for m in range(10)}}}  # nothing after the reference
    assert "cpu" not in robust_scores(f)["email"]


def test_prediction_ranks_services_and_maps_the_top_feature_to_a_fault_type():
    f = {svc: quiet() for svc in ("payment", "checkout", "frontend", "frontend-proxy", "cart", "email")}
    f["payment"]["error_ratio"] = flat(0.0, m12=1.0)
    f["checkout"]["error_ratio"] = flat(0.0, m12=0.6)
    f["frontend"]["error_ratio"] = flat(0.0, m12=0.2)
    f["frontend-proxy"]["error_ratio"] = flat(0.0, m12=0.02)  # z = 2: below the threshold
    pred = predict_from_features(f, incident_id="INC-001")
    assert pred["origin_candidates"][:3] == ["payment", "checkout", "frontend"]
    assert set(pred["affected_services"]) == {"payment", "checkout", "frontend"}
    assert pred["fault"] == {"fault_type": "error_response", "fault_family": None}
    assert pred["user_symptom"]["kinds"] == ["errors"]  # frontend's error ratio z >= 3
    assert pred["method"] == {"name": "stat-anomaly", "version": "2"}
    assert check_prediction(pred) == []


def test_resource_and_latency_faults_and_a_quiet_incident():
    f = {svc: quiet() for svc in ("email", "frontend", "frontend-proxy")}
    f["email"]["memory"] = flat(50 * 2**20, m15=400 * 2**20)
    pred = predict_from_features(f, incident_id="INC-002")
    assert pred["origin_candidates"][0] == "email" and pred["fault"]["fault_type"] == "memory_leak"
    assert pred["user_symptom"]["kinds"] == ["none"]
    f["frontend-proxy"]["p95_latency_ms"] = flat(20.0, m14=400.0)
    assert "latency" in predict_from_features(f, incident_id="INC-002")["user_symptom"]["kinds"]
    calm = predict_from_features({svc: quiet() for svc in ("email", "cart")}, incident_id="INC-003")
    assert calm["origin_candidates"] == [] and calm["fault"]["fault_type"] is None
    assert calm["affected_services"] == []


def test_v2_thresholds_come_from_fault_free_runs_and_scores_are_compared_in_threshold_units():
    # decision 014 revision 1: T_f = max(3, the largest z of any service on the fault-free calibration snapshots)
    assert NULL_THRESHOLDS == {"error_ratio": 3.0, "p95_latency_ms": 45.0, "warn_logs": 3.0, "cpu": 3.6, "memory": 34.0}
    f = {svc: quiet() for svc in ("payment", "cart", "frontend", "frontend-proxy")}
    f["cart"]["p95_latency_ms"] = flat(20.0, m14=100.0)  # z = 40: a fault-free run has seen 44.9
    f["payment"]["error_ratio"] = flat(0.0, m14=0.04)  # z = 4 of 3
    pred = predict_from_features(f, incident_id="INC-004")
    assert pred["origin_candidates"][:2] == ["payment", "cart"]  # 4 / 3 > 40 / 45
    assert pred["affected_services"] == ["payment"] and pred["fault"]["fault_type"] == "error_response"
    f["frontend-proxy"]["p95_latency_ms"] = flat(20.0, m14=100.0)  # z = 40 < 45: not a user-facing slowdown
    assert predict_from_features(f, incident_id="INC-004")["user_symptom"]["kinds"] == ["none"]


def test_minutes_without_a_warn_log_count_as_zero_for_every_service():
    # clock audit / decision 014 §2: warn_logs is a per-minute count; a service with no spans (kafka) still scores
    from baselines.statistical import features

    M = 60 * 10**9

    class Snap:
        services = ["kafka"]
        window = {"start_ns": 0, "end_ns": 25 * M}

        def spans(self):
            return iter(())

        def logs(self):
            return iter([{"service": "kafka", "time_unix_nano": 15 * M + k, "observed_time_unix_nano": None,
                          "severity_number": 13} for k in range(200)])

        def series(self):
            return iter(())

        def points(self):
            return iter(())

    f = features(Snap())
    assert f["kafka"]["warn_logs"] == {m: (200 if m == 15 else 0) for m in range(25)}
    assert robust_scores(f)["kafka"]["warn_logs"] == 200.0
