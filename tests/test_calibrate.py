"""Calibrating the normalize policy on soak raw (no fault) before it is frozen (decision 011 §4)."""

import json

import pytest

from collect.calibrate import calibrate, freeze_check, inventory
from normalize_fixtures import S, T0, log, logs_line, raw_lines, res, write_raw


def soak(tmp_path, name="soak", *, lines=None):
    d = tmp_path / name
    if lines is None:
        write_raw(d / "raw")
    else:
        (d / "raw").mkdir(parents=True)
        for sig, ls in lines.items():
            (d / "raw" / f"{sig}.jsonl").write_text("\n".join(ls) + "\n")
    (d / "report.json").write_text(json.dumps({"env_lock_sha256": "sha256:" + "1" * 64, "criteria": {}, "raw": {}}))
    return d


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
    out = calibrate(soak(tmp_path), tmp_path / "calibration")
    assert out["check_problems"] == []
    assert out["report"]["signals"]["traces"]["kept"] >= 3
    assert out["seconds"] >= 0 and out["max_rss_bytes"] > 0
    saved = json.loads((tmp_path / "calibration" / "calibration.json").read_text())
    assert saved["inventory"]["services"] == out["inventory"]["services"]


def test_calibrate_only_reads_a_soak_and_never_overwrites_an_earlier_iteration(tmp_path):
    not_a_soak = tmp_path / "rg"
    write_raw(not_a_soak / "raw")  # raw/ but no soak report: could be anything, including fault raw
    with pytest.raises(ValueError, match="soak"):
        calibrate(not_a_soak, tmp_path / "c0")
    s = soak(tmp_path)
    calibrate(s, tmp_path / "c1")
    with pytest.raises(FileExistsError):
        calibrate(s, tmp_path / "c1")
    assert calibrate(s, tmp_path / "c2")["check_problems"] == []  # a second iteration in a fresh directory


def test_freeze_criteria_fail_on_fault_artifacts_or_tokens_in_a_no_fault_soak(tmp_path):
    # the fixture raw carries fault-only lines on purpose (X7 templates, X8 tokens): in a real soak they are false positives
    out = calibrate(soak(tmp_path), tmp_path / "c")
    fc = out["freeze_check"]
    assert fc["F3"]["pass"] is False and fc["F4"]["pass"] is False and fc["pass"] is False
    assert fc["F1"]["pass"] is True and fc["F2"]["pass"] is True
    clean = {sig: [ln for ln in ls if not any(t in ln for t in ("garbage collection", "kafkaQueueProblems", "Feature Flag",
                                                                "paymentFailure"))]
             for sig, ls in raw_lines().items()}
    clean["logs"].append(logs_line(res("shipping"), [log(T0 + 120 * S, "quote sent")]))  # its only other log is X5
    ok = calibrate(soak(tmp_path, "clean", lines=clean), tmp_path / "c2")["freeze_check"]
    assert {k: v["pass"] for k, v in ok.items() if k != "pass"} == {f"F{i}": True for i in range(1, 7)} and ok["pass"]


def test_freeze_check_budget_and_service_coverage():
    report = {"signals": {}, "removed": {}, "tokens_deleted": {}, "unknown_services": {}}
    fc = freeze_check(report, check_problems=[], unknown_fields={}, raw_services={"cart", "email"},
                      kept_services={"cart"}, seconds=700, max_rss_bytes=5 * 2**30)
    assert fc["F5"]["pass"] is False and "email" in fc["F5"]["detail"]
    assert fc["F6"]["pass"] is False


def test_the_soak_window_starts_at_the_earliest_item_whatever_its_timestamp_width(tmp_path):
    # "...:40Z" (no fraction) sorts after "...:40.250000Z" as a string: compare times, not strings
    import json as _json

    from normalize_fixtures import T0 as t0
    from normalize_fixtures import gauge_line, pt, span, traces_line
    lines = {"traces": [traces_line(res("payment"), [span("a" * 32, "b" * 16, t0)])],
             "logs": [logs_line(res("payment"), [log(t0 + 250_000_000, "first log")])],
             "metrics": [gauge_line(res("cart"), "app.cart.items", [pt(t0 + 250_000_000)])]}
    out = calibrate(soak(tmp_path, lines=lines), tmp_path / "c")
    sig = out["report"]["signals"]
    assert sig["traces"]["kept"] == 1 and all(sig[s].get("out_of_window", 0) == 0 for s in sig), _json.dumps(sig)


