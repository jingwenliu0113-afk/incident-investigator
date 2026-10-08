"""Agent tools v1 (decisions 011 §5, 019): data access over one frozen snapshot, metered, with an exposure log.

The index is built only from records served by collect.snapshot (open_snapshot verified them) and cached by the
snapshot's content digest. Every tool answers in render-v1 lines, in time order; text filters are case-insensitive
substrings (ASCII case folding) of those lines. There is no ranking of anything: which services and records matter is the agent's call.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from collect.derive import container_minute_stats, service_minute_stats
from collect.snapshot import proxy_tokens, render_v1

INDEX_VERSION = 2  # 2: LIKE on the line itself, no lower-case copy
MAX_LIMIT = 50
DEFAULT_LIMIT = 20
MAX_SECONDS = 10**7  # time arguments are seconds since the window start; larger values are a unit mistake
MAX_OFFSET = 10**7
MAX_TEXT = 1000
CUT_NOTE = "(output cut: token budget reached)"
MiB = 2**20

_T = {"type": "number", "description": "seconds since the start of the time window"}
_PAGE = {"limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "description": f"at most {MAX_LIMIT} (default {DEFAULT_LIMIT})"},
         "offset": {"type": "integer", "minimum": 0, "description": "skip this many matches (paging)"}}
_TEXT = {"type": "string", "description": "case-insensitive substring of the record as shown"}


def _spec(name: str, description: str, properties: dict, required: tuple = ()) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}}


TOOL_SPECS = [
    _spec("list_services", "The services in the snapshot and how many spans, logs and metric series each has.", {}),
    _spec("search_spans", "Spans in time order, optionally filtered by service, status, minimum duration, time range [t0, t1) and text.",
          {"service": {"type": "string"}, "text": _TEXT, "status": {"enum": ["error", "ok", "unset"]},
           "min_duration_ms": {"type": "number"}, "t0": _T, "t1": _T, **_PAGE}),
    _spec("search_logs", "Log records in time order, optionally filtered by service, minimum severity number (WARN = 13, "
                         "ERROR = 17), time range [t0, t1) and text.",
          {"service": {"type": "string"}, "text": _TEXT, "min_severity": {"type": "integer"}, "t0": _T, "t1": _T, **_PAGE}),
    _spec("get_trace", "All spans of one trace, in time order.", {"trace_id": {"type": "string"}, **_PAGE}, ("trace_id",)),
    _spec("list_series", "Metric series (one line each: service, metric name, kind, unit, attributes), optionally filtered by "
                         "service and text.", {"service": {"type": "string"}, "text": _TEXT, **_PAGE}),
    _spec("get_points", "Points of one metric series in time order, optionally in a time range [t0, t1). Cumulative sums are "
                        "running totals.", {"series_id": {"type": "string"}, "t0": _T, "t1": _T, **_PAGE}, ("series_id",)),
    _spec("service_minute_stats", "For one service, per minute: spans, error spans, p95 duration of server spans (ms), log "
                                  "records at WARN or above, CPU cores used and memory (MiB) of its container.",
          {"service": {"type": "string"}, "t0": _T, "t1": _T}, ("service",)),
]
_SPECS = {t["name"]: t for t in TOOL_SPECS}

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE spans (id TEXT PRIMARY KEY, trace_id TEXT, service TEXT, status TEXT, t INTEGER, dur_ms REAL, line TEXT);
CREATE TABLE logs (id TEXT PRIMARY KEY, service TEXT, t INTEGER, severity INTEGER, line TEXT);
CREATE TABLE series (id TEXT PRIMARY KEY, service TEXT, line TEXT);
CREATE TABLE points (id TEXT PRIMARY KEY, series_id TEXT, t INTEGER, line TEXT);
CREATE TABLE minutes (service TEXT, minute INTEGER, spans INTEGER, errors INTEGER, p95_ms REAL, warn_logs INTEGER,
                      cpu REAL, memory REAL, PRIMARY KEY (service, minute));
CREATE INDEX spans_t ON spans (t, id); CREATE INDEX spans_trace ON spans (trace_id);
CREATE INDEX logs_t ON logs (t, id); CREATE INDEX points_s ON points (series_id, t);
"""


