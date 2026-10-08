"""The task text every LLM method gets (decision 020 §1): the window, decision 014's one framing sentence, the answer space.

Nothing about how the incident was produced: no collection protocol, no fault mechanism hints beyond the closed
vocabularies the answers are scored in (decisions 006, 013).
"""

from __future__ import annotations

from collect.labels import FAULT_TYPES
from collect.snapshot import _rel

FRAMING = ("The system was healthy during the first 10 minutes of the time window; "
           "at some point after that a fault may have started.")
SYMPTOM_KINDS = ("errors", "latency", "degraded_feature", "none")

SYSTEM = ("You are an experienced site reliability engineer doing a read-only root-cause investigation. You only have a frozen "
          "telemetry snapshot; you cannot reach or change the running system. Use the tools to look at the data, reason from "
          "what you see, and finish by calling submit_diagnosis exactly once.")


def task_prompt(snapshot) -> str:
    w = snapshot.window
    families = sorted(set(FAULT_TYPES.values()))
    return "\n".join([
        "A microservice system had a problem. You have a frozen snapshot of its traces, logs and metrics for one time window.",
        f"Time window: from {_rel(w['start_ns'], w['start_ns'])} to {_rel(w['end_ns'], w['start_ns'])} "
        "(all times are minutes:seconds since the start of the window; tool time arguments are seconds since the start).",
        FRAMING,
        "",
        f"Services in the snapshot: {', '.join(snapshot.services)}.",
        "",
        "Call submit_diagnosis with:",
        f"- fault.fault_type: one of {', '.join(sorted(FAULT_TYPES))}; or null if you cannot tell.",
        f"- fault.fault_family: one of {', '.join(families)}; or null (it follows from fault_type when that is given).",
        "- origin_candidates: up to 5 services, most likely first: the service where the problem originates, i.e. whose own "
        "behaviour or configuration is faulty (not one that merely received less traffic). An empty list means no answer.",
        "- affected_services: every service whose own telemetry shows errors or slowdowns caused by the problem, including the origin.",
        f"- user_symptom.kinds: what users saw at the entry point of the system: any of {', '.join(SYMPTOM_KINDS[:3])}; or [\"none\"].",
        "- evidence: ids of the records that support your diagnosis, as the tools show them (s-..., l-..., m-..., p-..., or "
        "t-<trace id>); for a metric series (m-...) you may add t0 and t1 in seconds since the start of the window.",
    ])
