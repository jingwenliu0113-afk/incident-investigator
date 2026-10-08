"""raw OTLP JSON Lines -> canonical snapshot ctel/1 (decision 011).

GT-blind: the only inputs are the raw files, their recorded digests and duplicate counts, the incident
window (host clock) and the two host <-> VM clock offsets. No fault, flag or label is ever read here.
Everything removed is counted in a report that lives on the ground-truth side; the published snapshot
carries no trace of what was removed. Staging uses sqlite so ordering and the subtree closure stay
within bounded memory; output is byte-for-byte deterministic.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from collect.otlp import any_value, attributes, enum, log_key, nanos, point_key, series_key, span_key
from collect.policy import Policy

CANONICAL_SCHEMA = "ctel/1"
SNAPSHOT_VERSION = 1
DATA_FILES = ("resources.jsonl", "spans.jsonl", "logs.jsonl", "metric_series.jsonl", "metric_points.jsonl")
FILES = ("snapshot.json", *DATA_FILES)
MAX_CLOCK_DRIFT_S = 1.0  # decision 009 (amended)
_HEX = {32: re.compile(r"[0-9a-f]{32}"), 16: re.compile(r"[0-9a-f]{16}")}
_POINT_KINDS = {"gauge": "gauge", "sum": "sum", "histogram": "histogram",
                "exponentialHistogram": "exponential_histogram", "summary": "summary"}
_RUN_IDS = re.compile(rb"\b(?:RG|INC)-[0-9]{3,}\b")


class NormalizeError(RuntimeError):
    pass


@dataclass
class NormalizeInputs:
    raw_dir: Path
    raw_sha256: dict[str, str]  # per signal, from raw_export.json
    raw_duplicates: dict[str, int]  # per signal, from raw_export.json
    window_host: tuple[str, str]  # incident window, host clock (run.json)
    clock_offsets: list[float]  # VM - host, measured before normal_start and after end (run.json)


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _host_ns(ts: str) -> int:
    dt = datetime.fromisoformat(ts).astimezone(UTC)
    return int(dt.replace(microsecond=0).timestamp()) * 10**9 + dt.microsecond * 1000


def _minute(ns: int | None) -> str:
    return "untimed" if ns is None else datetime.fromtimestamp(ns // 10**9, UTC).strftime("%Y-%m-%dT%H:%M")


def _sha256_file(path: Path) -> str:
    from env.lock import sha256_path

    return sha256_path(path)


class _Run:
    """One normalize run: rule application, counting and id assignment."""

    def __init__(self, policy: Policy, key: bytes):
        self.policy, self.key = policy, key
        self.sut = set(policy.sut_services)
        self.removed: dict = defaultdict(lambda: defaultdict(int))
        self.detail: dict = defaultdict(lambda: defaultdict(lambda: {"by_service": defaultdict(int), "by_minute": defaultdict(int)}))
        self.tokens: dict = defaultdict(int)
        self.fixes: dict = defaultdict(int)
        self.unknown_services: dict = defaultdict(int)
        self.resources: dict[str, str] = {}
        self._rid_by_raw: dict[str, str] = {}
        self.signal = ""

    # ------------------------------------------------------------ counting
    def drop(self, rule: str, service: str | None, ns: int | None, n: int = 1) -> None:
        self.removed[rule][self.signal] += n
        d = self.detail[rule][self.signal]
        d["by_service"][service or "?"] += n
        d["by_minute"][_minute(ns)] += n

    def rid(self, kind: str, key: tuple) -> str:
        h = hashlib.blake2b(repr(key).encode(), digest_size=8, key=self.key, person=f"ctel1-{kind}".encode())
        return h.hexdigest()

    # ------------------------------------------------------------ transforms
    def scrub(self, value):
        """X8 on every visible string: values, map keys and text inside bytes values."""
        if isinstance(value, str):
            out, n = self.policy.scrub(value)
            self.tokens[self.signal] += n
            return out
        if isinstance(value, list):
            return [self.scrub(v) for v in value]
        if isinstance(value, dict) and "$bytes" in value:
            return self._scrub_bytes(value)
        if isinstance(value, dict) and "$double" not in value:
            return self._scrub_map(value)
        return value

    def _scrub_map(self, value: dict) -> dict:
        out = {}
        for k, v in value.items():
            k2 = self.scrub(k)
            if not k2 or k2 in out:  # the key was only a token, or scrubbing made two keys equal
                self.removed["X8_key"][self.signal] += 1
                continue
            out[k2] = self.scrub(v)
        return out

    def _scrub_bytes(self, value: dict) -> dict:
        try:
            text = base64.b64decode(value["$bytes"], validate=True).decode("utf-8")
        except ValueError:  # not base64 or not text: opaque, and check_snapshot still greps it decoded
            return value
        out, n = self.policy.scrub(text)
        if not n:
            return value
        self.tokens[self.signal] += n
        return {"$bytes": base64.b64encode(out.encode()).decode()}

    def attrs(self, kvs) -> dict:
        priv = self.policy.raw["privacy"]
        out = {}
        for k, v in attributes(kvs, self.fixes).items():
            if self.policy.is_flag_key(k):
                self.removed["X5_attribute"][self.signal] += 1
                continue
            if k in priv["delete_keys"] or any(re.search(p, k) for p in priv["delete_key_patterns"]):
                continue
            if k in priv["hash_keys"]:
                out[priv["hash_keys"][k]] = hashlib.sha256(str(v).encode()).hexdigest()
                continue
            if k in priv["mask_last4_keys"] and isinstance(v, str):
                out[k] = "****-****-****-" + "".join(c for c in v if c.isdigit())[-4:]
                continue
            k2 = self.scrub(k)
            if not k2 or k2 in out:
                self.removed["X8_key"][self.signal] += 1
                continue
            out[k2] = self.scrub(v)
        return out

    def resource_id(self, resource: dict) -> str:
        """Canonical resource of a KEPT record, stored once (built lazily so dropped items are never transformed)."""
        raw = dumps(resource)
        if raw not in self._rid_by_raw:
            signal, self.signal = self.signal, "resources"
            record = {"attributes": self.attrs(resource.get("attributes")),
                      "dropped_attributes_count": int(resource.get("droppedAttributesCount", 0)), "schema_url": None}
            self.signal = signal
            rid = "r-" + hashlib.blake2b(dumps(record).encode(), digest_size=8).hexdigest()
            self.resources.setdefault(rid, dumps({**record, "resource_id": rid}))
            self._rid_by_raw[raw] = rid
        return self._rid_by_raw[raw]

    def scope(self, scope: dict) -> dict:
        return {"name": self.scrub(scope.get("name") or "") or None, "version": self.scrub(scope.get("version") or "") or None,
                "attributes": self.attrs(scope.get("attributes"))}

    def service(self, raw_attrs: dict, scope_name: str | None, ns: int | None) -> str | None:
        """Attribution (N4) with X1 / X2; None means the item was dropped and counted."""
        for name, r in self.policy.raw["receivers"].items():
            if r["scope_contains"] in (scope_name or ""):
                if r.get("drop"):
                    self.drop("X2", name, ns)
                    return None
                svc = r.get("service") or str(raw_attrs.get(r["service_from"], "")).lstrip("/")
                break
        else:
            svc = raw_attrs.get("service.name")
        if svc not in self.sut:
            if svc not in self.policy.raw["excluded_services"]:
                self.unknown_services[str(svc)] += 1
            self.drop("X1", str(svc), ns)
            return None
        return svc


def _check_inputs(inputs: NormalizeInputs, policy: Policy, incident_dir: Path) -> tuple[int, int]:
    if (incident_dir / "normalized").exists():
        raise NormalizeError(f"{incident_dir / 'normalized'} already exists (snapshots are write-once)")
    o0, o1 = inputs.clock_offsets
    if abs(o1 - o0) > MAX_CLOCK_DRIFT_S:
        raise NormalizeError(f"clock drift {o1 - o0:+.3f} s during the run exceeds {MAX_CLOCK_DRIFT_S} s")
    for sig in ("traces", "metrics", "logs"):
        path = inputs.raw_dir / f"{sig}.jsonl"
        if not path.is_file() or _sha256_file(path) != inputs.raw_sha256[sig]:
            raise NormalizeError(f"{path} is missing or its sha256 differs from the raw export record")
    ws = _host_ns(inputs.window_host[0]) + round(o0 * 1e9)
    we = _host_ns(inputs.window_host[1]) + round(o1 * 1e9)
    if we <= ws:
        raise NormalizeError("empty window")
    return ws, we


def _lines(path: Path):
    with path.open("rb") as f:
        for raw in f:
            if raw.strip():
                yield json.loads(raw)


def normalize(inputs: NormalizeInputs, policy: Policy, *, incident_dir: Path, report_path: Path,
              staging_dir: Path) -> dict:
    ws, we = _check_inputs(inputs, policy, incident_dir)
    key = hashlib.blake2b(dumps(sorted(inputs.raw_sha256.values())).encode(), digest_size=32).digest()
    run = _Run(policy, key)
    stats = {sig: defaultdict(int) for sig in ("traces", "metrics", "logs")}
    staging_dir.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(staging_dir / "stage.sqlite")
    db.executescript("""
        CREATE TABLE spans(trace_id TEXT, span_id TEXT, parent TEXT, start INTEGER, in_window INTEGER,
                           self_drop TEXT, root_drop TEXT, service TEXT, raw TEXT, rid TEXT, record TEXT,
                           PRIMARY KEY(trace_id, span_id));
        CREATE TABLE logs(id TEXT PRIMARY KEY, t INTEGER, rid TEXT, record TEXT);
        CREATE TABLE series(id TEXT PRIMARY KEY, service TEXT, metric TEXT, rid TEXT, record TEXT);
        CREATE TABLE points(id TEXT PRIMARY KEY, series_id TEXT, t INTEGER, record TEXT);
    """)

    def seen(sig: str, k: tuple, content: str | None, memo: dict) -> bool:
        stats[sig]["raw_items"] += 1
        digest = hashlib.blake2b(repr(k).encode(), digest_size=16).digest()
        if digest in memo:
            stats[sig]["duplicates"] += 1
            if content is not None and memo[digest] != hashlib.blake2b(content.encode(), digest_size=8).digest():
                stats[sig]["conflicts"] += 1
            return True
        memo[digest] = hashlib.blake2b(content.encode(), digest_size=8).digest() if content is not None else b""
        return False

    # ---------------------------------------------------------------- traces
    run.signal, memo = "traces", {}
    for doc in _lines(inputs.raw_dir / "traces.jsonl"):
        for rs in doc.get("resourceSpans") or []:
            resource = rs.get("resource") or {}
            raw_attrs = attributes(resource.get("attributes"))
            for ss in rs.get("scopeSpans") or []:
                scope = ss.get("scope") or {}
                for s in ss.get("spans") or []:
                    if seen("traces", span_key(s), dumps(s), memo):
                        continue
                    tid, sid = str(s.get("traceId", "")).lower(), str(s.get("spanId", "")).lower()
                    parent = str(s.get("parentSpanId") or "").lower() or None
                    if not (_HEX[32].fullmatch(tid) and _HEX[16].fullmatch(sid)) or set(tid) == {"0"} or set(sid) == {"0"}:
                        stats["traces"]["invalid"] += 1
                        continue
                    start = nanos(s.get("startTimeUnixNano"))
                    in_window = start is not None and ws <= start < we
                    svc = raw_attrs.get("service.name")
                    self_drop = None if svc in run.sut else "X1"
                    span_attrs = attributes(s.get("attributes"))
                    root = "X6" if policy.scope_denied(scope.get("name")) else "X4" if policy.control_plane(span_attrs) else None
                    raw = dumps({"span": s, "resource": resource, "scope": scope}) \
                        if self_drop is None and root is None and in_window else None
                    db.execute("INSERT INTO spans VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL)",
                               (tid, sid, parent, start, int(in_window), self_drop, root, svc, raw))
    closure = dict(((t, s), rule) for t, s, rule in db.execute("""
        WITH RECURSIVE dropped(trace_id, span_id, rule) AS (
            SELECT trace_id, span_id, root_drop FROM spans WHERE root_drop IS NOT NULL
            UNION
            SELECT c.trace_id, c.span_id, d.rule FROM spans c JOIN dropped d ON c.trace_id = d.trace_id AND c.parent = d.span_id)
        SELECT trace_id, span_id, MIN(rule) FROM dropped GROUP BY trace_id, span_id"""))
    for tid, sid, start, in_window, self_drop, svc in db.execute(
            "SELECT trace_id, span_id, start, in_window, self_drop, service FROM spans").fetchall():
        if start is None:
            stats["traces"]["untimed"] += 1
        elif not in_window:
            stats["traces"]["out_of_window"] += 1
        elif self_drop:
            if svc not in policy.raw["excluded_services"]:
                run.unknown_services[str(svc)] += 1
            run.drop(self_drop, svc, start)
        elif (tid, sid) in closure:
            run.drop(closure[(tid, sid)], svc, start)
    for tid, sid, parent, start, svc, raw in db.execute(
            "SELECT trace_id, span_id, parent, start, service, raw FROM spans WHERE raw IS NOT NULL").fetchall():
        if (tid, sid) in closure:
            continue
        item = json.loads(raw)
        rid = run.resource_id(item["resource"])
        record = dumps(_span_record(run, item["span"], tid, sid, parent, start, rid, item["scope"], svc))
        db.execute("UPDATE spans SET rid = ?, record = ? WHERE trace_id = ? AND span_id = ?", (rid, record, tid, sid))

    # ---------------------------------------------------------------- logs
    run.signal, memo = "logs", {}
    for doc in _lines(inputs.raw_dir / "logs.jsonl"):
        for rl in doc.get("resourceLogs") or []:
            resource = rl.get("resource") or {}
            raw_attrs = attributes(resource.get("attributes"))
            for sl in rl.get("scopeLogs") or []:
                scope = sl.get("scope") or {}
                for r in sl.get("logRecords") or []:
                    k = log_key(resource, r)
                    if seen("logs", k, None, memo):
                        continue
                    t = nanos(r.get("timeUnixNano")) or nanos(r.get("observedTimeUnixNano"))
                    if t is None:
                        stats["logs"]["untimed"] += 1
                        continue
                    if not ws <= t < we:
                        stats["logs"]["out_of_window"] += 1
                        continue
                    svc = run.service(raw_attrs, None, t)
                    if svc is None:
                        continue
                    body = any_value(r.get("body"), run.fixes)
                    tid = str(r.get("traceId") or "").lower() or None
                    sid = str(r.get("spanId") or "").lower() or None
                    rule = ("X6" if policy.scope_denied(scope.get("name"))
                            else "X4" if policy.control_plane(attributes(r.get("attributes"))) or (tid, sid) in closure
                            else "X5" if r.get("eventName") and policy.is_flag_key(r["eventName"])
                            else "X7" if isinstance(body, str) and policy.is_fault_artifact(body)
                            else None)
                    if rule:
                        run.drop(rule, svc, t)
                        continue
                    rid = run.resource_id(resource)
                    record = {"id": "l-" + run.rid("log", k), "time_unix_nano": nanos(r.get("timeUnixNano")),
                              "observed_time_unix_nano": nanos(r.get("observedTimeUnixNano")),
                              "severity_number": int(r.get("severityNumber") or 0) if str(r.get("severityNumber", "0")).isdigit() else 0,
                              "severity_text": run.scrub(r.get("severityText") or "") or None, "body": run.scrub(body),
                              "event_name": run.scrub(r["eventName"]) if r.get("eventName") else None,
                              "attributes": run.attrs(r.get("attributes")), "trace_id": tid, "span_id": sid,
                              "flags": int(r.get("flags") or 0), "dropped_attributes_count": int(r.get("droppedAttributesCount", 0)),
                              "resource_id": rid, "scope": run.scope(scope), "service": svc}
                    db.execute("INSERT INTO logs VALUES (?,?,?,?)", (record["id"], t, rid, dumps(record)))

    # ---------------------------------------------------------------- metrics
    run.signal, memo = "metrics", {}
    for doc in _lines(inputs.raw_dir / "metrics.jsonl"):
        for rm in doc.get("resourceMetrics") or []:
            resource = rm.get("resource") or {}
            raw_attrs = attributes(resource.get("attributes"))
            for sm in rm.get("scopeMetrics") or []:
                scope = sm.get("scope") or {}
                for m in sm.get("metrics") or []:
                    name = m.get("name", "")
                    for raw_kind, kind in _POINT_KINDS.items():
                        body = m.get(raw_kind)
                        if body is None:
                            continue
                        for p in body.get("dataPoints") or []:
                            k = point_key(resource, scope, name, p)
                            if seen("metrics", k, dumps(p), memo):
                                continue
                            t = nanos(p.get("timeUnixNano"))
                            if t is None:
                                stats["metrics"]["untimed"] += 1
                                continue
                            if not ws < t <= we:
                                stats["metrics"]["out_of_window"] += 1
                                continue
                            svc = run.service(raw_attrs, scope.get("name"), t)
                            if svc is None:
                                continue
                            p_attrs = attributes(p.get("attributes"))
                            rule = ("X6" if policy.scope_denied(scope.get("name"))
                                    else "X3" if any(name.startswith(x) for x in policy.raw["drop_metric_prefixes"])
                                    else "X5" if policy.is_flag_key(name) or policy.lexicon_hit(name)
                                    or any(policy.is_flag_key(a) for a in p_attrs)
                                    else "X4" if policy.control_plane(p_attrs)
                                    else "X10" if int(p.get("flags") or 0) & 1
                                    else None)
                            if rule:
                                run.drop(rule, svc, t)
                                continue
                            sk = series_key(resource, scope, name, p)
                            series_id = "m-" + run.rid("series", sk)
                            if not db.execute("SELECT 1 FROM series WHERE id = ?", (series_id,)).fetchone():
                                rid = run.resource_id(resource)
                                series = {"id": series_id, "resource_id": rid, "scope": run.scope(scope), "service": svc,
                                          "metric": name, "kind": kind, "unit": run.scrub(m.get("unit") or "") or None,
                                          "description": run.scrub(m.get("description") or "") or None,
                                          "temporality": enum("temporality", body.get("aggregationTemporality")) if kind in ("sum", "histogram", "exponential_histogram") else None,
                                          "monotonic": bool(body.get("isMonotonic")) if kind == "sum" else None,
                                          "attributes": run.attrs(p.get("attributes"))}
                                db.execute("INSERT INTO series VALUES (?,?,?,?,?)", (series_id, svc, name, rid, dumps(series)))
                            point = {"id": "p-" + run.rid("point", k), "series_id": series_id, "service": svc, "metric": name,
                                     "kind": kind, "start_time_unix_nano": nanos(p.get("startTimeUnixNano")),
                                     "time_unix_nano": t, "flags": int(p.get("flags") or 0), **_point_values(kind, p)}
                            db.execute("INSERT INTO points VALUES (?,?,?,?)", (point["id"], series_id, t, dumps(point)))

    for sig in ("traces", "metrics", "logs"):
        if stats[sig]["duplicates"] != inputs.raw_duplicates[sig]:
            raise NormalizeError(f"{sig}: {stats[sig]['duplicates']} duplicates removed, raw export recorded "
                                 f"{inputs.raw_duplicates[sig]} (dedupe keys disagree)")

    # ---------------------------------------------------------------- write, check, publish
    tmp = incident_dir / f"normalized.tmp-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    firsts = {pid for (pid,) in db.execute(
        "SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY series_id ORDER BY t, id) AS rn FROM points) WHERE rn = 1")}
    used_rids: set[str] = set()
    counts = {}
    queries = {
        "spans.jsonl": "SELECT rid, record FROM spans WHERE record IS NOT NULL ORDER BY start, 's-' || span_id",
        "logs.jsonl": "SELECT rid, record FROM logs ORDER BY t, id",
        "metric_series.jsonl": "SELECT rid, record FROM series ORDER BY service, metric, id",
    }
    for name, sql in queries.items():
        with (tmp / name).open("w") as f:
            n = 0
            for rid, record in db.execute(sql):
                used_rids.add(rid)
                f.write(record + "\n")
                n += 1
        counts[name] = n
    with (tmp / "metric_points.jsonl").open("w") as f:
        n = 0
        for pid, record in db.execute("SELECT id, record FROM points ORDER BY t, id"):
            point = json.loads(record)
            point["first_in_window"] = pid in firsts
            f.write(dumps(point) + "\n")
            n += 1
        counts["metric_points.jsonl"] = n
    with (tmp / "resources.jsonl").open("w") as f:
        for rid in sorted(used_rids):
            f.write(run.resources[rid] + "\n")
        counts["resources.jsonl"] = len(used_rids)
    stats["traces"]["kept"], stats["logs"]["kept"] = counts["spans.jsonl"], counts["logs.jsonl"]
    stats["metrics"]["kept"] = counts["metric_points.jsonl"]
    db.close()

    files = [{"path": name, "records": counts[name], "bytes": (tmp / name).stat().st_size,
              "sha256": _sha256_file(tmp / name)} for name in DATA_FILES]
    content = hashlib.sha256("".join(f"{f['path']}\0{f['sha256']}\n" for f in files).encode()).hexdigest()
    snapshot = {"snapshot_version": SNAPSHOT_VERSION, "canonical_schema": CANONICAL_SCHEMA,
                "policy": {"version": policy.raw["version"], "sha256": policy.sha256},
                "window": {"start_ns": ws, "end_ns": we}, "services": sorted(policy.sut_services),
                "files": files, "content_sha256": "sha256:" + content}
    (tmp / "snapshot.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    if problems := check_snapshot(tmp, policy):
        raise NormalizeError(f"snapshot failed its checks (left in {tmp}): {problems[:10]}")
    for p in tmp.iterdir():
        p.chmod(0o444)
    os.replace(tmp, incident_dir / "normalized")
    shutil.rmtree(staging_dir)

    report = {
        "report_version": 1,
        "policy": {"version": policy.raw["version"], "sha256": policy.sha256},
        "raw_sha256": inputs.raw_sha256,
        "window": {"host": list(inputs.window_host), "clock_offsets": inputs.clock_offsets, "data_ns": [ws, we]},
        "signals": {sig: dict(v) for sig, v in stats.items()},
        "removed": {rule: dict(v) for rule, v in run.removed.items()},
        "removed_detail": {rule: {sig: {"by_service": dict(d["by_service"]), "by_minute": dict(d["by_minute"])}
                                  for sig, d in v.items()} for rule, v in run.detail.items()},
        "tokens_deleted": dict(run.tokens),
        "value_fixes": dict(run.fixes),
        "unknown_services": dict(run.unknown_services),
        "outputs": files,
        "content_sha256": snapshot["content_sha256"],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _span_record(run: _Run, s: dict, tid: str, sid: str, parent: str | None, start: int, rid: str, scope: dict,
                 svc: str) -> dict:
    status = s.get("status") or {}
    events = []
    for e in s.get("events") or []:
        name = e.get("name", "")
        if run.policy.is_flag_key(name):
            run.removed["X5_event"]["traces"] += 1
            continue
        if run.policy.is_fault_artifact(name):
            run.removed["X7_event"]["traces"] += 1
            continue
        events.append({"time_unix_nano": nanos(e.get("timeUnixNano")), "name": run.scrub(name),
                       "attributes": run.attrs(e.get("attributes")),
                       "dropped_attributes_count": int(e.get("droppedAttributesCount", 0))})
    links = [{"trace_id": str(link.get("traceId", "")).lower(), "span_id": str(link.get("spanId", "")).lower(),
              "trace_state": run.scrub(link.get("traceState") or "") or None, "flags": int(link.get("flags") or 0),
              "attributes": run.attrs(link.get("attributes")),
              "dropped_attributes_count": int(link.get("droppedAttributesCount", 0))} for link in s.get("links") or []]
    message = run.scrub(status.get("message") or "") or None
    return {"id": "s-" + sid, "trace_id": tid, "span_id": sid, "parent_span_id": parent,
            "trace_state": run.scrub(s.get("traceState") or "") or None, "flags": int(s.get("flags") or 0), "name": run.scrub(s.get("name", "")),
            "kind": enum("span_kind", s.get("kind")), "start_time_unix_nano": start,
            "end_time_unix_nano": nanos(s.get("endTimeUnixNano")), "status_code": enum("status_code", status.get("code")),
            "status_message": message, "attributes": run.attrs(s.get("attributes")), "events": events, "links": links,
            "dropped_attributes_count": int(s.get("droppedAttributesCount", 0)),
            "dropped_events_count": int(s.get("droppedEventsCount", 0)),
            "dropped_links_count": int(s.get("droppedLinksCount", 0)),
            "resource_id": rid, "scope": run.scope(scope), "service": svc}


def _dbl(d):
    """OTLP JSON writes NaN / ±Infinity as strings; the canonical form is {"$double": ...} (decision 011 §2)."""
    return {"$double": d} if isinstance(d, str) else d


def _point_values(kind: str, p: dict) -> dict:
    # proto3 doubles that are not `optional` are omitted by OTLP JSON when 0: .get(key, 0), never `or` (keeps NaN strings)
    if kind in ("gauge", "sum"):
        if "asInt" in p:
            return {"value": int(p["asInt"])}
        return {"value": _dbl(p.get("asDouble", 0))}
    if kind == "histogram":
        return {"count": int(p.get("count") or 0), "sum": _dbl(p.get("sum")), "min": _dbl(p.get("min")),
                "max": _dbl(p.get("max")), "bucket_counts": [int(c) for c in p.get("bucketCounts") or []],
                "explicit_bounds": [_dbl(b) for b in p.get("explicitBounds") or []]}
    if kind == "exponential_histogram":
        def buckets(b):
            return {"offset": int((b or {}).get("offset") or 0), "bucket_counts": [int(c) for c in (b or {}).get("bucketCounts") or []]}
        return {"count": int(p.get("count") or 0), "sum": _dbl(p.get("sum")), "min": _dbl(p.get("min")),
                "max": _dbl(p.get("max")), "scale": int(p.get("scale") or 0), "zero_count": int(p.get("zeroCount") or 0),
                "zero_threshold": _dbl(p.get("zeroThreshold", 0)), "positive": buckets(p.get("positive")),
                "negative": buckets(p.get("negative"))}
    return {"count": int(p.get("count") or 0), "sum": _dbl(p.get("sum", 0)),
            "quantile_values": [{"quantile": _dbl(q.get("quantile", 0)), "value": _dbl(q.get("value", 0))}
                                for q in p.get("quantileValues") or []]}


# -------------------------------------------------------------------- fail-closed checks

_KINDS = {"resources.jsonl": "resource", "spans.jsonl": "span", "logs.jsonl": "log",
          "metric_series.jsonl": "metric_series", "metric_points.jsonl": "metric_point"}


def _validators() -> dict:
    from jsonschema import Draft202012Validator

    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas/canonical_telemetry.schema.json").read_text())
    return {name: Draft202012Validator({**schema, "$ref": f"#/$defs/{kind}"}) for name, kind in _KINDS.items()}


def _visible(value):
    """Every string a reader of the record sees once the JSON is decoded: keys, values, and text inside bytes values."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _visible(v)
    elif isinstance(value, dict):
        if set(value) == {"$bytes"}:
            try:
                yield base64.b64decode(value["$bytes"], validate=True).decode("utf-8", "replace")
            except ValueError:
                yield value["$bytes"]
            return
        for k, v in value.items():
            yield k
            yield from _visible(v)


