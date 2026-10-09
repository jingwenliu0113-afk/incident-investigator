"""Run one method over one set of incidents and score it (SPEC Core §7–§10; decisions 013, 014).

The incidents of a set come from the ground-truth side (injection.json `split`, fixed at collection); a method only
ever receives an opened frozen snapshot and the incident id. Labels are read only when scoring, after all predictions
of the set exist.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import median

from collect.layout import DataLayout
from collect.snapshot import open_snapshot
from eval.evidence import existence
from eval.score import aggregate, check_prediction, score_incident


def _stat(snapshot, incident_id):
    from baselines.statistical import predict

    return predict(snapshot, incident_id)


LLM_CONFIG = Path(__file__).resolve().parent / "llm_methods.json"


def load_llm_config(path: Path = LLM_CONFIG, *, need_client: bool = True) -> dict:
    """The approved model, prices and budgets of the LLM methods; refuses anything not approved (MACHINE_POLICY:
    no paid call before the user approves the cost). The API client is an adapter added after approval (decision 020 §6)."""
    config = json.loads(Path(path).read_text())
    if config.get("status") != "approved" or not config.get("model"):
        raise ValueError(f"the LLM methods are not approved yet ({path.name}: status {config.get('status')!r}); the model, "
                         "budgets and estimated cost go to the user first (MACHINE_POLICY, decisions 020 / 021)")
    if need_client:
        raise ValueError("no model API adapter is installed yet: it is added only after the cost is approved (decision 020 §6)")
    return config


def _llm(kind: str):
    def run(snapshot, incident_id):
        config = load_llm_config()
        raise AssertionError(f"unreachable until an adapter exists: {kind} {config['model']}")
    return run


LLM_METHODS = ("dump-all", "retrieval", "agent")
METHODS = {"stat-anomaly": _stat, **{m: _llm(m) for m in LLM_METHODS}}
SCOPES = {  # SPEC §7 "visible data" of each method (decision 024)
    "stat-anomaly": "every span, log and container metric of the snapshot, but only as per-service, per-minute aggregates "
                    "(decision 014)",
    "dump-all": "the per-minute overview, then error-level groups and a time-stratified sample, packed within the "
                "proxy-token budget (decision 021 §2)",
    "retrieval": "the per-minute overview, then the spans and logs found by at most q queries of k results each "
                 "(decision 021 §3)",
    "agent": "any record of the snapshot through 7 read-only tools, within the tool-call, proxy-token and turn budgets "
             "(decision 019)",
}
USAGE_FIELDS = ("tokens_in", "tokens_out", "proxy_tokens", "tool_calls", "retrievals", "latency_s", "cost_usd")


def method_budgets(method: str, config: dict | None) -> dict:
    """The SPEC §7 budgets of one run (decision 024): none for the statistical baseline, the approved values otherwise."""
    if method not in LLM_METHODS:
        return {}
    b = config["budgets"]
    return {"dump-all": {"proxy_tokens": b["dump_all_proxy_tokens"]},
            "retrieval": {"queries": b["retrieval_queries"], "k": b["retrieval_k"]},
            "agent": {"tool_calls": b["agent_max_tool_calls"], "proxy_tokens": b["agent_max_proxy_tokens"],
                      "turns": b["agent_max_turns"]}}[method]
MAIN_METRICS = ("fault_type", "origin_top1", "affected_f1", "symptom_exact")  # decision 013: one per layer
DIFFICULTIES = ("easy", "medium", "hard")  # decision 015


def incidents_in(layout: DataLayout, split: str) -> list[tuple[str, str]]:
    """(incident id, run group id) of every incident of `split` that has a published snapshot and was not withdrawn."""
    from collect.pilot import withdrawn

    gone, out = withdrawn(layout), []
    for path in sorted((layout.ground_truth_root / "run_groups").glob("RG-*/injection.json")):
        inj = json.loads(path.read_text())
        if inj.get("split") == split:
            out += [(inc, inj["run_group_id"]) for inc in inj["incident_ids"]
                    if (layout.incident_dir(inc) / "normalized" / "snapshot.json").exists() and inc not in gone]
    return sorted(out)


def run_method(layout: DataLayout, method: str, split: str, out_root: Path) -> list[Path]:
    """Predictions of `method` for every incident of `split`, written to out_root/<split>/<method>/<INC>.json."""
    config = load_llm_config() if method in LLM_METHODS else None  # refuses before any snapshot is opened
    out_dir = Path(out_root) / split / method
    out_dir.mkdir(parents=True, exist_ok=True)
    # decision 024: the budgets of this run stay with its results, written before any prediction
    run_config = {"method": method, "split": split, "model": config["model"] if config else None,
                  "budgets": method_budgets(method, config), "scope": SCOPES.get(method)}
    (out_dir / "run_config.json").write_text(json.dumps(run_config, indent=2) + "\n")
    written = []
    for inc, _ in incidents_in(layout, split):
        snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
        out = METHODS[method](snapshot, inc)
        pred, transcript = out if isinstance(out, tuple) else (out, None)
        if problems := check_prediction(pred):
            raise ValueError(f"{method} wrote an invalid prediction for {inc}: {problems[:5]}")
        path = out_dir / f"{inc}.json"
        path.write_text(json.dumps(pred, indent=2) + "\n")
        if transcript is not None:  # LLM methods: messages, exposure, stop reason (decisions 020, 022)
            (out_dir / f"{inc}.transcript.json").write_text(json.dumps(transcript, indent=2) + "\n")
        written.append(path)
    return written


STRATUM_MIN_RUN_GROUPS = 10  # decision 023 §7: smaller strata report means only


def difficulty_strata(rows: list[dict]) -> dict:
    """Main metrics per difficulty (decision 015): means, plus run-group bootstrap intervals for strata with at least
    STRATUM_MIN_RUN_GROUPS run groups."""
    out = {}
    for d in DIFFICULTIES:
        group = [r for r in rows if r["difficulty"] == d]
        if not group:
            continue
        entry = {"n_incidents": len(group), "metrics": {m: sum(r[m] for r in group) / len(group) for m in MAIN_METRICS},
                 "ci95": None}
        if len({r["run_group_id"] for r in group}) >= STRATUM_MIN_RUN_GROUPS:
            agg = aggregate([{"incident_id": r["incident_id"], "run_group_id": r["run_group_id"],
                              **{m: r[m] for m in MAIN_METRICS}} for r in group])
            entry["ci95"] = {m: agg["metrics"][m]["ci95"] for m in MAIN_METRICS}
        out[d] = entry
    return out


def _clock_offset(layout: DataLayout, inc: str) -> float:
    """Data clock minus host clock of the incident's run (the label is on the host clock)."""
    return json.loads(layout.normalize_report_path(inc).read_text())["window"]["clock_offsets"][0]


