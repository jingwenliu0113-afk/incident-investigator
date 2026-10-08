"""The a priori (catalog) label of one incident, from its injection record (decisions 006, 010). Ground-truth side only.

The answer facts (flag, variant, fault time, seed) come from injection.json, never from a person; the person supplies
origin, affected services and the user symptom from the fault design (decision 010 rule 3). check_label() must pass
before anything is written, and a label is never overwritten.
"""

from __future__ import annotations

import json

from collect.incident import find_run
from collect.labels import FAULT_TYPES, FLAG_FAULT_TYPES, check_label
from collect.layout import DataLayout
from collect.policy import load_policy
from collect.traffic import TRAFFIC_PROFILES


def catalog_label(layout: DataLayout, incident_id: str, *, origin: str, affected: list[str], symptom_kinds: list[str],
                  symptom_description: str, labeler: str, now: str, notes: str | None = None) -> dict:
    path = layout.label_path(incident_id)
    if path.exists():
        raise FileExistsError(f"{path} exists: a label is never overwritten (a review writes catalog+review separately)")
    rg = find_run(layout, incident_id)["run_group_id"]
    injection = json.loads(layout.injection_path(rg).read_text())
    manifest = json.loads(layout.manifest_path(incident_id).read_text())
    settings = manifest["traffic"]["settings"]
    profile = next((name for name, s in TRAFFIC_PROFILES.items() if s == settings), None)
    if profile is None:
        raise ValueError(f"the manifest's traffic settings match no traffic profile: {settings}")
    flag = injection["fault"]["flag"]
    if (fault_type := FLAG_FAULT_TYPES.get(flag)) is None:
        raise ValueError(f"flag {flag!r} is not a Core fault (decision 006)")
    label = {
        "label_version": 1,
        "incident_id": incident_id,
        "run_group_id": rg,
        "fault_family": FAULT_TYPES[fault_type],
        "injected_fault": {"fault_type": fault_type, "flag": flag, "variant": injection["fault"]["variant"]},
        "origin_service": origin,
        "affected_services": list(affected),
        "user_symptom": {"kinds": list(symptom_kinds), "description": symptom_description},
        "fault_start": injection["schedule"]["fault_on"],
        "fault_end": injection["schedule"]["fault_off"],
        "traffic_profile": profile,
        "seed": injection["seed"],
        "labeling": {"method": "catalog", "labeled_at": now, "labeler": labeler},
    }
    if notes:
        label["labeling"]["notes"] = notes
    # the label vocabulary is the 18 SUT services of the snapshot (decision 011)
    if problems := check_label(label, injection, services=load_policy().sut_services, manifest=manifest):
        raise ValueError(f"label of {incident_id} fails its checks: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(label, indent=2) + "\n")
    return label
