"""Label review (decision 018): a person checks the a priori label against the frozen snapshot. Ground-truth side only.

review_sheet() writes a worksheet next to the label (a priori label, checks, a per-service normal / fault / recovery
summary of the snapshot, container events of the run); apply_review() turns a filled worksheet into a separate
catalog+review label plus a review record. label.json (a priori) is never changed; the origin is never reviewed.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from statistics import mean, median

from collect.derive import container_minute_stats, service_minute_stats
from collect.incident import find_run
from collect.labels import check_label
from collect.layout import DataLayout
from collect.pilot import GENERAL_CHECKS, REVIEW_CHECKS
from collect.policy import load_policy
from collect.snapshot import open_snapshot

PERIODS = ("normal", "fault", "recovery")
COVERAGE = ("origin", "symptom_only", "none")
REVIEWABLE = ("affected_services", "user_symptom", "telemetry_coverage", "fault_exercised", "saw_method_outputs", "notes",
              "reasons")
MINUTE = 60 * 10**9
MiB = 2**20


def _paths(layout: DataLayout, incident_id: str) -> dict:
    base = layout.label_path(incident_id)
    return {"todo": base.with_name("label_review_todo.json"), "label": base.with_name("label.reviewed.json"),
            "record": base.with_name("label_review.json")}


def _ns(ts: str) -> int:
    return int(datetime.fromisoformat(ts).timestamp() * 10**9)


def _period(t: int, on: int, off: int) -> str:
    return "normal" if t < on else "fault" if t < off else "recovery"


def _r(x):
    return None if x is None else round(x, 3)


def _summary(snapshot, on: int, off: int) -> dict:
    """Per service and period: the decision 018 §5 columns, from the derived minute views (minute midpoints decide)."""
    start, end = snapshot.window["start_ns"], snapshot.window["end_ns"]
    minutes = {p: [] for p in PERIODS}
    for m in range(-(-(end - start) // MINUTE)):
        minutes[_period(start + m * MINUTE + MINUTE // 2, on, off)].append(m)
    spans, containers = service_minute_stats(snapshot)["services"], container_minute_stats(snapshot)["services"]
    out = {}
    for svc in snapshot.services:
        s, c = spans.get(svc, {}), containers.get(svc, {})
        out[svc] = {}
        for p, ms in minutes.items():
            rows = [s[m] for m in ms if m in s]
            n_spans, n_err = sum(r["spans"] for r in rows), sum(r["error_spans"] for r in rows)
            p95 = [r["p95_server_ms"] for r in rows if r["p95_server_ms"] is not None]
            cpu = [c[m]["cpu"] for m in ms if c.get(m, {}).get("cpu") is not None]
            mem = [c[m]["memory"] for m in ms if c.get(m, {}).get("memory") is not None]
            out[svc][p] = {"minutes": len(ms),
                           "spans_per_min": _r(n_spans / len(ms)) if ms else None,
                           "error_ratio": _r(n_err / n_spans) if n_spans else None,
                           "p95_server_ms_median": _r(median(p95)) if p95 else None,
                           "p95_server_ms_max": _r(max(p95)) if p95 else None,
                           "warn_logs_per_min": _r(sum(r["warn_logs"] for r in rows) / len(ms)) if ms else None,
                           "cpu_mean": _r(mean(cpu)) if cpu else None,
                           "memory_max_mib": _r(max(mem) / MiB) if mem else None}
    return out


def review_sheet(layout: DataLayout, incident_id: str, *, overwrite: bool = False) -> dict:
    paths = _paths(layout, incident_id)
    if paths["label"].exists():
        raise FileExistsError(f"{incident_id} is already reviewed (decision 018): no new worksheet")
    if paths["todo"].exists() and not overwrite:
        raise FileExistsError(f"{paths['todo']} exists: a worksheet that may be half filled is never overwritten "
                              "(pass overwrite to start again)")
    label = json.loads(layout.label_path(incident_id).read_text())
    rg = find_run(layout, incident_id)["run_group_id"]
    injection = json.loads(layout.injection_path(rg).read_text())
    run = json.loads((layout.run_group_truth_dir(rg) / "run.json").read_text())
    offset = json.loads(layout.normalize_report_path(incident_id).read_text())["window"]["clock_offsets"][0]
    snapshot = open_snapshot(layout.incident_dir(incident_id) / "normalized", layout)
    shift = int(offset * 10**9)  # label and schedule: host clock; snapshot and docker events (the daemon runs in the VM): data clock
    on, off = _ns(label["fault_start"]) + shift, _ns(label["fault_end"]) + shift
    events = {p: [] for p in PERIODS}
    for e in run.get("events", []):
        if _ns(e["ts"]) >= _ns(injection["schedule"]["normal_start"]) + shift:  # warm-up events are not part of the incident
            events[_period(_ns(e["ts"]), on, off)].append(e)
    sheet = {
        "incident_id": incident_id,
        "how_to": "edit only `review` (decision 018): fix affected_services / user_symptom where the snapshot disagrees and give "
                  "each change a reason in review.reasons, fill telemetry_coverage, fault_exercised and saw_method_outputs; then "
                  "python -m collect review --incident <INC> --file <this file> --reviewer human:<name>",
        "checks": GENERAL_CHECKS + REVIEW_CHECKS.get(label["injected_fault"]["flag"], []),
        "a_priori": {k: label[k] for k in ("injected_fault", "origin_service", "affected_services", "user_symptom",
                                           "fault_start", "fault_end")} | {"notes": label["labeling"].get("notes")},
        "clock_offset_s": offset,
        "services": _summary(snapshot, on, off),
        "events": events,
        "review": {"affected_services": list(label["affected_services"]), "user_symptom": copy.deepcopy(label["user_symptom"]),
                   "telemetry_coverage": {"traces": None, "metrics": None, "logs": None},
                   "fault_exercised": None, "saw_method_outputs": None,
                   "notes": label["labeling"].get("notes"), "reasons": {}},
    }
    paths["todo"].write_text(json.dumps(sheet, indent=2) + "\n")
    return sheet


def _differences(a_priori: dict, review: dict) -> list[dict]:
    """Every reviewable field that differs from the a priori label (decision 018 §2, §3)."""
    out = []
    if sorted(review["affected_services"]) != sorted(a_priori["affected_services"]):
        out.append({"field": "affected_services", "a_priori": a_priori["affected_services"],
                    "reviewed": review["affected_services"]})
    before, after = a_priori["user_symptom"], review["user_symptom"]
    if (sorted(after.get("kinds") or []), after.get("description") or "") != (sorted(before["kinds"]), before.get("description") or ""):
        out.append({"field": "user_symptom", "a_priori": before, "reviewed": after})
    if (review.get("notes") or "") != (a_priori["labeling"].get("notes") or ""):
        out.append({"field": "notes", "a_priori": a_priori["labeling"].get("notes"), "reviewed": review.get("notes")})
    return out


def apply_review(layout: DataLayout, incident_id: str, sheet: dict, *, reviewer: str, now: str) -> dict:
    if not reviewer.startswith("human:"):
        raise ValueError(f"a label review is made by a person (human:<name>), not {reviewer!r} (decision 018 §4)")
    if sheet.get("incident_id") != incident_id:
        raise ValueError(f"the worksheet belongs to {sheet.get('incident_id')}, not {incident_id}")
    paths = _paths(layout, incident_id)
    if paths["label"].exists() or paths["record"].exists():
        raise FileExistsError(f"{incident_id} is already reviewed: a review is written once (decision 018)")
    review = sheet["review"]
    if extra := sorted(set(review) - set(REVIEWABLE)):
        raise ValueError(f"{extra} cannot be reviewed: the origin, fault and times come from the design (decision 018 §2)")
    for flag in ("fault_exercised", "saw_method_outputs"):
        if not isinstance(review.get(flag), bool):
            raise ValueError(f"review.{flag} must be true or false")
    coverage = review.get("telemetry_coverage") or {}
    if set(coverage) != {"traces", "metrics", "logs"} or not all(v in COVERAGE for v in coverage.values()):
        raise ValueError(f"review.telemetry_coverage needs traces / metrics / logs, each one of {COVERAGE}")
    a_priori = json.loads(layout.label_path(incident_id).read_text())
    differences = _differences(a_priori, review)
    reasons = review.get("reasons") or {}
    for d in differences:
        if not str(reasons.get(d["field"]) or "").strip():
            raise ValueError(f"{d['field']} differs from the a priori label: give a reason in review.reasons (decision 018 §3)")
        d["reason"] = reasons[d["field"]]
    labeling = {"method": "catalog+review", "labeled_at": now, "labeler": reviewer}
    if review.get("notes"):
        labeling["notes"] = review["notes"]
    label = {**a_priori, "affected_services": list(review["affected_services"]), "user_symptom": review["user_symptom"],
             "telemetry_coverage": coverage, "labeling": labeling}
    rg = find_run(layout, incident_id)["run_group_id"]
    injection = json.loads(layout.injection_path(rg).read_text())
    manifest = json.loads(layout.manifest_path(incident_id).read_text())
    if problems := check_label(label, injection, services=load_policy().sut_services, manifest=manifest):
        raise ValueError(f"the reviewed label of {incident_id} fails its checks: {problems}")
    record = {"review_version": 1, "incident_id": incident_id, "reviewer": reviewer, "reviewed_at": now,
              "fault_exercised": review["fault_exercised"], "saw_method_outputs": review["saw_method_outputs"],
              "differences": differences}
    paths["label"].write_text(json.dumps(label, indent=2) + "\n")
    paths["record"].write_text(json.dumps(record, indent=2) + "\n")
    return record


def effective_label(layout: DataLayout, incident_id: str) -> tuple[dict, str | None]:
    """The label scores use (reviewed if there is one, decision 018 §7) and why the incident is excluded, if it is."""
    paths = _paths(layout, incident_id)
    if not paths["label"].exists():
        return json.loads(layout.label_path(incident_id).read_text()), None
    record = json.loads(paths["record"].read_text())
    excluded = None if record["fault_exercised"] else "fault not exercised (decisions 016 §5, 018 §6)"
    return json.loads(paths["label"].read_text()), excluded
