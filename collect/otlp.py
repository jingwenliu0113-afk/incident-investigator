"""OTLP JSON helpers shared by the raw scan (collect.rawfile) and normalize (decisions 008 §7, 011 §2).

OTLP JSON encodes trace / span ids as hex, int64 as decimal strings, non-finite doubles as strings,
enums as numbers or names, and omits zero values. Never decode it with protobuf json_format (it reads
hex ids as base64 and silently returns wrong bytes).
"""

from __future__ import annotations

import json
from collections.abc import MutableMapping

_ENUMS = {
    "span_kind": ["unspecified", "internal", "server", "client", "producer", "consumer"],
    "status_code": ["unset", "ok", "error"],
    "temporality": [None, "delta", "cumulative"],
}
_ENUM_PREFIX = {"span_kind": "SPAN_KIND_", "status_code": "STATUS_CODE_", "temporality": "AGGREGATION_TEMPORALITY_"}
_NONFINITE = {"NaN", "Infinity", "-Infinity"}


def nanos(value) -> int | None:
    """OTLP JSON int64 (decimal string or number); 0 / missing / garbage -> None."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n or None


def enum(kind: str, value):
    names = _ENUMS[kind]
    if value is None:
        return names[0]
    if isinstance(value, str) and not value.isdigit():
        name = value.removeprefix(_ENUM_PREFIX[kind]).lower()
        if name == "unspecified" and kind == "temporality":
            return None
        if name in names:
            return name
        raise ValueError(f"unknown {kind} {value!r}")
    i = int(value)
    if not 0 <= i < len(names):
        raise ValueError(f"unknown {kind} {value!r}")
    return names[i]


def _text(s: str, counts: MutableMapping[str, int] | None) -> str:
    try:
        s.encode("utf-8")
        return s
    except UnicodeEncodeError:
        if counts is not None:
            counts["lone_surrogates"] = counts.get("lone_surrogates", 0) + 1
        return "".join("�" if 0xD800 <= ord(c) <= 0xDFFF else c for c in s)


def any_value(v, counts: MutableMapping[str, int] | None = None):
    """Lossless AnyValue -> JSON value (decision 011 §2)."""
    if not v:
        return None
    if "stringValue" in v:
        return _text(v["stringValue"], counts)
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        d = v["doubleValue"]
        if isinstance(d, str) and d in _NONFINITE:
            return {"$double": d}
        return float(d)
    if "bytesValue" in v:
        return {"$bytes": v["bytesValue"]}
    if "arrayValue" in v:
        return [any_value(x, counts) for x in (v["arrayValue"] or {}).get("values") or []]
    if "kvlistValue" in v:
        return attributes((v["kvlistValue"] or {}).get("values") or [], counts, nested=True)
    return None


def attributes(kvs, counts: MutableMapping[str, int] | None = None, *, nested: bool = False) -> dict:
    out: dict = {}
    for kv in kvs or []:
        key = _text(kv.get("key", ""), counts)
        if nested and key.startswith("$"):
            raise ValueError(f"kvlist key {key!r} collides with the typed-value markers")
        if key in out:
            if counts is not None:
                counts["duplicate_keys"] = counts.get("duplicate_keys", 0) + 1
            continue
        out[key] = any_value(kv.get("value"), counts)
    return out


def _canon(kvs) -> str:
    return json.dumps(sorted(kvs or [], key=lambda a: a.get("key", "")), sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------- dedupe keys (decision 008 §7)

def span_key(span: dict) -> tuple:
    return ("span", span.get("traceId"), span.get("spanId"))


def series_key(resource: dict, scope: dict, metric_name: str, point: dict) -> tuple:
    return ("point", _canon(resource.get("attributes")), scope.get("name"), scope.get("version"), metric_name,
            _canon(point.get("attributes")))


def point_key(resource: dict, scope: dict, metric_name: str, point: dict) -> tuple:
    return series_key(resource, scope, metric_name, point) + (point.get("startTimeUnixNano"), point.get("timeUnixNano"))


def log_key(resource: dict, record: dict) -> tuple:
    return ("log", _canon(resource.get("attributes")), json.dumps(record, sort_keys=True, separators=(",", ":")))
