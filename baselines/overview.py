"""The overview block every LLM method can see (decision 021 §1): per service and minute, neutral counts and resources.

Same definitions as the agent's service_minute_stats tool (collect.derive); no scores, no ranking.
"""

from __future__ import annotations

from collect.derive import container_minute_stats, service_minute_stats

MiB = 2**20


def _num(x, fmt: str = ".3f") -> str:
    return "-" if x is None else format(x, fmt)


def overview(snapshot) -> str:
    spans, containers = service_minute_stats(snapshot)["services"], container_minute_stats(snapshot)["services"]
    lines = ["## Per service and minute (spans, error spans, p95 of server spans in ms, logs at WARN or above, "
             "CPU cores used, memory MiB)"]
    for svc in snapshot.services:
        s, c = spans.get(svc, {}), containers.get(svc, {})
        for minute in sorted(set(s) | set(c)):
            a, b = s.get(minute, {}), c.get(minute, {})
            mem = b.get("memory")
            lines.append(f"{svc} +{minute:03d}:00 spans={a.get('spans', 0)} errors={a.get('error_spans', 0)} "
                         f"p95_ms={_num(a.get('p95_server_ms'))} warn_logs={a.get('warn_logs', 0)} "
                         f"cpu_cores={_num(b.get('cpu'))} memory_mib={_num(None if mem is None else mem / MiB, '.1f')}")
    return "\n".join(lines)
