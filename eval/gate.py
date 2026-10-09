"""The SPEC Gate analysis (decision 023 §7) over score rows (scores.json "incidents") and written comparisons.

Condition 1 is read from the paired comparison `eval compare` wrote (eval.compare.paired; nothing is resampled here),
conditions 2 and 3 from the decision-022 failure categories; the per-fault table and the coverage share are descriptive.
Pure functions: nothing here runs a method or touches a file (eval.runner.gate_methods does the I/O).
"""

from __future__ import annotations

import math

GATE_METRIC = "origin_top1"  # decision 023 §7: the only primary test
GATE_BOOTSTRAP = {"seed": 0, "resamples": 10_000}  # decision 013 §3
REASONING = ("not_seen", "seen_misread")  # decision 022 §3: failures of the reasoning path


def condition_1(compares: dict[str, dict]) -> dict:
    """Agent - baseline origin_top1, paired 95% lower bound > 0 against every statistical baseline (023 §7).
    `compares`: baseline -> its compare document (a = the Agent)."""
    by = {}
    for baseline, doc in compares.items():
        p = doc["paired"][GATE_METRIC]
        by[baseline] = {"n": p["n"], "n_run_groups": p["n_run_groups"], "mean_diff": p["mean_diff"], "ci95": p["ci95"],
                        "lower_bound": p["ci95"][0], "met": p["ci95"][0] > 0, "only_in_one": p["only_in_one"]}
    return {"metric": GATE_METRIC, "by_baseline": by, "met": bool(by) and all(v["met"] for v in by.values())}


PILOT_MIN_K = 2  # a fault scored once on the Pilot cannot show a reproducible failure (023 "Gate 計算" note 4)


def condition_2(rows: list[dict], k_of: dict[str, int], *, min_k: int = 1) -> dict:
    """A reproducible stable failure (023 §7): a fault whose origin_top1 is wrong on >= ceil(K/2) of its incidents, with
    more than half of those failures in one decision-022 category. `k_of`: fault -> K (eval.runner.gate_methods: the
    design's slots on the held-out set, the scored count on the Pilot). A fault with K < `min_k` is not evaluated and
    never met (the Pilot passes PILOT_MIN_K; the held-out set keeps 023 §7 as written)."""
    by = {}
    for fault in sorted(k_of):
        mine = [r for r in rows if r["fault"] == fault]
        wrong = [r for r in mine if r["origin_top1"] != 1]  # an abstention scores 0 (013 §2) and counts
        if any(r["failure"] is None for r in wrong):
            raise ValueError(f"{fault}: a wrong origin without a failure category (decision 022): score the method again")
        cats = [r["failure"] for r in wrong]  # "these failures": the origin-wrong ones only
        counts = {c: cats.count(c) for c in sorted(set(cats))}
        majority = next((c for c, n in counts.items() if 2 * n > len(cats)), None)
        k = k_of[fault]
        threshold = math.ceil(k / 2)
        evaluable = k >= min_k
        by[fault] = {"k": k, "threshold": threshold, "n_scored": len(mine), "origin_wrong": len(wrong),
                     "categories": counts, "majority_category": majority, "evaluable": evaluable,
                     "met": evaluable and len(wrong) >= threshold and len(wrong) > 0 and majority is not None}
    met = [f for f, v in by.items() if v["met"]]
    return {"by_fault": by, "faults_met": met, "not_evaluable": [f for f, v in by.items() if not v["evaluable"]],
            "met": bool(met)}


def condition_3(rows: list[dict]) -> dict:
    """Among the failures (022 §1: origin or fault type wrong), the share of not_seen + seen_misread > 0.5 (023 §7).
    Without any failure the share is undefined and the condition is not met."""
    failed = [r["failure"] for r in rows if r["failure"] is not None]
    by = {c: failed.count(c) for c in REASONING}
    share = sum(by.values()) / len(failed) if failed else None
    return {"n_failures": len(failed), "by_category": by, "share": share, "met": share is not None and share > 0.5}


