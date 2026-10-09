"""The Pilot loop (SPEC Week 1: automated collect -> normalize -> label): next, one locked run, process, until done."""

import json

from collect.layout import DataLayout
from collect.pilot import PLANS
from collect.pilot_loop import LOCK_BUSY, pilot_loop
from test_pilot_progress import run_group


class Stack:
    """Stands in for the subprocesses: `collect run` stores a run group, `collect process` writes the label."""

    def __init__(self, layout, outcomes, process_rc=0):
        self.layout, self.outcomes, self.process_rc, self.calls = layout, list(outcomes), process_rc, []

    def __call__(self, cmd, log_path):
        self.calls.append(cmd)
        sub = cmd[cmd.index("collect") + 1] if "collect" in cmd else None
        if sub == "run":
            outcome = self.outcomes.pop(0)
            if outcome == "busy":
                return LOCK_BUSY
            if outcome == "refused":
                return 2
            flag, variant = cmd[cmd.index("--flag") + 1], cmd[cmd.index("--variant") + 1]
            n = len(list((self.layout.ground_truth_root / "run_groups").glob("RG-*"))) + 1 \
                if (self.layout.ground_truth_root / "run_groups").exists() else 1
            inc = f"INC-{n:03d}" if outcome == "valid" else None
            run_group(self.layout, f"RG-{n:03d}", flag, variant, outcome, inc=inc)
            return 0 if outcome == "valid" else 1
        if sub == "process":
            inc = cmd[cmd.index("--incident") + 1]
            if self.process_rc == 0:
                path = self.layout.label_path(inc)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")
            return self.process_rc
        return 0  # eval steps


def loop(tmp_path, stack, **kw):
    waits = []
    out = pilot_loop(DataLayout(tmp_path), stack, labeler="agent:test", log_dir=tmp_path / "logs",
                     sleep=waits.append, **{"lock_wait_s": 300, "max_lock_waits": 3, **kw})
    return out, waits


def test_each_fault_is_run_under_its_own_lock_then_processed_and_the_set_is_scored_when_complete(tmp_path):
    layout = DataLayout(tmp_path)
    stack = Stack(layout, ["valid"] * len(PLANS["pilot"]))
    out, waits = loop(tmp_path, stack)
    assert out["stopped"] == "complete" and waits == []
    runs = [c for c in stack.calls if "run" in c and "--flag" in c]
    assert len(runs) == len(PLANS["pilot"])
    assert all(c[0].endswith("tools/with-mac-lock") for c in runs)  # the lock covers one run only
    assert not any(c[0].endswith("with-mac-lock") for c in stack.calls if "process" in c or "eval" in c)
    assert [c[c.index("--flag") + 1] for c in runs] == [e["flag"] for e in PLANS["pilot"]]
    evals = [c[c.index("eval") + 1:] for c in stack.calls if "eval" in c]
    assert evals == [["leakage", "--set", "pilot"], ["run", "--method", "stat-anomaly", "--set", "pilot"],
                     ["score", "--method", "stat-anomaly", "--set", "pilot"]]
    assert [s["status"] for s in out["runs"]] == ["valid"] * len(PLANS["pilot"])
    assert len(list((tmp_path / "logs").glob("*.log"))) == len(stack.calls)  # one log per step


def test_a_busy_lock_is_waited_for_never_taken_and_a_long_wait_stops_the_loop(tmp_path):
    layout = DataLayout(tmp_path)
    out, waits = loop(tmp_path, Stack(layout, ["busy", "valid"]), max_runs=1)
    assert waits == [300] and out["stopped"] == "max_runs" and out["runs"][0]["status"] == "valid"
    out, waits = loop(tmp_path / "b", Stack(DataLayout(tmp_path / "b"), ["busy"] * 4))
    assert out["stopped"] == "lock_busy" and waits == [300] * 3


def test_an_invalid_run_is_collected_again_and_a_fault_that_needs_a_person_stops_the_loop(tmp_path):
    layout = DataLayout(tmp_path)
    stack = Stack(layout, ["invalid", "aborted_unstable", "invalid"])
    out, _ = loop(tmp_path, stack)
    assert out["stopped"] == "needs_person" and "paymentFailure" in out["reason"]
    assert [s["status"] for s in out["runs"]] == ["invalid", "aborted_unstable", "invalid"]
    assert not any("process" in c for c in stack.calls) and not any("eval" in c for c in stack.calls)


