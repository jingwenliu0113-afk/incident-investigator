"""Writing an incident's a priori label from its injection record (decisions 006, 010)."""

import json

import pytest

from collect.labeling import catalog_label
from collect.layout import DataLayout
from collect.traffic import TRAFFIC_PROFILES
from test_records import injection, manifest

NOW = "2026-10-08T15:00:00Z"
DECISION_010 = dict(origin="payment", affected=["payment", "checkout", "frontend", "frontend-proxy"],
                    symptom_kinds=["errors"], symptom_description="orders fail: failed to charge card")


@pytest.fixture
def stored(tmp_path):
    layout = DataLayout(tmp_path / "data")
    truth = layout.run_group_truth_dir("RG-001")
    truth.mkdir(parents=True)
    inj = injection()
    layout.injection_path("RG-001").write_text(json.dumps(inj))
    (truth / "run.json").write_text(json.dumps({"run_group_id": "RG-001", "status": "valid", "incident_ids": ["INC-001"]}))
    m = manifest(traffic={"generator_service": "load-generator", "settings": dict(TRAFFIC_PROFILES["locust-upstream-3.1.0"]),
                          "seed": None, "seed_applied": False})
    layout.incident_dir("INC-001").mkdir(parents=True)
    layout.manifest_path("INC-001").write_text(json.dumps(m))
    return layout, inj


def test_catalog_label_takes_the_answer_facts_from_the_injection_record(stored):
    layout, inj = stored
    label = catalog_label(layout, "INC-001", labeler="agent:claude-code", now=NOW, **DECISION_010)
    assert label["fault_start"] == inj["schedule"]["fault_on"] and label["fault_end"] == inj["schedule"]["fault_off"]
    assert label["injected_fault"] == {"fault_type": "error_response", "flag": "paymentFailure", "variant": "100%"}
    assert label["fault_family"] == "error" and label["seed"] == inj["seed"] and label["run_group_id"] == "RG-001"
    assert label["traffic_profile"] == "locust-upstream-3.1.0"
    assert label["labeling"] == {"method": "catalog", "labeled_at": NOW, "labeler": "agent:claude-code"}
    assert "telemetry_coverage" not in label  # only a review against the snapshot can know it (decision 006)
    saved = json.loads(layout.label_path("INC-001").read_text())
    assert saved == label and layout.is_ground_truth(layout.label_path("INC-001"))


def test_a_label_that_fails_its_checks_is_never_written(stored):
    layout, _ = stored
    with pytest.raises(ValueError, match="origin_service"):
        catalog_label(layout, "INC-001", labeler="agent:claude-code", now=NOW,
                      **{**DECISION_010, "affected": ["checkout", "frontend"]})  # origin must be affected
    with pytest.raises(ValueError, match="unknown service"):
        catalog_label(layout, "INC-001", labeler="agent:claude-code", now=NOW,
                      **{**DECISION_010, "affected": ["payment", "load-generator"]})  # not one of the 18 SUT services
    assert not layout.label_path("INC-001").exists()


def test_an_existing_label_is_never_overwritten(stored):
    layout, _ = stored
    catalog_label(layout, "INC-001", labeler="agent:claude-code", now=NOW, **DECISION_010)
    with pytest.raises(FileExistsError):
        catalog_label(layout, "INC-001", labeler="agent:claude-code", now=NOW, **DECISION_010)


def test_label_cli_writes_the_catalog_label_and_reports_problems_with_exit_2(stored, monkeypatch, capsys):
    import collect.__main__ as cli

    layout, _ = stored
    monkeypatch.setattr(cli, "PROJECT_DIR", layout.root.parent.parent)  # data/external lives under it
    layout_root = layout.root
    monkeypatch.setattr(cli, "DataLayout", lambda root: DataLayout(layout_root))
    args = ["label", "--incident", "INC-001", "--origin", "payment", "--affected", "payment,checkout,frontend,frontend-proxy",
            "--symptom", "errors", "--description", "orders fail", "--labeler", "agent:claude-code"]
    assert cli.main(args) == 0 and json.loads(layout.label_path("INC-001").read_text())["origin_service"] == "payment"
    assert cli.main(args) == 2 and "never overwritten" in capsys.readouterr().err
