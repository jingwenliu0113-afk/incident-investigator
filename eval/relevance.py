"""Evidence relevance (SPEC Core §9, decision 017). Ground-truth side: weak labels and gold judgments need the label.

Weak labels: a cited record is temporal when its time is in [fault_start, fault_end + 60 s] (data clock) and service-relevant
when its service is affected. Gold: a blind, human, append-only judgment of a fixed per-method sample of the pooled
citations. Existence (decision 013), weak-label rates and gold precision are reported side by side, never combined.
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

GRACE_S = 60
GOLD_PER_METHOD = 5
SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "evidence_gold.schema.json"


def key(e: dict) -> tuple:
    return e["id"], e.get("t0"), e.get("t1")


def resolved_unique(cited: list[dict], snapshot) -> list[tuple[tuple, dict]]:
    """(key, record) of each distinct citation that names a record of the snapshot (existence), in citation order."""
    seen, out = set(), []
    for e in cited:
        k = key(e)
        if k in seen:
            continue
        seen.add(k)
        if (rec := snapshot.resolve(*k)) is not None:
            out.append((k, rec))
    return out


def _ns(ts: str, offset_s: float) -> int:
    return int(datetime.fromisoformat(ts).timestamp() * 10**9) + int(offset_s * 10**9)


def _traces(snapshot, wanted: set[str]) -> dict[str, tuple[int, set[str]]]:
    """trace id -> (earliest span start, services of its spans), for the cited traces only."""
    out: dict[str, tuple[int, set[str]]] = {}
    if wanted:
        for s in snapshot.spans():
            if s["trace_id"] in wanted:
                t, svcs = out.get(s["trace_id"], (s["start_time_unix_nano"], set()))
                out[s["trace_id"]] = (min(t, s["start_time_unix_nano"]), svcs | {s["service"]})
    return out


def _time_and_services(k: tuple, rec: dict, traces: dict) -> tuple[int | None, set[str]]:
    eid, t0, t1 = k
    kind = eid[:2]
    if kind == "t-":
        return traces.get(rec["trace_id"], (None, set()))
    if kind == "s-":
        t = rec["start_time_unix_nano"]
    elif kind == "l-":
        t = rec["time_unix_nano"] if rec.get("time_unix_nano") is not None else rec.get("observed_time_unix_nano")
    elif kind == "p-":
        t = rec.get("time_unix_nano")
    else:  # m-: a series has a time only through the range cited with it
        t = None if t0 is None or t1 is None else (t0 + t1) // 2
    return t, {rec.get("service")} - {None}


def weak_score(cited: list[dict], snapshot, label: dict, *, clock_offset_s: float = 0.0) -> dict:
    """Shares of the distinct resolved citations that are temporal / service / origin / weak (temporal and service)."""
    items = resolved_unique(cited, snapshot)
    n = len(items)
    if not n:
        return {"n": 0, "temporal": None, "service": None, "origin": None, "weak": None}
    on = _ns(label["fault_start"], clock_offset_s)
    end = _ns(label["fault_end"], clock_offset_s) + GRACE_S * 10**9
    affected, origin = set(label["affected_services"]), label["origin_service"]
    traces = _traces(snapshot, {rec["trace_id"] for k, rec in items if k[0].startswith("t-")})
    counts = {"temporal": 0, "service": 0, "origin": 0, "weak": 0}
    for k, rec in items:
        t, services = _time_and_services(k, rec, traces)
        temporal = t is not None and on <= t <= end
        service = bool(services & affected)
        counts["temporal"] += temporal
        counts["service"] += service
        counts["origin"] += origin in services
        counts["weak"] += temporal and service
    return {"n": n, **{name: c / n for name, c in counts.items()}}


def gold_sample(incident_id: str, cited_by_method: dict[str, list[dict]], annotated: set[tuple]) -> list[dict]:
    """The citations still to judge: per method a fixed random sample (seed `<incident>:<method>`) of at most
    GOLD_PER_METHOD distinct citations, minus those already judged; method-blind and in a stable order."""
    chosen: set[tuple] = set()
    for method, cited in cited_by_method.items():
        keys = sorted({key(e) for e in cited}, key=lambda k: (k[0], k[1] or 0, k[2] or 0))
        random.Random(f"{incident_id}:{method}").shuffle(keys)
        chosen.update(keys[:GOLD_PER_METHOD])
    todo = sorted(chosen - annotated, key=lambda k: (k[0], k[1] or 0, k[2] or 0))
    return [{"id": i, "t0": t0, "t1": t1} for i, t0, t1 in todo]


def gold_score(cited: list[dict], snapshot, gold: dict | None) -> dict:
    """Gold precision over the method's judged citations, and the share of its resolved citations that are judged."""
    judged = {key(e): e["relevant"] for e in (gold or {}).get("items", [])}
    keys = [k for k, _ in resolved_unique(cited, snapshot)]
    hits = [judged[k] for k in keys if k in judged]
    return {"cited": len(keys), "judged": len(hits), "relevant": sum(hits),
            "precision": sum(hits) / len(hits) if hits else None, "coverage": len(hits) / len(keys) if keys else None}


def check_gold(doc: dict) -> list[str]:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
    problems = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:160]}" for e in validator.iter_errors(doc)]
    keys = [key(e) for e in doc.get("items", []) if isinstance(e, dict) and "id" in e]
    if len(keys) != len(set(keys)):
        problems.append("an item is judged twice")
    return problems


def merge_gold(existing: dict | None, incident_id: str, judged: list[dict], *, annotator: str, now: str) -> dict:
    """Append new human judgments; a citation already judged keeps its judgment (decision 017 §3)."""
    if not annotator.startswith("human:"):
        raise ValueError(f"gold judgments are made by a person (human:<name>), not {annotator!r}")
    doc = existing or {"gold_version": 1, "incident_id": incident_id, "items": []}
    if doc["incident_id"] != incident_id:
        raise ValueError(f"the gold file belongs to {doc['incident_id']}, not {incident_id}")
    before = {key(e): e["relevant"] for e in doc["items"]}
    items = list(doc["items"])
    for e in judged:
        if not isinstance(e.get("relevant"), bool):
            raise ValueError(f"{e.get('id')}: relevant must be true or false")
        k = key(e)
        if k in before:
            if before[k] != e["relevant"]:
                raise ValueError(f"{k[0]} is already judged {before[k]}; judgments are never changed (decision 017)")
            continue
        entry = {"id": k[0], "t0": k[1], "t1": k[2], "relevant": e["relevant"], "annotator": annotator, "annotated_at": now}
        if e.get("note"):
            entry["note"] = e["note"]
        items.append(entry)
        before[k] = e["relevant"]
    out = {**doc, "items": items}
    if problems := check_gold(out):
        raise ValueError(f"gold judgments fail their schema: {problems[:5]}")
    return out
