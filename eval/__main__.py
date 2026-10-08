"""python -m eval run|score --method <name> --set pilot | leakage --set pilot — predictions, scores, leakage audit.

Predictions and scores go to data/external/results/<set>/<method>/ (gitignored); table.md there is the summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from collect.layout import DataLayout
from env.lock import PROJECT_DIR
from eval.runner import METHODS, run_method, score_method


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__)
    parser.add_argument("command", choices=["run", "score", "leakage"])
    parser.add_argument("--method", choices=sorted(METHODS), help="required for run / score")
    parser.add_argument("--set", dest="split", required=True, choices=["pilot", "heldout"])
    ns = parser.parse_args(argv)
    layout = DataLayout(PROJECT_DIR / "data/external")
    out = PROJECT_DIR / "data/external/results"
    if ns.command in ("run", "score") and ns.method is None:
        parser.error("--method is required for run / score")
    try:
        if ns.command == "leakage":
            from eval.runner import audit_set

            print(json.dumps(audit_set(layout, ns.split, out), indent=2))
        elif ns.command == "run":
            print(json.dumps({"predictions": [str(p) for p in run_method(layout, ns.method, ns.split, out)]}, indent=2))
        else:
            result = score_method(layout, ns.method, ns.split, out)
            print(json.dumps(result["aggregate"], indent=2))
    except (ValueError, OSError, LookupError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
