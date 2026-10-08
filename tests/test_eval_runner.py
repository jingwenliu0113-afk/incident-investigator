"""Running a method over one set and scoring it (SPEC Core §7–§10; decisions 013, 014)."""

import json

import pytest

from collect.layout import DataLayout
from collect.normalize import NormalizeInputs, normalize
from collect.policy import load_policy
from collect.rawfile import scan_raw_file
from eval.runner import METHODS, audit_set, incidents_in, run_method, score_method
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
    audit_set(layout, "pilot", out)
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


def test_evidence_relevance_weak_labels_a_blind_gold_worksheet_and_gold_precision(tmp_path, monkeypatch):
    from baselines.statistical import predict
    from collect.snapshot import open_snapshot
    from eval.runner import gold_add, gold_todo_set

    layout = stored(tmp_path / "data")
    snap = open_snapshot(layout.incident_dir("INC-001") / "normalized", layout)
    spans = [s["id"] for s in snap.spans()][:3]

    def cites(snapshot, incident_id):
        return {**predict(snapshot, incident_id), "evidence": [{"id": i} for i in spans] + [{"id": "s-" + "f" * 16}]}

    monkeypatch.setitem(METHODS, "cites", cites)
    out = tmp_path / "results"
    run_method(layout, "cites", "pilot", out)
    audit_set(layout, "pilot", out)
    todo = gold_todo_set(layout, "pilot", out)
    path = layout.label_path("INC-001").with_name("evidence_gold_todo.json")
    assert todo["incidents"] == [{"incident_id": "INC-001", "to_judge": 3}] and layout.is_ground_truth(path)
    sheet = json.loads(path.read_text())
    assert sheet["context"]["origin_service"] == "payment" and len(sheet["items"]) == 3
    assert all(set(e) == {"id", "t0", "t1", "record", "relevant"} and e["relevant"] is None for e in sheet["items"])
    assert "cites" not in path.read_text()  # blind: no method name

    sheet["items"][0]["relevant"] = True
    sheet["items"][1]["relevant"] = False  # the third is left for later
    filled = tmp_path / "filled.json"
    filled.write_text(json.dumps(sheet))
    assert gold_add(layout, "INC-001", filled, annotator="human:jw", now="2026-10-09T10:00:00Z") == {"added": 2, "unjudged": 1}
    assert gold_todo_set(layout, "pilot", out)["incidents"][0]["to_judge"] == 1

    result = score_method(layout, "cites", "pilot", out)
    row = result["incidents"][0]
    assert row["evidence_existence"] == 0.75 and row["evidence_weak"]["n"] == 3
    assert row["evidence_gold"] == {"cited": 3, "judged": 2, "relevant": 1, "precision": 0.5, "coverage": 2 / 3}
    assert result["evidence"]["gold_precision"]["n"] == 1 and "weak" in result["evidence"]
    table = (out / "pilot" / "cites" / "table.md").read_text()
    assert "gold precision" in table and "weak" in table and "existence" in table


def test_eval_cli_checks_its_arguments_and_gold_add_refuses_an_agent(tmp_path, monkeypatch, capsys):
    import eval.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["gold-add", "--incident", "INC-001"])  # needs --file and --annotator
    with pytest.raises(SystemExit):
        cli.main(["leakage"])  # needs --set
    assert cli.main(["gold-todo", "--set", "pilot"]) == 0  # an empty set: nothing to judge
    sheet = tmp_path / "s.json"
    sheet.write_text(json.dumps({"items": [{"id": "s-" + "a" * 16, "t0": None, "t1": None, "relevant": True}]}))
    assert cli.main(["gold-add", "--incident", "INC-001", "--file", str(sheet), "--annotator", "agent:claude-code"]) == 2
    assert "human" in capsys.readouterr().err


def test_scoring_needs_the_leakage_audit_drops_lexicon_hits_and_reports_by_difficulty(tmp_path):
    # decision 015: an incident whose snapshot hits the lexicon enters no score; reports are layered by difficulty
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    run_method(layout, "stat-anomaly", "pilot", out)
    with pytest.raises(LookupError, match="leakage"):
        score_method(layout, "stat-anomaly", "pilot", out)
    audit_set(layout, "pilot", out)
    difficulty = json.loads(layout.label_path("INC-001").with_name("leakage_audit.json").read_text())["difficulty"]
    result = score_method(layout, "stat-anomaly", "pilot", out)
    assert result["incidents"][0]["difficulty"] == difficulty and result["excluded"] == []
    assert result["by_difficulty"][difficulty]["n_incidents"] == 1
    assert set(result["by_difficulty"][difficulty]["metrics"]) == {"fault_type", "origin_top1", "affected_f1", "symptom_exact"}
    assert "by difficulty" in (out / "pilot" / "stat-anomaly" / "table.md").read_text()

    path = layout.label_path("INC-001").with_name("leakage_audit.json")
    path.write_text(json.dumps({**json.loads(path.read_text()), "lexicon_hits": 2}))
    result = score_method(layout, "stat-anomaly", "pilot", out)
    assert result["aggregate"]["n_incidents"] == 0 and result["incidents"] == []
    assert result["excluded"] == [{"incident_id": "INC-001", "reason": "lexicon_hits=2 (decision 015)"}]
    assert "INC-001" in (out / "pilot" / "stat-anomaly" / "table.md").read_text()
