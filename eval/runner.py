"""Run one method over one set of incidents and score it (SPEC Core §7–§10; decisions 013, 014).

The incidents of a set come from the ground-truth side (injection.json `split`, fixed at collection); a method only
ever receives an opened frozen snapshot and the incident id. Labels are read only when scoring, after all predictions
of the set exist.
"""

from __future__ import annotations

import json
from pathlib import Path

from collect.layout import DataLayout
from collect.snapshot import open_snapshot
from eval.evidence import existence
from eval.score import aggregate, check_prediction, score_incident


def _stat(snapshot, incident_id):
    from baselines.statistical import predict

    return predict(snapshot, incident_id)


METHODS = {"stat-anomaly": _stat}
MAIN_METRICS = ("fault_type", "origin_top1", "affected_f1", "symptom_exact")  # decision 013: one per layer


def incidents_in(layout: DataLayout, split: str) -> list[tuple[str, str]]:
    """(incident id, run group id) of every incident of `split` that has a published snapshot."""
    out = []
    for path in sorted((layout.ground_truth_root / "run_groups").glob("RG-*/injection.json")):
        inj = json.loads(path.read_text())
        if inj.get("split") == split:
            out += [(inc, inj["run_group_id"]) for inc in inj["incident_ids"]
                    if (layout.incident_dir(inc) / "normalized" / "snapshot.json").exists()]
    return sorted(out)


def run_method(layout: DataLayout, method: str, split: str, out_root: Path) -> list[Path]:
    """Predictions of `method` for every incident of `split`, written to out_root/<split>/<method>/<INC>.json."""
    out_dir = Path(out_root) / split / method
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for inc, _ in incidents_in(layout, split):
        snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
        pred = METHODS[method](snapshot, inc)
        if problems := check_prediction(pred):
            raise ValueError(f"{method} wrote an invalid prediction for {inc}: {problems[:5]}")
        path = out_dir / f"{inc}.json"
        path.write_text(json.dumps(pred, indent=2) + "\n")
        written.append(path)
    return written


def score_method(layout: DataLayout, method: str, split: str, out_root: Path) -> dict:
    out_dir = Path(out_root) / split / method
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for inc, rg in incidents_in(layout, split):
        pred = json.loads((out_dir / f"{inc}.json").read_text())
        label = json.loads(layout.label_path(inc).read_text())
        snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
        rows.append(score_incident(pred, label) | {"run_group_id": rg,
                                                    "evidence_existence": existence(pred["evidence"], snapshot)["rate"]})
    scored = [{k: v for k, v in r.items() if k != "evidence_existence"} for r in rows]
    agg = aggregate(scored) if scored else {"n_incidents": 0, "n_run_groups": 0, "metrics": {}}
    result = {"method": method, "split": split, "incidents": rows, "aggregate": agg}
    (out_dir / "scores.json").write_text(json.dumps(result, indent=2) + "\n")
    (out_dir / "table.md").write_text(_table(result))
    return result


def _table(result: dict) -> str:
    agg = result["aggregate"]
    lines = [f"# {result['method']} on the {result['split']} set",
             "",
             f"n = {agg['n_incidents']} incidents in {agg['n_run_groups']} run groups; 95% interval: run-group cluster bootstrap "
             f"({agg.get('bootstrap', {}).get('resamples', 0)} resamples, seed {agg.get('bootstrap', {}).get('seed', '-')}).",
             "",
             "| metric | mean | 95% interval |",
             "|---|---:|---|"]
    for name, m in agg["metrics"].items():
        mark = " (main)" if name in MAIN_METRICS else ""
        lines.append(f"| {name}{mark} | {m['mean']:.3f} | [{m['ci95'][0]:.3f}, {m['ci95'][1]:.3f}] |")
    rates = [r["evidence_existence"] for r in result["incidents"] if r["evidence_existence"] is not None]
    lines += ["", f"evidence existence: {sum(rates) / len(rates):.3f} over {len(rates)} incidents that cite evidence"
              if rates else "evidence existence: no incident cites evidence"]
    return "\n".join(lines) + "\n"
