"""Layered scoring (SPEC Core §8, decision 013): each layer on its own, never a single root-cause string.

score_incident(): one prediction against one label. aggregate(): means with a 95% cluster-bootstrap interval,
resampling whole run groups (SPEC §10: incidents of one run group are never separated).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from collect.labels import FAULT_TYPES

SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "prediction.schema.json"
ORIGIN_TOP_K = 3


def check_prediction(prediction: dict, services: list[str] | None = None) -> list[str]:
    """Schema problems plus services outside the snapshot vocabulary (the 18 SUT services, decision 011)."""
    from jsonschema import Draft202012Validator

    from collect.policy import load_policy

    validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
    problems = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:160]}" for e in validator.iter_errors(prediction)]
    if problems:
        return problems
    known = set(services if services is not None else load_policy().sut_services)
    if unknown := sorted({*prediction["origin_candidates"], *prediction["affected_services"]} - known):
        problems.append(f"unknown service(s) {unknown}: predictions use the snapshot's services")
    return problems


def _sets(predicted: list[str], gold: list[str]) -> dict:
    p, g = set(predicted), set(gold)
    hit = len(p & g)
    precision = hit / len(p) if p else 0.0
    recall = hit / len(g) if g else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    jaccard = hit / len(p | g) if p | g else 1.0
    return {"precision": precision, "recall": recall, "f1": f1, "jaccard": jaccard}


def score_incident(prediction: dict, label: dict) -> dict:
    gold_type = label["injected_fault"]["fault_type"]
    ptype = prediction["fault"]["fault_type"]
    pfamily = prediction["fault"]["fault_family"] or (FAULT_TYPES.get(ptype) if ptype else None)
    candidates = prediction["origin_candidates"]
    rank = candidates.index(label["origin_service"]) + 1 if label["origin_service"] in candidates else None
    affected = _sets(prediction["affected_services"], label["affected_services"])
    symptom = _sets(prediction["user_symptom"]["kinds"], label["user_symptom"]["kinds"])
    return {
        "incident_id": label["incident_id"],
        "fault_type": int(ptype == gold_type),
        "fault_family": int(pfamily == label["fault_family"]),
        "origin_top1": int(rank == 1),
        f"origin_top{ORIGIN_TOP_K}": int(rank is not None and rank <= ORIGIN_TOP_K),
        "origin_rr": 1.0 / rank if rank else 0.0,
        **{f"affected_{k}": v for k, v in affected.items()},
        "symptom_exact": int(set(prediction["user_symptom"]["kinds"]) == set(label["user_symptom"]["kinds"])),
        "symptom_jaccard": symptom["jaccard"],
    }


def aggregate(scores: list[dict], *, seed: int = 0, resamples: int = 10_000) -> dict:
    """Mean of each metric and its 95% percentile interval from a bootstrap over run groups."""
    metrics = [k for k in scores[0] if k not in ("incident_id", "run_group_id")]
    groups: dict[str, list[dict]] = {}
    for s in scores:
        groups.setdefault(s["run_group_id"], []).append(s)
    names = sorted(groups)
    rng = random.Random(seed)
    draws = [[rng.choice(names) for _ in names] for _ in range(resamples)]
    out = {}
    for m in metrics:
        mean = sum(s[m] for s in scores) / len(scores)
        boot = sorted(sum(s[m] for g in d for s in groups[g]) / sum(len(groups[g]) for g in d) for d in draws)
        lo, hi = boot[int(0.025 * (resamples - 1))], boot[-(int(0.025 * (resamples - 1))) - 1]
        out[m] = {"mean": round(mean, 6), "ci95": [round(lo, 6), round(hi, 6)]}
    return {"n_incidents": len(scores), "n_run_groups": len(names), "bootstrap": {"seed": seed, "resamples": resamples},
            "metrics": out}
