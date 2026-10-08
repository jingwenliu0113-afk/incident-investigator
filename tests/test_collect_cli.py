"""`python -m collect`: argument checks before anything starts (decision 009) and clean errors (exit 2)."""

import pytest

from collect.__main__ import main
from collect.layout import DataLayout
from collect.rungroup import next_id


@pytest.mark.parametrize("args, message", [
    (["--flag", "emitRawPii", "--variant", "on"], "not a Core fault"),
    (["--flag", "paymentFailure", "--variant", "200%"], "no variant"),
    (["--flag", "paymentFailure", "--variant", "off"], "no variant"),  # the baseline value injects nothing
])
def test_run_rejects_protocol_violations_before_touching_docker(args, message, capsys):
    assert main(["run", "--set", "pilot", *args]) == 2
    assert message in capsys.readouterr().err


def test_run_group_ids_skip_a_crashed_staging_directory(tmp_path):
    layout = DataLayout(tmp_path)
    (tmp_path / "staging" / "RG-003").mkdir(parents=True)
    assert next_id(layout, "RG") == "RG-004"


def test_pilot_runs_have_one_fixed_fault_duration():
    import collect.__main__ as cli

    assert cli.PILOT_FAULT_MINUTES == 10  # decision 009 (amended)
    with pytest.raises(SystemExit):
        main(["run", "--set", "pilot", "--flag", "paymentFailure", "--variant", "100%", "--fault-minutes", "3"])


def test_errors_exit_2_with_a_message_not_a_traceback(tmp_path, monkeypatch, capsys):
    import subprocess

    import collect.__main__ as cli
    import env.soak as soak_mod

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)  # an empty data tree
    assert main(["normalize", "--incident", "INC-404"]) == 2
    assert main(["calibrate", "--soak", str(tmp_path / "not-a-soak")]) == 2

    def daemon_down(*a, **kw):
        raise subprocess.CalledProcessError(1, ["docker", "ps"], "", "Cannot connect to the Docker daemon")

    monkeypatch.setattr(soak_mod, "project_container_ids", daemon_down)
    monkeypatch.setattr("env.cli._load_lock", lambda project_dir: {"startup": {"project_name": "ii-otel-demo"}})
    assert main(["replay", "--incident", "INC-404"]) == 2
    err = capsys.readouterr().err
    assert err.count("error:") == 3 and "Traceback" not in err


def test_freeze_cli_refuses_without_passing_calibrations(tmp_path, capsys):
    (tmp_path / "c.json").write_text('{"policy": {"sha256": "sha256:0"}, "freeze_check": {"pass": false}}')
    assert main(["freeze", "--calibration", str(tmp_path / "c.json")]) == 2
    assert "calibrated with" in capsys.readouterr().err


def test_every_run_names_its_set_and_held_out_waits_for_its_protocol(capsys):
    # SPEC §5 / §10: Pilot incidents never enter the test; the set is fixed when the run group is collected
    with pytest.raises(SystemExit):
        main(["run", "--flag", "paymentFailure", "--variant", "100%"])  # --set is required
    assert main(["run", "--set", "heldout", "--flag", "paymentFailure", "--variant", "100%"]) == 2
    assert "held-out" in capsys.readouterr().err


def test_a_smoke_run_never_writes_into_the_formal_data_tree(tmp_path, capsys):
    # a short, non-formal pipeline check: its data root must be outside data/external (never a set, never an id there)
    import collect.__main__ as cli

    assert main(["smoke", "--root", str(cli.PROJECT_DIR / "data" / "external" / "x")]) == 2
    assert "outside" in capsys.readouterr().err
    # the normal part covers the statistical baseline's reference (its first 10 minutes), so the baseline has fault
    # minutes to score; a shorter window makes it abstain by design and the last smoke step checks nothing
    from baselines.statistical import REFERENCE_MINUTES

    assert cli.SMOKE_MINUTES == {"normal": REFERENCE_MINUTES, "fault": 2, "recovery": 2}
