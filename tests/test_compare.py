"""Paired comparison of two methods on the same incidents (decision 023 §7): run-group cluster bootstrap, LOFO."""

import pytest

from eval.compare import lofo, paired


def rows(values, faults=None):
    return [{"incident_id": f"INC-{i:03d}", "run_group_id": f"RG-{i:03d}", "origin_top1": v,
             **({"fault": faults[i - 1]} if faults else {})} for i, v in enumerate(values, start=1)]


def test_the_difference_uses_the_same_resampled_run_groups_for_both_methods():
    a = rows([1, 1, 1, 1, 0, 1, 1, 1, 0, 1])
    b = rows([0, 1, 0, 1, 0, 0, 1, 0, 0, 1])
    out = paired(a, b, "origin_top1", resamples=2000)
    assert out["n"] == 10 and out["mean_diff"] == pytest.approx(0.4)
    assert out["ci95"][0] > 0 and out["ci95"][1] <= 1  # a always >= b on every incident: the lower bound stays positive
    same = paired(a, a, "origin_top1", resamples=500)
    assert same["mean_diff"] == 0 and same["ci95"] == [0, 0]
    assert paired(a, b, "origin_top1", resamples=2000) == out  # seed 0: reproducible


def test_only_incidents_scored_for_both_methods_count_and_a_mismatch_is_reported():
    a = rows([1, 1, 1])
    b = rows([0, 1])
    out = paired(a, b, "origin_top1", resamples=200)
    assert out["n"] == 2 and out["only_in_one"] == ["INC-003"]
    with pytest.raises(ValueError, match="no incident"):
        paired(a, [], "origin_top1")


def test_leave_one_fault_out_gives_one_bound_per_fault():
    faults = ["f1", "f1", "f2", "f2", "f3", "f3"]
    a = rows([1, 1, 1, 1, 1, 0], faults)
    b = rows([0, 0, 1, 1, 1, 0], faults)
    out = lofo(a, b, "origin_top1", resamples=500)
    assert set(out) == {"f1", "f2", "f3"}
    assert out["f1"]["n"] == 4 and out["f1"]["mean_diff"] == 0  # without f1 the methods agree everywhere
    assert out["f2"]["mean_diff"] == pytest.approx(0.5)


def test_a_fault_that_is_all_there_is_leaves_nothing_to_compare():
    a, b = rows([1, 0], ["f1", "f1"]), rows([0, 0], ["f1", "f1"])
    assert lofo(a, b, "origin_top1", resamples=100) == {"f1": {"metric": "origin_top1", "n": 0, "mean_diff": None, "ci95": None}}
