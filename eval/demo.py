"""The 2-minute demo (decision 027): the statistical baseline on the SYNTHETIC sample, scored layer by layer.

It runs only on a sample whose sample.json says synthetic: true and lists every file with its exact sha256, then follows
the scoring path's order: open the frozen snapshot, predict, and only then read the label for the leakage audit (decision
015, in memory; lexicon hits refuse the sample as the runner excludes such an incident), the layered scores (decision 013),
evidence existence and weak relevance (decision 017) and the failure category (decision 022). Nothing is written. The
numbers come from one generated incident with an obvious fault: they are not results.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from collect.layout import DataLayout
from collect.sample import OS_FILES, PREDICTION, SAMPLE_FILE

BANNER = "SYNTHETIC SAMPLE: generated data, not a collected incident. These numbers are not results."
FOOTER = ("SYNTHETIC: one generated incident with an obvious fault, so the scores say nothing about any method; "
          "results come only from the Pilot and held-out sets (README).")
LAYERS = {"fault_type": "injected fault", "fault_family": "injected fault", "origin_top1": "origin service",
          "origin_top3": "origin service", "origin_rr": "origin service", "affected_precision": "affected services",
          "affected_recall": "affected services", "affected_f1": "affected services", "affected_jaccard": "affected services",
          "symptom_exact": "user symptom", "symptom_jaccard": "user symptom"}
WEAK = {"temporal": "weak: temporal", "service": "weak: affected service", "origin": "weak: origin service",
        "weak": "weak: temporal and service"}


def check_sample(root: Path) -> dict:
    """The sample's manifest, once it says synthetic and every file is exactly what it lists (ValueError otherwise)."""
    from env.lock import sha256_path

    root = Path(root)
    try:
        manifest = json.loads((root / SAMPLE_FILE).read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"{root / SAMPLE_FILE} is missing or not JSON: the demo runs on the synthetic sample only") from e
    if manifest.get("synthetic") is not True:
        raise ValueError(f"{root / SAMPLE_FILE} does not say synthetic: true: the demo runs on the synthetic sample only")
    listed = {e["path"]: e["sha256"] for e in manifest.get("files", [])}
    for path, digest in sorted(listed.items()):
        if not (root / path).is_file() or sha256_path(root / path) != digest:
            raise ValueError(f"{path}: missing or its sha256 differs from {SAMPLE_FILE} (regenerate the sample)")
    present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name not in OS_FILES} - {SAMPLE_FILE}
    if unlisted := sorted(present - set(listed)):
        raise ValueError(f"files not listed in {SAMPLE_FILE}: {unlisted}")
    return manifest


def run_demo(root: Path) -> dict:
    from baselines.statistical import METHOD, predict
    from collect.snapshot import open_snapshot
    from eval.evidence import existence
    from eval.failures import classify
    from eval.leakage import audit
    from eval.relevance import weak_score
    from eval.score import check_prediction, score_incident

    root = Path(root)
    manifest = check_sample(root)
    inc, layout = manifest["incident_id"], DataLayout(root)
    t0 = time.monotonic()
    snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
    pred = predict(snapshot, inc)
    if problems := check_prediction(pred):
        raise ValueError(f"the baseline wrote an invalid prediction: {problems[:5]}")
    label = json.loads(layout.label_path(inc).read_text())  # read only once the prediction exists (decision 013)
    report = json.loads(layout.normalize_report_path(inc).read_text())
    offset = report["window"]["clock_offsets"][0]
    leakage = audit(snapshot, label, clock_offset_s=offset, new_attribute_keys=report.get("new_attribute_keys"))
    if leakage["lexicon_hits"]:  # the runner keeps such an incident out of every score (decision 015)
        raise ValueError(f"the sample's leakage audit has lexicon_hits={leakage['lexicon_hits']}: it is scored nowhere")
    scores = score_incident(pred, label)
    example = json.loads((root / PREDICTION).read_text())
    return {"synthetic": True, "sample": manifest, "incident_id": inc, "method": dict(METHOD),
            "window_minutes": (snapshot.window["end_ns"] - snapshot.window["start_ns"]) / 60e9,
            "records": {f["path"]: f["records"] for f in snapshot.meta["files"]},
            "prediction": pred, "label": label, "leakage": leakage, "scores": scores,
            "evidence": {"existence": existence(pred["evidence"], snapshot),
                         "weak": weak_score(pred["evidence"], snapshot, label, clock_offset_s=offset)},
            "failure": classify(pred, label, scores, None, snapshot, clock_offset_s=offset),
            "matches_example": example == {**pred, "usage": {**pred["usage"], "latency_s": None}},
            "seconds": round(time.monotonic() - t0, 2)}


def _num(x) -> str:
    return "-" if x is None else str(x) if isinstance(x, int) else f"{x:.3f}"


def demo_text(result: dict, shown_root: str) -> str:
    from eval.runner import MAIN_METRICS

    pred, label, n = result["prediction"], result["label"], result["records"]
    gen = result["sample"]["generator"]
    lines = [BANNER, "",
             f"sample:     {shown_root} ({result['incident_id']}; {gen['name']} v{gen['version']}; decision 027)",
             f"snapshot:   {result['window_minutes']:.0f}-minute window; {n['spans.jsonl']} spans, {n['logs.jsonl']} logs, "
             f"{n['metric_series.jsonl']} metric series, {n['metric_points.jsonl']} metric points (ctel/1)",
             f"method:     {result['method']['name']} v{result['method']['version']} (statistical baseline, decision 014; "
             "reference = the first 10 minutes)",
             f"prediction: fault {pred['fault']['fault_type']}; origin {' > '.join(pred['origin_candidates']) or '-'}; "
             f"affected {', '.join(pred['affected_services']) or '-'}; symptom {', '.join(pred['user_symptom']['kinds'])}; "
             f"evidence ids cited: {len(pred['evidence'])}",
             f"label:      fault {label['injected_fault']['fault_type']}; origin {label['origin_service']}; "
             f"affected {', '.join(label['affected_services'])}; symptom {', '.join(label['user_symptom']['kinds'])} "
             f"(synthetic, {label['labeling']['method']})",
             "", "| layer | metric | value (SYNTHETIC sample, not a result) |", "|---|---|---:|"]
    leak = result["leakage"]
    lines += [f"| leakage audit | difficulty (decision 015) | {leak['difficulty']} |",
              f"| leakage audit | lexicon hits | {leak['lexicon_hits']} |"]
    for metric, value in result["scores"].items():
        if metric in LAYERS:
            lines.append(f"| {LAYERS[metric]} | {metric}{' (main)' if metric in MAIN_METRICS else ''} | {_num(value)} |")
    ex = result["evidence"]["existence"]
    lines.append(f"| evidence | existence | {ex['resolved']}/{ex['cited']} |")
    for key, name in WEAK.items():
        lines.append(f"| evidence | {name} | {_num(result['evidence']['weak'][key])} |")
    lines.append(f"| failure category | decision 022 | {result['failure'] or 'none (origin and fault type right)'} |")
    lines += ["", f"matches the committed example prediction: {'yes' if result['matches_example'] else 'NO'}",
              f"took {result['seconds']} s", "", FOOTER]
    return "\n".join(lines) + "\n"
