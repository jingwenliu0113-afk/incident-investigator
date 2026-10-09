"""python -m eval — predictions, scores, leakage audit and gold evidence judgments of one set.

    python -m eval run|score --method <name> --set pilot
    python -m eval leakage --set pilot
    python -m eval gold-todo --set pilot          # blind worksheets of citations to judge (decision 017)
    python -m eval gold-add --incident INC-001 --file <worksheet> --annotator human:<name>
    python -m eval compare --method agent --against stat-anomaly --set pilot   # paired differences (decision 023 §7)

Predictions and scores go to data/external/results/<set>/<method>/ (gitignored); table.md there is the summary.
Worksheets and gold judgments stay on the ground-truth side next to the label.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from collect.layout import DataLayout
from env.lock import PROJECT_DIR
from eval.runner import METHODS, run_method, score_method


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "score", "leakage", "gold-todo", "gold-add", "compare"])
    parser.add_argument("--method", choices=sorted(METHODS), help="required for run / score")
    parser.add_argument("--set", dest="split", choices=["pilot", "heldout"], help="required except for gold-add")
    parser.add_argument("--against", choices=sorted(METHODS), help="compare: the second method (difference = method - against)")
    parser.add_argument("--incident", help="gold-add: the incident whose worksheet is filled")
    parser.add_argument("--file", type=Path, help="gold-add: the filled worksheet")
    parser.add_argument("--annotator", help="gold-add: human:<name> (gold judgments are made by a person)")
    ns = parser.parse_args(argv)
    if ns.command in ("run", "score", "compare") and ns.method is None:
        parser.error("--method is required for run / score / compare")
    if ns.command == "compare" and ns.against is None:
        parser.error("compare needs --against")
    if ns.command == "gold-add" and not (ns.incident and ns.file and ns.annotator):
        parser.error("gold-add needs --incident, --file and --annotator")
    if ns.command != "gold-add" and ns.split is None:
        parser.error("--set is required")
    layout = DataLayout(PROJECT_DIR / "data/external")
    out = PROJECT_DIR / "data/external/results"
    try:
        if ns.command == "leakage":
            from eval.runner import audit_set

            print(json.dumps(audit_set(layout, ns.split, out, project_dir=PROJECT_DIR), indent=2))
        elif ns.command == "gold-todo":
            from eval.runner import gold_todo_set

            print(json.dumps(gold_todo_set(layout, ns.split, out, project_dir=PROJECT_DIR), indent=2))
        elif ns.command == "gold-add":
            from eval.runner import gold_add

            print(json.dumps(gold_add(layout, ns.incident, ns.file, annotator=ns.annotator,
                                      now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), project_dir=PROJECT_DIR)))
        elif ns.command == "compare":
            from eval.runner import compare_methods

            print(json.dumps(compare_methods(ns.split, ns.method, ns.against, out, layout=layout,
                                             project_dir=PROJECT_DIR)["paired"], indent=2))
        elif ns.command == "run":
            done = run_method(layout, ns.method, ns.split, out, project_dir=PROJECT_DIR)
            key = "without_prediction" if ns.split == "heldout" else "predictions"  # decision 023 §5
            print(json.dumps({key: [str(p) for p in done]}, indent=2))
        else:
            result = score_method(layout, ns.method, ns.split, out, project_dir=PROJECT_DIR)
            print(json.dumps({"aggregate": result["aggregate"], "evidence": result["evidence"]}, indent=2))
    except (ValueError, OSError, LookupError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