def build_index(snapshot, cache_root: Path) -> Path:
    """The cached index of `snapshot` (rebuilt when missing or built from other content or another index version)."""
    digest = snapshot.meta["content_sha256"].removeprefix("sha256:")
    path = Path(cache_root) / digest / "index.sqlite"
    if path.exists():
        with sqlite3.connect(path) as db:
            meta = dict(db.execute("SELECT key, value FROM meta"))
        if meta.get("content_sha256") == snapshot.meta["content_sha256"] and meta.get("index_version") == str(INDEX_VERSION):
            return path
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    start = snapshot.window["start_ns"]
    with sqlite3.connect(tmp) as db:
        db.executescript(_SCHEMA)
        for s in snapshot.spans():
            line = render_v1(s, start)
            end = s.get("end_time_unix_nano")
            db.execute("INSERT INTO spans VALUES (?,?,?,?,?,?,?)",
                       (s["id"], s["trace_id"], s["service"], s.get("status_code"), s["start_time_unix_nano"],
                        None if end is None else (end - s["start_time_unix_nano"]) / 1e6, line))
        for r in snapshot.logs():
            line = render_v1(r, start)
            t = r["time_unix_nano"] if r.get("time_unix_nano") is not None else r.get("observed_time_unix_nano")
            db.execute("INSERT INTO logs VALUES (?,?,?,?,?)", (r["id"], r["service"], t, r.get("severity_number") or 0, line))
        for m in snapshot.series():
            db.execute("INSERT INTO series VALUES (?,?,?)", (m["id"], m.get("service"), render_v1(m, start)))
        for p in snapshot.points():
            db.execute("INSERT INTO points VALUES (?,?,?,?)", (p["id"], p["series_id"], p["time_unix_nano"], render_v1(p, start)))
        spans, containers = service_minute_stats(snapshot)["services"], container_minute_stats(snapshot)["services"]
        for svc in set(spans) | set(containers):
            s, c = spans.get(svc, {}), containers.get(svc, {})
            for minute in sorted(set(s) | set(c)):
                a, b = s.get(minute, {}), c.get(minute, {})
                db.execute("INSERT INTO minutes VALUES (?,?,?,?,?,?,?,?)",
                           (svc, minute, a.get("spans", 0), a.get("error_spans", 0), a.get("p95_server_ms"),
                            a.get("warn_logs", 0), b.get("cpu"), b.get("memory")))
        db.executemany("INSERT INTO meta VALUES (?,?)", [("content_sha256", snapshot.meta["content_sha256"]),
                                                          ("index_version", str(INDEX_VERSION))])
    tmp.replace(path)
    return path


class ToolError(ValueError):
    pass


def _cut(text: str, remaining: int) -> tuple[str, int]:
    """`text` if it fits in `remaining` proxy tokens, else its leading lines plus CUT_NOTE; and how many lines were kept."""
    lines = text.split("\n")
    if proxy_tokens(text) <= remaining:
        return text, len(lines)
    kept: list[str] = []
    for line in lines:
        if proxy_tokens("\n".join([*kept, line, CUT_NOTE])) > remaining:
            break
        kept.append(line)
    return ("\n".join([*kept, CUT_NOTE]) if kept else "(cut)"), len(kept)


def _rel_minute(minute: int) -> str:
    return f"+{minute:03d}:00"


def _num(x, fmt: str = ".3f") -> str:
    return "-" if x is None else format(x, fmt)