def check_snapshot(snapshot_dir: Path, policy: Policy) -> list[str]:
    """decision 011 §3: everything a published snapshot must satisfy; any problem blocks publishing."""
    problems = []
    validators = _validators()
    names = sorted(p.name for p in snapshot_dir.iterdir())
    if extra := sorted(set(names) - set(FILES)):
        problems.append(f"unexpected files: {extra}")
    if missing := sorted(set(FILES) - set(names)):
        return problems + [f"missing files: {missing}"]
    snap = json.loads((snapshot_dir / "snapshot.json").read_text())
    excluded = {s.encode() for s in policy.raw["excluded_services"]}
    ids, series_ids, rids, ref_rids, ref_series = set(), set(), set(), set(), set()
    listed = {f["path"]: f for f in snap.get("files", [])}
    for name in DATA_FILES:
        path = snapshot_dir / name
        data = path.read_bytes()
        if policy.lexicon_hit(data.decode("utf-8", "replace")):
            problems.append(f"{name}: lexicon token present")
        if _RUN_IDS.search(data):
            problems.append(f"{name}: run group / incident id present")
        entry = listed.get(name)
        if entry is None or entry["sha256"] != _sha256_file(path) or entry["bytes"] != len(data):
            problems.append(f"{name}: not as listed in snapshot.json")
        n = 0
        for line in data.splitlines():
            n += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"{name}: line {n} is not JSON")
                continue
            if not isinstance(rec, dict) or ("resource_id" if name == "resources.jsonl" else "id") not in rec:
                problems.append(f"{name}: line {n} is not a {name.removesuffix('.jsonl')} record")
                continue
            # the file-wide grep above reads escaped JSON: an escape (\\n, \\u00e9) before a token hides its boundary, and
            # base64 hides it completely, so those lines are also checked decoded
            if (b"\\" in line or b"$bytes" in line) and any(policy.lexicon_hit(v) for v in _visible(rec)):
                problems.append(f"{name}: line {n}: lexicon token present")
            for err in validators[name].iter_errors(rec):
                problems.append(f"{name}: line {n}: schema: {'/'.join(map(str, err.absolute_path)) or '<root>'}: {err.message[:120]}")
                break
            if name == "resources.jsonl":
                rids.add(rec["resource_id"])
                continue
            if rec.get("service") not in policy.sut_services:
                problems.append(f"{name}: service {rec.get('service')!r} is not a SUT service")
            if rec["id"] in ids:
                problems.append(f"{name}: duplicate id {rec['id']}")
            ids.add(rec["id"])
            if "resource_id" in rec:
                ref_rids.add(rec["resource_id"])
            if name == "metric_series.jsonl":
                series_ids.add(rec["id"])
            if name == "metric_points.jsonl":
                ref_series.add(rec["series_id"])
        if entry is not None and entry["records"] != n:
            problems.append(f"{name}: {n} records, snapshot.json says {entry['records']}")
        for svc in excluded:
            if b'"service":"' + svc + b'"' in data:
                problems.append(f"{name}: excluded service {svc.decode()} present")
    if missing_r := ref_rids - rids:
        problems.append(f"{len(missing_r)} resource ids referenced but not present")
    if missing_s := ref_series - series_ids:
        problems.append(f"{len(missing_s)} series ids referenced but not present")
    for k in ("incident", "run_group", "raw", "clock_offset", "offsets"):
        if k in snap:
            problems.append(f"snapshot.json carries {k!r}")
    return problems
