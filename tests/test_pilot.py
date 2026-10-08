"""The pre-registered Pilot list and its a priori labels (decision 016), written before any of its faults is collected."""

import json

import pytest

from collect.__main__ import FLAG_FILE, main
from collect.faults import inject
from collect.labeling import catalog_label_from_plan
from collect.labels import FLAG_FAULT_TYPES
from collect.layout import DataLayout
from collect.pilot import PLANS, planned
from collect.policy import load_policy
from collect.traffic import TRAFFIC_PROFILES
from test_records import injection, manifest

PILOT = PLANS["pilot"]
NOW = "2026-10-08T16:00:00Z"


def test_the_pilot_has_ten_distinct_faults_and_the_first_is_decision_010():
    assert len(PILOT) == 10  # SPEC §5: about 10 incidents
    assert len({e["flag"] for e in PILOT}) == 10  # one variant per flag
    assert PILOT[0] == {"flag": "paymentFailure", "variant": "100%", "origin": "payment",
                        "affected": ["payment", "checkout", "frontend", "frontend-proxy"], "symptom_kinds": ["errors"],
                        "description": "orders fail: failed to charge card", "notes": None}
    # decision 016: two injection points (no single origin) and an origin outside the snapshot are not Pilot faults
    assert not {e["flag"] for e in PILOT} & {"kafkaQueueProblems", "loadGeneratorFloodHomepage"}


@pytest.mark.parametrize("entry", PILOT, ids=lambda e: e["flag"])
def test_every_entry_is_a_core_fault_that_injects_and_names_snapshot_services(entry):
    assert entry["flag"] in FLAG_FAULT_TYPES
    inject(json.loads(FLAG_FILE.read_text()), entry["flag"], entry["variant"])  # raises if it would inject nothing
    sut = set(load_policy().sut_services)
    assert entry["origin"] in entry["affected"] and set(entry["affected"]) <= sut
    assert entry["symptom_kinds"] == ["none"] or "none" not in entry["symptom_kinds"]


def test_planned_finds_only_the_registered_variant():
    assert planned("pilot", "cartFailure", "100%")["origin"] == "cart"
    assert planned("pilot", "cartFailure", "10%") is None
    assert planned("pilot", "kafkaQueueProblems", "on") is None
    with pytest.raises(LookupError, match="no fault plan"):
        planned("heldout", "paymentFailure", "100%")  # held-out waits for its own protocol


def stored(root, flag, variant):
    layout = DataLayout(root)
    truth = layout.run_group_truth_dir("RG-001")
    truth.mkdir(parents=True)
    layout.injection_path("RG-001").write_text(json.dumps(
        injection(fault={"mechanism": "flagd", "flag": flag, "variant": variant})))
    (truth / "run.json").write_text(json.dumps({"run_group_id": "RG-001", "status": "valid", "incident_ids": ["INC-001"]}))
    layout.incident_dir("INC-001").mkdir(parents=True)
    layout.manifest_path("INC-001").write_text(json.dumps(manifest(
        traffic={"generator_service": "load-generator", "settings": dict(TRAFFIC_PROFILES["locust-upstream-3.1.0"]),
                 "seed": None, "seed_applied": False})))
    return layout


@pytest.mark.parametrize("entry", PILOT, ids=lambda e: e["flag"])
def test_the_a_priori_label_comes_from_the_plan_and_passes_its_checks(tmp_path, entry):
    layout = stored(tmp_path / "data", entry["flag"], entry["variant"])
    label = catalog_label_from_plan(layout, "INC-001", labeler="agent:claude-code", now=NOW)
    assert label["origin_service"] == entry["origin"] and label["affected_services"] == entry["affected"]
    assert label["user_symptom"] == {"kinds": entry["symptom_kinds"], "description": entry["description"]}
    assert label["labeling"].get("notes") == entry["notes"]
    assert label["injected_fault"]["fault_type"] == FLAG_FAULT_TYPES[entry["flag"]]


def test_an_incident_off_the_plan_gets_no_label(tmp_path):
    layout = stored(tmp_path / "data", "cartFailure", "10%")
    with pytest.raises(LookupError, match="not in the pilot plan"):
        catalog_label_from_plan(layout, "INC-001", labeler="agent:claude-code", now=NOW)
    assert not layout.label_path("INC-001").exists()


def test_a_pilot_run_must_be_on_the_plan(capsys):
    assert main(["run", "--set", "pilot", "--flag", "cartFailure", "--variant", "10%"]) == 2
    assert "pilot plan" in capsys.readouterr().err
    assert main(["run", "--set", "pilot", "--flag", "kafkaQueueProblems", "--variant", "on"]) == 2


def test_the_label_command_takes_the_answer_from_the_plan(tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli

    layout = stored(tmp_path / "data/external", "adManualGc", "on")
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    assert main(["label", "--incident", "INC-001", "--labeler", "agent:claude-code"]) == 0
    assert json.loads(layout.label_path("INC-001").read_text())["origin_service"] == "ad"
    out = capsys.readouterr().out
    assert "ad" not in json.loads(out).values()  # ground truth: only say that it was written