def test_freeze_needs_passing_calibrations_of_this_exact_policy_and_records_them(tmp_path):
    import hashlib
    import shutil

    from collect.calibrate import freeze
    from collect.policy import POLICY_PATH, load_policy

    policy_path = tmp_path / "policy.json"
    shutil.copy(POLICY_PATH, policy_path)
    unfrozen = {k: v for k, v in json.loads(policy_path.read_text()).items()
                if k not in ("attribute_key_inventory", "frozen_from")} | {"status": "calibrating"}
    policy_path.write_text(json.dumps(unfrozen, indent=2) + "\n")  # the real file is frozen since 2026-10-08
    clean = {sig: [ln for ln in ls if not any(t in ln for t in ("garbage collection", "kafkaQueueProblems", "Feature Flag",
                                                                "paymentFailure"))]
             for sig, ls in raw_lines().items()}
    clean["logs"].append(logs_line(res("shipping"), [log(T0 + 120 * S, "quote sent")]))
    code = {"commit": "a" * 40, "dirty": False}
    a = calibrate(soak(tmp_path, "a", lines=clean), tmp_path / "ca", policy=load_policy(policy_path), code=code)
    b = calibrate(soak(tmp_path, "b", lines=clean), tmp_path / "cb", policy=load_policy(policy_path), code=code)
    bad = calibrate(soak(tmp_path, "bad"), tmp_path / "cbad", policy=load_policy(policy_path), code=code)  # fails F3 / F4
    dirty = calibrate(soak(tmp_path, "d", lines=clean), tmp_path / "cd", policy=load_policy(policy_path),
                      code={"commit": "a" * 40, "dirty": True})
    assert a["code"] == code and a["report"]["code"] == code
    with pytest.raises(ValueError, match="clean"):  # the normalizer behind the evidence must be a commit
        freeze(policy_path, [tmp_path / "cd" / "calibration.json"])
    with pytest.raises(ValueError, match="same commit"):
        other = json.loads((tmp_path / "cb" / "calibration.json").read_text())
        (tmp_path / "cb2.json").write_text(json.dumps({**other, "code": {"commit": "b" * 40, "dirty": False}}))
        freeze(policy_path, [tmp_path / "ca" / "calibration.json", tmp_path / "cb2.json"])
    assert dirty["freeze_check"]["pass"] is True
    with pytest.raises(ValueError, match="freeze criteria"):
        freeze(policy_path, [tmp_path / "ca" / "calibration.json", tmp_path / "cbad" / "calibration.json"])
    assert json.loads(policy_path.read_text())["status"] == "calibrating"
    frozen = freeze(policy_path, [tmp_path / "ca" / "calibration.json", tmp_path / "cb" / "calibration.json"])
    raw = json.loads(policy_path.read_text())
    assert raw["status"] == "frozen" and frozen["sha256"] == "sha256:" + hashlib.sha256(policy_path.read_bytes()).hexdigest()
    assert raw["attribute_key_inventory"] == {k: sorted(set(a["report"]["attribute_keys"][k]) | set(b["report"]["attribute_keys"][k]))
                                              for k in a["report"]["attribute_keys"]}
    assert [s["soak"] for s in raw["frozen_from"]] == [str(tmp_path / "a"), str(tmp_path / "b")]
    assert all(s["calibration_sha256"].startswith("sha256:") for s in raw["frozen_from"])
    with pytest.raises(ValueError, match="calibrated with"):  # the file changed: old calibrations no longer apply
        freeze(policy_path, [tmp_path / "ca" / "calibration.json"])
    assert bad["freeze_check"]["pass"] is False
