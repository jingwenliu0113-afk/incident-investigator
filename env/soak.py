"""Baseline soak test for the locked stack (decision 004).

`python -m env soak` brings the stack up, waits for it to be healthy, lets it warm up, samples a
fixed window, then tears it down and judges the samples against criteria R1–R6, which were fixed
in docs/decisions/004 before the first run. Must run under ./tools/with-mac-lock.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from env.lock import pinned_images
from env.runtime import PROJECT_LABEL, SERVICE_LABEL

HEAVY_LOCK_DIR = Path("/tmp/ai-portfolio-mac-heavy.lock")
WATCHED_SERVICES = ("product-catalog", "checkout")  # R6: every service whose memory limit env/compose.overrides.yaml changes
NEAR_LIMIT = 0.80  # R6: p95 of memory.current must stay below this share of the limit

_5XX = re.compile(r"HTTPError\('5\d\d\b")
_SIGNALS = {"Traces": ("traces", "spans"), "Metrics": ("metrics", "data points"), "Logs": ("logs", "log records")}


class LockNotHeld(RuntimeError):
    pass


# ---------------------------------------------------------------- pure helpers

def count_5xx(errors: Mapping[str, int]) -> int:
    return sum(n for key, n in errors.items() if _5XX.search(key))


def is_ambient(error_key: str) -> bool:
    """decision 005: ask_agent -> agent:8010 that does not exist in the locked stack."""
    return error_key.startswith("/prompt") and any(s in error_key for s in ("gaierror", "NameResolution", "ConnectionError"))


def parse_memcg_dump(text: str, id_to_service: Mapping[str, str]) -> dict[str, dict]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0] not in id_to_service:
            continue
        kv = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        out[id_to_service[parts[0]]] = {
            "current": int(kv["current"]),
            "max": None if kv["max"] == "max" else int(kv["max"]),
            "oom_kill": int(kv.get("oom_kill") or 0),
            "max_events": int(kv.get("max_events") or 0),
        }
    return out


def debug_exporter_minutes(log_text: str) -> dict[str, set[str]]:
    """Minutes (HH:MM, UTC) in which the collector's debug exporter saw a non-empty batch, per signal."""
    seen: dict[str, set[str]] = {sig: set() for sig, _ in _SIGNALS.values()}
    for line in log_text.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or parts[2] not in _SIGNALS:
            continue
        try:
            fields = json.loads(parts[-1])
        except json.JSONDecodeError:
            continue
        signal, count_key = _SIGNALS[parts[2]]
        if fields.get("otelcol.component.id") == "debug" and fields.get(count_key, 0) > 0:
            seen[signal].add(parts[0][11:16])
    return seen


