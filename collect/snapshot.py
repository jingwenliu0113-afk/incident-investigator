"""The single way agents, baselines and replays read a frozen snapshot (decision 011 §5).

open_snapshot() refuses anything outside the agent-readable allow-list and any file whose bytes differ
from snapshot.json; records are served as parsed dicts; evidence ids resolve to single records only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from collect.layout import DataLayout
from collect.normalize import DATA_FILES

RENDER_VERSION = 1
MAX_LINE_BYTES = 1024


class SnapshotError(RuntimeError):
    pass


def proxy_tokens(text: str) -> int:
    """Model-independent budget unit (decision 011 §5): ceil(utf8 bytes / 4)."""
    return -(-len(text.encode()) // 4)


class Snapshot:
    def __init__(self, path: Path, meta: dict):
        self.path, self.meta = path, meta
        self._index: dict[str, tuple[str, int]] | None = None
        self._traces: set[str] | None = None
        self._series_times: dict[str, list[int]] | None = None

    @property
    def window(self) -> dict:
        return self.meta["window"]

    @property
    def services(self) -> list[str]:
        return self.meta["services"]

    def _iter(self, name: str) -> Iterator[dict]:
        with (self.path / name).open("rb") as f:
            for line in f:
                yield json.loads(line)

    def resources(self) -> Iterator[dict]:
        return self._iter("resources.jsonl")

    def spans(self) -> Iterator[dict]:
        return self._iter("spans.jsonl")

    def logs(self) -> Iterator[dict]:
        return self._iter("logs.jsonl")

    def series(self) -> Iterator[dict]:
        return self._iter("metric_series.jsonl")

    def points(self) -> Iterator[dict]:
        return self._iter("metric_points.jsonl")

    def _build_index(self) -> None:
        self._index, self._traces, self._series_times = {}, set(), {}
        for name in ("spans.jsonl", "logs.jsonl", "metric_series.jsonl", "metric_points.jsonl"):
            with (self.path / name).open("rb") as f:
                offset = 0
                for line in f:
                    rec = json.loads(line)
                    self._index[rec["id"]] = (name, offset)
                    if name == "spans.jsonl":
                        self._traces.add(rec["trace_id"])
                    elif name == "metric_points.jsonl":
                        self._series_times.setdefault(rec["series_id"], []).append(rec["time_unix_nano"])
                    offset += len(line)

    def _read_at(self, name: str, offset: int) -> dict:
        with (self.path / name).open("rb") as f:
            f.seek(offset)
            return json.loads(f.readline())

    def resolve(self, evidence_id: str, t0: int | None = None, t1: int | None = None) -> dict | None:
        """Existence (SPEC §9): the record an evidence id names, or None. `m-` ids may carry a time range."""
        if self._index is None:
            self._build_index()
        if evidence_id.startswith("t-"):
            tid = evidence_id[2:]
            return {"trace_id": tid} if tid in self._traces else None
        if evidence_id[:2] not in ("s-", "l-", "m-", "p-") or evidence_id not in self._index:
            return None
        if evidence_id.startswith("m-") and (t0 is not None or t1 is not None):
            lo, hi = t0 if t0 is not None else -1, t1 if t1 is not None else 2**63
            if not any(lo <= t <= hi for t in self._series_times.get(evidence_id, [])):
                return None
        return self._read_at(*self._index[evidence_id])


def open_snapshot(path: Path, layout: DataLayout) -> Snapshot:
    path = Path(path)
    if not layout.is_agent_readable(path) or not all(layout.is_agent_readable(path / n) for n in ("snapshot.json", *DATA_FILES)):
        raise SnapshotError(f"{path} is not an agent-readable snapshot (decision 008 §5)")
    meta = json.loads((path / "snapshot.json").read_text())
    listed = {f["path"]: f for f in meta["files"]}
    for name in DATA_FILES:
        digest = "sha256:" + hashlib.sha256((path / name).read_bytes()).hexdigest()
        if listed.get(name, {}).get("sha256") != digest:
            raise SnapshotError(f"{name}: sha256 differs from snapshot.json (tampered or truncated)")
    content = hashlib.sha256("".join(f"{n}\0{listed[n]['sha256']}\n" for n in DATA_FILES).encode()).hexdigest()
    if meta.get("content_sha256") != "sha256:" + content:
        raise SnapshotError("content_sha256 does not match the listed files")
    return Snapshot(path, meta)


def _rel(ns: int | None, origin: int) -> str | None:
    if ns is None:
        return None
    ms = (ns - origin) // 1_000_000
    sign = "-" if ms < 0 else "+"
    ms = abs(ms)
    return f"{sign}{ms // 60000:03d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"  # +MMM:SS.mmm (decision 011 §5)


def _relativize(rec: dict, origin: int) -> dict:
    out = dict(rec)
    for key in list(out):
        if key.endswith("time_unix_nano"):
            out[key.removesuffix("_unix_nano")] = _rel(out.pop(key), origin)
    return out


def _prune(value):
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in sorted(value.items()) if v is not None and v != [] and v != {}}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def render_v1(record: dict, window_start_ns: int) -> str:
    """One line per record: id first, times relative to the window start, no nulls, at most 1024 bytes."""
    rec = _relativize({k: v for k, v in record.items() if k != "id"}, window_start_ns)
    if isinstance(rec.get("events"), list):  # only events: attribute keys that end in time_unix_nano stay as they are
        rec["events"] = [_relativize(e, window_start_ns) if isinstance(e, dict) else e for e in rec["events"]]
    line = f"{record.get('id', '')} " + json.dumps(_prune(rec), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    data = line.encode()
    if len(data) <= MAX_LINE_BYTES:
        return line
    return data[: MAX_LINE_BYTES - 3].decode("utf-8", "ignore") + "..."
