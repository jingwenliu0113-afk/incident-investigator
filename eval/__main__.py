"""python -m eval — predictions, scores, leakage audit and gold evidence judgments of one set.

    python -m eval run|score --method <name> --set pilot
    python -m eval leakage --set pilot
    python -m eval gold-todo --set pilot          # blind worksheets of citations to judge (decision 017)
    python -m eval gold-add --incident INC-001 --file <worksheet> --annotator human:<name>
    python -m eval compare --method agent --against stat-anomaly --set pilot   # paired differences (decision 023 §7)
    python -m eval gate --method agent --against stat-anomaly --set heldout    # SPEC Gate from written scores (023 §7)
    python -m eval version-check --set pilot [--method <m> ...]   # read only: every Pilot prediction is its method's current
                                                                  # version (decision 021's Pilot revision); exit 1 if not
    python -m eval demo                           # 2 minutes: the statistical baseline on the SYNTHETIC sample (decision 027)
    ./tools/with-remote-ollama uv run python -m eval local-probe --model <ollama tag> [--host gpu-server] [--num-ctx N]
        [--think] [--context-sizes 8000,32000,100000] [--out PATH]   # one local model on the SYNTHETIC sample (decision 029)
    ./tools/with-mac-lock ./tools/with-local-ollama uv run python -m eval local-probe --model <ollama tag> --host local ...

`gate` reads only scores.json and the compare outputs (it never runs a method) and writes gate.json / gate.md next to
the Agent's scores: the Gate decision on the held-out set, a diagnostic only (NOT a Gate decision) on the Pilot.

`version-check` (default: every LLM method; --method may repeat) prints eval.runner.method_version_problems: each Pilot
prediction that its method's current version (LLM_METHOD_VERSIONS) did not write, unreadable predictions and methods
without predictions. It reads only the prediction files and writes nothing; exit 1 when it lists anything, 0 when not.
It is a process check: `eval score` and `collect heldout-freeze` never run it (decision 021, review 2026-10-11).

Predictions and scores go to data/external/results/<set>/<method>/ (gitignored); table.md there is the summary.
Worksheets and gold judgments stay on the ground-truth side next to the label. The demo only reads data/samples/synthetic/
and writes nothing; its numbers are not results. The local probe also runs only on that sample (dump-all, retrieval
and the Agent with one local Ollama model, a context-guard self-test and prefill / decode speed on generated filler),
writes its JSON to stdout or --out (never under data/) and is not a result either; it exits 3 when the Ollama did not
refuse a prompt above num_ctx itself (GUARD FAILED; the report is still written). --host (default: ollama.host of
eval/llm_methods.json, decision 029 revision 1): gpu-server needs tools/with-remote-ollama, local the Mac heavy lock
and tools/with-local-ollama; `eval run` of an LLM method has the same requirement for the configured host.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from agent.harness import CallError
from collect.layout import DataLayout
from env.lock import PROJECT_DIR
from eval.runner import METHODS, run_method, score_method


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "score", "leakage", "gold-todo", "gold-add", "compare", "gate", "demo",
                                            "local-probe", "version-check"])
    parser.add_argument("--method", choices=sorted(METHODS), action="append",
                        help="required (once) for run / score / compare / gate (gate: agent); version-check: may repeat, "
                             "default every LLM method")
    parser.add_argument("--set", dest="split", choices=["pilot", "heldout"], help="required except for gold-add")
    parser.add_argument("--against", choices=sorted(METHODS),
                        help="compare: the second method (difference = method - against); gate: a statistical baseline")
    parser.add_argument("--incident", help="gold-add: the incident whose worksheet is filled")
    parser.add_argument("--file", type=Path, help="gold-add: the filled worksheet")
    parser.add_argument("--annotator", help="gold-add: human:<name> (gold judgments are made by a person)")
    parser.add_argument("--model", help="local-probe: the tag of an installed local Ollama model (decision 029)")
    parser.add_argument("--host", choices=["local", "gpu-server"],
                        help="local-probe: where the model runs (default: ollama.host of eval/llm_methods.json; decision "
                             "029 revision 1): gpu-server under tools/with-remote-ollama, local under tools/with-mac-lock "
                             "and tools/with-local-ollama")
    parser.add_argument("--num-ctx", type=int, help="local-probe: the context length (default: the model's, at most 65536)")
    parser.add_argument("--think", action="store_true", help="local-probe: think on (default off)")
    parser.add_argument("--context-sizes", help="local-probe: proxy-token sizes of generated filler for the speed "
                                                "measurement, comma-separated (e.g. 8000,32000,100000)")
    parser.add_argument("--out", type=Path, help="local-probe: write the JSON report here (never under data/)")
    ns = parser.parse_args(argv)
    if ns.command == "version-check":
        return _version_check(parser, ns)
    if ns.command in ("run", "score", "compare", "gate") and ns.method is None:
        parser.error("--method is required for run / score / compare / gate")
    if ns.method is not None and len(ns.method) > 1:
        parser.error(f"{ns.command} takes one --method")
    ns.method = ns.method[0] if ns.method else None
    if ns.command in ("compare", "gate") and ns.against is None:
        parser.error(f"{ns.command} needs --against")
    if ns.command == "gold-add" and not (ns.incident and ns.file and ns.annotator):
        parser.error("gold-add needs --incident, --file and --annotator")
    if ns.command not in ("gold-add", "demo", "local-probe") and ns.split is None:
        parser.error("--set is required")
    if ns.command == "local-probe":
        if ns.model is None:
            parser.error("local-probe needs --model")
        return _local_probe(ns)
    if ns.command == "demo":
        from collect.sample import SAMPLE_DIR
        from eval.demo import demo_text, run_demo

        try:
            print(demo_text(run_demo(PROJECT_DIR / SAMPLE_DIR), SAMPLE_DIR.as_posix()), end="")
        except (ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
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
        elif ns.command == "gate":
            from eval.runner import gate_methods, gate_summary

            result = gate_methods(ns.split, ns.method, ns.against, out, layout=layout, project_dir=PROJECT_DIR)
            print(gate_summary(result, out / ns.split / ns.method))
        elif ns.command == "run":
            done = run_method(layout, ns.method, ns.split, out, project_dir=PROJECT_DIR)
            key = "without_prediction" if ns.split == "heldout" else "predictions"  # decision 023 §5
            print(json.dumps({key: [str(p) for p in done]}, indent=2))
        else:
            result = score_method(layout, ns.method, ns.split, out, project_dir=PROJECT_DIR)
            print(json.dumps({"aggregate": result["aggregate"], "evidence": result["evidence"]}, indent=2))
    except (ValueError, OSError, LookupError, RuntimeError, CallError) as e:  # CallError: a failed model call (023 §5, 029 §2)
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def _version_check(parser, ns) -> int:
    """decision 021's Pilot revision (review 2026-10-11): list the Pilot predictions that are not their LLM method's
    current version. Read only; a process check that scoring and the freeze never call."""
    from eval.runner import LLM_METHOD_VERSIONS, LLM_METHODS, method_version_problems

    if ns.split != "pilot":
        parser.error("version-check needs --set pilot: it checks decision 021's Pilot revision (the freeze pins the "
                     "held-out code, and held-out outputs never show incident ids)")
    methods = list(dict.fromkeys(ns.method or LLM_METHODS))
    if other := [m for m in methods if m not in LLM_METHODS]:
        parser.error(f"version-check checks only the LLM methods ({', '.join(LLM_METHODS)}), not {', '.join(other)}")
    problems = method_version_problems(PROJECT_DIR / "data/external/results", ns.split, methods)
    head = "version-check (decision 021's Pilot revision; read only, a process check that scoring and the freeze never run)"
    if problems:
        print(f"{head}: {len(problems)} problem(s)")
        print("\n".join(problems))
        return 1
    current = ", ".join(f"{m} {LLM_METHOD_VERSIONS[m]}" for m in methods)
    print(f"{head}: every {ns.split} prediction of {', '.join(methods)} is its method's current version ({current})")
    return 0


def _local_probe(ns) -> int:
    """decision 029: the synthetic-sample probe of one local model; NOT results."""
    from eval.probe import BANNER, FOOTER, out_problem, run_probe

    try:
        sizes = tuple(int(x) for x in ns.context_sizes.split(",")) if ns.context_sizes else ()
        if any(s <= 0 for s in sizes):
            raise ValueError
    except ValueError:
        print(f"error: --context-sizes must be comma-separated positive integers, got {ns.context_sizes!r}", file=sys.stderr)
        return 2
    if ns.out is not None and (problem := out_problem(ns.out)):
        print(f"error: {problem}", file=sys.stderr)
        return 2
    print(BANNER, file=sys.stderr)
    try:
        report = run_probe(ns.model, host=ns.host, num_ctx=ns.num_ctx, think=ns.think, context_sizes=sizes)
    except (ValueError, OSError, LookupError, RuntimeError, CallError) as e:  # RuntimeError: no heavy lock / no wrapper
        print(f"error: {e}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2) + "\n"
    if ns.out is None:
        print(text, end="")
    else:
        ns.out.parent.mkdir(parents=True, exist_ok=True)
        ns.out.write_text(text)
    print(FOOTER, file=sys.stderr)
    if not report["guard_selftest"]["passed"]:  # the report is written; a person decides (decision 029 §2)
        print("GUARD FAILED: the local Ollama did not refuse a prompt above num_ctx; do not run the LLM methods on it "
              "(see guard_selftest and warnings)", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