class ToolSession:
    """One method's tool access to one incident: budgets (calls, proxy tokens of tool output), usage and exposure."""

    def __init__(self, snapshot, *, cache_root: Path, max_calls: int | None = None, max_proxy_tokens: int | None = None):
        self.snapshot = snapshot
        self.db = sqlite3.connect(build_index(snapshot, cache_root))
        self.start = snapshot.window["start_ns"]
        self.max_calls, self.max_proxy_tokens = max_calls, max_proxy_tokens
        self.usage = {"tool_calls": 0, "proxy_tokens": 0}
        self.exposure: list[str] = []
        self._seen: set[str] = set()
        self._cut_reached = False

    @property
    def exhausted(self) -> bool:
        """No more tool output: the call limit is reached, or the token budget is used up or cut an answer."""
        u = self.usage
        return ((self.max_calls is not None and u["tool_calls"] >= self.max_calls) or self._cut_reached
                or (self.max_proxy_tokens is not None and u["proxy_tokens"] >= self.max_proxy_tokens))

    def call(self, name: str, args: dict) -> str:
        if self.exhausted:
            return "error: budget used up; no more tool output for this incident"
        self.usage["tool_calls"] += 1
        try:
            if name not in _SPECS:
                raise ToolError(f"unknown tool {name!r}; tools: {', '.join(_SPECS)}")
            self._check(name, args)
            text, shown = getattr(self, "_" + name)(**args)
        except (ToolError, OverflowError, ValueError, sqlite3.Error) as e:  # a bad argument never ends a paid run
            text, shown = f"error: {e}", []
        if self.max_proxy_tokens is not None:  # decision 019 §6: never more than the budget, cut at a line
            text, kept = _cut(text, self.max_proxy_tokens - self.usage["proxy_tokens"])
            shown = [(n, i) for n, i in shown if n < kept]
            self._cut_reached |= text.endswith(CUT_NOTE) or text == "(cut)"
        for _, i in shown:
            if i not in self._seen:
                self._seen.add(i)
                self.exposure.append(i)
        self.usage["proxy_tokens"] += proxy_tokens(text)
        return text

    def _check(self, name: str, args: dict) -> None:
        if not isinstance(args, dict):
            raise ToolError("arguments must be an object")
        props, spec = _SPECS[name]["parameters"]["properties"], _SPECS[name]["parameters"]
        if extra := sorted(set(args) - set(props)):
            raise ToolError(f"{name} has no argument(s) {extra}")
        if missing := [k for k in spec["required"] if args.get(k) in (None, "")]:
            raise ToolError(f"{name} needs {', '.join(missing)}")
        for k, v in args.items():
            p = props[k]
            if v is None:
                continue
            if "enum" in p and v not in p["enum"]:
                raise ToolError(f"{k} must be one of {p['enum']}")
            if p.get("type") in ("number", "integer"):
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ToolError(f"{k} must be a finite number")
                if p["type"] == "integer" and v != int(v):
                    raise ToolError(f"{k} must be a whole number")
                if "minimum" in p and v < p["minimum"]:
                    raise ToolError(f"{k} must be at least {p['minimum']}")
                if k in ("t0", "t1") and abs(v) > MAX_SECONDS:
                    raise ToolError(f"{k} is seconds since the start of the window (|{k}| <= {MAX_SECONDS})")
                if k == "offset" and v > MAX_OFFSET:
                    raise ToolError(f"offset must be at most {MAX_OFFSET}")
            if p.get("type") == "string":
                if not isinstance(v, str):
                    raise ToolError(f"{k} must be a string")
                if len(v) > MAX_TEXT:
                    raise ToolError(f"{k} must be at most {MAX_TEXT} characters")

    def _ns(self, seconds) -> int:
        return self.start + int(round(seconds * 1e9))

    def _page(self, what: str, table: str, where: list[str], params: list, limit, offset, order: str = "t, id") -> tuple[str, list]:
        limit = min(int(limit or DEFAULT_LIMIT), MAX_LIMIT)
        offset = int(offset or 0)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.db.execute(f"SELECT count(*) FROM {table}{clause}", params).fetchone()[0]
        trace = "trace_id" if table == "spans" else "NULL"
        rows = self.db.execute(f"SELECT id, line, {trace} FROM {table}{clause} ORDER BY {order} LIMIT ? OFFSET ?",
                               [*params, limit, offset]).fetchall()
        head = f"{total} {what} match; showing {offset + 1}-{offset + len(rows)}" if rows else f"{total} {what} match"
        shown = []  # (line number, exposure id): the record, then its trace (decision 019 §6)
        for n, (i, _, t) in enumerate(rows, start=1):
            shown.append((n, i))
            if t:
                shown.append((n, "t-" + t))
        return "\n".join([head, *(line for _, line, _ in rows)]), shown

    def _filters(self, service=None, text=None, t0=None, t1=None) -> tuple[list[str], list]:
        where, params = [], []
        if service is not None:
            where.append("service = ?")
            params.append(service)
        if text:  # LIKE: case-insensitive for ASCII; % and _ in the text are literal
            where.append("line LIKE ? ESCAPE '\\'")
            params.append("%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if t0 is not None:
            where.append("t >= ?")
            params.append(self._ns(t0))
        if t1 is not None:
            where.append("t < ?")
            params.append(self._ns(t1))
        return where, params

    def _list_services(self):
        counts = {}
        for table in ("spans", "logs", "series"):
            for svc, n in self.db.execute(f"SELECT service, count(*) FROM {table} GROUP BY service"):
                counts.setdefault(svc, {})[table] = n
        lines = [f"{svc} spans={counts.get(svc, {}).get('spans', 0)} logs={counts.get(svc, {}).get('logs', 0)} "
                 f"series={counts.get(svc, {}).get('series', 0)}" for svc in self.snapshot.services]
        return "\n".join([f"{len(lines)} services", *lines]), []

    def _search_spans(self, service=None, text=None, status=None, min_duration_ms=None, t0=None, t1=None, limit=None, offset=None):
        where, params = self._filters(service, text, t0, t1)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if min_duration_ms is not None:
            where.append("dur_ms >= ?")
            params.append(min_duration_ms)
        return self._page("spans", "spans", where, params, limit, offset)

    def _search_logs(self, service=None, text=None, min_severity=None, t0=None, t1=None, limit=None, offset=None):
        where, params = self._filters(service, text, t0, t1)
        if min_severity is not None:
            where.append("severity >= ?")
            params.append(min_severity)
        return self._page("log records", "logs", where, params, limit, offset)

    def _get_trace(self, trace_id, limit=None, offset=None):
        return self._page("spans", "spans", ["trace_id = ?"], [trace_id], limit, offset)

    def _list_series(self, service=None, text=None, limit=None, offset=None):
        where, params = self._filters(service, text)
        return self._page("series", "series", where, params, limit, offset, order="id")

    def _get_points(self, series_id, t0=None, t1=None, limit=None, offset=None):
        where, params = ["series_id = ?"], [series_id]
        if t0 is not None:
            where.append("t >= ?")
            params.append(self._ns(t0))
        if t1 is not None:
            where.append("t < ?")
            params.append(self._ns(t1))
        return self._page("points", "points", where, params, limit, offset)

    def _service_minute_stats(self, service, t0=None, t1=None):
        if service not in self.snapshot.services:
            raise ToolError(f"service {service!r} is not in the snapshot")
        lo = -(10**9) if t0 is None else int(t0 // 60)
        hi = 10**9 if t1 is None else -(-t1 // 60)
        rows = self.db.execute("SELECT minute, spans, errors, p95_ms, warn_logs, cpu, memory FROM minutes "
                               "WHERE service = ? AND minute >= ? AND minute < ? ORDER BY minute", (service, lo, hi)).fetchall()
        lines = [f"{_rel_minute(m)} spans={n} errors={e} p95_ms={_num(p)} warn_logs={w} cpu_cores={_num(c)} "
                 f"memory_mib={_num(None if mem is None else mem / MiB, '.1f')}" for m, n, e, p, w, c, mem in rows]
        shown = [(1, f"stats:{service}:{rows[0][0]}-{rows[-1][0]}")] if rows else []  # decision 022: what was looked at
        return "\n".join([f"{service} per minute ({len(lines)} minutes)", *lines]), shown
