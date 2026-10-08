"""python -m collect run — collect one run group under the Mac heavy lock (decision 009).

    ./tools/with-mac-lock uv run python -m collect run --flag paymentFailure --variant 100%
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
from collect.records import load_flag_catalog
from collect.rungroup import Plan, next_id, run_group, store_run_group
from env.lock import PROJECT_DIR

UPSTREAM_DIR = PROJECT_DIR / "env/upstream/opentelemetry-demo"
FLAG_FILE = UPSTREAM_DIR / "src/flagd/demo.flagd.json"
PILOT_FAULT_MINUTES = 10  # decision 009 (amended): every Pilot fault lasts the same, so window length tells nothing


class UsageError(Exception):
    pass


def _check_args(ns: argparse.Namespace) -> None:
    if ns.flag not in FLAG_FAULT_TYPES:
        raise UsageError(f"flag {ns.flag!r} is not a Core fault (decision 006)")
    catalog = load_flag_catalog(FLAG_FILE)
    if ns.variant not in catalog[ns.flag]["variants"] or ns.variant == catalog[ns.flag]["default"]:
        raise UsageError(f"flag {ns.flag!r} has no variant {ns.variant!r} that injects a fault")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m collect", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="collect one run group (needs the Mac heavy lock)")
    run.add_argument("--flag", required=True)
    run.add_argument("--variant", required=True)
    run.add_argument("--seed", type=int, help="default: a fresh random seed (recorded)")
    norm = sub.add_parser("normalize", help="raw -> canonical snapshot of one incident (policy must be frozen)")
    norm.add_argument("--incident", required=True)
    cal = sub.add_parser("calibrate", help="dry normalize + inventory on a soak's raw (no fault), before freezing")
    cal.add_argument("--soak", type=Path, required=True)
    rep = sub.add_parser("replay", help="Day 1 #6: analyse an incident from its snapshot alone (live system deleted)")
    rep.add_argument("--incident", required=True)
    ns = parser.parse_args(argv)

    if ns.command == "replay":
        import os

        from collect.replay import replay
        from env import compose, soak
        from env.cli import _load_lock

        lock, env = _load_lock(PROJECT_DIR), compose.sanitized_env(os.environ)
        try:
            out = replay(DataLayout(PROJECT_DIR / "data/external"), ns.incident,
                         live_containers=lambda: sorted(soak.project_container_ids(lock, env).values()))
        except (RuntimeError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2))
        return 0 if out["every_id_resolves"] and not out["checks"] else 1

    if ns.command == "normalize":
        from datetime import UTC, datetime

        from collect.incident import normalize_incident
        from env.cli import _load_lock
        from env.lock import lock_sha256

        layout = DataLayout(PROJECT_DIR / "data/external")
        try:
            report = normalize_incident(layout, ns.incident, lock_sha256=lock_sha256(_load_lock(PROJECT_DIR)),
                                        now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        except (LookupError, ValueError, PermissionError, RuntimeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        # counts of what was removed stay in the ground-truth report; only the snapshot digest is printed
        print(json.dumps({"incident_id": ns.incident, "content_sha256": report["content_sha256"]}, indent=2))
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
    plan = Plan(run_group_id=rg, seed=seed, flag=ns.flag, variant=ns.variant, fault_minutes=PILOT_FAULT_MINUTES)
    stack = LiveStack(PROJECT_DIR, UPSTREAM_DIR, layout.root)
    work = layout.root / "staging" / rg
    try:
        record = run_group(plan, stack, RealClock(), flag_path=FLAG_FILE, work_dir=work)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    stored = store_run_group(record, work, layout, lock_sha256=stack.lock_sha256)
    after = verify_against_disk(stack.lock, UPSTREAM_DIR, PROJECT_DIR)
    print(json.dumps({"run_group_id": rg, "status": record["status"], "reasons": record["reasons"],
                      "incident_ids": stored["incident_ids"], "teardown_verify": after}, indent=2))
    return 0 if record["status"] == "valid" and not after else 1


if __name__ == "__main__":
    sys.exit(main())
