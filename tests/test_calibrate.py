"""Calibrating the normalize policy on soak raw (no fault) before it is frozen (decision 011 §4)."""

import json

from collect.calibrate import calibrate, inventory
from normalize_fixtures import write_raw


def test_inventory_lists_what_the_policy_must_know_about(tmp_path):
    files = write_raw(tmp_path / "raw")
    inv = inventory(tmp_path / "raw")
    assert inv["services"]["traces"]["checkout"] >= 1 and "load-generator" in inv["services"]["traces"]
    scopes = inv["metric_scopes"]
    assert any("dockerstatsreceiver" in s for s in scopes) and any("postgresqlreceiver" in s for s in scopes)
    assert "checkout" in inv["docker_container_names"] and "flagd" in inv["docker_container_names"]
    assert "rpc.service" in inv["attribute_keys"]["traces"]["checkout"]
    assert "feature_flag.evaluation" in inv["event_names"]
    assert inv["unknown_fields"] == {}
    assert files


def test_calibrate_runs_normalize_dry_over_the_whole_soak_and_reports(tmp_path):
    soak = tmp_path / "soak"
    write_raw(soak / "raw")
    out = calibrate(soak, tmp_path / "calibration")
    assert out["check_problems"] == []
    assert out["report"]["signals"]["traces"]["kept"] >= 3
    assert out["seconds"] >= 0 and out["max_rss_bytes"] > 0
    saved = json.loads((tmp_path / "calibration" / "calibration.json").read_text())
    assert saved["inventory"]["services"] == out["inventory"]["services"]
