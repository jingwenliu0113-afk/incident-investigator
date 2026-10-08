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
from datetime import UTC, datetime, timedelta
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


MAX_SECONDS = 600  # F6: normalize of a ~40-minute soak
MAX_RSS_BYTES = 4 * 2**30


def freeze_check(report: dict, *, check_problems: list[str], unknown_fields: dict, raw_services: set[str],
                 kept_services: set[str], seconds: float, max_rss_bytes: int) -> dict:
    """Pre-registered criteria for freezing the policy on no-fault soak raw (decision 011, freeze criteria F1–F6)."""
    removed = report.get("removed", {})
    x7 = sum(sum(v.values()) for rule, v in removed.items() if rule.startswith("X7"))
    tokens = sum(report.get("tokens_deleted", {}).values())
    lost = sorted(raw_services - kept_services)
    crit = {
        "F1": {"pass": not check_problems, "detail": f"check_snapshot problems: {check_problems[:5] or 'none'}"},
        "F2": {"pass": not report.get("unknown_services") and not unknown_fields,
               "detail": f"unknown services {report.get('unknown_services') or 'none'}; unknown OTLP fields {unknown_fields or 'none'}"},
        "F3": {"pass": x7 == 0, "detail": f"{x7} items matched a fault-artifact template in raw without a fault"},
        "F4": {"pass": tokens == 0, "detail": f"{tokens} lexicon tokens deleted in raw without a fault"},
        "F5": {"pass": not lost, "detail": f"SUT services with raw telemetry but nothing kept: {lost or 'none'}"},
        "F6": {"pass": seconds <= MAX_SECONDS and max_rss_bytes <= MAX_RSS_BYTES,
               "detail": f"normalize {seconds:.1f} s (<= {MAX_SECONDS}), max RSS {max_rss_bytes / 2**30:.2f} GiB (<= 4)"},
    }
    crit["pass"] = all(c["pass"] for c in crit.values())
    return crit


def _require_soak(soak_dir: Path) -> None:
    """Only a soak directory: its report.json says so and raw/ holds the three files. Never a run group's raw."""
    try:
        report = json.loads((soak_dir / "report.json").read_text())
    except (OSError, ValueError):
        report = None
    if not isinstance(report, dict) or not {"env_lock_sha256", "criteria", "raw"} <= report.keys():
        raise ValueError(f"{soak_dir} is not a soak directory (no soak report.json): calibrate only reads no-fault soak raw")
    if missing := [s for s in ("traces", "metrics", "logs") if not (soak_dir / "raw" / f"{s}.jsonl").is_file()]:
        raise ValueError(f"{soak_dir}/raw has no {missing}")


def _kept_services(snapshot: Path) -> set[str]:
    out = set()
    for name in ("spans.jsonl", "logs.jsonl", "metric_series.jsonl"):
        with (snapshot / name).open("rb") as f:
            out.update(json.loads(line)["service"] for line in f)
    return out