def _gold_path(layout: DataLayout, inc: str) -> Path:
    return layout.label_path(inc).with_name("evidence_gold.json")


def _gold(layout: DataLayout, inc: str) -> dict | None:
    path = _gold_path(layout, inc)
    return json.loads(path.read_text()) if path.exists() else None


EVIDENCE_LAYERS = {  # decision 017 §4: each reported on its own, never combined
    "existence": lambda r: r["evidence_existence"],
    "temporal": lambda r: r["evidence_weak"]["temporal"],
    "service": lambda r: r["evidence_weak"]["service"],
    "origin": lambda r: r["evidence_weak"]["origin"],
    "weak": lambda r: r["evidence_weak"]["weak"],
    "gold_precision": lambda r: r["evidence_gold"]["precision"],
    "gold_coverage": lambda r: r["evidence_gold"]["coverage"],
}


_STATS = re.compile(r"^stats:(.+):(-?\d+)-(-?\d+)$")


def exposure_of(exposure: list[str], snapshot) -> dict:
    """What a method was shown (decision 024 §3): distinct spans, logs and metric points, their share of the snapshot's,
    and the share of the per-minute overview (service x minute cells; "stats:*" is the whole overview)."""
    counts = {f["path"]: f["records"] for f in snapshot.meta["files"]}
    total = counts["spans.jsonl"] + counts["logs.jsonl"] + counts["metric_points.jsonl"]
    records = {i for i in exposure if i[:2] in ("s-", "l-", "p-")}
    minutes = -(-(snapshot.window["end_ns"] - snapshot.window["start_ns"]) // 60_000_000_000)
    services = set(snapshot.services)
    if "stats:*" in exposure:
        cells = len(services) * minutes
    else:
        seen = set()
        for e in exposure:
            if (m := _STATS.match(e)) and m.group(1) in services:
                seen.update((m.group(1), t) for t in range(max(int(m.group(2)), 0), min(int(m.group(3)), minutes - 1) + 1))
        cells = len(seen)
    return {"records_seen": len(records), "records_share": len(records) / total if total else None,
            "overview_share": cells / (len(services) * minutes) if services and minutes else None}


def _spread(values: list) -> dict:
    v = [x for x in values if x is not None]
    if not v:
        return {"n": 0, "mean": None, "median": None, "max": None}
    return {"n": len(v), "mean": sum(v) / len(v), "median": median(v), "max": max(v)}


def _usage_aggregate(rows: list[dict]) -> dict:
    """decision 024 §2: usage over the scored incidents, stop reasons and measured exposure (reported, never scored)."""
    costs = [r["usage"].get("cost_usd") for r in rows]
    reasons = [r["stop_reason"] for r in rows if r["stop_reason"] is not None]
    seen = [r["exposure"] for r in rows if r["exposure"] is not None]
    return {"fields": {f: _spread([r["usage"].get(f) for r in rows]) for f in USAGE_FIELDS},
            "cost_total": sum(costs) if costs and None not in costs else None,
            "stop_reasons": {k: reasons.count(k) for k in sorted(set(reasons))},
            "exposure": {k: _spread([e[k] for e in seen]) for k in ("records_seen", "records_share", "overview_share")}
            if seen else None}


def _evidence_aggregate(rows: list[dict]) -> dict:
    out = {}
    for name, get in EVIDENCE_LAYERS.items():
        have = [{"incident_id": r["incident_id"], "run_group_id": r["run_group_id"], name: get(r)} for r in rows
                if get(r) is not None]
        m = aggregate(have)["metrics"][name] if have else {"mean": None, "ci95": None}
        out[name] = {"n": len(have), **m}
    return out


REPORTED_ONLY = ("difficulty", "fault", "failure", "label_reviewed", "saw_method_outputs", "usage", "stop_reason", "exposure")


def score_method(layout: DataLayout, method: str, split: str, out_root: Path) -> dict:
    from collect.review import effective_label
    from eval.failures import CATEGORIES, classify
    from eval.relevance import gold_score, weak_score

    out_dir = Path(out_root) / split / method
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, excluded, reviewed, differences = [], [], 0, {}
    from collect.pilot import withdrawn

    gone = withdrawn(layout)  # decision 025 revision 3: kept on disk, listed, never scored
    for path in sorted((layout.ground_truth_root / "run_groups").glob("RG-*/injection.json")):
        inj = json.loads(path.read_text())
        if inj.get("split") == split:
            excluded += [{"incident_id": i, "reason": f"withdrawn: {gone[i]}"} for i in inj["incident_ids"] if i in gone]
    for inc, rg in incidents_in(layout, split):
        audit_path = layout.label_path(inc).with_name("leakage_audit.json")
        if not audit_path.exists():
            raise LookupError(f"{inc} has no leakage audit: run `python -m eval leakage --set {split}` first (decision 015)")
        audit = json.loads(audit_path.read_text())
        if audit["lexicon_hits"]:  # decision 015: normalize leaked a lexicon term; the incident enters no score
            excluded.append({"incident_id": inc, "reason": f"lexicon_hits={audit['lexicon_hits']} (decision 015)"})
            continue
        label, why = effective_label(layout, inc)
        if why:
            excluded.append({"incident_id": inc, "reason": why})
            continue
        reviewed += label["labeling"]["method"] == "catalog+review"
        pred = json.loads((out_dir / f"{inc}.json").read_text())
        snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
        tpath = out_dir / f"{inc}.transcript.json"
        transcript = json.loads(tpath.read_text()) if tpath.exists() else None
        scores = score_incident(pred, label)
        review_path = layout.label_path(inc).with_name("label_review.json")
        review = json.loads(review_path.read_text()) if review_path.exists() else None
        if review and review.get("differences"):
            differences[inc] = review["differences"]
        rows.append(scores | {
            "saw_method_outputs": None if review is None else review.get("saw_method_outputs"),
            "run_group_id": rg,
            "difficulty": audit["difficulty"],
            "fault": f"{label['injected_fault']['flag']} {label['injected_fault']['variant']}",
            "failure": classify(pred, label, scores, transcript, snapshot, clock_offset_s=_clock_offset(layout, inc)),
            "label_reviewed": label["labeling"]["method"] == "catalog+review",
            "evidence_existence": existence(pred["evidence"], snapshot)["rate"],
            "evidence_weak": weak_score(pred["evidence"], snapshot, label, clock_offset_s=_clock_offset(layout, inc)),
            "evidence_gold": gold_score(pred["evidence"], snapshot, _gold(layout, inc)),
            "usage": pred.get("usage") or {},
            "stop_reason": None if transcript is None else transcript.get("stop_reason"),
            "exposure": None if transcript is None else exposure_of(transcript.get("exposure", []), snapshot)})
    scored = [{k: v for k, v in r.items()
               if not k.startswith("evidence_") and k not in REPORTED_ONLY}
              for r in rows]
    agg = aggregate(scored) if scored else {"n_incidents": 0, "n_run_groups": 0, "metrics": {}}
    by_difficulty = difficulty_strata(rows)
    failed = [r for r in rows if r["failure"] is not None]
    failures = {"n_failures": len(failed), "by_category": {c: sum(r["failure"] == c for r in failed) for c in CATEGORIES},
                "by_difficulty": {d: {c: sum(r["failure"] == c for r in failed if r["difficulty"] == d) for c in CATEGORIES}
                                  for d in DIFFICULTIES if any(r["difficulty"] == d for r in failed)},
                "classified_without_review": sum(not r["label_reviewed"] for r in failed),
                "list": [{"incident_id": r["incident_id"], "difficulty": r["difficulty"], "category": r["failure"]} for r in failed]}
    failures["share"] = {c: (n / len(failed) if failed else None) for c, n in failures["by_category"].items()}
    config_path = out_dir / "run_config.json"
    result = {"method": method, "split": split, "labels": {"reviewed": reviewed, "a_priori": len(rows) - reviewed},
              "incidents": rows, "excluded": excluded, "aggregate": agg,
              "by_difficulty": by_difficulty, "evidence": _evidence_aggregate(rows), "failures": failures,
              "review_differences": differences,
              "run_config": json.loads(config_path.read_text()) if config_path.exists() else None,
              "usage": _usage_aggregate(rows)}
    (out_dir / "scores.json").write_text(json.dumps(result, indent=2) + "\n")
    (out_dir / "table.md").write_text(_table(result))
    return result


def _table(result: dict) -> str:
    agg = result["aggregate"]
    lines = [f"# {result['method']} on the {result['split']} set",
             "",
             f"n = {agg['n_incidents']} incidents in {agg['n_run_groups']} run groups; 95% interval: run-group cluster bootstrap "
             f"({agg.get('bootstrap', {}).get('resamples', 0)} resamples, seed {agg.get('bootstrap', {}).get('seed', '-')}).",
             f"Labels: {result['labels']['reviewed']} reviewed (catalog+review), {result['labels']['a_priori']} a priori (catalog) "
             "(decision 018).",
             "",
             "| metric | mean | 95% interval |",
             "|---|---:|---|"]
    for name, m in agg["metrics"].items():
        mark = " (main)" if name in MAIN_METRICS else ""
        lines.append(f"| {name}{mark} | {m['mean']:.3f} | [{m['ci95'][0]:.3f}, {m['ci95'][1]:.3f}] |")
    lines += ["", f"## Main metrics by difficulty (decision 015; intervals only with >= {STRATUM_MIN_RUN_GROUPS} run groups)", "",
              "| difficulty | n | " + " | ".join(MAIN_METRICS) + " |", "|---|---:|" + "---:|" * len(MAIN_METRICS)]
    for d, g in result["by_difficulty"].items():
        cells = [f"{g['metrics'][m]:.3f}" + ("" if g["ci95"] is None else f" [{g['ci95'][m][0]:.3f}, {g['ci95'][m][1]:.3f}]")
                 for m in MAIN_METRICS]
        lines.append(f"| {d} | {g['n_incidents']} | " + " | ".join(cells) + " |")
    if result["excluded"]:
        lines += ["", "Excluded from every score: " + ", ".join(f"{e['incident_id']} ({e['reason']})" for e in result["excluded"])]
    f = result["failures"]
    lines += ["", f"## Failures (decision 022): {f['n_failures']} incidents with origin or fault type wrong"
              f" ({f['classified_without_review']} classified without a reviewed label)", "",
              "| category | count | share | easy | medium | hard |", "|---|---:|---:|---:|---:|---:|"]
    for c, n in f["by_category"].items():
        share = "-" if f["share"][c] is None else f"{f['share'][c]:.2f}"
        per = [str(f["by_difficulty"].get(d, {}).get(c, 0)) for d in DIFFICULTIES]
        lines.append(f"| {c} | {n} | {share} | " + " | ".join(per) + " |")
    if f["list"]:
        lines += ["", "| incident | difficulty | category |", "|---|---|---|"]
        lines += [f"| {e['incident_id']} | {e['difficulty']} | {e['category']} |" for e in f["list"]]
    saw = [r["incident_id"] for r in result["incidents"] if r.get("saw_method_outputs")]
    if saw:
        lines += ["", "Labels reviewed after seeing method outputs: " + ", ".join(saw) + " (decision 018 §4)."]
    if result["review_differences"]:
        lines += ["", "## A priori vs reviewed labels (decision 018)", ""]
        lines += [f"- {inc}: {d['field']}: {d['a_priori']} -> {d['reviewed']} ({d['reason']})"
                  for inc, ds in result["review_differences"].items() for d in ds]
    lines += ["", "## Evidence (decisions 013 §4, 017; each layer on its own)", "",
              "| layer | n incidents | mean | 95% interval |", "|---|---:|---:|---|"]
    names = {"existence": "existence", "temporal": "weak: temporal", "service": "weak: affected service",
             "origin": "weak: origin service", "weak": "weak: temporal and service", "gold_precision": "gold precision",
             "gold_coverage": "gold coverage"}
    for key, m in result["evidence"].items():
        if m["mean"] is None:
            lines.append(f"| {names[key]} | 0 | - | - |")
        else:
            lines.append(f"| {names[key]} | {m['n']} | {m['mean']:.3f} | [{m['ci95'][0]:.3f}, {m['ci95'][1]:.3f}] |")
    return "\n".join(lines + _usage_lines(result)) + "\n"


def _fmt(x) -> str:
    return "-" if x is None else f"{x:,.0f}" if abs(x) >= 1000 else f"{x:.3f}"


def _usage_lines(result: dict) -> list[str]:
    config, usage = result["run_config"], result["usage"]
    lines = ["", "## Budgets, usage and visible data (SPEC §7, decision 024; reported, never scored)", ""]
    if config is None:
        lines.append("Run configuration: not recorded (a result from before decision 024).")
    else:
        budgets = ", ".join(f"{k} {v}" for k, v in config["budgets"].items()) or "none"
        lines += [f"Visible data: {config['scope'] or 'not described'}.", f"Model: {config['model'] or '-'}. Budgets: {budgets}."]
    lines += ["", f"Usage over the {result['aggregate']['n_incidents']} scored incidents:", "",
              "| quantity | n | mean | median | max |", "|---|---:|---:|---:|---:|"]
    for name, s in usage["fields"].items():
        lines.append(f"| {name} | {s['n']} | {_fmt(s['mean'])} | {_fmt(s['median'])} | {_fmt(s['max'])} |")
    cost = "-" if usage["cost_total"] is None else f"{usage['cost_total']:.2f}"
    lines += ["", f"Total cost (USD): {cost}."]
    if usage["stop_reasons"]:
        lines.append("Stop reasons: " + ", ".join(f"{k} {n}" for k, n in usage["stop_reasons"].items()) + ".")
    if usage["exposure"] is None:
        lines.append("Exposure: no exposure log (the method's visible data is described above).")
    else:
        lines += ["", "| shown to the method, per incident | n | mean | median | max |", "|---|---:|---:|---:|---:|"]
        for name, s in usage["exposure"].items():
            lines.append(f"| {name} | {s['n']} | {_fmt(s['mean'])} | {_fmt(s['median'])} | {_fmt(s['max'])} |")
    return lines


def gold_todo_set(layout: DataLayout, split: str, out_root: Path) -> dict:
    """Blind gold worksheets (decision 017 §3): per incident of `split`, the pooled citations of every method's predictions
    still to judge, written to the ground-truth side as evidence_gold_todo.json (record text and label, no method)."""
    from collect.review import effective_label
    from collect.snapshot import _rel
    from eval.relevance import _ns, gold_sample, key, resolved_unique

    rows = []
    for inc, _ in incidents_in(layout, split):
        snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
        cited = {}
        for path in sorted(Path(out_root, split).glob(f"*/{inc}.json")):
            pred = json.loads(path.read_text())
            cited[pred["method"]["name"]] = [{"id": k[0], "t0": k[1], "t1": k[2]}
                                             for k, _ in resolved_unique(pred["evidence"], snapshot)]
        gold = _gold(layout, inc)
        todo = gold_sample(inc, cited, annotated={key(e) for e in (gold or {}).get("items", [])})
        label = effective_label(layout, inc)[0]
        start, offset = snapshot.window["start_ns"], _clock_offset(layout, inc)
        sheet = {"incident_id": inc,
                 "how_to": "set relevant to true or false for each item (decision 017 §3), leave null to judge later, "
                           "then: python -m eval gold-add --incident <INC> --file <this file> --annotator human:<name>",
                 "context": {"fault_type": label["injected_fault"]["fault_type"], "origin_service": label["origin_service"],
                             "affected_services": label["affected_services"],
                             "fault": [_rel(_ns(label["fault_start"], offset), start), _rel(_ns(label["fault_end"], offset), start)]},
                 "items": [{**e, "record": _render(snapshot, e), "relevant": None} for e in todo]}
        todo_path = layout.label_path(inc).with_name("evidence_gold_todo.json")
        if todo_path.exists():  # judgments typed into the old sheet but not added yet are never wiped
            done = {key(e) for e in (gold or {}).get("items", [])}
            pending = [e for e in json.loads(todo_path.read_text()).get("items", [])
                       if e.get("relevant") is not None and key(e) not in done]
            if pending:
                raise ValueError(f"{todo_path} has {len(pending)} judgments not merged yet: run "
                                 f"`python -m eval gold-add --incident {inc} ...` first")
        todo_path.write_text(json.dumps(sheet, indent=2) + "\n")
        rows.append({"incident_id": inc, "to_judge": len(todo)})
    return {"split": split, "incidents": rows}


def _render(snapshot, e: dict, limit: int = 20) -> list[str]:
    """The cited record as the snapshot renders it (decision 011 §5 renderer): a trace as its spans, a series with its points in range."""
    from collect.snapshot import render

    start = snapshot.window["start_ns"]
    if e["id"].startswith("t-"):
        return [render(s, start) for s in snapshot.spans() if s["trace_id"] == e["id"][2:]][:limit]
    lines = [render(snapshot.resolve(e["id"], e["t0"], e["t1"]), start)]
    if e["id"].startswith("m-"):
        lo, hi = e["t0"] if e["t0"] is not None else -1, e["t1"] if e["t1"] is not None else 2**63
        lines += [render(p, start) for p in snapshot.points()
                  if p["series_id"] == e["id"] and lo <= p["time_unix_nano"] <= hi][:limit]
    return lines


def gold_add(layout: DataLayout, incident_id: str, sheet_path: Path, *, annotator: str, now: str) -> dict:
    """Merge the judged items of a filled worksheet into evidence_gold.json (append-only, decision 017 §3)."""
    from eval.relevance import merge_gold

    sheet = json.loads(Path(sheet_path).read_text())
    if sheet.get("incident_id") != incident_id:
        raise ValueError(f"the worksheet belongs to {sheet.get('incident_id')}, not {incident_id}")
    items = sheet["items"]
    judged = [e for e in items if e.get("relevant") is not None]
    before = _gold(layout, incident_id)
    doc = merge_gold(before, incident_id, judged, annotator=annotator, now=now)
    _gold_path(layout, incident_id).write_text(json.dumps(doc, indent=2) + "\n")
    return {"added": len(doc["items"]) - len((before or {}).get("items", [])), "unjudged": len(items) - len(judged)}


def audit_set(layout: DataLayout, split: str, out_root: Path) -> dict:
    """Leakage audit of every incident of `split` (decision 015): per-incident JSON on the ground-truth side,
    a summary table under out_root/<split>/leakage.md (difficulty and counts only, no templates)."""
    from collect.review import effective_label
    from eval.leakage import audit

    rows = []
    for inc, _ in incidents_in(layout, split):
        snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
        label = effective_label(layout, inc)[0]
        report = json.loads(layout.normalize_report_path(inc).read_text())
        out = audit(snapshot, label, clock_offset_s=report["window"]["clock_offsets"][0],
                    new_attribute_keys=report.get("new_attribute_keys"))
        layout.label_path(inc).with_name("leakage_audit.json").write_text(json.dumps(out, indent=2) + "\n")
        rows.append({k: out[k] for k in ("incident_id", "difficulty", "fault_only_count", "lexicon_hits")}
                    | {"origin_named": len(out["origin_named"]), "new_keys": sum(map(len, out["new_attribute_keys"].values()))})
    table = ["# Leakage audit (decision 015)", "", "| incident | difficulty | fault-only templates | naming the origin | lexicon hits | new keys |",
             "|---|---|---:|---:|---:|---:|"]
    table += [f"| {r['incident_id']} | {r['difficulty']} | {r['fault_only_count']} | {r['origin_named']} | {r['lexicon_hits']} | "
              f"{r['new_keys']} |" for r in rows]
    out_dir = Path(out_root) / split
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "leakage.md").write_text("\n".join(table) + "\n")
    return {"split": split, "incidents": rows}


