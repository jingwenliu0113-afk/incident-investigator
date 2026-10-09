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


def condition_2(rows: list[dict], k_of: dict[str, int]) -> dict:
    """A reproducible stable failure (023 §7): a fault whose origin_top1 is wrong on >= ceil(K/2) of its incidents, with
    more than half of those failures in one decision-022 category. `k_of`: fault -> K (eval.runner.gate_methods: the
    design's slots on the held-out set, the scored count on the Pilot)."""
    by = {}
    for fault in sorted(k_of):
        mine = [r for r in rows if r["fault"] == fault]
        wrong = [r for r in mine if r["origin_top1"] != 1]  # an abstention scores 0 (013 §2) and counts
        if any(r["failure"] is None for r in wrong):
            raise ValueError(f"{fault}: a wrong origin without a failure category (decision 022): score the method again")
        cats = [r["failure"] for r in wrong]
        counts = {c: cats.count(c) for c in sorted(set(cats))}
        majority = next((c for c, n in counts.items() if 2 * n > len(cats)), None)
        k = k_of[fault]
        threshold = math.ceil(k / 2)
        by[fault] = {"k": k, "threshold": threshold, "n_scored": len(mine), "origin_wrong": len(wrong),
                     "categories": counts, "majority_category": majority,
                     "met": len(wrong) >= threshold and len(wrong) > 0 and majority is not None}
    met = [f for f, v in by.items() if v["met"]]
    return {"by_fault": by, "faults_met": met, "met": bool(met)}


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
