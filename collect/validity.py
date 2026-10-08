"""Stability gate before the normal period and per-period observations for run validity (decision 009 §3–4).

Works on the same samples as the soak test (env.soak.Sampler: state / locust) and the project's Docker
oom / die events (env.soak.EventWatch). Times are the host UTC strings the samplers write.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from env.soak import count_5xx

GATE_MINUTES = 5


def _t(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _kills(events: list[dict], start: datetime | None = None, end: datetime | None = None) -> list[str]:
    return [f"{e['ts'][11:19]} {e['service']} {e['action']}" + (f" exit={e['exit_code']}" if e["exit_code"] else "")
            for e in events
            if (e["action"] == "oom" or e["exit_code"] == 137)
            and (start is None or _t(e["ts"]) >= start) and (end is None or _t(e["ts"]) <= end)]


def _health_problems(states: list[dict]) -> list[str]:
    return sorted({f"{s['ts'][11:19]} {svc} {c['health']} streak={c['streak']}" for s in states
                   for svc, c in s["containers"].items()
                   if c["health"] is not None and (c["health"] != "healthy" or c["streak"])})


def _last_before(samples: list[dict], t: datetime) -> dict | None:
    before = [s for s in samples if _t(s["ts"]) <= t]
    return before[-1] if before else None


def gate(samples: list[dict], events: list[dict], *, now: str, minutes: int = GATE_MINUTES) -> dict:
    """G1–G3 over the last `minutes` before `now`. G1 failing is final (restarts / OOM since up never undo)."""
    t1 = _t(now)
    t0 = t1 - timedelta(minutes=minutes)
    states = [s for s in samples if s["kind"] == "state" and _t(s["ts"]) <= t1]
    locs = [s for s in samples if s["kind"] == "locust" and _t(s["ts"]) <= t1]
    covered = bool(states) and _t(states[0]["ts"]) <= t0

    restarted = {svc: c["restarts"] for svc, c in (states[-1]["containers"].items() if states else []) if c["restarts"]}
    kills = _kills(events)
    g1 = {"pass": bool(states) and not restarted and not kills,
          "detail": f"restarts since up {restarted or 'none'}; oom / SIGKILL {kills or 'none'}"}
    if not g1["pass"] and (restarted or kills):
        g1["final"] = True

    window_states = [s for s in states if _t(s["ts"]) >= t0]
    bad = _health_problems(window_states)
    g2 = {"pass": covered and bool(window_states) and not bad, "detail": f"{len(window_states)} samples; problems {bad or 'none'}"}

    first, last = _last_before(locs, t0), (locs[-1] if locs else None)
    if first is not None and last is not None:
        n5xx = count_5xx(last["errors"]) - count_5xx(first["errors"])
        g3 = {"pass": n5xx == 0, "value": n5xx, "detail": f"{n5xx} HTTP 5xx in the last {minutes} minutes"}
    else:
        g3 = {"pass": False, "value": None, "detail": f"no Locust samples spanning the last {minutes} minutes"}

    return {"pass": covered and g1["pass"] and g2["pass"] and g3["pass"], "covered": covered,
            "window": {"start": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": now}, "G1": g1, "G2": g2, "G3": g3}


def period_observations(samples: list[dict], events: list[dict], *, start: str, end: str) -> dict:
    """What happened between `start` and `end`: new restarts, OOM / SIGKILL, health problems, non-ambient HTTP 5xx."""
    t0, t1 = _t(start), _t(end)
    states = [s for s in samples if s["kind"] == "state"]
    locs = [s for s in samples if s["kind"] == "locust"]
    base = _last_before(states, t0)
    inside = [s for s in states if t0 <= _t(s["ts"]) <= t1]
    base_restarts = {svc: c["restarts"] for svc, c in (base["containers"].items() if base else [])}
    peak: dict[str, int] = {}
    for s in inside:
        for svc, c in s["containers"].items():
            peak[svc] = max(peak.get(svc, 0), c["restarts"])
    new_restarts = {svc: n - base_restarts.get(svc, 0) for svc, n in peak.items() if n > base_restarts.get(svc, 0)}

    first, last = _last_before(locs, t0), _last_before(locs, t1)
    http_5xx = (count_5xx(last["errors"]) - count_5xx(first["errors"])) if first and last else None

    obs = {"start": start, "end": end, "state_samples": len(inside), "new_restarts": new_restarts,
           "kills": _kills(events, t0, t1), "health": _health_problems(inside), "http_5xx": http_5xx}
    obs["clean"] = bool(inside) and http_5xx == 0 and not (new_restarts or obs["kills"] or obs["health"])
    return obs


def container_metric_gaps(container_minutes: dict[str, list[str]], *, services: list[str], start: str,
                          end: str) -> dict[str, list[str]]:
    """decision 012: the full minutes of [start, end] in which docker_stats has no data for a service's container."""
    t = _t(start).replace(second=0, microsecond=0)
    if t < _t(start):
        t += timedelta(minutes=1)
    full = []
    while t + timedelta(minutes=1) <= _t(end):
        full.append(t.strftime("%Y-%m-%dT%H:%M"))
        t += timedelta(minutes=1)
    gaps = {}
    for svc in services:
        have = set(container_minutes.get(svc, ()))
        if missing := [m[11:] for m in full if m not in have]:
            gaps[svc] = missing
    return gaps