def compare_methods(split: str, a: str, b: str, out_root: Path, *, metrics: tuple = MAIN_METRICS,
                    resamples: int = 10_000) -> dict:
    """Paired differences a - b on the incidents both were scored on (decision 023 §7), with LOFO bounds; written to
    out_root/<split>/compare-<a>-vs-<b>.json / .md. Reads only the two methods' scores.json."""
    from eval.compare import lofo, paired

    scored = {}
    for m in (a, b):
        path = Path(out_root) / split / m / "scores.json"
        if not path.exists():
            raise LookupError(f"{m} has no scores on the {split} set: run `python -m eval score --method {m} --set {split}`")
        scored[m] = json.loads(path.read_text())["incidents"]
    result = {"split": split, "a": a, "b": b,
              "paired": {m: paired(scored[a], scored[b], m, resamples=resamples) for m in metrics},
              "lofo": {m: lofo(scored[a], scored[b], m, resamples=resamples) for m in metrics}}
    base = Path(out_root) / split / f"compare-{a}-vs-{b}"
    base.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [f"# {a} - {b} on the {split} set (decision 023 §7; paired run-group cluster bootstrap)", "",
             "| metric | n | mean difference | 95% interval |", "|---|---:|---:|---|"]
    lines += [f"| {m} | {r['n']} | {r['mean_diff']:.3f} | [{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}] |"
              for m, r in result["paired"].items()]
    lines += ["", "Leave one fault out (descriptive): lower bound of the interval without each fault", "",
              "| metric | fault left out | n | mean difference | lower bound |", "|---|---|---:|---:|---:|"]
    lines += [f"| {m} | {f} | {r['n']} | " + ("- | - |" if r["mean_diff"] is None else f"{r['mean_diff']:.3f} | {r['ci95'][0]:.3f} |")
              for m, by in result["lofo"].items() for f, r in by.items()]
    base.with_suffix(".md").write_text("\n".join(lines) + "\n")
    return result
