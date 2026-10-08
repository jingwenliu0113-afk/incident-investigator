"""Leakage audit v1 (SPEC Core §6, decision 015). Ground-truth side: it reads the label to know the fault window.

For every text an agent can read (span status messages and event names, log bodies and event names) it builds a
template (ids and numbers masked) and counts it in the normal period, the fault period and the recovery. Templates that
appear only from fault_on on are the "obvious error messages"; difficulty follows from who emits them (decision 015).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

from collect.policy import Policy, load_policy

WARN = 13  # OTLP severity_number: WARN and above count as error-level text
MAX_LISTED = 50
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_HEX = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_NUM = re.compile(r"[A-Za-z0-9_.-]*[0-9][A-Za-z0-9_.-]*")  # revision 1: the whole word that holds a digit


def template(text: str) -> str:
    return _NUM.sub("<n>", _HEX.sub("<hex>", _UUID.sub("<uuid>", text)))


def _texts(snapshot):
    """(time, service, text, error_level) for every readable text of the snapshot."""
    for s in snapshot.spans():
        if s.get("status_message"):
            yield s["start_time_unix_nano"], s["service"], s["status_message"], s.get("status_code") == "error"
        for e in s.get("events") or []:
            if e.get("name"):
                yield e.get("time_unix_nano") or s["start_time_unix_nano"], s["service"], e["name"], e["name"] == "exception"
    for r in snapshot.logs():
        t = r["time_unix_nano"] if r.get("time_unix_nano") is not None else r.get("observed_time_unix_nano")
        if isinstance(r.get("body"), str) and r["body"]:
            yield t, r["service"], r["body"], (r.get("severity_number") or 0) >= WARN
        if r.get("event_name"):
            yield t, r["service"], r["event_name"], False


def _ns(ts: str, offset_s: float) -> int:
    return int(datetime.fromisoformat(ts).timestamp() * 10**9) + int(offset_s * 10**9)


def audit(snapshot, label: dict, *, clock_offset_s: float = 0.0, new_attribute_keys: dict | None = None,
          policy: Policy | None = None) -> dict:
    """`clock_offset_s`: data clock minus host clock (the run's measured offset; the label is on the host clock)."""
    policy = policy or load_policy()
    on, off = _ns(label["fault_start"], clock_offset_s), _ns(label["fault_end"], clock_offset_s)
    counts: dict = defaultdict(lambda: {"normal": 0, "fault": 0, "recovery": 0, "services": set(), "error_level": False})
    lexicon_hits = 0
    for t, service, text, error_level in _texts(snapshot):
        lexicon_hits += policy.lexicon_hit(text)
        period = "normal" if t is None or t < on else "fault" if t < off else "recovery"
        c = counts[template(text)]
        c[period] += 1
        if period != "normal":
            c["services"].add(service)
            c["error_level"] |= error_level
    fault_only = sorted(({"template": k, "normal": 0, "fault": v["fault"], "recovery": v["recovery"],
                          "services": sorted(v["services"]), "error_level": v["error_level"]}
                         for k, v in counts.items() if v["normal"] == 0 and v["fault"] > 0),
                        key=lambda e: (-e["fault"], e["template"]))
    origin = label["origin_service"]
    names_origin = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(origin)}(?![A-Za-z0-9-])", re.IGNORECASE)
    errors = [e for e in fault_only if e["error_level"]]
    difficulty = ("easy" if any(origin in e["services"] for e in errors) else "medium" if errors else "hard")
    return {
        "audit_version": 1,
        "incident_id": label["incident_id"],
        "difficulty": difficulty,
        "fault_only_templates": fault_only[:MAX_LISTED],
        "fault_only_count": len(fault_only),
        "origin_named": [e["template"] for e in fault_only if names_origin.search(e["template"])],
        "lexicon_hits": lexicon_hits,
        "new_attribute_keys": new_attribute_keys or {},
    }
