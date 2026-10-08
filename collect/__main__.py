"""python -m collect run — collect one run group under the Mac heavy lock (decision 009).

    ./tools/with-mac-lock uv run python -m collect run --set pilot --flag paymentFailure --variant 100%
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


class UsageError(Exception):
    pass


def _check_args(ns: argparse.Namespace) -> None:
    if ns.split == "heldout":
        raise UsageError("held-out collection needs its own protocol decision first (fault list, durations, split); "
                         "only --set pilot is collected for now")
    if ns.flag not in FLAG_FAULT_TYPES:
        raise UsageError(f"flag {ns.flag!r} is not a Core fault (decision 006)")
    catalog = load_flag_catalog(FLAG_FILE)
    if ns.variant not in catalog[ns.flag]["variants"] or ns.variant == catalog[ns.flag]["default"]:
        raise UsageError(f"flag {ns.flag!r} has no variant {ns.variant!r} that injects a fault")
    if planned(ns.split, ns.flag, ns.variant) is None:
        raise UsageError(f"{ns.flag} {ns.variant} is not on the {ns.split} plan (decision 016): "
                         "a set collects only its pre-registered faults")


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

    label = catalog_label_from_plan(layout, incident, labeler=labeler, now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    # the label is ground truth: only say where it went
    return {"incident_id": incident, "label": "written", "method": label["labeling"]["method"]}


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
    sta = sub.add_parser("status", help="decision 016: run groups and incidents of every planned fault of a set")
    sta.add_argument("--set", dest="split", required=True, choices=["pilot"])
    nxt = sub.add_parser("next", help="the next planned fault to collect, as `--flag F --variant V` (nothing when complete)")
    nxt.add_argument("--set", dest="split", required=True, choices=["pilot"])
    pro = sub.add_parser("process", help="after a valid run: normalize, replay and the a priori label (steps already done are skipped)")
    pro.add_argument("--incident", required=True)
    pro.add_argument("--labeler", required=True, help="who writes the a priori label, e.g. agent:claude-code")
    rsh = sub.add_parser("review-sheet", help="decision 018: the label review worksheet of one incident (ground-truth side)")
    rsh.add_argument("--incident", required=True)
    rev = sub.add_parser("review", help="decision 018: write the catalog+review label from a filled worksheet (a person only)")
    rev.add_argument("--incident", required=True)
    rev.add_argument("--file", type=Path, required=True, help="the filled label_review_todo.json")
    rev.add_argument("--reviewer", required=True, help="human:<name>")
    ns = parser.parse_args(argv)

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
                review_sheet(layout, ns.incident)
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

    try:
        _check_args(ns)
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    from collect.live import LiveStack, RealClock  # Docker-backed; imported only for a real run
    from env.lock import verify_against_disk

    layout = DataLayout(PROJECT_DIR / "data/external")
    rg = next_id(layout, "RG")
    seed = ns.seed if ns.seed is not None else random.SystemRandom().randrange(2**31)
    plan = Plan(run_group_id=rg, seed=seed, flag=ns.flag, variant=ns.variant, fault_minutes=PILOT_FAULT_MINUTES,
                split=ns.split)
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
