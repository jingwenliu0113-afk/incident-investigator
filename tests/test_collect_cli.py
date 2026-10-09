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


def test_every_run_names_its_set_and_held_out_waits_for_its_protocol(tmp_path, monkeypatch, capsys):
    # SPEC §5 / §10: Pilot incidents never enter the test; the set is fixed when the run group is collected
    import collect.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)  # no freeze record (decision 023 §4)
    with pytest.raises(SystemExit):
        main(["run", "--flag", "paymentFailure", "--variant", "100%"])  # --set is required
    assert main(["run", "--set", "heldout", "--flag", "paymentFailure", "--variant", "100%"]) == 2
    err = capsys.readouterr().err
    assert "held-out" in err and "freeze" in err
    assert not (tmp_path / "data").exists()


def test_heldout_next_and_status_refuse_without_a_freeze_record(tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    for command in ("next", "status"):
        assert main([command, "--set", "heldout"]) == 2
        assert "freeze" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
    ["normalize", "--incident", "INC-001"],
    ["replay", "--incident", "INC-001"],
    ["label", "--incident", "INC-001", "--labeler", "agent:claude-code"],
    ["process", "--incident", "INC-001", "--labeler", "agent:claude-code"],
    ["review-sheet", "--incident", "INC-001"],
    ["review", "--incident", "INC-001", "--file", "x.json", "--reviewer", "human:jw"],
], ids=lambda a: a[0])
def test_incident_commands_on_a_heldout_incident_need_a_passing_freeze(tmp_path, monkeypatch, capsys, args):
    # decision 023 §4 / §6: held-out data is produced only by the frozen code
    import collect.__main__ as cli
    from heldout_fixtures import FREEZE_SHA, write_run

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    layout = DataLayout(tmp_path / "data/external")
    write_run(layout, "RG-001", "paymentFailure", "100%", inc="INC-001", split="heldout", slot="H01", freeze_sha=FREEZE_SHA)
    for name in ("_normalize", "_replay", "_label"):
        monkeypatch.setattr(cli, name, lambda *a, **kw: pytest.fail("ran before the freeze check"))
    assert main(args) == 2
    err = capsys.readouterr().err
    assert "freeze" in err and "held-out" in err


def test_a_smoke_run_never_writes_into_the_formal_data_tree(tmp_path, capsys):
    # a short, non-formal pipeline check: its data root must be outside data/external (never a set, never an id there)
    import collect.__main__ as cli

    assert main(["smoke", "--root", str(cli.PROJECT_DIR / "data" / "external" / "x")]) == 2
    assert "outside" in capsys.readouterr().err
    # the normal part covers the statistical baseline's reference (its first 10 minutes), so the baseline has fault
    # minutes to score; a shorter window makes it abstain by design and the last smoke step checks nothing
    from baselines.statistical import REFERENCE_MINUTES

    assert cli.SMOKE_MINUTES == {"normal": REFERENCE_MINUTES, "fault": 2, "recovery": 2}


# ---------------------------------------------------------------- held-out collection (decision 023 §4)

def heldout_project(tmp_path, monkeypatch, *, k=2, reviewed=True):
    """PROJECT_DIR = tmp with a two-fault held-out plan (the other Pilot faults removed), its slot list and a freeze
    record that passes (the git-facing check has its own tests); a complete Pilot unless `reviewed` is False."""
    import collect.__main__ as cli
    from collect.freeze import freeze_sha256
    from collect.pilot import PILOT
    from heldout_fixtures import complete_pilot, passing_freeze, plan_doc, write_project, write_run

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    passing_freeze(monkeypatch)
    plan = plan_doc(PILOT[:2], removed=[(e["flag"], e["variant"]) for e in PILOT[2:]])
    slots = write_project(tmp_path, plan, k=k)
    layout = DataLayout(tmp_path / "data/external")
    n = complete_pilot(layout, PILOT[:2])
    if not reviewed:
        write_run(layout, f"RG-{n:03d}", "paymentFailure", "100%", inc=f"INC-{n:03d}")
    return layout, slots["slots"], freeze_sha256(tmp_path)


