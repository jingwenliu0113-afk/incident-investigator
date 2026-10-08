"""Raw export record of one run group (decision 008 §6)."""

import json

import pytest

from collect.rawexport import build_raw_export, check_raw_export
from collect.rawfile import scan_raw_file

LOCK = "sha256:" + "1" * 64


@pytest.fixture
def scans(tmp_path):
    out = {}
    for sig, top in (("traces", "resourceSpans"), ("metrics", "resourceMetrics"), ("logs", "resourceLogs")):
        p = tmp_path / f"{sig}.jsonl"
        p.write_text(json.dumps({top: []}) + "\n")
        out[sig] = scan_raw_file(p, sig)
    return out


def collector(**over):
    c = {"container_id": "c" * 64, "restarts": 0, "stop_exit_code": 0, "stop_seconds": 2.5, "cp_seconds": 1.0,
         "copied": True}
    c.update(over)
    return c


def test_complete_export_has_no_flags_and_passes(scans):
    rec = build_raw_export("RG-001", LOCK, collector(), scans)
    assert rec["complete"] is True and rec["flags"] == []
    assert [f["signal"] for f in rec["files"]] == ["traces", "metrics", "logs"]
    assert rec["files"][0]["path"] == "traces.jsonl"
    assert check_raw_export(rec) == []


@pytest.mark.parametrize("over, flag", [
    ({"restarts": 1}, "collector_restarted"),
    ({"stop_exit_code": 137}, "collector_sigkilled"),
    ({"stop_exit_code": 1}, "collector_unclean_stop"),
    ({"stop_exit_code": 1, "graceful_stop": False}, "collector_unclean_stop"),
    ({"stop_exit_code": None}, "collector_unclean_stop"),  # state unknown
    ({"copied": False}, "copy_failed"),
])
def test_collector_problems_make_the_export_incomplete(scans, over, flag):
    rec = build_raw_export("RG-001", LOCK, collector(**over), scans)
    assert flag in rec["flags"] and rec["complete"] is False
    assert check_raw_export(rec) == []


def test_exit_1_with_a_graceful_shutdown_verdict_is_complete(scans):
    # decision 008 revision: the self-telemetry flush to the collector's own stopped receiver makes every graceful stop exit 1
    rec = build_raw_export("RG-001", LOCK, collector(stop_exit_code=1, graceful_stop=True,
                                                     shutdown_reason="self-telemetry flush only"), scans)
    assert rec["complete"] is True and rec["collector"]["graceful_stop"] is True
    assert check_raw_export(rec) == []


def test_accounting_flags_join_the_record_and_are_schema_checked(scans):
    accounting = {"accounting_version": 1, "window_ns": [1, 2], "snapshots": {"base": None, "final": 3},
                  "signals": {"traces": {"accepted": 5, "refused": 0, "failed": 0, "sent": 4, "send_failed": 0,
                                         "memory_limiter_dropped": 0, "file_items": 4, "final_sent": 4}},
                  "sdk_errors": {}, "flags": ["accounting_mismatch:traces"]}
    rec = build_raw_export("RG-001", LOCK, collector(), scans, accounting=accounting)
    assert rec["complete"] is False and rec["flags"] == ["accounting_mismatch:traces"]
    assert check_raw_export(rec) == []
    for flag in ("accounting_unavailable", "memory_limiter_refused", "exporter_rejected"):
        assert check_raw_export(build_raw_export("RG-001", LOCK, collector(), scans,
                                                 accounting=dict(accounting, flags=[flag]))) == []
    bad = build_raw_export("RG-001", LOCK, collector(), scans, accounting=dict(accounting, signals={"traces": {"sent": -1}}))
    assert check_raw_export(bad) != []


def test_missing_or_broken_files_make_the_export_incomplete(tmp_path, scans):
    scans = dict(scans, logs=None)
    rec = build_raw_export("RG-001", LOCK, collector(), scans)
    assert "missing_file:logs" in rec["flags"]
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n")
    rec = build_raw_export("RG-001", LOCK, collector(), dict(scans, logs=scan_raw_file(bad, "logs")))
    assert "parse_errors:logs" in rec["flags"]


def test_check_rejects_inconsistent_records(scans):
    rec = build_raw_export("RG-001", LOCK, collector(restarts=1), scans)
    rec["complete"] = True  # claims completeness despite a flag
    assert any("complete" in p for p in check_raw_export(rec))
    rec = build_raw_export("RG-001", LOCK, collector(), scans)
    rec["files"] = rec["files"][:2]
    assert any("logs" in p for p in check_raw_export(rec))
    rec = build_raw_export("RG-001", LOCK, collector(), scans)
    rec["run_group_id"] = "INC-001"
    assert any(p.startswith("schema:") for p in check_raw_export(rec))
