"""Where a finished run group's records and raw telemetry go (decisions 002 / 008 / 009)."""

import json

import pytest

from collect.layout import DataLayout
from collect.records import check_injection, load_flag_catalog
from collect.rungroup import next_id, store_run_group

LOCK = "sha256:" + "1" * 64


@pytest.fixture
def catalog(tmp_path):
    p = tmp_path / "flags.json"
    p.write_text(json.dumps({"flags": {"paymentFailure": {"defaultVariant": "off", "variants": {"off": 0, "100%": 1}}}}))
    return load_flag_catalog(p)


def finished(tmp_path, status="valid"):
    work = tmp_path / "work"
    (work / "raw").mkdir(parents=True)
    for sig, top in (("traces", "resourceSpans"), ("metrics", "resourceMetrics"), ("logs", "resourceLogs")):
        (work / "raw" / f"{sig}.jsonl").write_text(json.dumps({top: []}) + "\n")
    (work / "samples.jsonl").write_text("{}\n")
    (work / "docker-events.jsonl").write_text("")
    (work / "otel-collector-shutdown.log").write_text("Shutdown complete.\n")
    from collect.rawfile import scan_raw_file
    rec = {
        "run_group_id": "RG-001", "status": status, "reasons": [] if status == "valid" else ["normal_period_not_clean"],
        "plan": {"seed": 7, "flag": "paymentFailure", "variant": "100%"},
        "flag": {"path": "demo.flagd.json", "baseline_sha256": "sha256:" + "b" * 64, "injected_sha256": "sha256:" + "c" * 64},
        "schedule": {"normal_start": "2026-10-08T12:05:00Z", "fault_on": "2026-10-08T12:17:00Z",
                     "fault_off": "2026-10-08T12:27:00Z", "end": "2026-10-08T12:32:00Z"},
        "raw": {"collector": {"container_id": "c", "restarts": 0, "stop_exit_code": 0, "stop_seconds": 1.0,
                              "cp_seconds": 1.0, "copied": True},
                "files": {sig: scan_raw_file(work / "raw" / f"{sig}.jsonl", sig) for sig in ("traces", "metrics", "logs")}},
    }
    rec["raw_accounting"] = {"accounting_version": 1, "window_ns": [1, 2], "snapshots": {"base": 1, "final": 3},
                             "signals": {}, "sdk_errors": {"kafka": {"otel.sdk.exporter.log.exported X": 4}}, "flags": []}
    if status == "valid":
        rec["incident_window"] = {"start": "2026-10-08T12:05:00Z", "end": "2026-10-08T12:32:00Z"}
    return rec, work


def test_next_id_counts_past_everything_already_on_disk(tmp_path):
    layout = DataLayout(tmp_path / "data")
    assert next_id(layout, "RG") == "RG-001" and next_id(layout, "INC") == "INC-001"
    layout.raw_dir("RG-004").mkdir(parents=True)
    layout.run_group_truth_dir("RG-002").mkdir(parents=True)
    layout.label_path("INC-009").parent.mkdir(parents=True)
    assert next_id(layout, "RG") == "RG-005" and next_id(layout, "INC") == "INC-010"


def test_valid_run_gets_an_incident_and_records_on_the_right_sides(tmp_path, catalog):
    layout = DataLayout(tmp_path / "data")
    rec, work = finished(tmp_path)
    out = store_run_group(rec, work, layout, lock_sha256=LOCK)
    assert out["incident_ids"] == ["INC-001"]
    raw = layout.raw_dir("RG-001")
    assert sorted(p.name for p in raw.iterdir()) == ["logs.jsonl", "metrics.jsonl", "raw_export.json", "traces.jsonl"]
    export = json.loads((raw / "raw_export.json").read_text())
    assert export["complete"] is True
    assert export["accounting"]["sdk_errors"] == {"kafka": {"otel.sdk.exporter.log.exported X": 4}}  # decision 008 §6
    truth = layout.run_group_truth_dir("RG-001")
    injection = json.loads((truth / "injection.json").read_text())
    assert check_injection(injection, catalog) == []
    assert injection["incident_ids"] == ["INC-001"] and injection["schedule"] == rec["schedule"]
    run = json.loads((truth / "run.json").read_text())
    assert run["status"] == "valid" and run["incident_ids"] == ["INC-001"] and run["raw_dir"] == "raw/RG-001"
    assert (truth / "harness" / "samples.jsonl").exists()  # sampled timings reveal the fault: ground-truth side
    assert (truth / "harness" / "otel-collector-shutdown.log").exists()  # R7 evidence (decision 008 revision)
    # nothing about the run group or the fault lands on the agent-readable side
    assert not layout.incidents_root.exists() or not any(layout.incidents_root.rglob("*"))
    assert not work.exists()


def test_invalid_run_keeps_its_evidence_but_gets_no_incident(tmp_path):
    layout = DataLayout(tmp_path / "data")
    rec, work = finished(tmp_path, status="invalid")
    out = store_run_group(rec, work, layout, lock_sha256=LOCK)
    assert out["incident_ids"] == []
    truth = layout.run_group_truth_dir("RG-001")
    assert not (truth / "injection.json").exists()
    assert json.loads((truth / "run.json").read_text())["status"] == "invalid"
    assert (layout.raw_dir("RG-001") / "traces.jsonl").exists()


def test_store_refuses_to_overwrite_an_existing_run_group(tmp_path):
    layout = DataLayout(tmp_path / "data")
    layout.run_group_truth_dir("RG-001").mkdir(parents=True)
    rec, work = finished(tmp_path)
    with pytest.raises(FileExistsError):
        store_run_group(rec, work, layout, lock_sha256=LOCK)
