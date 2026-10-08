"""Retrieval + LLM (SPEC Core §7 #2, decision 021 §3): the model proposes up to q queries after seeing the task and the
overview; each query takes the top k spans / logs by BM25 (sqlite FTS5 over render-v1 lines; ties by time); the
deduplicated records, in time order, go back to the model with only submit_diagnosis available.
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
from pathlib import Path

from agent.harness import finish, submit_round
from agent.prompt import SYSTEM, task_prompt
from agent.tools import MAX_SECONDS, MAX_TEXT
from baselines.overview import overview
from collect.snapshot import proxy_tokens, render_v1

INDEX_VERSION = 1

PROPOSE_SPEC = {
    "name": "propose_queries",
    "description": "Propose search queries over the spans and logs of the snapshot. Each query returns the best-matching "
                   "records (by word overlap); you get one round of results and then submit your diagnosis.",
    "input_schema": {"type": "object", "required": ["queries"], "additionalProperties": False, "properties": {
        "queries": {"type": "array", "items": {"type": "object", "required": ["text"], "additionalProperties": False,
                                               "properties": {"text": {"type": "string"}, "service": {"type": "string"},
                                                              "t0": {"type": "number", "description": "seconds since the start"},
                                                              "t1": {"type": "number", "description": "seconds since the start"}}}}}},
}


def _index(snapshot, cache_root: Path) -> Path:
    digest = snapshot.meta["content_sha256"].removeprefix("sha256:")
    path = Path(cache_root) / digest / "retrieval.sqlite"
    if path.exists():
        try:
            with sqlite3.connect(path) as db:
                meta = dict(db.execute("SELECT key, value FROM meta"))
        except sqlite3.DatabaseError:  # a derived cache that is not a usable database: rebuild it
            meta = {}
        if meta.get("content_sha256") == snapshot.meta["content_sha256"] and meta.get("index_version") == str(INDEX_VERSION):
            return path
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    start = snapshot.window["start_ns"]
    with sqlite3.connect(tmp) as db:
        db.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
                         "CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, service UNINDEXED, t UNINDEXED, line);")
        for kind, records in (("s", snapshot.spans()), ("l", snapshot.logs())):
            for r in records:
                t = r["start_time_unix_nano"] if kind == "s" else (
                    r["time_unix_nano"] if r.get("time_unix_nano") is not None else r.get("observed_time_unix_nano"))
                db.execute("INSERT INTO docs VALUES (?,?,?,?)", (r["id"], r["service"], t, render_v1(r, start)))
        db.executemany("INSERT INTO meta VALUES (?,?)", [("content_sha256", snapshot.meta["content_sha256"]),
                                                          ("index_version", str(INDEX_VERSION))])
    tmp.replace(path)
    return path


def search(snapshot, cache_root: Path, text: str, *, k: int, service: str | None = None, t0: float | None = None,
           t1: float | None = None) -> list[str]:
    """Ids of the top k spans / logs for `text` (its words, any of them; BM25, ties by time)."""
    return [i for i, _, _ in _rows(snapshot, cache_root, text, k=k, service=service, t0=t0, t1=t1)]


def _rows(snapshot, cache_root: Path, text: str, *, k: int, service=None, t0=None, t1=None, db_path=None) -> list[tuple]:
    """(id, time, render-v1 line) of the top k matches."""
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    if not words:
        return []
    query = " OR ".join(f'"{w}"' for w in words)
    where, params = ["docs MATCH ?"], [query]
    start = snapshot.window["start_ns"]
    if service is not None:
        where.append("service = ?")
        params.append(service)
    if t0 is not None:
        where.append("t >= ?")
        params.append(start + int(t0 * 1e9))
    if t1 is not None:
        where.append("t < ?")
        params.append(start + int(t1 * 1e9))
    with sqlite3.connect(_index(snapshot, cache_root) if db_path is None else db_path) as db:
        return db.execute(f"SELECT id, t, line FROM docs WHERE {' AND '.join(where)} ORDER BY bm25(docs), t, id LIMIT ?",
                          [*params, k]).fetchall()


def retrieval(snapshot, incident_id: str, model, *, method: dict, cache_root: Path, q: int, k: int,
              price_per_mtok: dict | None = None):
    t_start = time.monotonic()
    tokens = {"input": 0, "output": 0}
    view = overview(snapshot)
    ask = (task_prompt(snapshot) + "\n\n# Data\n\n" + view + "\n\nFirst call propose_queries with up to "
           f"{q} queries; each returns up to {k} records. Then you will submit your diagnosis.")
    messages = [{"role": "user", "content": [{"type": "text", "text": ask}]}]
    response = model.complete(SYSTEM, messages, [PROPOSE_SPEC])
    tokens["input"] += response.get("usage", {}).get("input_tokens", 0)
    tokens["output"] += response.get("usage", {}).get("output_tokens", 0)
    messages.append({"role": "assistant", "content": response["content"]})
    uses = [b for b in response["content"] if b.get("type") == "tool_use"]
    proposals = [b for b in uses if b.get("name") == "propose_queries"]
    queries = [x for b in proposals for x in ((b.get("input") or {}).get("queries") or []) if isinstance(x, dict)][:q]
    db_path = _index(snapshot, cache_root)  # opened once; a failure here is an error, never "0 records found"
    found: dict[str, tuple] = {}
    skipped, ran = [], 0
    for n, x in enumerate(queries, start=1):
        bounds = [x.get(b) for b in ("t0", "t1") if x.get(b) is not None]
        if not isinstance(x.get("text"), str) or len(x["text"]) > MAX_TEXT or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= MAX_SECONDS
                for v in bounds) or not (x.get("service") is None or isinstance(x["service"], str)):
            skipped.append(f"query {n} skipped: text must be a string of at most {MAX_TEXT} characters and t0 / t1 seconds "
                           "since the start of the window")
            continue
        ran += 1
        for i, t, line in _rows(snapshot, cache_root, x["text"], k=k, service=x.get("service"), t0=x.get("t0"),
                                t1=x.get("t1"), db_path=db_path):
            found.setdefault(i, (t or 0, line))
    order = sorted(found, key=lambda i: (found[i][0], i))
    lines = [found[i][1] for i in order]
    results = "\n".join([*skipped, f"{len(lines)} records found by {ran} queries, in time order:", *lines])
    reply = []
    for b in uses:  # every tool_use gets a tool_result
        if b is (proposals[0] if proposals else None):
            reply.append({"type": "tool_result", "tool_use_id": b["id"], "content": results})
        elif b.get("name") == "propose_queries":
            reply.append({"type": "tool_result", "tool_use_id": b["id"], "content": "merged into the first result"})
        else:
            reply.append({"type": "tool_result", "tool_use_id": b["id"], "is_error": True,
                          "content": "error: only propose_queries is available now"})
    if not proposals:
        reply.append({"type": "text", "text": results})
    messages.append({"role": "user", "content": reply + [{"type": "text", "text": "Now call submit_diagnosis."}]})
    pred, stop = submit_round(model, SYSTEM, messages, snapshot, incident_id, method, tokens)
    pred = finish(pred, incident_id, method, tokens, proxy=proxy_tokens(view) + proxy_tokens(results), tool_calls=0,
                  retrievals=ran, t_start=t_start, price_per_mtok=price_per_mtok)
    return pred, {"incident_id": incident_id, "method": dict(method), "stop_reason": stop, "messages": messages,
                  "exposure": ["stats:*", *order], "usage": pred["usage"], "queries": queries}
