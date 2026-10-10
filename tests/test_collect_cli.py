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


def test_a_heldout_run_is_the_next_slot_of_a_passing_freeze_and_takes_no_seed(tmp_path, monkeypatch, capsys):
    import argparse

    import collect.__main__ as cli

    layout, slots, sha = heldout_project(tmp_path, monkeypatch)
    ns = argparse.Namespace(split="heldout", flag=slots[0]["flag"], variant=slots[0]["variant"], seed=None)
    assert cli._check_args(ns, layout) == {"slot": "H01", "freeze_sha256": sha}
    assert main(run_args(slots[0], "--seed", "7")) == 2 and "seed" in capsys.readouterr().err  # 023 §4
    assert main(run_args(slots[1])) == 2 and "next slot" in capsys.readouterr().err
    assert main(["run", "--set", "heldout", "--flag", "adHighCpu", "--variant", "on"]) == 2  # removed from the plan
    assert "not the next slot" in capsys.readouterr().err


def test_a_heldout_run_of_a_slot_whose_fault_is_not_on_the_plan_is_refused(tmp_path, monkeypatch, capsys):
    # decision 023 §1: the run's fault must be on the committed held-out plan, whatever the slot list says
    import json

    layout, slots, sha = heldout_project(tmp_path, monkeypatch)
    plan_path = tmp_path / "docs/heldout/plan.json"
    plan = json.loads(plan_path.read_text())
    plan["entries"] = [e for e in plan["entries"] if (e["flag"], e["variant"]) != (slots[0]["flag"], slots[0]["variant"])]
    plan_path.write_text(json.dumps(plan))
    assert main(run_args(slots[0])) == 2 and "not on the held-out plan" in capsys.readouterr().err


def test_a_heldout_run_records_the_next_open_slot_its_freeze_and_a_seed_no_run_group_used(tmp_path, monkeypatch, capsys):
    # decision 023 §4 / 026 #14, #15: the slot is the next open one (never the first slot of the fault), and the plan
    # handed to run_group carries it, the freeze sha, 10 fault minutes and a fresh seed
    import json
    import signal

    import collect.__main__ as cli
    import collect.live as live

    layout, slots, sha = heldout_project(tmp_path, monkeypatch)
    fill(layout, slots[0], sha, 50)
    fill(layout, slots[1], sha, 51)
    nxt = slots[2]  # block 2: its fault already has a slot in block 1
    assert nxt["slot"] == "H03" and (nxt["flag"], nxt["variant"]) in {(s["flag"], s["variant"]) for s in slots[:2]}
    planned = []

    class Stack:
        lock_sha256 = "sha256:" + "1" * 64

        def __init__(self, *args):
            pass

    def run_group(plan, stack, clock, **kw):
        planned.append(plan)
        raise RuntimeError("stopped by the test before anything starts")

    monkeypatch.setattr(live, "LiveStack", Stack)
    monkeypatch.setattr(cli, "run_group", run_group)
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    assert main(run_args(nxt)) == 2 and "stopped by the test" in capsys.readouterr().err
    (plan,) = planned
    used = {json.loads(p.read_text())["plan"]["seed"] for p in layout.ground_truth_root.glob("run_groups/RG-*/run.json")}
    assert (plan.split, plan.slot, plan.freeze_sha256, plan.flag, plan.variant) == (
        "heldout", "H03", sha, nxt["flag"], nxt["variant"])
    assert plan.fault_minutes == 10 and plan.seed not in used and 0 <= plan.seed < 2**31


def test_a_heldout_run_waits_for_the_pilot_review(tmp_path, monkeypatch, capsys):
    layout, slots, _ = heldout_project(tmp_path, monkeypatch, reviewed=False)
    assert main(run_args(slots[0])) == 2 and "not reviewed" in capsys.readouterr().err
    assert main(["next", "--set", "heldout"]) == 2 and "not reviewed" in capsys.readouterr().err


NOT_CLEAN = "the checkout is not clean (untracked or modified files): held-out work needs a clean checkout"