def parse_docker_events(text: str, *, project: str) -> list[dict]:
    """`docker events --format '{{json .}}'` lines -> the project's compose-service events."""
    out = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        attrs = (event.get("Actor") or {}).get("Attributes") or {}
        if attrs.get(PROJECT_LABEL) != project or SERVICE_LABEL not in attrs:
            continue
        seconds = event["timeNano"] // 10**9 if "timeNano" in event else event["time"]
        code = attrs.get("exitCode")
        out.append({"ts": datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "service": attrs[SERVICE_LABEL], "action": event.get("Action"),
                    "exit_code": None if code is None else int(code)})
    return out


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _p95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def evaluate(
    samples: list[dict],
    *,
    window_start: str,
    window_end: str,
    limits: Mapping[str, int],
    flow_minutes: Mapping[str, set[str]],
    events: list[dict] | None,
) -> dict:
    """Judge samples against R1–R6 (docs/decisions/004).

    `limits`: memory limit in bytes of every service whose limit the project overlay changed (R6).
    `events` are the project's Docker oom/die events since before `up`, or None when the stream broke.
    """
    w0, w1 = _ts(window_start), _ts(window_end)

    def in_window(s: dict) -> bool:
        return w0 <= _ts(s["ts"]) <= w1

    by_kind = {k: [s for s in samples if s["kind"] == k] for k in ("state", "memcg", "locust")}
    states, mems, locs = by_kind["state"], by_kind["memcg"], by_kind["locust"]
    crit: dict[str, dict] = {}

    restarted = {svc: c["restarts"] for s in states for svc, c in s["containers"].items() if c["restarts"]}
    crit["R1"] = {"pass": bool(states) and not restarted,
                  "detail": f"restarts since up: {restarted or 'none'} ({len(states)} state samples)"}

    # A restart recreates the container's cgroup and resets memory.events, so memcg counters alone
    # miss an OOM kill (soak #1). Docker's oom events and SIGKILL deaths (exit 137) before teardown cover that.
    oom = {svc: c["oom_kill"] for s in mems for svc, c in s["cgroups"].items() if c["oom_kill"]}
    killed = sorted({f"{e['ts'][11:19]} {e['service']} {e['action']}" + (f" exit={e['exit_code']}" if e["exit_code"] else "")
                     for e in events or [] if e["action"] == "oom" or e["exit_code"] == 137})
    crit["R2"] = {"pass": bool(mems) and events is not None and not oom and not killed, "detail": (
        f"memcg oom_kill since up: {oom or 'none'} ({len(mems)} memcg samples); "
        f"docker oom / SIGKILL events: {killed or 'none'}" + ("" if events is not None else " (event stream missing)"))}

    win_locs = [s for s in locs if in_window(s)]
    ambient = warm_5xx = None
    if len(win_locs) >= 2:
        first, last = win_locs[0], win_locs[-1]
        n5xx = count_5xx(last["errors"]) - count_5xx(first["errors"])
        warm_5xx = count_5xx(first["errors"])
        amb = lambda e: sum(n for k, n in e.items() if is_ambient(k))  # noqa: E731
        ambient = amb(last["errors"]) - amb(first["errors"])
        crit["R3"] = {"pass": n5xx == 0, "value": n5xx,
                      "detail": f"{n5xx} HTTP 5xx in window ({last['requests'] - first['requests']} requests)"}
    else:
        crit["R3"] = {"pass": False, "value": None, "detail": "fewer than 2 Locust samples in the window"}

    win_states = [s for s in states if in_window(s)]
    bad = sorted({f"{s['ts'][11:19]} {svc} {c['health']} streak={c['streak']}" for s in win_states
                  for svc, c in s["containers"].items()
                  if c["health"] is not None and (c["health"] != "healthy" or c["streak"])})
    crit["R4"] = {"pass": bool(win_states) and not bad,
                  "detail": f"{len(win_states)} samples; problems: {bad[:10] or 'none'}"}

    minutes, t = [], w0.replace(second=0, microsecond=0)
    while t < w1:
        minutes.append(t.strftime("%H:%M"))
        t += timedelta(minutes=1)
    gaps = {sig: [m for m in minutes if m not in flow_minutes.get(sig, set())] for sig in ("traces", "metrics", "logs")}
    gaps = {k: v for k, v in gaps.items() if v}
    crit["R5"] = {"pass": bool(minutes) and not gaps, "detail": f"{len(minutes)} minutes; gaps: {gaps or 'none'}"}

    r6_ok, r6_detail = bool(limits), []
    for service, limit_bytes in sorted(limits.items()):
        win_mem = [s["cgroups"][service] for s in mems if in_window(s) and service in s["cgroups"]]
        if not win_mem:
            r6_ok = False
            r6_detail.append(f"{service}: no memcg samples in the window")
            continue
        p95 = _p95([m["current"] for m in win_mem])
        hits = win_mem[-1]["max_events"] - win_mem[0]["max_events"]
        seen = {m["max"] for m in win_mem}
        ok = p95 < NEAR_LIMIT * limit_bytes and hits == 0 and seen == {limit_bytes}
        r6_ok &= ok
        r6_detail.append(
            f"{service} {'ok' if ok else 'FAIL'}: p95 memory.current {p95 / 2**20:.1f} MiB = {p95 / limit_bytes:.0%} of "
            f"{limit_bytes / 2**20:.0f} MiB (max {max(m['current'] for m in win_mem) / 2**20:.1f} MiB); "
            f"memory.max hits in window {hits}; cgroup limit seen {sorted(map(str, seen))}")
    crit["R6"] = {"pass": r6_ok, "detail": "; ".join(r6_detail) or "no watched service"}

    return {
        "pass": all(c["pass"] for c in crit.values()),
        "window": {"start": window_start, "end": window_end},
        "criteria": crit,
        "ambient": {"ask_agent": ambient},
        "warmup": {"http_5xx": warm_5xx},
    }


def require_heavy_lock(project_dir: Path, *, lock_dir: Path = HEAVY_LOCK_DIR) -> dict:
    owner_file = lock_dir / "owner.txt"
    if not owner_file.exists():
        raise LockNotHeld(f"Mac heavy lock not held; run via ./tools/with-mac-lock (MACHINE_POLICY.md)")
    owner = dict(line.split("=", 1) for line in owner_file.read_text().splitlines() if "=" in line)
    if Path(owner.get("cwd", "")).resolve() != Path(project_dir).resolve():
        raise LockNotHeld(f"Mac heavy lock is held by another workload (cwd={owner.get('cwd')}); do not preempt it")
    try:
        os.kill(int(owner.get("pid", "-1")), 0)
    except (ValueError, ProcessLookupError, PermissionError):
        raise LockNotHeld(f"lock owner pid {owner.get('pid')} is not alive (stale lock?); report it, do not delete it")
    return owner


# ---------------------------------------------------------------- sampling (needs Docker)

Run = Callable[..., str]


