"""The overview block of dump-all and retrieval (decision 021 §1): per service and minute, neutral counts and resources.

Same definitions as the agent's service_minute_stats tool (collect.derive); no scores, no ranking. The Agent does not
get this block (it calls service_minute_stats itself).

Decision 021's Pilot revision (user decision 2026-10-11): a statement right after the header says the rows are not
records, have no id and cannot be cited; the header and every row are unchanged.
"""

from __future__ import annotations

from collect.derive import container_minute_stats, service_minute_stats

MiB = 2**20
HEADER = ("## Per service and minute (spans, error spans, p95 of server spans in ms, logs at WARN or above, "
          "CPU cores used, memory MiB)")
NOTE = ("These rows are aggregates computed from the snapshot, not records: they have no id and cannot be cited as evidence. "
        "Evidence must be ids that appear in the span and log records shown to you: the id at the start of a record line "
        "(s-... for a span, l-... for a log), or t- followed by the trace_id of a span shown. This data shows no metric "
        "series (m-...) or metric point (p-...) ids.")


def _num(x, fmt: str = ".3f") -> str:
    return "-" if x is None else format(x, fmt)


def overview_lines(snapshot) -> list[str]:
    """The head (header and statement, one unit: dump-all packs it only together with the first row), then one row per
    service and minute."""
    spans, containers = service_minute_stats(snapshot)["services"], container_minute_stats(snapshot)["services"]
    lines = [HEADER + "\n" + NOTE]
    for svc in snapshot.services:
        s, c = spans.get(svc, {}), containers.get(svc, {})
        for minute in sorted(set(s) | set(c)):
            a, b = s.get(minute, {}), c.get(minute, {})
            mem = b.get("memory")
            lines.append(f"{svc} +{minute:03d}:00 spans={a.get('spans', 0)} errors={a.get('error_spans', 0)} "
                         f"p95_ms={_num(a.get('p95_server_ms'))} warn_logs={a.get('warn_logs', 0)} "
                         f"cpu_cores={_num(b.get('cpu'))} memory_mib={_num(None if mem is None else mem / MiB, '.1f')}")
    return lines


def overview(snapshot) -> str:
    return "\n".join(overview_lines(snapshot))