def calibrate(soak_dir: Path, out_dir: Path, policy: Policy | None = None, code: dict | None = None) -> dict:
    """One calibration iteration into a fresh `out_dir` (earlier iterations stay as evidence).

    `code`: git state of the normalizer (taken from this checkout when not given); freezing needs a clean commit."""
    policy = policy or load_policy()
    if code is None:
        from collect.provenance import project_git_state
        from env.lock import PROJECT_DIR

        code = project_git_state(PROJECT_DIR)
    _require_soak(soak_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    raw_dir = soak_dir / "raw"
    scans = {sig: scan_raw_file(raw_dir / f"{sig}.jsonl", sig) for sig in ("traces", "metrics", "logs")}
    # parsed, not compared as strings: "...:40Z" (no fraction) sorts after "...:40.250000Z"; 1 s of padding on both sides
    # also keeps a metric point sitting exactly at the start inside the (start, end] point rule
    times = [datetime.fromisoformat(t).astimezone(UTC) for s in scans.values() for t in (s["min_time"], s["max_time"]) if t]
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    start, end = (min(times) - timedelta(seconds=1)).strftime(fmt), (max(times) + timedelta(seconds=1)).strftime(fmt)
    inputs = NormalizeInputs(raw_dir=raw_dir, raw_sha256={sig: s["sha256"] for sig, s in scans.items()},
                             raw_duplicates={sig: s["duplicates"] for sig, s in scans.items()},
                             window_host=(start, end), clock_offsets=[0.0, 0.0])  # soak: the window is the whole raw
    layout = DataLayout(out_dir)
    t0 = time.monotonic()
    report = normalize(inputs, policy, incident_dir=layout.incident_dir("INC-000"),
                       report_path=out_dir / "normalize_report.json", staging_dir=out_dir / "staging", code=code)
    seconds = time.monotonic() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    snapshot = layout.incident_dir("INC-000") / "normalized"
    inv = inventory(raw_dir)
    problems = check_snapshot(snapshot, policy)
    sut = set(policy.sut_services)
    receiver_services = {r["service"] for r in policy.raw["receivers"].values()
                         if "service" in r and any(r["scope_contains"] in scope for scope in inv["metric_scopes"])}
    raw_services = sut & ({svc for per in inv["services"].values() for svc in per} | set(inv["docker_container_names"])
                          | receiver_services)
    result = {"soak": str(soak_dir), "policy": {"version": policy.raw["version"], "sha256": policy.sha256}, "code": code,
              "scans": {sig: {k: s[k] for k in ("bytes", "lines", "items", "duplicates", "min_time", "max_time")}
                        for sig, s in scans.items()},
              "inventory": inv, "report": report, "check_problems": problems,
              "snapshot_bytes": sum(p.stat().st_size for p in snapshot.iterdir()), "seconds": round(seconds, 2),
              "max_rss_bytes": rss}
    result["freeze_check"] = freeze_check(report, check_problems=problems, unknown_fields=inv["unknown_fields"],
                                          raw_services=raw_services, kept_services=_kept_services(snapshot),
                                          seconds=seconds, max_rss_bytes=rss)
    (out_dir / "calibration.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def freeze(policy_path: Path, calibrations: list[Path]) -> dict:
    """Freeze a calibrating policy (decision 011): every calibration must be of this exact file and meet F1–F6.

    Writes status "frozen", the attribute-key inventory (union of the calibrations' attribute_keys) and where it came
    from. POLICY_SHA256 in collect/policy.py must then be re-pinned to the returned sha256 (tests/test_policy.py checks).
    """
    from env.lock import sha256_path

    current = sha256_path(policy_path)
    if not calibrations:
        raise ValueError("freezing needs at least one calibration")
    loaded = []
    for path in calibrations:
        cal = json.loads(Path(path).read_text())
        if cal["policy"]["sha256"] != current:
            raise ValueError(f"{path} was calibrated with {cal['policy']['sha256']}, not the current file {current}")
        if not cal.get("code") or cal["code"].get("commit") is None or cal["code"].get("dirty"):
            raise ValueError(f"{path} was not calibrated from a clean commit: {cal.get('code')}")
        if not cal["freeze_check"]["pass"]:
            failing = {k: v["detail"] for k, v in cal["freeze_check"].items() if k != "pass" and not v["pass"]}
            raise ValueError(f"{path} does not meet the freeze criteria: {failing}")
        loaded.append((path, cal))
    if len({cal["code"]["commit"] for _, cal in loaded}) != 1:
        raise ValueError("the calibrations must come from the same commit of the normalizer")
    raw = json.loads(policy_path.read_text())
    if raw.get("status") != "calibrating":
        raise ValueError(f"policy status is {raw.get('status')!r}: only a calibrating policy can be frozen (decision 011 §4)")
    inventory: dict[str, set[str]] = {}
    for _, cal in loaded:
        for key, names in cal["report"]["attribute_keys"].items():
            inventory.setdefault(key, set()).update(names)
    sources = [{"soak": cal["soak"], "calibration_sha256": sha256_path(path), "code_commit": cal["code"]["commit"]}
               for path, cal in loaded]
    raw.update(status="frozen", attribute_key_inventory={k: sorted(v) for k, v in sorted(inventory.items())},
               frozen_from=sources)
    policy_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return {"sha256": sha256_path(policy_path), "sources": sources}
