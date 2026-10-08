"""Running a method over one set and scoring it (SPEC Core §7–§10; decisions 013, 014)."""

import json

import pytest

from collect.layout import DataLayout
from collect.normalize import NormalizeInputs, normalize
from collect.policy import load_policy
from collect.rawfile import scan_raw_file
from eval.runner import METHODS, incidents_in, run_method, score_method
from normalize_fixtures import HOST_END, HOST_START, write_raw
from test_records import injection

LABEL = {"label_version": 1, "incident_id": "INC-001", "run_group_id": "RG-001", "fault_family": "error",
         "injected_fault": {"fault_type": "error_response", "flag": "paymentFailure", "variant": "100%"},
         "origin_service": "payment", "affected_services": ["payment", "checkout"],
         "user_symptom": {"kinds": ["errors"]}, "fault_start": "2026-10-08T11:50:00Z", "fault_end": "2026-10-08T11:55:00Z",
         "traffic_profile": "locust-upstream-3.1.0", "seed": 42,
         "labeling": {"method": "catalog", "labeled_at": "2026-10-08T13:00:00Z", "labeler": "agent:test"}}


def stored(root, split="pilot", inc="INC-001", rg="RG-001"):
    layout = DataLayout(root)
    files = write_raw(layout.raw_dir(rg))
    scans = {sig: scan_raw_file(p, sig) for sig, p in files.items()}
    inputs = NormalizeInputs(raw_dir=layout.raw_dir(rg), raw_sha256={k: v["sha256"] for k, v in scans.items()},
                             raw_duplicates={k: v["duplicates"] for k, v in scans.items()},
                             window_host=(HOST_START, HOST_END), clock_offsets=[0.0, 0.0])
    normalize(inputs, load_policy(), incident_dir=layout.incident_dir(inc), report_path=layout.normalize_report_path(inc),
              staging_dir=layout.root / "staging" / inc)
    truth = layout.run_group_truth_dir(rg)
    truth.mkdir(parents=True, exist_ok=True)
    layout.injection_path(rg).write_text(json.dumps(injection(run_group_id=rg, incident_ids=[inc], split=split)))
    layout.label_path(inc).write_text(json.dumps({**LABEL, "incident_id": inc, "run_group_id": rg}))
    return layout


def test_incidents_are_chosen_by_the_set_fixed_at_collection(tmp_path):
    layout = stored(tmp_path / "data")
    assert incidents_in(layout, "pilot") == [("INC-001", "RG-001")]
    assert incidents_in(layout, "heldout") == []


def test_a_method_reads_only_the_snapshot_and_its_predictions_are_checked_and_scored(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    paths = run_method(layout, "stat-anomaly", "pilot", out)
    pred = json.loads(paths[0].read_text())
    assert pred["incident_id"] == "INC-001" and pred["method"]["name"] == "stat-anomaly"
    result = score_method(layout, "stat-anomaly", "pilot", out)
    assert result["aggregate"]["n_incidents"] == 1 and "origin_top1" in result["aggregate"]["metrics"]
    assert result["incidents"][0]["run_group_id"] == "RG-001" and "evidence_existence" in result["incidents"][0]
    table = (out / "pilot" / "stat-anomaly" / "table.md").read_text()
    assert "origin_top1" in table and "fault_type" in table and "n = 1" in table

    def bad(snapshot, incident_id):
        return {"prediction_version": 1, "incident_id": incident_id, "root_cause": "payment"}

    monkeypatch.setitem(METHODS, "broken", bad)
    with pytest.raises(ValueError, match="prediction"):
        run_method(layout, "broken", "pilot", tmp_path / "r2")


def test_an_empty_set_scores_to_an_empty_table(tmp_path):
    result = score_method(DataLayout(tmp_path / "data"), "stat-anomaly", "pilot", tmp_path / "results")
    assert result["aggregate"]["n_incidents"] == 0
    assert "n = 0" in (tmp_path / "results" / "pilot" / "stat-anomaly" / "table.md").read_text()


def test_leakage_audit_of_a_set_lands_on_the_ground_truth_side(tmp_path):
    from eval.runner import audit_set

    layout = stored(tmp_path / "data")
    out = audit_set(layout, "pilot", tmp_path / "results")
    path = layout.ground_truth_root / "incidents" / "INC-001" / "leakage_audit.json"
    assert layout.is_ground_truth(path) and json.loads(path.read_text())["difficulty"] in ("easy", "medium", "hard")
    assert out["incidents"][0]["incident_id"] == "INC-001" and out["incidents"][0]["lexicon_hits"] == 0
    assert "difficulty" in (tmp_path / "results" / "pilot" / "leakage.md").read_text()