def test_a_failing_freeze_check_refuses_every_heldout_collect_step(tmp_path, monkeypatch, capsys):
    # a freeze record exists and its check fails (here: a dirty checkout): nothing held-out goes ahead
    import collect.__main__ as cli
    import collect.freeze as freeze
    import collect.live as live
    from heldout_fixtures import freeze_record

    layout, slots, sha = heldout_project(tmp_path, monkeypatch, k=1)
    fill(layout, slots[0], sha, 50)  # a held-out incident for the incident commands
    monkeypatch.setattr(freeze, "check_freeze", lambda project_dir, run=None: (freeze_record(), [NOT_CLEAN]))
    monkeypatch.setattr(freeze, "commit_problems", lambda *a, **kw: pytest.fail("listed under a failing freeze check"))
    monkeypatch.setattr(live, "LiveStack", lambda *a: pytest.fail("a run started under a failing freeze check"))
    for name in ("_normalize", "_replay", "_label"):
        monkeypatch.setattr(cli, name, lambda *a, **kw: pytest.fail("ran under a failing freeze check"))
    incident = ["--incident", "INC-050"]
    for n in (51, 52, 53):  # slot H02 needs a person: its acknowledgment is refused too (user decision 2026-10-10)
        fill(layout, slots[1], sha, n, "invalid")
    for args in (run_args(slots[1]), ["next", "--set", "heldout"], ["heldout-list"],
                 ["ack-failures", "--set", "heldout", "--slot", "H02", "--reason", "r", "--decided-by", "user"],
                 ["normalize", *incident], ["replay", *incident], ["label", *incident, "--labeler", "agent:t"],
                 ["process", *incident, "--labeler", "agent:t"], ["review-sheet", *incident],
                 ["review", *incident, "--file", "x.json", "--reviewer", "human:jw"]):
        assert main(args) == 2, args
        err = capsys.readouterr().err
        assert "not clean" in err and "Traceback" not in err, args
    assert not layout.heldout_incidents_path.exists() and not (layout.root / "staging").exists()
    assert not (layout.ground_truth_root / "failure_acks.jsonl").exists()


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


@pytest.mark.parametrize("amendments", [
    {"remove": [{"flag": ["paymentFailure"], "variant": "100%", "basis": "pipeline", "reason": "r"}]},
    {"amend": [{"flag": "paymentFailure", "variant": "100%", "field": ["notes"], "value": "x", "reason": "r"}]},
    {"amend": [{"flag": ["paymentFailure"], "variant": "100%", "field": "notes", "value": "x", "reason": "r"}]},
    {"amend": [{"flag": "paymentFailure", "variant": {"v": 1}, "field": "notes", "value": "x", "reason": "r"}]},
], ids=["remove-flag-list", "amend-field-list", "amend-flag-list", "amend-variant-object"])
def test_a_malformed_amendments_file_is_refused_with_exit_2_and_writes_nothing(tmp_path, monkeypatch, capsys, amendments):
    import json

    import collect.__main__ as cli
    from eval.runner import METHODS
    from test_heldout_freeze import project, write

    repo, layout = project(tmp_path)
    for m in METHODS:
        write(layout.root, f"results/pilot/{m}/scores.json", "{}")
    monkeypatch.setattr(cli, "PROJECT_DIR", repo)
    path = tmp_path / "amend.json"
    path.write_text(json.dumps(amendments))
    assert main(["heldout-plan", "--amendments", str(path)]) == 2
    err = capsys.readouterr().err
    assert "flag, variant and field are strings" in err and "Traceback" not in err
    assert not (repo / "docs/heldout/plan.json").exists()


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


def test_heldout_list_command_checks_every_run_and_normalize_commit_against_the_freeze(tmp_path, monkeypatch, capsys):
    # decision 023 §6 / 026 #24: the CLI wires collect.freeze.commit_problems with the record that passed the check
    import collect.freeze as freeze
    from heldout_fixtures import COMMIT, freeze_record, write_heldout_incident

    layout, slots, sha = heldout_project(tmp_path, monkeypatch, k=1)
    run_commit, normalize_commit = "d" * 40, "e" * 40
    write_heldout_incident(layout, 50, slots[0], freeze_sha=sha)
    write_heldout_incident(layout, 51, slots[1], freeze_sha=sha, commit=run_commit,
                           code={"commit": normalize_commit, "dirty": False})
    seen = []

    def commit_problems(project_dir, record, commit, run=None):
        seen.append((project_dir, record, commit))
        return ["changes collect/x.py after the freeze"] if commit == normalize_commit else []

    monkeypatch.setattr(freeze, "commit_problems", commit_problems)
    assert main(["heldout-list"]) == 2
    assert "normalize: changes collect/x.py after the freeze" in capsys.readouterr().err
    assert not layout.heldout_incidents_path.exists()
    assert {c for _, _, c in seen} == {COMMIT, run_commit, normalize_commit}
    assert all(p == tmp_path and r == freeze_record() for p, r, _ in seen)