def _run(cmd: list[str], env: dict[str, str] | None = None) -> str:
    return subprocess.run(cmd, env=env, check=True, capture_output=True, text=True).stdout


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventWatch:
    """`docker events` for the project's oom / die events, streamed to `path` until stop()."""

    def __init__(self, path: Path, *, project: str, env: dict[str, str], popen=subprocess.Popen):
        self.path, self.project = path, project
        self._file = path.open("w")
        self._proc = popen(["docker", "events", "--format", "{{json .}}", "--filter", "type=container",
                            "--filter", f"label={PROJECT_LABEL}={project}",
                            "--filter", "event=oom", "--filter", "event=die"],
                           stdout=self._file, stderr=subprocess.STDOUT, env=env)
        self._stopped = False
        self._events: list[dict] | None = None

    def stop(self) -> list[dict] | None:
        """The events seen, or None if the stream ended on its own (a hole in the record)."""
        if not self._stopped:
            self._stopped = True
            broken = self._proc.poll() is not None
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._file.close()
            if not broken:
                self._events = parse_docker_events(self.path.read_text(), project=self.project)
        return self._events


class Sampler:
    def __init__(self, lock: dict, project_ids: Mapping[str, str], env: dict[str, str], run: Run = _run):
        self.lock, self.ids, self.env, self.run = lock, dict(project_ids), env, run
        self.helper_image = pinned_images(lock)["prometheus"]  # already pulled; read-only cgroup access

    def state(self) -> dict:
        inspected = json.loads(self.run(["docker", "inspect", *self.ids], self.env))
        containers = {}
        for c in inspected:
            health = c["State"].get("Health") or {}
            containers[c["Config"]["Labels"][SERVICE_LABEL]] = {
                "restarts": c.get("RestartCount", 0), "status": c["State"]["Status"],
                "health": health.get("Status"), "streak": health.get("FailingStreak") if health else None}
        return {"kind": "state", "ts": _now(), "containers": containers}

    def memcg(self) -> dict:
        script = ("for id in " + " ".join(self.ids) + "; do d=/sys/fs/cgroup/docker/$id; "
                  "echo \"$id current=$(cat $d/memory.current) max=$(cat $d/memory.max) "
                  "oom_kill=$(awk '/^oom_kill /{print $2}' $d/memory.events) "
                  "max_events=$(awk '/^max /{print $2}' $d/memory.events)\"; done")
        out = self.run(["docker", "run", "--rm", "--network", "none", "--cgroupns=host",
                        "--entrypoint", "/bin/sh", self.helper_image, "-c", script], self.env)
        return {"kind": "memcg", "ts": _now(), "cgroups": parse_memcg_dump(out, self.ids)}

    def locust(self) -> dict:
        lg = next(i for i, svc in self.ids.items() if svc == "load-generator")
        code = ("import json, urllib.request\n"
                "s = json.load(urllib.request.urlopen('http://localhost:8089/stats/requests'))\n"
                "a = next(r for r in s['stats'] if r['name'] == 'Aggregated')\n"
                "print(json.dumps({'requests': a['num_requests'], 'failures': a['num_failures'],"
                " 'errors': {e['name'] + ' | ' + e['error'][:90]: e['occurrences'] for e in s['errors']}}))")
        data = json.loads(self.run(["docker", "exec", lg, "python", "-c", code], self.env))
        return {"kind": "locust", "ts": _now(), **data}


def project_container_ids(lock: dict, env: dict[str, str], run: Run = _run) -> dict[str, str]:
    ids = run(["docker", "ps", "-a", "-q", "--no-trunc", "--filter",
               f"label={PROJECT_LABEL}={lock['startup']['project_name']}"], env).split()
    if not ids:
        return {}
    return {c["Id"]: c["Config"]["Labels"][SERVICE_LABEL] for c in json.loads(run(["docker", "inspect", *ids], env))}


def opensearch_rejections(collector_log: str) -> dict:
    requests = items = 0
    for line in collector_log.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4 and parts[1] == "error" and "Dropping data" in parts[3]:
            try:
                fields = json.loads(parts[-1])
            except json.JSONDecodeError:
                continue
            if fields.get("otelcol.component.id") == "opensearch":
                requests += 1
                items += int(fields.get("dropped_items", 0))
    return {"failed_requests": requests, "dropped_items": items,
            "mapping_rejections": collector_log.count("mapper_parsing_exception")}


def write_report(out_dir: Path, report: dict) -> None:
    """Always writable, also for an aborted run (missing parts are shown as such)."""
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    window = report.get("window") or {}
    lines = [f"# soak test {'PASSED' if report.get('pass') else 'FAILED'}", "",
             f"window {window.get('start', '?')} – {window.get('end', '?')}"]
    if report.get("aborted"):
        lines += ["", f"**aborted**: {report['aborted']}"]
    lines += [""] + [f"- {k}: {'pass' if v['pass'] else 'FAIL'} — {v['detail']}"
                     for k, v in (report.get("criteria") or {}).items()]
    lines += ["", f"- initial verify-running problems: {report.get('initial_verify_running')}",
              f"- sampling errors: {len(report.get('sampling_errors') or [])}",
              f"- known ambient (decision 005): ask_agent failures in window = "
              f"{(report.get('ambient') or {}).get('ask_agent')}; OpenSearch: {report.get('opensearch')}",
              f"- warm-up HTTP 5xx (recorded, not judged) = {(report.get('warmup') or {}).get('http_5xx')}",
              f"- teardown: {report.get('teardown')}"]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
