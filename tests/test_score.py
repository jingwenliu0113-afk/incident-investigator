"""Layered scoring (SPEC Core §8, decision 013): injected fault, origin, affected services and user symptom, never one string."""

import pytest

from eval.score import aggregate, check_prediction, score_incident

LABEL = {"incident_id": "INC-001", "run_group_id": "RG-001", "fault_family": "error",
         "injected_fault": {"fault_type": "error_response", "flag": "paymentFailure", "variant": "100%"},
         "origin_service": "payment", "affected_services": ["payment", "checkout", "frontend", "frontend-proxy"],
         "user_symptom": {"kinds": ["errors"]}}


def pred(**over):
    p = {"prediction_version": 1, "incident_id": "INC-001", "method": {"name": "stat", "version": "1"},
         "fault": {"fault_type": "error_response", "fault_family": None},
         "origin_candidates": ["payment", "checkout"], "affected_services": ["payment", "checkout"],
         "user_symptom": {"kinds": ["errors"]}, "evidence": [], "usage": {}}
    p.update(over)
    return p


def test_a_prediction_is_scored_layer_by_layer():
    s = score_incident(pred(), LABEL)
    assert s["fault_type"] == 1 and s["fault_family"] == 1  # the family follows from the type when not given
    assert s["origin_top1"] == 1 and s["origin_top3"] == 1 and s["origin_rr"] == 1.0
    assert s["affected_precision"] == 1.0 and s["affected_recall"] == 0.5 and s["affected_f1"] == pytest.approx(2 / 3)
    assert s["affected_jaccard"] == 0.5 and s["symptom_exact"] == 1 and s["symptom_jaccard"] == 1.0
    assert "root_cause" not in s  # SPEC §8: no single string


def test_origin_rank_abstention_and_wrong_answers():
    s = score_incident(pred(origin_candidates=["checkout", "frontend", "payment"]), LABEL)
    assert s["origin_top1"] == 0 and s["origin_top3"] == 1 and s["origin_rr"] == pytest.approx(1 / 3)
    s = score_incident(pred(origin_candidates=[], fault={"fault_type": None, "fault_family": "error"},
                            affected_services=[], user_symptom={"kinds": ["latency"]}), LABEL)
    assert s["origin_top1"] == 0 and s["origin_rr"] == 0.0  # abstaining is wrong, not skipped
    assert s["fault_type"] == 0 and s["fault_family"] == 1  # a family alone can still be right
    assert s["affected_f1"] == 0.0 and s["symptom_exact"] == 0 and s["symptom_jaccard"] == 0.0


def test_predictions_are_checked_against_the_schema_and_the_service_vocabulary():
    assert check_prediction(pred()) == []
    assert check_prediction(pred(origin_candidates=["payment"] * 2))  # unique
    assert check_prediction(pred(origin_candidates=["a", "b", "c", "d", "e", "f"]))  # at most 5
    assert any("load-generator" in p for p in check_prediction(pred(affected_services=["load-generator"])))
    assert check_prediction(pred(fault={"fault_type": "rootcause", "fault_family": None}))
    assert check_prediction({**pred(), "root_cause": "payment"})  # no free-form answer field


def test_aggregate_reports_means_with_a_run_group_cluster_bootstrap():
    scores = [score_incident(pred(), LABEL) | {"run_group_id": f"RG-{i:03d}"} for i in range(1, 5)]
    scores.append(score_incident(pred(origin_candidates=["checkout"]), LABEL) | {"run_group_id": "RG-005"})
    agg = aggregate(scores, seed=0, resamples=2000)
    assert agg["n_incidents"] == 5 and agg["n_run_groups"] == 5
    o = agg["metrics"]["origin_top1"]
    assert o["mean"] == pytest.approx(0.8) and 0.0 <= o["ci95"][0] <= 0.8 <= o["ci95"][1] <= 1.0
    assert aggregate(scores, seed=0, resamples=2000) == agg  # deterministic given the seed
    # incidents of the same run group move together in a resample (SPEC §10: never split a run group)
    same = [s | {"run_group_id": "RG-001"} for s in scores]
    assert aggregate(same, seed=0, resamples=500)["metrics"]["origin_top1"]["ci95"] == [0.8, 0.8]


def test_the_prediction_schema_uses_the_label_vocabulary():
    import json
    from pathlib import Path

    from collect.labels import FAULT_TYPES

    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas/prediction.schema.json").read_text())
    fault = schema["properties"]["fault"]["properties"]
    assert set(fault["fault_type"]["enum"]) - {None} == set(FAULT_TYPES)
    assert set(fault["fault_family"]["enum"]) - {None} == set(FAULT_TYPES.values())