def coverage(rows: list[dict]) -> dict:
    """SPEC Gate "收尾或改題": the share of failures in category coverage, reported only (no threshold). Failures
    classified without a reviewed label could not be judged coverage (decision 022 §2) and are counted."""
    failed = [r for r in rows if r["failure"] is not None]
    n = sum(r["failure"] == "coverage" for r in failed)
    return {"n_scored": len(rows), "n_failures": len(failed), "coverage": n, "share": n / len(failed) if failed else None,
            "classified_without_review": sum(not r["label_reviewed"] for r in failed)}


def per_fault(rows: list[dict], expected: dict[str, int | None], missing: list[dict], metrics: tuple) -> dict:
    """Descriptive only (023 §7): each fault's mean of the main metrics, their equal-weight mean over the faults with a
    scored incident, the mean over incidents for contrast, and the missing cells. K is the design's (`expected`), never
    below the scored count."""
    def mean(values):
        return sum(values) / len(values) if values else None

    faults = {}
    for fault in sorted(set(expected) | {r["fault"] for r in rows}):
        mine = [r for r in rows if r["fault"] == fault]
        faults[fault] = {"n": len(mine), "k": max(expected.get(fault) or 0, len(mine)),
                         "means": {m: mean([r[m] for r in mine]) for m in metrics}}
    present = [v for v in faults.values() if v["n"]]
    return {"faults": faults,
            "equal_weight": {"n_faults": len(present), "means": {m: mean([v["means"][m] for v in present]) for m in metrics}},
            "incident_mean": {m: mean([r[m] for r in rows]) for m in metrics},
            "missing": missing}


def fault_directions(a_rows: list[dict], b_rows: list[dict], k_a: dict[str, int], k_b: dict[str, int]) -> dict:
    """023 §7 robustness report, descriptive only: per fault, each method's origin_top1 right k of K (over its own scored
    incidents; K from its per-fault table) and the direction (+, 0, -) of a - b over the fault's incidents scored for
    both; no direction without one."""
    out = {}
    for fault in sorted(set(k_a) | set(k_b) | {r["fault"] for r in a_rows + b_rows}):
        a = {r["incident_id"]: r[GATE_METRIC] for r in a_rows if r["fault"] == fault}
        b = {r["incident_id"]: r[GATE_METRIC] for r in b_rows if r["fault"] == fault}
        common = sorted(set(a) & set(b))
        diff = sum(a[i] - b[i] for i in common)
        out[fault] = {"a": {"right": sum(v == 1 for v in a.values()), "scored": len(a), "k": k_a.get(fault, len(a))},
                      "b": {"right": sum(v == 1 for v in b.values()), "scored": len(b), "k": k_b.get(fault, len(b))},
                      "n_paired": len(common), "mean_diff": diff / len(common) if common else None,
                      "direction": None if not common else "+" if diff > 0 else "-" if diff < 0 else "0"}
    return out


STATEMENTS = {
    "heldout": "Held-out set: this is the Gate decision of decision 023 §7 (SPEC Gate, entering Advanced), from first-run "
               "results only: each method ran once per listed incident under the freeze record (decision 023 §5, §6).",
    "pilot": "Pilot set: DIAGNOSTIC ONLY, NOT a Gate decision. The Gate is decided only on the held-out set (SPEC Gate, "
             "decision 023 §7); the Pilot never enters the test (SPEC §5) and its numbers check the pipeline (decision 013).",
}


def verdict(c1: dict, c2: dict, c3: dict, split: str) -> dict:
    """All three conditions; a decision ("pass" / "not_passed") on the held-out set only, None on the Pilot."""
    all_met = bool(c1["met"] and c2["met"] and c3["met"])
    held = split == "heldout"
    return {"kind": "gate_decision" if held else "diagnostic", "statement": STATEMENTS[split], "all_met": all_met,
            "decision": ("pass" if all_met else "not_passed") if held else None}
