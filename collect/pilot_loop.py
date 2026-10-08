"""The Pilot loop (SPEC Week 1: automated collect -> normalize -> label; decisions 009, 016).

Until the Pilot plan is complete: `collect next` decides the fault, one `collect run` holds the Mac heavy lock for that
run only (other projects can take the lock between runs), `collect process` normalizes, replays and labels a valid run.
A busy lock is waited for and never taken (MACHINE_POLICY); anything that needs a person stops the loop. When every
fault has an incident: leakage audit, then the statistical baseline is run and scored.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from collect.layout import DataLayout
from collect.pilot import next_planned

LOCK_BUSY = 75  # tools/with-mac-lock: another workload holds the lock
SPLIT = "pilot"

PROJECT_DIR = Path(__file__).resolve().parent.parent

Call = Callable[[Sequence[str], Path], int]


def _subprocess(cmd: Sequence[str], log_path: Path) -> int:
    with log_path.open("a") as log:
        return subprocess.run(list(cmd), cwd=PROJECT_DIR, stdout=log, stderr=subprocess.STDOUT, check=False).returncode


def _run_groups(layout: DataLayout) -> set[str]:
    root = layout.ground_truth_root / "run_groups"
    return {p.name for p in root.glob("RG-*")} if root.exists() else set()


def _unprocessed(layout: DataLayout) -> list[str]:
    """Incidents of valid Pilot run groups without a label: a process that failed or was interrupted earlier."""
    out = []
    for path in sorted((layout.ground_truth_root / "run_groups").glob("RG-*/run.json")):
        r = json.loads(path.read_text())
        if r.get("status") == "valid" and (r.get("plan") or {}).get("split", SPLIT) == SPLIT:
            out += [inc for inc in r.get("incident_ids") or [] if not layout.label_path(inc).exists()]
    return out


def pilot_loop(layout: DataLayout, call: Call = _subprocess, *, project_dir: Path | None = None, labeler: str,
               log_dir: Path, lock_wait_s: float = 300, max_lock_waits: int = 48, max_runs: int | None = None,
               sleep: Callable[[float], None] | None = None) -> dict:
    """Collect the Pilot set to completion or to the first thing a person must look at; returns what happened."""
    import time

    sleep = sleep or time.sleep
    project_dir = project_dir or PROJECT_DIR
    lock = str(project_dir / "tools" / "with-mac-lock")
    py = ["uv", "run", "python", "-m"]
    log_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {"runs": [], "logs": []}

    def step(name: str, cmd: list[str]) -> int:
        log = log_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{name}.log"
        log.write_text(f"$ {' '.join(cmd)}\n")
        summary["logs"].append(str(log))
        return call(cmd, log)

    def stop(stopped: str, **extra) -> dict:
        return {"stopped": stopped, **extra, **summary}

    def process(inc: str) -> int:
        return step(f"process-{inc}", [*py, "collect", "process", "--incident", inc, "--labeler", labeler])

    for inc in _unprocessed(layout):  # `next` already counts these incidents: finish them before anything else
        if (rc := process(inc)) != 0:
            return stop("process_failed", incident_id=inc, exit_code=rc)
    waits = 0
    while max_runs is None or len(summary["runs"]) < max_runs:
        try:
            entry = next_planned(layout, SPLIT)
        except RuntimeError as e:  # decision 016 §5 / 009 §4: a fault a person must look at first
            return stop("needs_person", reason=str(e))
        if entry is None:
            for name, args in (("leakage", ["leakage", "--set", SPLIT]),
                               ("stat-run", ["run", "--method", "stat-anomaly", "--set", SPLIT]),
                               ("stat-score", ["score", "--method", "stat-anomaly", "--set", SPLIT])):
                if (rc := step(name, [*py, "eval", *args])) != 0:
                    return stop("eval_failed", step=name, exit_code=rc)
            return stop("complete")
        before = _run_groups(layout)
        rc = step(f"run-{entry['flag']}", [lock, *py, "collect", "run", "--set", SPLIT, "--flag", entry["flag"],
                                            "--variant", entry["variant"]])
        new = sorted(_run_groups(layout) - before)
        if rc == LOCK_BUSY and not new:
            waits += 1
            if waits > max_lock_waits:
                return stop("lock_busy", waited_s=(waits - 1) * lock_wait_s)
            sleep(lock_wait_s)
            continue
        if not new:  # refused before any run group existed: preflight (dirty tree, soak, lock), arguments, Docker
            return stop("run_refused", flag=entry["flag"], variant=entry["variant"], exit_code=rc)
        record = json.loads((layout.run_group_truth_dir(new[-1]) / "run.json").read_text())
        summary["runs"].append({"run_group_id": record["run_group_id"], "flag": entry["flag"], "variant": entry["variant"],
                                "status": record["status"], "incident_ids": record.get("incident_ids") or []})
        incidents = (record.get("incident_ids") or []) if record["status"] == "valid" else []
        for inc in incidents:
            if (rc := process(inc)) != 0:
                return stop("process_failed", incident_id=inc, exit_code=rc)
    return stop("max_runs")
