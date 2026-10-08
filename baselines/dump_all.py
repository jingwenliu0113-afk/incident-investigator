"""Dump-all + LLM (SPEC Core §7 #1, decision 021 §2): one fixed packing of the snapshot within B proxy tokens.

Order: the overview block; error-level records grouped by template (count, first / last time, first and last record);
then a time-stratified sample of the other spans and logs (one-minute cells, seeded by the incident id). Whatever does
not fit is cut from the end. One answering step with only submit_diagnosis (decision 020 §3).
"""

from __future__ import annotations

import hashlib
import heapq
import time
from collections import defaultdict

from agent.harness import finish, submit_round
from agent.prompt import SYSTEM, task_prompt
from baselines.overview import overview
from collect.snapshot import _rel, proxy_tokens, render
from eval.leakage import WARN, template

MINUTE = 60 * 10**9
SAMPLE_CAP_PER_CELL = 400  # records kept per minute and kind before rendering; far more than any budget can use


def _error_level(kind: str, rec: dict) -> bool:
    return rec.get("status_code") == "error" if kind == "span" else (rec.get("severity_number") or 0) >= WARN


def _time(kind: str, rec: dict) -> int:
    if kind == "span":
        return rec["start_time_unix_nano"]
    return rec["time_unix_nano"] if rec.get("time_unix_nano") is not None else rec.get("observed_time_unix_nano")


def _text(kind: str, rec: dict) -> str:
    if kind == "span":
        return f"{rec.get('name') or ''} {rec.get('status_message') or ''}".strip()
    body = rec.get("body")
    return body if isinstance(body, str) else str(body)


def pack(snapshot, incident_id: str, *, budget: int) -> tuple[str, dict]:
    start = snapshot.window["start_ns"]
    groups: dict = {}
    cells: dict = defaultdict(list)  # (minute, kind) -> heap of (-rank, id, record)
    for kind, records in (("span", snapshot.spans()), ("log", snapshot.logs())):
        for rec in records:
            t = _time(kind, rec)
            if _error_level(kind, rec):
                key = (kind, rec["service"], template(_text(kind, rec)))
                g = groups.setdefault(key, {"count": 0, "first": (t, rec), "last": (t, rec)})
                g["count"] += 1
                g["first"] = min(g["first"], (t, rec), key=lambda x: (x[0], x[1]["id"]))
                g["last"] = max(g["last"], (t, rec), key=lambda x: (x[0], x[1]["id"]))
                continue
            rank = int(hashlib.sha256(f"{incident_id}:{rec['id']}".encode()).hexdigest()[:16], 16)
            heap = cells[((t - start) // MINUTE, kind)]  # keeps the SAMPLE_CAP_PER_CELL smallest ranks
            heapq.heappush(heap, (-rank, rec["id"], rec))
            if len(heap) > SAMPLE_CAP_PER_CELL:
                heapq.heappop(heap)
    sections = [overview(snapshot).splitlines()]
    err = ["## Error-level records (grouped by message template: count, first and last time, then the first and last record)"]
    for (kind, svc, tmpl), g in sorted(groups.items(), key=lambda kv: (kv[1]["first"][0], kv[0])):
        err.append(f"{g['count']} x {svc} {kind} first={_rel(g['first'][0], start)} last={_rel(g['last'][0], start)}: {tmpl}")
        err.append(render(g["first"][1], start))
        if g["last"][1]["id"] != g["first"][1]["id"]:
            err.append(render(g["last"][1], start))
    sections.append(err)
    order = {key: sorted(heap, key=lambda x: -x[0]) for key, heap in cells.items()}  # ascending rank
    minutes = sorted({m for m, _ in order})
    sample = ["## Sample of the other spans and logs (time-stratified; each minute in turn)"]
    i = 0
    while True:
        added = False
        for m in minutes:
            for kind in ("span", "log"):
                cell = order.get((m, kind), [])
                if i < len(cell):
                    sample.append(render(cell[i][2], start))
                    added = True
        if not added:
            break
        i += 1
    sections.append(sample)
    out, used, records = [], 0, 0
    for section in sections:
        for n, line in enumerate(section):
            cost = proxy_tokens(line + "\n")
            if used + cost > budget or (n == 0 and len(section) > 1 and used + cost + proxy_tokens(section[1] + "\n") > budget):
                break  # a section header goes in only with its first line
            out.append(line)
            used += cost
            records += line[:2] in ("s-", "l-")
        else:
            continue
        break
    text = "\n".join(out)
    return text, {"proxy_tokens": proxy_tokens(text), "records": records}


def dump_all(snapshot, incident_id: str, model, *, method: dict, budget: int, price_per_mtok: dict | None = None):
    t_start = time.monotonic()
    packed, stats = pack(snapshot, incident_id, budget=budget)
    messages = [{"role": "user", "content": [{"type": "text", "text": task_prompt(snapshot) + "\n\n# Data\n\n" + packed}]}]
    tokens = {"input": 0, "output": 0}
    pred, stop = submit_round(model, SYSTEM, messages, snapshot, incident_id, method, tokens)
    pred = finish(pred, incident_id, method, tokens, proxy=stats["proxy_tokens"], tool_calls=0, retrievals=0,
                  t_start=t_start, price_per_mtok=price_per_mtok)
    exposure = ["stats:*"] + [line.split(" ", 1)[0] for line in packed.splitlines() if line[:2] in ("s-", "l-")]
    return pred, {"incident_id": incident_id, "method": dict(method), "stop_reason": stop, "messages": messages,
                  "exposure": exposure, "usage": pred["usage"], "packing": stats}