def test_a_refused_run_or_a_failed_process_stops_for_a_person(tmp_path):
    out, _ = loop(tmp_path, Stack(DataLayout(tmp_path), ["refused"]))
    assert out["stopped"] == "run_refused" and out["exit_code"] == 2  # e.g. dirty tree, soak or lock preflight
    out, _ = loop(tmp_path / "b", Stack(DataLayout(tmp_path / "b"), ["valid"], process_rc=1))
    assert out["stopped"] == "process_failed" and out["runs"][0]["incident_ids"] == ["INC-001"]
    json.dumps(out)  # the summary is printed as JSON


def test_the_command_prints_the_power_mode_and_maps_why_it_stopped_to_an_exit_code(tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli
    import collect.pilot_loop as pl
    import collect.provenance as prov

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(prov, "power_facts", lambda: {"source": "AC Power", "settings": {"powermode": "2"}})
    for stopped, code in (("complete", 0), ("needs_person", 3), ("lock_busy", 75), ("run_refused", 1)):
        monkeypatch.setattr(pl, "pilot_loop", lambda layout, **kw: {"stopped": stopped, "runs": [], "logs": []})
        assert cli.main(["pilot-loop", "--labeler", "agent:test"]) == code
    assert '"powermode": "2"' in capsys.readouterr().out  # decision 025: printed before the first run


def test_each_step_runs_in_the_project_directory_and_its_output_goes_to_its_log(tmp_path):
    from collect.pilot_loop import PROJECT_DIR, _subprocess

    log = tmp_path / "step.log"
    log.write_text("$ pwd\n")
    assert _subprocess(["pwd"], log) == 0
    assert log.read_text().splitlines() == ["$ pwd", str(PROJECT_DIR)]
    assert _subprocess(["sh", "-c", "echo oops >&2; exit 4"], log) == 4 and "oops" in log.read_text()


def test_a_restarted_loop_first_processes_valid_incidents_left_without_a_label(tmp_path):
    # a process that failed earlier: `next` already counts the incident, so the loop must finish it before moving on
    layout = DataLayout(tmp_path)
    run_group(layout, "RG-001", "paymentFailure", "100%", "valid", inc="INC-001")
    stack = Stack(layout, ["valid"])
    out, _ = loop(tmp_path, stack, max_runs=1)
    first = stack.calls[0]
    assert first[first.index("collect") + 1] == "process" and first[first.index("--incident") + 1] == "INC-001"
    assert layout.label_path("INC-001").exists() and out["runs"][0]["flag"] == "productCatalogFailure"
    stack = Stack(DataLayout(tmp_path / "b"), [], process_rc=2)
    run_group(DataLayout(tmp_path / "b"), "RG-001", "paymentFailure", "100%", "valid", inc="INC-001")
    out, _ = loop(tmp_path / "b", stack)
    assert out["stopped"] == "process_failed" and out["incident_id"] == "INC-001" and len(stack.calls) == 1


def test_a_restarted_loop_never_processes_an_incident_of_a_withdrawn_run_group(tmp_path):
    # decision 025 revision 3: a withdrawn incident counts for no set (the real RG-002 has no label and is withdrawn)
    from collect.pilot import withdraw

    layout = DataLayout(tmp_path)
    run_group(layout, "RG-001", "paymentFailure", "100%", "valid", inc="INC-001")
    withdraw(layout, "RG-001", reason="started in the automatic power mode", decided_by="user", now="2026-10-09T02:00:00Z")
    stack = Stack(layout, ["valid"])
    out, _ = loop(tmp_path, stack, max_runs=1)
    assert not any(c[c.index("collect") + 1] == "process" and "INC-001" in c for c in stack.calls if "collect" in c)
    first = stack.calls[0]
    assert first[first.index("collect") + 1] == "run" and out["runs"][0]["flag"] == "paymentFailure"  # collected again
