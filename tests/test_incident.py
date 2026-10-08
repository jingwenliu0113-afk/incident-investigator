"""Normalize one stored incident and write its manifest (decisions 002, 011)."""

import json

import pytest

from collect.incident import find_run, normalize_incident
from collect.layout import DataLayout
from collect.policy import Policy, load_policy
from collect.rawexport import build_raw_export
from collect.rawfile import scan_raw_file
from collect.records import check_manifest
from normalize_fixtures import HOST_END, HOST_START, write_raw

LOCK = "sha256:" + "1" * 64


def frozen():
    p = load_policy()
    return Policy({**p.raw, "status": "frozen"}, p.sha256)
PROVENANCE = {
    "project": {"commit": "c" * 40, "dirty": False},
    "env_lock": {"path": "env/otel-demo.lock.json", "sha256": LOCK, "upstream_tag": "3.1.0",
                 "upstream_commit": "dedc0178918e260823323b8d95005a8cb924b007"},
    "machine": {"role": "mac", "os": "Darwin 27.0.0", "arch": "arm64", "cpu_model": "Apple M4 Pro", "cpu_count": 12,
                "memory_bytes": 51539607552,
                "docker": {"server_version": "29.8.1", "platform": "linux/arm64", "operating_system": "Docker Desktop",
                           "cpus": 12, "memory_bytes": 16745562112}},
    "compose_command": ["docker", "compose", "up", "--detach"],
    "traffic_settings": {"LOCUST_USERS": "5"},
}


@pytest.fixture
def stored(tmp_path):
    layout = DataLayout(tmp_path / "data")
    files = write_raw(layout.raw_dir("RG-001"))
    scans = {sig: scan_raw_file(p, sig) for sig, p in files.items()}
    collector = {"container_id": "c", "restarts": 0, "stop_exit_code": 0, "stop_seconds": 1.0, "cp_seconds": 1.0, "copied": True}
    layout.raw_export_path("RG-001").write_text(json.dumps(build_raw_export("RG-001", LOCK, collector, scans)))
    truth = layout.run_group_truth_dir("RG-001")
    truth.mkdir(parents=True)
    run = {"run_group_id": "RG-001", "status": "valid", "incident_ids": ["INC-001"], "raw_dir": "raw/RG-001",
           "plan": {"seed": 7}, "up_at": "2026-10-08T11:40:00Z", "clock_offset_seconds": [0.0, 0.0],
           "incident_window": {"start": HOST_START, "end": HOST_END}, "provenance": PROVENANCE, "env_lock_sha256": LOCK}
    (truth / "run.json").write_text(json.dumps(run))
    return layout


def test_find_run_by_incident_id(stored):
    run = find_run(stored, "INC-001")
    assert run["run_group_id"] == "RG-001"
    with pytest.raises(LookupError):
        find_run(stored, "INC-002")


def test_normalize_incident_writes_snapshot_report_and_a_formal_manifest(stored):
    out = normalize_incident(stored, "INC-001", lock_sha256=LOCK, now="2026-10-08T13:00:00Z", policy=frozen())
    inc = stored.incident_dir("INC-001")
    assert (inc / "normalized" / "snapshot.json").exists()
    assert stored.normalize_report_path("INC-001").exists()
    manifest = json.loads(stored.manifest_path("INC-001").read_text())
    assert check_manifest(manifest, formal=True, lock_sha256=LOCK) == []
    assert manifest["window"] == {"start": HOST_START, "end": HOST_END} and manifest["seed"] == 7
    assert sorted(f["path"] for f in manifest["files"]) == sorted(
        f"normalized/{n}" for n in ("snapshot.json", "resources.jsonl", "spans.jsonl", "logs.jsonl",
                                    "metric_series.jsonl", "metric_points.jsonl"))
    assert "RG-001" not in stored.manifest_path("INC-001").read_text()  # the run group stays on the truth side
    assert out["content_sha256"].startswith("sha256:")


def test_invalid_or_incomplete_runs_are_never_normalized(stored):
    truth = stored.run_group_truth_dir("RG-001") / "run.json"
    run = json.loads(truth.read_text())
    truth.write_text(json.dumps({**run, "status": "invalid"}))
    with pytest.raises(LookupError):
        normalize_incident(stored, "INC-001", lock_sha256=LOCK, now="2026-10-08T13:00:00Z", policy=frozen())
    truth.write_text(json.dumps(run))
    export = json.loads(stored.raw_export_path("RG-001").read_text())
    stored.raw_export_path("RG-001").write_text(json.dumps({**export, "complete": False, "flags": ["copy_failed"]}))
    with pytest.raises(ValueError, match="complete"):
        normalize_incident(stored, "INC-001", lock_sha256=LOCK, now="2026-10-08T13:00:00Z", policy=frozen())


def test_fault_raw_is_never_normalized_with_a_policy_that_is_not_frozen(stored):
    # decision 011 §4: the rules are calibrated on soak raw only, then frozen, before any fault raw is opened
    calibrating = Policy({**load_policy().raw, "status": "calibrating"}, load_policy().sha256)
    with pytest.raises(PermissionError, match="frozen"):
        normalize_incident(stored, "INC-001", lock_sha256=LOCK, now="2026-10-08T13:00:00Z", policy=calibrating)
    assert not stored.incident_dir("INC-001").exists()