def fill(layout, slot, sha, n, status="valid"):
    from heldout_fixtures import write_run

    write_run(layout, f"RG-{n:03d}", slot["flag"], slot["variant"], status, inc=f"INC-{n:03d}", split="heldout",
              slot=slot["slot"], freeze_sha=sha)


def run_args(slot, *extra):
    return ["run", "--set", "heldout", "--flag", slot["flag"], "--variant", slot["variant"], *extra]


def test_a_heldout_run_is_the_next_slot_of_a_passing_freeze_with_a_fresh_seed(tmp_path, monkeypatch, capsys):
    import argparse

    import collect.__main__ as cli

    layout, slots, sha = heldout_project(tmp_path, monkeypatch)
    ns = argparse.Namespace(split="heldout", flag=slots[0]["flag"], variant=slots[0]["variant"], seed=None)
    assert cli._check_args(ns, layout) == {"slot": "H01", "freeze_sha256": sha}
    assert main(run_args(slots[0], "--seed", "7")) == 2 and "seed" in capsys.readouterr().err  # 023 §4
    assert main(run_args(slots[1])) == 2 and "next slot" in capsys.readouterr().err
    assert main(["run", "--set", "heldout", "--flag", "adHighCpu", "--variant", "on"]) == 2  # removed from the plan


def test_a_heldout_run_waits_for_the_pilot_review(tmp_path, monkeypatch, capsys):
    layout, slots, _ = heldout_project(tmp_path, monkeypatch, reviewed=False)
    assert main(run_args(slots[0])) == 2 and "not reviewed" in capsys.readouterr().err


def test_a_full_set_or_three_slots_waiting_for_a_person_refuse_a_heldout_run(tmp_path, monkeypatch, capsys):
    layout, slots, sha = heldout_project(tmp_path, monkeypatch, k=1)
    for n, slot in enumerate(slots, start=50):
        fill(layout, slot, sha, n)
    assert main(run_args(slots[0])) == 2 and "filled or closed" in capsys.readouterr().err

    layout, slots, sha = heldout_project(tmp_path / "b", monkeypatch, k=2)
    n = 50
    for slot in slots[:3]:
        for _ in range(3):
            fill(layout, slot, sha, n, "invalid")
            n += 1
    assert main(run_args(slots[3])) == 2 and "need a person" in capsys.readouterr().err


def test_a_heldout_run_reaches_the_same_preflight_as_a_pilot_run(tmp_path, monkeypatch, capsys):
    # decision 025: `run --set heldout` builds the same LiveStack and run_group; nothing starts off the formal power
    import signal

    import collect.live as live
    from collect.heldout import heldout_runs
    from collect.provenance import power_problems

    layout, slots, sha = heldout_project(tmp_path, monkeypatch)
    seen = []

    class Stack:
        lock_sha256 = "sha256:" + "1" * 64

        def __init__(self, *args):
            seen.append(args)

        def preflight(self):
            return power_problems({"source": "AC Power", "settings": {"powermode": "0"}})

    monkeypatch.setattr(live, "LiveStack", Stack)
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    assert main(run_args(slots[0])) == 2
    assert "not starting" in (err := capsys.readouterr().err) and "high power mode" in err
    assert len(seen) == 1 and not (layout.root / "staging").exists() and heldout_runs(layout) == []


def test_the_pilot_is_closed_once_a_freeze_record_exists(tmp_path, monkeypatch, capsys):
    heldout_project(tmp_path, monkeypatch)
    assert main(["run", "--set", "pilot", "--flag", "cartFailure", "--variant", "100%"]) == 2
    assert "Pilot is closed" in capsys.readouterr().err


