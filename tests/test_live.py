"""Preflight of a real collection run (decision 009 §2), without Docker."""

import json

from collect.live import foreign_running, passing_soak

LOCK = "sha256:" + "1" * 64


def soak_dir(root, name, **report):
    d = root / "soak" / name
    d.mkdir(parents=True)
    (d / "report.json").write_text(json.dumps(report))
    return d


def test_passing_soak_must_be_for_this_exact_lock(tmp_path):
    assert passing_soak(tmp_path, LOCK) is None
    soak_dir(tmp_path, "a", **{"pass": True, "env_lock_sha256": "sha256:" + "2" * 64, "teardown": {"verify": []}})
    soak_dir(tmp_path, "b", **{"pass": False, "env_lock_sha256": LOCK, "teardown": {"verify": []}})
    soak_dir(tmp_path, "c", **{"pass": True, "env_lock_sha256": LOCK, "teardown": {"verify": ["drift"]}})
    assert passing_soak(tmp_path, LOCK) is None
    good = soak_dir(tmp_path, "d", **{"pass": True, "env_lock_sha256": LOCK, "teardown": {"verify": []}})
    assert passing_soak(tmp_path, LOCK) == good
    (tmp_path / "soak" / "e").mkdir()  # an aborted soak without a report is ignored
    assert passing_soak(tmp_path, LOCK) == good


def test_foreign_running_lists_containers_of_other_projects():
    ps = "rtu-maintenance-platform-db-1\trtu-maintenance-platform\ncheckout\tii-otel-demo\nloose\t\n"
    assert foreign_running(lambda cmd, env: ps, {}, project="ii-otel-demo") == ["loose", "rtu-maintenance-platform-db-1"]
    assert foreign_running(lambda cmd, env: "", {}, project="ii-otel-demo") == []
