"""Diagnostic (not formal, decision 012): does a no-op `docker update` make docker_stats collect a container it missed?

up -> verify-running -> wait 90 s -> rescan -> wait 150 s -> stop collector -> cp raw -> down.
Compares, per container, docker_stats minutes before and after the rescan. Run under ./tools/with-mac-lock.
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run as a script from the project root

from collect.live import LiveStack  # noqa: E402
from collect.rawfile import container_minutes  # noqa: E402
from env import soak  # noqa: E402
from env.lock import PROJECT_DIR  # noqa: E402

UPSTREAM_DIR = PROJECT_DIR / "env/upstream/opentelemetry-demo"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(out: Path) -> int:
    out.mkdir(parents=True)
    stack = LiveStack(PROJECT_DIR, UPSTREAM_DIR, PROJECT_DIR / "data")
    if soak.project_container_ids(stack.lock, stack.env):
        print("project containers already exist")
        return 2
    rec: dict = {"up_at": now()}
    try:
        rec["up_rc"] = stack.compose(["up"])
        if rec["up_rc"] != 0:
            return 1
        rec["verify_running"] = stack.verify_running(300)
        rec["expected"] = sorted(soak.project_container_ids(stack.lock, stack.env).values())
        rec["verified_at"] = now()
        time.sleep(90)  # two docker_stats minutes before the rescan
        rec["rescan_at"] = now()
        rec["rescan"] = stack.rescan_containers()
        time.sleep(150)
        rec["stop_at"] = now()
        raw = stack.finalize_raw(out)
        rec["collector"] = raw["collector"]
    finally:
        rec["down_rc"] = stack.compose(["down", "--volumes"])
        metrics = out / "raw" / "metrics.jsonl"
        cm = container_minutes(metrics) if metrics.is_file() else {}
        rescan_minute = rec.get("rescan_at", "")[:16]
        rec["containers"] = {name: {"before": [m for m in mins if m < rescan_minute],
                                    "after": [m for m in mins if m > rescan_minute]}
                             for name in sorted(set(rec.get("expected", [])) | set(cm)) for mins in [cm.get(name, [])]}
        (out / "rescan.json").write_text(json.dumps(rec, indent=2) + "\n")
        print(json.dumps({k: rec.get(k) for k in ("up_rc", "rescan", "down_rc")}))
        print("containers seen:", len(cm))
        for name, d in rec["containers"].items():
            if not d["before"] or not d["after"]:
                print(f"  {name}: before={d['before']} after={d['after']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
