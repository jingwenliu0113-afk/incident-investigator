"""Streaming scan of raw OTLP JSON Lines files written by the collector's file exporter (decision 008).

Read-only: counts lines, parse errors, items, duplicates (fixed dedupe keys of decision 008 §7),
data-time range, per-service counts and the minutes that have data, and hashes the file in the
same pass. Raw files are never modified; dedupe happens later, in normalize.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from collect.otlp import log_key, nanos, point_key, span_key

# signal -> (top-level key, scope key, item key) of TracesData / MetricsData / LogsData
_LAYOUT = {
    "traces": ("resourceSpans", "scopeSpans", "spans"),
    "metrics": ("resourceMetrics", "scopeMetrics", "metrics"),
    "logs": ("resourceLogs", "scopeLogs", "logRecords"),
}
_POINT_KINDS = ("gauge", "sum", "histogram", "exponentialHistogram", "summary")
MAX_ERROR_LINES = 20


def _service(resource: dict) -> str:
    for attr in resource.get("attributes") or []:
        if attr.get("key") == "service.name":
            return (attr.get("value") or {}).get("stringValue", "")
    return ""


def _items(signal: str, doc: dict) -> Iterator[tuple[str, int | None, tuple]]:
    """(service.name, item time in unix nanos, dedupe key) per span / data point / log record."""
    top, scope_key, leaf = _LAYOUT[signal]
    for rs in doc[top] or []:
        resource = rs.get("resource") or {}
        service = _service(resource)
        for ss in rs.get(scope_key) or []:
            scope = ss.get("scope") or {}
            for item in ss.get(leaf) or []:
                if signal == "traces":
                    yield service, nanos(item.get("startTimeUnixNano")), span_key(item)
                elif signal == "logs":
                    yield service, nanos(item.get("timeUnixNano")) or nanos(item.get("observedTimeUnixNano")), \
                        log_key(resource, item)
                else:
                    for kind in _POINT_KINDS:
                        for p in (item.get(kind) or {}).get("dataPoints") or []:
                            yield service, nanos(p.get("timeUnixNano")), point_key(resource, scope, item.get("name"), p)


def _utc(nanos: int) -> datetime:
    return datetime.fromtimestamp(nanos // 10**9, UTC).replace(microsecond=nanos % 10**9 // 1000)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"


def scan_raw_file(path: Path, signal: str) -> dict:
    if signal not in _LAYOUT:
        raise ValueError(f"unknown signal {signal!r} (expected one of {sorted(_LAYOUT)})")
    top = _LAYOUT[signal][0]
    sha, size = hashlib.sha256(), 0
    lines = empty = wrong = items = duplicates = 0
    errors: list[int] = []
    last_unparsed_without_newline = False
    seen: set[bytes] = set()
    by_service: dict[str, int] = {}
    minutes: set[str] = set()
    t_min = t_max = None

    with Path(path).open("rb") as f:
        for lines, raw in enumerate(f, 1):
            sha.update(raw)
            size += len(raw)
            last_unparsed_without_newline = False
            body = raw.rstrip(b"\r\n")
            if not body.strip():
                empty += 1
                continue
            try:
                doc = json.loads(body)
                if not isinstance(doc, dict) or top not in doc:
                    wrong += 1
                    continue
                found = list(_items(signal, doc))
            except (ValueError, TypeError, AttributeError):  # JSONDecodeError / UnicodeDecodeError are ValueErrors
                errors.append(lines)
                last_unparsed_without_newline = not raw.endswith(b"\n")
                continue
            for service, t, key in found:
                digest = hashlib.blake2b(repr(key).encode(), digest_size=16).digest()
                if digest in seen:
                    duplicates += 1
                    continue
                seen.add(digest)
                items += 1
                by_service[service] = by_service.get(service, 0) + 1
                if t is not None:
                    t_min = t if t_min is None else min(t_min, t)
                    t_max = t if t_max is None else max(t_max, t)
                    minutes.add(_utc(t).strftime("%Y-%m-%dT%H:%M"))

    return {
        "signal": signal,
        "format": "otlp-json-lines",
        "bytes": size,
        "sha256": "sha256:" + sha.hexdigest(),
        "lines": lines,
        "empty_lines": empty,
        "parse_errors": len(errors),
        "parse_error_lines": errors[:MAX_ERROR_LINES],
        "last_line_truncated": last_unparsed_without_newline,
        "wrong_signal_lines": wrong,
        "items": items,
        "duplicates": duplicates,
        "min_time": None if t_min is None else _iso(_utc(t_min)),
        "max_time": None if t_max is None else _iso(_utc(t_max)),
        "by_service": dict(sorted(by_service.items())),
        "minutes": sorted(minutes),
    }


DOCKER_STATS_SCOPE = "dockerstatsreceiver"


def container_minutes(path: Path) -> dict[str, list[str]]:
    """container.name -> the minutes (UTC, "YYYY-MM-DDTHH:MM") in which docker_stats reported it (decision 012).

    Unparsable lines are skipped here; scan_raw_file() reports them.
    """
    seen: dict[str, set[str]] = {}
    with Path(path).open("rb") as f:
        for raw in f:
            try:
                doc = json.loads(raw)
            except ValueError:
                continue
            for rm in doc.get("resourceMetrics") or [] if isinstance(doc, dict) else []:
                name = next((a.get("value", {}).get("stringValue") for a in (rm.get("resource") or {}).get("attributes") or []
                             if a.get("key") == "container.name"), None)
                for sm in rm.get("scopeMetrics") or []:
                    if name is None or DOCKER_STATS_SCOPE not in ((sm.get("scope") or {}).get("name") or ""):
                        continue
                    for m in sm.get("metrics") or []:
                        for kind in _POINT_KINDS:
                            for pt in (m.get(kind) or {}).get("dataPoints") or []:
                                if t := nanos(pt.get("timeUnixNano")):
                                    seen.setdefault(name, set()).add(_utc(t).strftime("%Y-%m-%dT%H:%M"))
    return {name: sorted(minutes) for name, minutes in sorted(seen.items())}
