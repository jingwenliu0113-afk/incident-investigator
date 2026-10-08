"""Paired comparison of two methods on the same incidents (decision 023 §7).

The difference of a per-incident metric (method a minus method b) with a 95% percentile interval from a run-group
cluster bootstrap in which both methods use the same resampled run groups (decision 013 §3: 10,000 resamples, seed 0);
leave-one-fault-out (LOFO) bounds show whether an advantage rests on a single fault (descriptive only).
"""

from __future__ import annotations

import random


def paired(a: list[dict], b: list[dict], metric: str, *, seed: int = 0, resamples: int = 10_000) -> dict:
    """`a`, `b`: per-incident score rows (incident_id, run_group_id, the metric) of two methods on one set."""
    ra, rb = {r["incident_id"]: r for r in a}, {r["incident_id"]: r for r in b}
    common = sorted(set(ra) & set(rb))
    if not common:
        raise ValueError("no incident is scored for both methods")
    groups: dict[str, list[float]] = {}
    for inc in common:
        groups.setdefault(ra[inc]["run_group_id"], []).append(ra[inc][metric] - rb[inc][metric])
    names = sorted(groups)
    rng = random.Random(seed)
    boot = []
    for _ in range(resamples):
        drawn = [rng.choice(names) for _ in names]
        values = [d for g in drawn for d in groups[g]]
        boot.append(sum(values) / len(values))
    boot.sort()
    cut = int(0.025 * (resamples - 1))
    diffs = [d for g in names for d in groups[g]]
    return {"metric": metric, "n": len(common), "n_run_groups": len(names),
            "mean_diff": round(sum(diffs) / len(diffs), 6), "ci95": [round(boot[cut], 6), round(boot[-cut - 1], 6)],
            "only_in_one": sorted(set(ra) ^ set(rb)), "bootstrap": {"seed": seed, "resamples": resamples}}


def lofo(a: list[dict], b: list[dict], metric: str, *, seed: int = 0, resamples: int = 10_000) -> dict:
    """The paired difference with each fault left out in turn (rows carry a "fault" key)."""
    faults = sorted({r["fault"] for r in a} | {r["fault"] for r in b})
    out = {}
    for f in faults:
        rest_a, rest_b = [r for r in a if r["fault"] != f], [r for r in b if r["fault"] != f]
        common = {r["incident_id"] for r in rest_a} & {r["incident_id"] for r in rest_b}
        out[f] = (paired(rest_a, rest_b, metric, seed=seed, resamples=resamples) if common
                  else {"metric": metric, "n": 0, "mean_diff": None, "ci95": None})  # nothing left without this fault
    return out