def test_heldout_next_and_status(tmp_path, monkeypatch, capsys):
    import json

    layout, slots, sha = heldout_project(tmp_path, monkeypatch)
    assert main(["next", "--set", "heldout"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == f"--flag {slots[0]['flag']} --variant {slots[0]['variant']}" and "H01" in out.err
    fill(layout, slots[0], sha, 50)
    for n in range(51, 54):
        fill(layout, slots[1], sha, n, "aborted_unstable")
    assert main(["next", "--set", "heldout"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == f"--flag {slots[2]['flag']} --variant {slots[2]['variant']}"
    assert "H02" in out.err and "RG-053" in out.err  # the skipped slot and its non-valid run groups
    assert main(["status", "--set", "heldout"]) == 0
    text = capsys.readouterr().out
    status = json.loads(text)
    assert [s["state"] for s in status["slots"]] == ["filled", "needs_person", "open", "open"]
    assert status["summary"] == {"filled": 1, "open": 2, "closed": 0, "needs_person": 1} and status["freeze_problems"] == []
    assert "INC-" not in text and "RG-050" not in text  # no incident id and no valid run-group id
    for slot in slots[2:]:
        for _ in range(3):
            n += 1
            fill(layout, slot, sha, n + 50, "invalid")
    assert main(["next", "--set", "heldout"]) == 3 and "need a person" in capsys.readouterr().err


def test_a_heldout_incident_is_labelled_from_the_committed_heldout_plan(tmp_path, monkeypatch, capsys):
    import json

    from collect.traffic import TRAFFIC_PROFILES
    from test_records import manifest

    layout, slots, sha = heldout_project(tmp_path, monkeypatch)
    plan_path = tmp_path / "docs/heldout/plan.json"
    plan = json.loads(plan_path.read_text())
    plan["entries"][0]["affected"] = [*plan["entries"][0]["affected"], "accounting"]  # differs from PLANS["pilot"]
    plan_path.write_text(json.dumps(plan))
    entry = plan["entries"][0]
    slot = next(s for s in slots if (s["flag"], s["variant"]) == (entry["flag"], entry["variant"]))
    fill(layout, slot, sha, 50)
    layout.incident_dir("INC-050").mkdir(parents=True)
    layout.manifest_path("INC-050").write_text(json.dumps(manifest(incident_id="INC-050", traffic={
        "generator_service": "load-generator", "settings": dict(TRAFFIC_PROFILES["locust-upstream-3.1.0"]),
        "seed": None, "seed_applied": False})))
    assert main(["label", "--incident", "INC-050", "--labeler", "agent:claude-code"]) == 0
    assert json.loads(layout.label_path("INC-050").read_text())["affected_services"] == entry["affected"]


def test_heldout_plan_and_freeze_commands_write_once(tmp_path, monkeypatch, capsys):
    import json

    import collect.__main__ as cli
    from eval.runner import METHODS
    from test_heldout_freeze import REVISIONS, git, project, write

    repo, layout = project(tmp_path)
    for m in METHODS:
        write(layout.root, f"results/pilot/{m}/scores.json", "{}")
    monkeypatch.setattr(cli, "PROJECT_DIR", repo)
    amendments, revisions = tmp_path / "amend.json", tmp_path / "rev.json"
    amendments.write_text(json.dumps({"amend": [], "remove": []}))
    revisions.write_text(json.dumps(REVISIONS))
    assert main(["heldout-plan", "--amendments", str(amendments)]) == 0
    assert main(["heldout-plan", "--amendments", str(amendments)]) == 2 and "written once" in capsys.readouterr().err
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "plan")
    assert main(["heldout-freeze", "--pilot-revisions", str(revisions)]) == 0
    assert "one commit" in capsys.readouterr().out
    assert main(["heldout-freeze", "--pilot-revisions", str(revisions)]) == 2
    assert (repo / "docs/heldout/slots.json").exists() and (repo / "docs/heldout/freeze.json").exists()


def test_heldout_list_command_writes_once_and_prints_counts_only(tmp_path, monkeypatch, capsys):
    import json

    import collect.__main__ as cli
    import collect.freeze as freeze
    from heldout_fixtures import write_heldout_incident

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path / "empty")
    assert main(["heldout-list"]) == 2 and "freeze" in capsys.readouterr().err  # no freeze record
    layout, slots, sha = heldout_project(tmp_path, monkeypatch, k=1)
    monkeypatch.setattr(freeze, "commit_problems", lambda project_dir, record, commit, run=None: [])
    for n, slot in enumerate(slots, start=50):
        write_heldout_incident(layout, n, slot, freeze_sha=sha)
    assert main(["heldout-list"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["listed"] == 2 and "INC-" not in out and "RG-" not in out
    assert layout.heldout_incidents_path.exists()
    assert main(["heldout-list"]) == 2 and "File exists" in capsys.readouterr().err