# ---------------------------------------------------------------- a needs-person slot (user decision 2026-10-10)

def ack_args(split="heldout", *extra):
    return ["ack-failures", "--set", split, *extra, "--reason", "grafana plugin download timed out", "--decided-by", "user"]


def test_heldout_ack_failures_records_a_persons_look_at_a_slot_and_it_is_collected_again(tmp_path, monkeypatch, capsys):
    import json

    layout, slots, sha = heldout_project(tmp_path, monkeypatch)
    fill(layout, slots[0], sha, 50)
    for n in range(51, 54):
        fill(layout, slots[1], sha, n, "aborted_unstable")
    assert main(["next", "--set", "heldout"]) == 0
    assert "ack-failures --set heldout --slot H02" in capsys.readouterr().err  # what a person runs after looking
    assert main(ack_args("heldout", "--slot", "H02")) == 0
    out = capsys.readouterr().out
    record = json.loads(out)
    assert (record["split"], record["slot"], record["run_groups"], record["freeze_sha256"]) == (
        "heldout", "H02", ["RG-051", "RG-052", "RG-053"], sha)
    assert "INC-" not in out and "RG-050" not in out  # non-valid run-group ids only (026 #23)
    assert main(["next", "--set", "heldout"]) == 0
    assert capsys.readouterr().out.strip() == f"--flag {slots[1]['flag']} --variant {slots[1]['variant']}"
    assert main(["status", "--set", "heldout"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["slots"][1]["state"] == "open" and status["slots"][1]["acknowledged_run_groups"] == record["run_groups"]
    assert status["slots"][1]["counts"]["non_valid"] == 3
    assert main(ack_args("heldout", "--slot", "H02")) == 2 and "needs a person" in capsys.readouterr().err
    assert main(ack_args("heldout", "--slot", "H99")) == 2 and "H99" in capsys.readouterr().err
    for extra in ([], ["--slot", "H02", "--flag", slots[1]["flag"], "--variant", slots[1]["variant"]],
                  ["--slot", "H02", "--flag", slots[1]["flag"]], ["--slot", "H02", "--variant", slots[1]["variant"]]):
        assert main(ack_args("heldout", *extra)) == 2 and "--slot" in capsys.readouterr().err, extra
    assert len((layout.ground_truth_root / "failure_acks.jsonl").read_text().splitlines()) == 1


def test_heldout_ack_failures_without_a_freeze_record_writes_nothing(tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    assert main(ack_args("heldout", "--slot", "H01")) == 2
    assert "freeze" in capsys.readouterr().err and not (tmp_path / "data").exists()


def test_pilot_ack_failures_is_unchanged(tmp_path, monkeypatch, capsys):
    # decision 016 "實作說明（2026-10-09）": a fault, by --flag / --variant; never a slot
    import json

    import collect.__main__ as cli
    from heldout_fixtures import write_run

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    layout = DataLayout(tmp_path / "data/external")
    for n in (1, 2, 3):
        write_run(layout, f"RG-{n:03d}", "paymentFailure", "100%", "aborted_unstable")
    assert main(["next", "--set", "pilot"]) == 3
    capsys.readouterr()
    assert main(ack_args("pilot", "--slot", "H01", "--flag", "paymentFailure", "--variant", "100%")) == 2
    assert "--slot" in capsys.readouterr().err
    assert main(ack_args("pilot", "--flag", "paymentFailure")) == 2 and "--variant" in capsys.readouterr().err
    assert main(ack_args("pilot", "--variant", "100%")) == 2 and "--flag" in capsys.readouterr().err
    assert main(ack_args("pilot", "--flag", "paymentFailure", "--variant", "100%")) == 0
    record = json.loads(capsys.readouterr().out)
    assert set(record) == {"split", "flag", "variant", "run_groups", "reason", "decided_by", "acknowledged_at"}
    assert record["split"] == "pilot" and record["run_groups"] == ["RG-001", "RG-002", "RG-003"]
    assert main(["next", "--set", "pilot"]) == 0 and "paymentFailure" in capsys.readouterr().out
