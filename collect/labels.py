"""Incident labels (Core §3, decision 006): ground truth per incident, kept consistent with the run group's record."""

from __future__ import annotations

from collections.abc import Collection

from collect.records import _schema_problems, _timestamps
from collect.traffic import TRAFFIC_PROFILES

# fault_type -> fault_family. Mechanism-level vocabulary: predictions are scored against these, never flag names.
FAULT_TYPES = {
    "error_response": "error",
    "unreachable_dependency": "connectivity",
    "added_latency": "latency",
    "lock_contention": "latency",
    "cpu_saturation": "resource",
    "gc_pressure": "resource",
    "memory_leak": "resource",
    "queue_backlog": "messaging",
    "traffic_flood": "traffic",
}

# flagd flag -> fault_type (decision 006 table). Flags not listed are not Core faults in the locked stack.
FLAG_FAULT_TYPES = {
    "adFailure": "error_response",
    "paymentFailure": "error_response",
    "productCatalogFailure": "error_response",
    "cartFailure": "unreachable_dependency",
    "paymentUnreachable": "unreachable_dependency",
    "intlShippingSlowdown": "added_latency",
    "productCatalogLockContention": "lock_contention",
    "adHighCpu": "cpu_saturation",
    "adManualGc": "gc_pressure",
    "emailMemoryLeak": "memory_leak",
    "recommendationCacheFailure": "memory_leak",
    "kafkaQueueProblems": "queue_backlog",
    "loadGeneratorFloodHomepage": "traffic_flood",
}


def check_label(
    label: dict,
    injection: dict,
    *,
    services: Collection[str],
    manifest: dict | None = None,
) -> list[str]:
    """`services`: compose services of the locked stack; `manifest`: the incident's manifest, when written."""
    problems = _schema_problems(label, "incident_label.schema.json")
    problems += [f"injection {p}" for p in _schema_problems(injection, "fault_injection.schema.json")]
    if manifest is not None:
        problems += [f"manifest {p}" for p in _schema_problems(manifest, "run_manifest.schema.json")]
    if problems:
        return problems

    fault = label["injected_fault"]
    if label["fault_family"] != FAULT_TYPES[fault["fault_type"]]:
        problems.append(f"fault_family {label['fault_family']!r} does not match fault_type {fault['fault_type']!r} "
                        f"({FAULT_TYPES[fault['fault_type']]!r})")
    expected = FLAG_FAULT_TYPES.get(fault["flag"])
    if expected is None:
        problems.append(f"flag {fault['flag']!r} is not a Core fault (decision 006)")
    elif fault["fault_type"] != expected:
        problems.append(f"fault_type {fault['fault_type']!r} does not match flag {fault['flag']!r} ({expected!r})")

    if label["run_group_id"] != injection["run_group_id"]:
        problems.append(f"run_group_id {label['run_group_id']} is not the injection's {injection['run_group_id']}")
    if label["incident_id"] not in injection["incident_ids"]:
        problems.append(f"{label['incident_id']} is not in the injection's incident_ids")
    if label["seed"] != injection["seed"]:
        problems.append(f"seed {label['seed']} is not the injection's {injection['seed']}")
    for key in ("flag", "variant"):
        if fault[key] != injection["fault"][key]:
            problems.append(f"injected_fault {key} {fault[key]!r} is not what was injected ({injection['fault'][key]!r})")
    for mine, theirs in (("fault_start", "fault_on"), ("fault_end", "fault_off")):
        if label[mine] != injection["schedule"][theirs]:
            problems.append(f"{mine} {label[mine]} is not the injection's schedule/{theirs} {injection['schedule'][theirs]}")

    ts, ts_problems = _timestamps({"fault_start": label["fault_start"], "fault_end": label["fault_end"],
                                   "labeling/labeled_at": label["labeling"]["labeled_at"]})
    problems += ts_problems
    fault_ok = {"fault_start", "fault_end"} <= ts.keys()
    if fault_ok and not ts["fault_start"] < ts["fault_end"]:
        problems.append("fault_start must be before fault_end")

    unknown = sorted({label["origin_service"], *label["affected_services"]} - set(services))
    if unknown:
        problems.append(f"unknown service(s) {unknown} (not in the locked stack)")
    if label["origin_service"] not in label["affected_services"]:
        problems.append(f"origin_service {label['origin_service']!r} must also be in affected_services")

    if manifest is not None:
        if manifest["incident_id"] != label["incident_id"]:
            problems.append(f"manifest incident_id {manifest['incident_id']} is not {label['incident_id']}")
        if manifest["traffic"]["settings"] != TRAFFIC_PROFILES[label["traffic_profile"]]:
            problems.append(f"traffic_profile {label['traffic_profile']!r} is not the traffic the manifest recorded")
        w, w_problems = _timestamps({"window/start": manifest["window"]["start"], "window/end": manifest["window"]["end"]})
        problems += w_problems
        if fault_ok and not w_problems and not (ts["fault_start"] < w["window/end"] and ts["fault_end"] > w["window/start"]):
            problems.append("fault interval does not overlap the incident's telemetry window")
    return problems
