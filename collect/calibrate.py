"""Calibrate the normalize policy on soak raw — no fault injected — before it is frozen (decision 011 §4).

inventory(): which services, receiver scopes, container names, attribute keys, event names and OTLP fields
actually occur. calibrate(): a dry normalize over the whole soak window plus that inventory, timing and RSS.
Never point this at a run group with a fault before the policy is frozen.
"""

from __future__ import annotations

import json
import resource
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from collect.layout import DataLayout
from collect.normalize import NormalizeInputs, check_snapshot, normalize
from collect.otlp import attributes, nanos
from collect.policy import Policy, load_policy
from collect.rawfile import scan_raw_file

_KNOWN = {
    "span": {"traceId", "spanId", "parentSpanId", "traceState", "flags", "name", "kind", "startTimeUnixNano",
             "endTimeUnixNano", "attributes", "droppedAttributesCount", "events", "droppedEventsCount", "links",
             "droppedLinksCount", "status"},
    "log": {"timeUnixNano", "observedTimeUnixNano", "severityNumber", "severityText", "body", "attributes",
            "droppedAttributesCount", "flags", "traceId", "spanId", "eventName"},
    "metric": {"name", "description", "unit", "gauge", "sum", "histogram", "exponentialHistogram", "summary", "metadata"},
    "point": {"attributes", "startTimeUnixNano", "timeUnixNano", "asInt", "asDouble", "exemplars", "flags", "count", "sum",
              "bucketCounts", "explicitBounds", "min", "max", "scale", "zeroCount", "positive", "negative",
              "zeroThreshold", "quantileValues"},
}


def _lines(path: Path):
    with path.open("rb") as f:
        for raw in f:
            if raw.strip():
                yield json.loads(raw)


def inventory(raw_dir: Path) -> dict:
    services = defaultdict(lambda: defaultdict(int))
    keys = defaultdict(lambda: defaultdict(set))
    scopes = defaultdict(lambda: {"items": 0, "metrics": set(), "resource_keys": set()})
    containers, events, unknown, enums = defaultdict(int), set(), defaultdict(int), defaultdict(set)

    def note_unknown(kind, item):
        for k in item.keys() - _KNOWN[kind]:
            unknown[f"{kind}.{k}"] += 1

    for doc in _lines(raw_dir / "traces.jsonl"):
        for rs in doc.get("resourceSpans") or []:
            r = attributes((rs.get("resource") or {}).get("attributes"))
            svc = str(r.get("service.name"))
            keys["resource"][svc] |= set(r)
            for ss in rs.get("scopeSpans") or []:
                for s in ss.get("spans") or []:
                    services["traces"][svc] += 1
                    keys["traces"][svc] |= {a["key"] for a in s.get("attributes") or []}
                    events.update(e.get("name", "") for e in s.get("events") or [])
                    enums["span_kind"].add(type(s.get("kind")).__name__)
                    note_unknown("span", s)
    for doc in _lines(raw_dir / "logs.jsonl"):
        for rl in doc.get("resourceLogs") or []:
            r = attributes((rl.get("resource") or {}).get("attributes"))
            svc = str(r.get("service.name"))
            keys["resource"][svc] |= set(r)
            for sl in rl.get("scopeLogs") or []:
                for rec in sl.get("logRecords") or []:
                    services["logs"][svc] += 1
                    keys["logs"][svc] |= {a["key"] for a in rec.get("attributes") or []}
                    if rec.get("eventName"):
                        events.add(rec["eventName"])
                    note_unknown("log", rec)
    for doc in _lines(raw_dir / "metrics.jsonl"):
        for rm in doc.get("resourceMetrics") or []:
            r = attributes((rm.get("resource") or {}).get("attributes"))
            svc = str(r.get("service.name"))
            for sm in rm.get("scopeMetrics") or []:
                scope = (sm.get("scope") or {}).get("name") or ""
                entry = scopes[scope]
                entry["resource_keys"] |= set(r)
                if "dockerstatsreceiver" in scope and "container.name" in r:
                    containers[str(r["container.name"])] += 1
                for m in sm.get("metrics") or []:
                    entry["metrics"].add(m.get("name", ""))
                    note_unknown("metric", m)
                    for kind in ("gauge", "sum", "histogram", "exponentialHistogram", "summary"):
                        for p in (m.get(kind) or {}).get("dataPoints") or []:
                            entry["items"] += 1
                            services["metrics"][svc] += 1
                            keys["metrics"][svc] |= {a["key"] for a in p.get("attributes") or []}
                            note_unknown("point", p)
    return {
        "services": {sig: dict(v) for sig, v in services.items()},
        "attribute_keys": {sig: {svc: sorted(v) for svc, v in d.items()} for sig, d in keys.items()},
        "metric_scopes": {s: {"items": e["items"], "metrics": sorted(e["metrics"]), "resource_keys": sorted(e["resource_keys"])}
                          for s, e in scopes.items()},
        "docker_container_names": dict(containers),
        "event_names": sorted(events),
        "unknown_fields": dict(unknown),
        "enum_encodings": {k: sorted(v) for k, v in enums.items()},
    }


def calibrate(soak_dir: Path, out_dir: Path, policy: Policy | None = None) -> dict:
    policy = policy or load_policy()
    raw_dir = soak_dir / "raw"
    scans = {sig: scan_raw_file(raw_dir / f"{sig}.jsonl", sig) for sig in ("traces", "metrics", "logs")}
    times = [t for s in scans.values() for t in (s["min_time"], s["max_time"]) if t]
    start = min(times)
    end_dt = datetime.fromisoformat(max(times)).astimezone(UTC)
    end = datetime.fromtimestamp(end_dt.timestamp() + 1, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    inputs = NormalizeInputs(raw_dir=raw_dir, raw_sha256={sig: s["sha256"] for sig, s in scans.items()},
                             raw_duplicates={sig: s["duplicates"] for sig, s in scans.items()},
                             window_host=(start, end), clock_offsets=[0.0, 0.0])  # soak: the window is the whole raw
    layout = DataLayout(out_dir)
    t0 = time.monotonic()
    report = normalize(inputs, policy, incident_dir=layout.incident_dir("INC-000"),
                       report_path=out_dir / "normalize_report.json", staging_dir=out_dir / "staging")
    seconds = time.monotonic() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    snapshot = layout.incident_dir("INC-000") / "normalized"
    result = {"soak": str(soak_dir), "policy": {"version": policy.raw["version"], "sha256": policy.sha256},
              "scans": {sig: {k: s[k] for k in ("bytes", "lines", "items", "duplicates", "min_time", "max_time")}
                        for sig, s in scans.items()},
              "inventory": inventory(raw_dir), "report": report, "check_problems": check_snapshot(snapshot, policy),
              "snapshot_bytes": sum(p.stat().st_size for p in snapshot.iterdir()), "seconds": round(seconds, 2),
              "max_rss_bytes": rss}
    (out_dir / "calibration.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result
