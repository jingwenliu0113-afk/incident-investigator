"""python -m collect run — collect one run group under the Mac heavy lock (decision 009).

    ./tools/with-mac-lock uv run python -m collect run --set pilot --flag paymentFailure --variant 100%

Held-out (decisions 023, 026): heldout-plan -> heldout-freeze -> per slot next / run --set heldout / process -> heldout-list;
every held-out step is refused without a passing freeze record.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

from collect.labels import FLAG_FAULT_TYPES
from collect.layout import DataLayout
from collect.pilot import planned
from collect.records import load_flag_catalog
from collect.rungroup import Plan, next_id, run_group, store_run_group
from env.lock import PROJECT_DIR

UPSTREAM_DIR = PROJECT_DIR / "env/upstream/opentelemetry-demo"
FLAG_FILE = UPSTREAM_DIR / "src/flagd/demo.flagd.json"
PILOT_FAULT_MINUTES = 10  # decision 009 (amended): every Pilot fault lasts the same, so window length tells nothing
HELDOUT_FAULT_MINUTES = PILOT_FAULT_MINUTES  # decision 023 §3: the held-out faults last as long as the Pilot ones


class UsageError(Exception):
    pass


def _freeze_problems() -> list[str]:
    from collect import freeze

    return freeze.check_freeze(PROJECT_DIR)[1]


def _heldout_docs() -> tuple[dict, dict]:
    from collect.heldout import PLAN_FILE, SLOTS_FILE

    return json.loads((PROJECT_DIR / PLAN_FILE).read_text()), json.loads((PROJECT_DIR / SLOTS_FILE).read_text())


def _heldout_slot(ns: argparse.Namespace, layout: DataLayout) -> dict:
    """decision 023 §4: a held-out run needs a passing freeze, a complete and reviewed Pilot, and must be the next slot."""
    from collect import freeze
    from collect.heldout import next_slot, pilot_problems

    if problems := freeze.check_freeze(PROJECT_DIR)[1]:
        raise UsageError("held-out collection is refused: " + "; ".join(problems))
    try:
        plan_doc, slots_doc = _heldout_docs()
        removed = {(r["flag"], r["variant"]) for r in plan_doc["removed"]}
        if problems := pilot_problems(layout, removed):
            raise UsageError("held-out collection waits for the Pilot and its review (decision 023 §4): " + "; ".join(problems))
        sha = freeze.freeze_sha256(PROJECT_DIR)
        slot = next_slot(layout, slots_doc, freeze_sha=sha)
    except (ValueError, RuntimeError, OSError, KeyError) as e:
        raise UsageError(f"held-out collection is refused: {e}") from e
    if slot is None:
        raise UsageError("every held-out slot is filled or closed: no added collection (decision 023 §2)")
    if (ns.flag, ns.variant) != (slot["flag"], slot["variant"]):
        raise UsageError(f"{ns.flag} {ns.variant} is not the next slot ({slot['slot']}: {slot['flag']} {slot['variant']}): "
                         "run `collect next --set heldout`")
    if planned("heldout", ns.flag, ns.variant, project_dir=PROJECT_DIR) is None:
        raise UsageError(f"{ns.flag} {ns.variant} is not on the held-out plan (decision 023 §1)")
    return {"slot": slot["slot"], "freeze_sha256": sha}


def _check_args(ns: argparse.Namespace, layout: DataLayout) -> dict:
    """The plan fields the set fixes ({} for the Pilot; slot and freeze sha for the held-out set, decision 023 §4)."""
    from collect.heldout import FREEZE_FILE

    if ns.split == "heldout" and ns.seed is not None:
        raise UsageError("--seed is refused for the held-out set: every run group draws a fresh SystemRandom seed, recorded "
                         "on the ground-truth side only (decision 023 §4)")
    if ns.flag not in FLAG_FAULT_TYPES:
        raise UsageError(f"flag {ns.flag!r} is not a Core fault (decision 006)")
    catalog = load_flag_catalog(FLAG_FILE)
    if ns.variant not in catalog[ns.flag]["variants"] or ns.variant == catalog[ns.flag]["default"]:
        raise UsageError(f"flag {ns.flag!r} has no variant {ns.variant!r} that injects a fault")
    if ns.split == "heldout":
        return _heldout_slot(ns, layout)
    if (PROJECT_DIR / FREEZE_FILE).exists():
        raise UsageError("the Pilot is closed at the held-out freeze (decision 023 §6): no Pilot run group after it")
    if planned(ns.split, ns.flag, ns.variant) is None:
        raise UsageError(f"{ns.flag} {ns.variant} is not on the {ns.split} plan (decision 016): "
                         "a set collects only its pre-registered faults")
    return {}


INCIDENT_COMMANDS = ("normalize", "replay", "label", "process", "review-sheet", "review")


def _heldout_incident_guard(layout: DataLayout, incident: str) -> None:
    """decision 023 §4 / §6: a held-out incident is processed only by the frozen code (a passing freeze check)."""
    from collect.heldout import run_split
    from collect.incident import find_run

    try:
        run = find_run(layout, incident)
    except LookupError:
        return  # unknown incident: the command's own error path reports it
    injection = layout.injection_path(run["run_group_id"])
    heldout = run_split(run) == "heldout" or (injection.exists() and json.loads(injection.read_text()).get("split") == "heldout")
    if heldout and (problems := _freeze_problems()):
        raise PermissionError(f"{incident} is a held-out incident and the freeze check fails: " + "; ".join(problems))


def _normalize(layout: DataLayout, incident: str) -> dict:
    from datetime import UTC, datetime

    from collect.incident import normalize_incident
    from env.cli import _load_lock
    from env.lock import lock_sha256

    report = normalize_incident(layout, incident, lock_sha256=lock_sha256(_load_lock(PROJECT_DIR)),
                                now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    # counts of what was removed stay in the ground-truth report; only the snapshot digest is printed
    return {"incident_id": incident, "content_sha256": report["content_sha256"]}


def _replay(layout: DataLayout, incident: str) -> dict:
    import os

    from collect.replay import replay
    from env import compose, soak
    from env.cli import _load_lock

    lock, env = _load_lock(PROJECT_DIR), compose.sanitized_env(os.environ)
    return replay(layout, incident, live_containers=lambda: sorted(soak.project_container_ids(lock, env).values()))


def _label(layout: DataLayout, incident: str, labeler: str) -> dict:
    from datetime import UTC, datetime

    from collect.labeling import catalog_label_from_plan

    label = catalog_label_from_plan(layout, incident, labeler=labeler, now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    project_dir=PROJECT_DIR)
    # the label is ground truth: only say where it went
    return {"incident_id": incident, "label": "written", "method": label["labeling"]["method"]}


def _heldout_progress(command: str) -> int:
    """`next|status --set heldout`: slots, faults, states, counts, non-valid run-group ids and power settings only (never an
    incident id or a valid run-group id). next: exit 2 on a failing freeze, an incomplete Pilot or a corrupt record, 3 when a
    person is needed."""
    from collect import freeze
    from collect.heldout import FREEZE_FILE, next_slot, pilot_problems, slot_status

    layout = DataLayout(PROJECT_DIR / "data/external")
    if command == "status":
        if not (PROJECT_DIR / FREEZE_FILE).exists():
            print(f"error: {freeze.NO_FREEZE}", file=sys.stderr)
            return 2
        problems = freeze.check_freeze(PROJECT_DIR)[1]
        try:
            rows = slot_status(layout, _heldout_docs()[1], freeze_sha=freeze.freeze_sha256(PROJECT_DIR))
        except (ValueError, OSError, KeyError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        summary = {state: sum(r["state"] == state for r in rows) for state in ("filled", "open", "closed", "needs_person")}
        print(json.dumps({"slots": rows, "summary": summary, "freeze_problems": problems}, indent=2))
        return 0
    if problems := freeze.check_freeze(PROJECT_DIR)[1]:
        print("error: " + "; ".join(problems), file=sys.stderr)
        return 2
    try:
        plan_doc, slots_doc = _heldout_docs()
        if problems := pilot_problems(layout, {(r["flag"], r["variant"]) for r in plan_doc["removed"]}):
            print("error: held-out collection waits for the Pilot and its review: " + "; ".join(problems), file=sys.stderr)
            return 2
        slot = next_slot(layout, slots_doc, freeze_sha=freeze.freeze_sha256(PROJECT_DIR))
    except RuntimeError as e:  # slots wait for a person (decision 023 §4)
        print(f"error: {e}", file=sys.stderr)
        return 3
    except (ValueError, OSError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if slot is not None:
        print(f"--flag {slot['flag']} --variant {slot['variant']}")
        print(json.dumps({"slot": slot["slot"], "skipped_needs_person": slot["skipped"]}), file=sys.stderr)
    return 0


def _heldout_writer(ns: argparse.Namespace) -> int:
    """heldout-plan / heldout-freeze (written once, after the Pilot; decision 023 line 6) and heldout-list (§5.5)."""
    import subprocess
    from datetime import UTC, datetime

    from collect import freeze
    from eval.runner import METHODS

    layout = DataLayout(PROJECT_DIR / "data/external")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    kw = {"methods": sorted(METHODS), "results_root": layout.root / "results"}
    try:
        if ns.command == "heldout-plan":
            out = freeze.write_heldout_plan(PROJECT_DIR, layout, json.loads(ns.amendments.read_text()), **kw)
        elif ns.command == "heldout-freeze":
            out = freeze.write_freeze(PROJECT_DIR, layout, json.loads(ns.pilot_revisions.read_text()), now=now, **kw)
        else:
            from collect.heldout import heldout_incidents, write_once

            record, problems = freeze.check_freeze(PROJECT_DIR)
            if problems:
                raise PermissionError("the held-out list is refused: " + "; ".join(problems))
            plan_doc, slots_doc = _heldout_docs()
            doc = heldout_incidents(layout, slots_doc, plan_doc, freeze=record, freeze_sha=freeze.freeze_sha256(PROJECT_DIR),
                                    results_root=kw["results_root"], now=now,
                                    commit_check=lambda commit: freeze.commit_problems(PROJECT_DIR, record, commit))
            sha = write_once(layout.heldout_incidents_path, doc)
            out = {"listed": len(doc["incidents"]), "excluded": len(doc["excluded"]), "closed_slots": len(doc["closed_slots"]),
                   "removed_faults": len(doc["removed_faults"]), "sha256": sha}
    except (ValueError, LookupError, OSError, KeyError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


# normal covers the statistical baseline's 10-minute reference: with less, it abstains by design and checks nothing
SMOKE_MINUTES = {"normal": 10, "fault": 2, "recovery": 2}


def _sample(ns: argparse.Namespace) -> int:
    """decision 027: the synthetic sample goes anywhere but the formal data root (generate refuses it in any spelling)."""
    from collect.sample import generate

    out = ns.out.resolve()
    try:
        manifest = generate(out, replace=ns.replace, project_dir=PROJECT_DIR)
    except (FileExistsError, ValueError, PermissionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"out": str(out), "synthetic": manifest["synthetic"], "files": len(manifest["files"]),
                      "bytes": sum(f["bytes"] for f in manifest["files"])}, indent=2))
    return 0


def _smoke(ns: argparse.Namespace) -> int:
    """A short non-formal run through the real stack and every later step, all under a scratch root."""
    root = ns.root.resolve()
    formal = (PROJECT_DIR / "data" / "external").resolve()
    if root == formal or formal in root.parents:
        print(f"error: the smoke root must be outside {formal} (a smoke run is never part of any set)", file=sys.stderr)
        return 2
    import subprocess
    from datetime import UTC, datetime

    from collect.live import LiveStack, RealClock
    from collect.review import review_sheet
    from eval.runner import audit_set, run_method, score_method

    layout = DataLayout(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "SMOKE.txt").write_text("non-formal smoke run: never use these data in any set\n")
    rg = next_id(layout, "RG")
    plan = Plan(run_group_id=rg, seed=random.SystemRandom().randrange(2**31), flag=ns.flag, variant=ns.variant,
                fault_minutes=SMOKE_MINUTES["fault"], normal_base_minutes=SMOKE_MINUTES["normal"], normal_jitter_minutes=0,
                recovery_base_minutes=SMOKE_MINUTES["recovery"], recovery_jitter_minutes=0)
    stack = LiveStack(PROJECT_DIR, UPSTREAM_DIR, PROJECT_DIR / "data/external")  # preflight: the formal lock and soak
    work = root / "staging" / rg
    record = run_group(plan, stack, RealClock(), flag_path=FLAG_FILE, work_dir=work)
    stored = store_run_group(record, work, layout, lock_sha256=stack.lock_sha256)
    steps: dict = {"run_group_id": rg, "status": record["status"], "reasons": record["reasons"],
                   "clock_offset_seconds": record.get("clock_offset_seconds"), "incident_ids": stored["incident_ids"]}
    if record["status"] == "valid":
        inc = stored["incident_ids"][0]
        try:
            steps["normalize"] = _normalize(layout, inc)["content_sha256"]
            out = _replay(layout, inc)
            steps["replay"] = {"every_id_resolves": out["every_id_resolves"], "checks": out["checks"]}
            steps["label"] = _label(layout, inc, "agent:smoke")["label"]
            review_sheet(layout, inc)
            steps["review_sheet"] = "written"
            results = root / "results"
            steps["leakage"] = audit_set(layout, "pilot", results)["incidents"]
            run_method(layout, "stat-anomaly", "pilot", results)
            scored = score_method(layout, "stat-anomaly", "pilot", results)
            steps["stat_anomaly"] = {"main": {m: v["mean"] for m, v in scored["aggregate"]["metrics"].items()},
                                     "failure": scored["incidents"][0]["failure"]}
        except (LookupError, ValueError, PermissionError, RuntimeError, OSError, subprocess.CalledProcessError) as e:
            steps["error"] = f"{type(e).__name__}: {e}"
    steps["finished_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(json.dumps(steps, indent=2, default=str))
    return 0 if record["status"] == "valid" and "error" not in steps else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m collect", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="collect one run group (needs the Mac heavy lock)")
    run.add_argument("--set", dest="split", required=True, choices=["pilot", "heldout"],
                     help="the set this run group belongs to, fixed now (SPEC §5: pilot incidents never enter the test)")
    run.add_argument("--flag", required=True)
    run.add_argument("--variant", required=True)
    run.add_argument("--seed", type=int, help="default: a fresh random seed (recorded)")
    norm = sub.add_parser("normalize", help="raw -> canonical snapshot of one incident (policy must be frozen)")
    norm.add_argument("--incident", required=True)
    cal = sub.add_parser("calibrate", help="dry normalize + inventory on a soak's raw (no fault), before freezing")
    cal.add_argument("--soak", type=Path, required=True)
    frz = sub.add_parser("freeze", help="freeze the calibrating policy from passing calibrations of this exact file")
    frz.add_argument("--calibration", type=Path, action="append", required=True, help="a calibration.json (repeat)")
    rep = sub.add_parser("replay", help="Day 1 #6: analyse an incident from its snapshot alone (live system deleted)")
    rep.add_argument("--incident", required=True)
    lab = sub.add_parser("label", help="write an incident's a priori (catalog) label: fault facts from injection.json, "
                                       "origin / affected / symptom from its set's pre-registered plan (decision 016)")
    lab.add_argument("--incident", required=True)
    lab.add_argument("--labeler", required=True, help="who labels, e.g. human:<name> or agent:claude-code")
    smk = sub.add_parser("smoke", help="NOT a formal run: a short run (10-minute normal, 2-minute fault / recovery) into a scratch "
                                       "data root, then normalize, replay, label, review sheet, leakage audit and the "
                                       "statistical baseline there; "
                                       "checks the whole pipeline and never enters any set")
    smk.add_argument("--root", type=Path, required=True, help="scratch data root, outside data/external")
    smk.add_argument("--flag", default="paymentFailure")
    smk.add_argument("--variant", default="100%")
    lp = sub.add_parser("pilot-loop", help="collect the Pilot set to completion: next -> one run under the Mac heavy lock "
                                           "-> process, repeated; waits for a busy lock, stops where a person is needed, "
                                           "then leakage audit and the statistical baseline (run it without with-mac-lock)")
    lp.add_argument("--labeler", required=True, help="who writes the a priori labels, e.g. agent:claude-code")
    lp.add_argument("--max-runs", type=int, help="stop after this many run groups")
    ack = sub.add_parser("ack-failures", help="decision 016 §5: record that a person looked at the failed run groups of a "
                                              "fault, so it is collected again and its invalid attempts count anew")
    ack.add_argument("--set", dest="split", required=True, choices=["pilot"])
    ack.add_argument("--flag", required=True)
    ack.add_argument("--variant", required=True)
    ack.add_argument("--reason", required=True)
    ack.add_argument("--decided-by", required=True, help="the person who looked, e.g. user")
    sta = sub.add_parser("status", help="decision 016: run groups and incidents of every planned fault of a set")
    sta.add_argument("--set", dest="split", required=True, choices=["pilot", "heldout"])
    nxt = sub.add_parser("next", help="the next planned fault to collect, as `--flag F --variant V` (nothing when complete)")
    nxt.add_argument("--set", dest="split", required=True, choices=["pilot", "heldout"])
    hpl = sub.add_parser("heldout-plan", help="decision 023 §1: write docs/heldout/plan.json once, from the Pilot plan, the Pilot "
                                              "review evidence and a person's amendments and removals (after the Pilot)")
    hpl.add_argument("--amendments", type=Path, required=True, help='{"amend": [...], "remove": [...]} (decision 026)')
    hfz = sub.add_parser("heldout-freeze", help="decision 023 §4, §6: write docs/heldout/slots.json and freeze.json once, on a "
                                                "clean checkout with the plan committed; commit exactly those two files next")
    hfz.add_argument("--pilot-revisions", type=Path, required=True, help="used / waived for each decision's one Pilot revision")
    sub.add_parser("heldout-list", help="decision 023 §5.5: write heldout_incidents.json once (ground-truth side), after every "
                                        "slot is filled or closed, processed, audited and reviewed; prints counts only")
    pro = sub.add_parser("process", help="after a valid run: normalize, replay and the a priori label (steps already done are skipped)")
    pro.add_argument("--incident", required=True)
    pro.add_argument("--labeler", required=True, help="who writes the a priori label, e.g. agent:claude-code")
    rsh = sub.add_parser("review-sheet", help="decision 018: the label review worksheet of one incident (ground-truth side)")
    rsh.add_argument("--incident", required=True)
    rsh.add_argument("--overwrite", action="store_true", help="replace an existing (possibly half filled) worksheet")
    rev = sub.add_parser("review", help="decision 018: write the catalog+review label from a filled worksheet (a person only)")
    rev.add_argument("--incident", required=True)
    rev.add_argument("--file", type=Path, required=True, help="the filled label_review_todo.json")
    rev.add_argument("--reviewer", required=True, help="human:<name>")
    smp = sub.add_parser("sample", help="decision 027: write the tiny SYNTHETIC sample (generated raw -> the real normalize, "
                                        "a catalog label, the statistical baseline's prediction); never collected data")
    smp.add_argument("--out", type=Path, required=True, help="e.g. data/samples/synthetic (never under data/external)")
    smp.add_argument("--replace", action="store_true", help="regenerate over a sample that collect.sample wrote")
    ns = parser.parse_args(argv)

    if ns.command in INCIDENT_COMMANDS:
        try:
            _heldout_incident_guard(DataLayout(PROJECT_DIR / "data/external"), ns.incident)
        except (PermissionError, ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if ns.command == "replay":
        import subprocess

        try:
            out = _replay(DataLayout(PROJECT_DIR / "data/external"), ns.incident)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as e:  # e.g. the Docker daemon is not running
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2))
        return 0 if out["every_id_resolves"] and not out["checks"] else 1

    if ns.command == "freeze":
        from collect.calibrate import freeze
        from collect.policy import POLICY_PATH

        try:
            out = freeze(POLICY_PATH, ns.calibration)
        except (ValueError, OSError, KeyError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps({**out, "next": "re-pin POLICY_SHA256 in collect/policy.py to this sha256, run the tests, "
                                         "record the freeze in decision 011, commit"}, indent=2))
        return 0
    if ns.command == "smoke":
        return _smoke(ns)
    if ns.command == "sample":
        return _sample(ns)
    if ns.command == "pilot-loop":
        from collect.pilot_loop import pilot_loop
        from collect.provenance import power_facts

        layout = DataLayout(PROJECT_DIR / "data/external")
        print(json.dumps({"power": power_facts()}), flush=True)  # decision 025: what this collection runs under
        out = pilot_loop(layout, labeler=ns.labeler, log_dir=layout.root / "logs" / "pilot-loop", max_runs=ns.max_runs)
        print(json.dumps(out, indent=2))
        return {"complete": 0, "max_runs": 0, "needs_person": 3, "lock_busy": 75}.get(out["stopped"], 1)
    if ns.command in ("status", "next") and ns.split == "heldout":
        return _heldout_progress(ns.command)
    if ns.command in ("heldout-plan", "heldout-freeze", "heldout-list"):
        return _heldout_writer(ns)
    if ns.command == "ack-failures":
        from datetime import UTC, datetime

        from collect.pilot import acknowledge_failures

        try:
            out = acknowledge_failures(DataLayout(PROJECT_DIR / "data/external"), ns.split, ns.flag, ns.variant,
                                       reason=ns.reason, decided_by=ns.decided_by,
                                       now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2))
        return 0
    if ns.command in ("status", "next"):
        from collect.pilot import next_planned, plan_status

        layout = DataLayout(PROJECT_DIR / "data/external")
        if ns.command == "status":
            print(json.dumps(plan_status(layout, ns.split), indent=2))
            return 0
        try:
            entry = next_planned(layout, ns.split)
        except RuntimeError as e:  # a fault needs a person before it is collected again
            print(f"error: {e}", file=sys.stderr)
            return 3
        if entry is not None:
            print(f"--flag {entry['flag']} --variant {entry['variant']}")
        return 0
    if ns.command == "process":
        import subprocess

        layout = DataLayout(PROJECT_DIR / "data/external")
        steps: dict = {"incident_id": ns.incident}
        try:
            if (layout.incident_dir(ns.incident) / "normalized" / "snapshot.json").exists():
                steps["normalize"] = "already done"
            else:
                steps["normalize"] = _normalize(layout, ns.incident)["content_sha256"]
            out = _replay(layout, ns.incident)
            steps["replay"] = {"every_id_resolves": out["every_id_resolves"], "checks": out["checks"]}
            if not out["every_id_resolves"] or out["checks"]:
                print(json.dumps(steps, indent=2))
                return 1
            steps["label"] = ("already done" if layout.label_path(ns.incident).exists()
                              else _label(layout, ns.incident, ns.labeler)["label"])
        except (LookupError, ValueError, PermissionError, RuntimeError, OSError, subprocess.CalledProcessError) as e:
            print(json.dumps(steps, indent=2))
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(steps, indent=2))
        return 0
    if ns.command in ("review-sheet", "review"):
        from datetime import UTC, datetime

        from collect.review import apply_review, review_sheet

        layout = DataLayout(PROJECT_DIR / "data/external")
        try:
            if ns.command == "review-sheet":
                review_sheet(layout, ns.incident, overwrite=ns.overwrite)
                path = layout.label_path(ns.incident).with_name("label_review_todo.json")
                print(json.dumps({"incident_id": ns.incident, "worksheet": str(path)}))
            else:
                record = apply_review(layout, ns.incident, json.loads(ns.file.read_text()), reviewer=ns.reviewer,
                                      now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
                print(json.dumps({"incident_id": ns.incident, "reviewed": True, "differences": len(record["differences"])}))
        except (LookupError, ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
    if ns.command == "label":
        try:
            print(json.dumps(_label(DataLayout(PROJECT_DIR / "data/external"), ns.incident, ns.labeler)))
        except (LookupError, ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
    if ns.command == "normalize":
        try:
            out = _normalize(DataLayout(PROJECT_DIR / "data/external"), ns.incident)
        except (LookupError, ValueError, PermissionError, RuntimeError, OSError) as e:  # OSError: a missing record file
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2))
        return 0
    if ns.command == "calibrate":
        from datetime import UTC, datetime

        from collect.calibrate import calibrate

        # one directory per iteration: earlier iterations stay as evidence (decision 011 §4)
        out = PROJECT_DIR / "data/external/calibration" / ns.soak.name / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        try:
            result = calibrate(ns.soak, out)
        except (ValueError, OSError, RuntimeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"out": str(out), "policy": result["policy"], "freeze_check": result["freeze_check"],
                          "seconds": result["seconds"], "max_rss_bytes": result["max_rss_bytes"]}, indent=2))
        return 0 if result["freeze_check"]["pass"] else 1

    layout = DataLayout(PROJECT_DIR / "data/external")
    try:
        fixed = _check_args(ns, layout)
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    from collect.live import LiveStack, RealClock  # Docker-backed; imported only for a real run
    from env.lock import verify_against_disk

    if ns.split == "heldout":
        from collect.heldout import fresh_seed

        seed, minutes = fresh_seed(layout), HELDOUT_FAULT_MINUTES  # decision 023 §3, §4
    else:
        seed, minutes = ns.seed if ns.seed is not None else random.SystemRandom().randrange(2**31), PILOT_FAULT_MINUTES
    rg = next_id(layout, "RG")
    plan = Plan(run_group_id=rg, seed=seed, flag=ns.flag, variant=ns.variant, fault_minutes=minutes, split=ns.split, **fixed)
    stack = LiveStack(PROJECT_DIR, UPSTREAM_DIR, layout.root)
    work = layout.root / "staging" / rg
    import signal

    def interrupt(signum, frame):  # SIGTERM / SIGHUP (terminal closed) unwind like Ctrl-C, so the teardown runs
        raise KeyboardInterrupt(f"signal {signum}")

    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, interrupt)
    try:
        record = run_group(plan, stack, RealClock(), flag_path=FLAG_FILE, work_dir=work)
    except BaseException as e:
        if (crashed := getattr(e, "run_record", None)) is not None:  # decision 009 §4: a started run keeps its record
            store_run_group(crashed, work, layout, lock_sha256=stack.lock_sha256)
        if isinstance(e, RuntimeError):
            print(f"error: {e}", file=sys.stderr)
            return 2
        raise
    stored = store_run_group(record, work, layout, lock_sha256=stack.lock_sha256)
    after = verify_against_disk(stack.lock, UPSTREAM_DIR, PROJECT_DIR)
    print(json.dumps({"run_group_id": rg, "status": record["status"], "reasons": record["reasons"],
                      "incident_ids": stored["incident_ids"], "teardown_verify": after}, indent=2))
    return 0 if record["status"] == "valid" and not after else 1


if __name__ == "__main__":
    sys.exit(main())
