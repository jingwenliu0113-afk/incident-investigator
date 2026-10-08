"""python -m collect run — collect one run group under the Mac heavy lock (decision 009).

    ./tools/with-mac-lock uv run python -m collect run --flag paymentFailure --variant 100% --fault-minutes 10
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence

from collect.labels import FLAG_FAULT_TYPES
from collect.layout import DataLayout
from collect.records import load_flag_catalog
from collect.rungroup import Plan, next_id, run_group, store_run_group
from env.lock import PROJECT_DIR

UPSTREAM_DIR = PROJECT_DIR / "env/upstream/opentelemetry-demo"
FLAG_FILE = UPSTREAM_DIR / "src/flagd/demo.flagd.json"
MIN_FAULT_MINUTES = MIN_RECOVERY_MINUTES = 5  # decision 009 §1


class UsageError(Exception):
    pass


def _check_args(ns: argparse.Namespace) -> None:
    if ns.fault_minutes < MIN_FAULT_MINUTES or ns.recovery_minutes < MIN_RECOVERY_MINUTES:
        raise UsageError("fault and recovery must each last at least 5 minutes (decision 009 §1)")
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
    run.add_argument("--fault-minutes", type=float, required=True)
    run.add_argument("--recovery-minutes", type=float, default=5)
    run.add_argument("--seed", type=int, help="default: a fresh random seed (recorded)")
    ns = parser.parse_args(argv)

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
    plan = Plan(run_group_id=rg, seed=seed, flag=ns.flag, variant=ns.variant, fault_minutes=ns.fault_minutes,
                recovery_minutes=ns.recovery_minutes)
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
