"""Synthetic Pilot / held-out records for the decision 023 tests: tiny generated files, never a real snapshot (user
decision 2026-10-09). Only the fields the held-out code reads are written."""

from __future__ import annotations

import json
from pathlib import Path

from collect.layout import DataLayout
from collect.pilot import PILOT
from collect.policy import load_policy
from test_records import injection

FREEZE_SHA = "sha256:" + "f" * 64
LOCK = "sha256:" + "1" * 64
COMMIT = "c" * 40
FROZEN_AT = "2026-10-20T00:00:00Z"
AFTER = "2026-10-21T00:00:00Z"
BEFORE = "2026-10-19T00:00:00Z"
POLICY = {"version": 1, "sha256": load_policy().sha256}


def entry(flag: str, variant: str) -> dict:
    return next(e for e in PILOT if (e["flag"], e["variant"]) == (flag, variant))


def a_priori(flag: str, variant: str) -> dict:
    e = entry(flag, variant)
    return {"affected_services": list(e["affected"]),
            "user_symptom": {"kinds": list(e["symptom_kinds"]), "description": e["description"]}, "notes": e["notes"]}


def write_run(layout: DataLayout, rg: str, flag: str, variant: str, status: str = "valid", *, inc: str | None = None,
              split: str | None = "pilot", seed: int | None = None, slot: str | None = None, freeze_sha: str | None = None,
              up_at: str = AFTER, commit: str | None = COMMIT, dirty: bool = False, lock: str = LOCK,
              injection_split: str | None = None, power: dict | None = None, **plan_extra) -> dict:
    """run.json (and injection.json for a valid run) of one run group; the incident's truth directory is created."""
    truth = layout.run_group_truth_dir(rg)
    truth.mkdir(parents=True)
    plan = {"run_group_id": rg, "seed": int(rg[3:]) if seed is None else seed, "flag": flag, "variant": variant,
            "fault_minutes": 10, "recovery_base_minutes": 5, "recovery_jitter_minutes": 5, "normal_base_minutes": 10,
            "normal_jitter_minutes": 5}
    if split is not None:
        plan["split"] = split
    if slot is not None:
        plan["slot"] = slot
    if freeze_sha is not None:
        plan["freeze_sha256"] = freeze_sha
    plan.update(plan_extra)
    incs = [inc] if inc and status == "valid" else []
    run = {"run_group_id": rg, "plan": plan, "status": status, "incident_ids": incs, "up_at": up_at,
           "env_lock_sha256": lock,
           "provenance": {"project": {"commit": commit, "dirty": dirty}, "machine": {"role": "mac", "power": power}}}
    (truth / "run.json").write_text(json.dumps(run))
    if incs:
        layout.injection_path(rg).write_text(json.dumps(injection(
            run_group_id=rg, incident_ids=incs, split=injection_split or split or "pilot", seed=plan["seed"],
            fault={"mechanism": "flagd", "flag": flag, "variant": variant})))
        layout.label_path(inc).parent.mkdir(parents=True, exist_ok=True)
    return run


def write_review(layout: DataLayout, inc: str, flag: str, variant: str, *, exercised: bool = True, saw: bool = False,
                 **values) -> None:
    """label.reviewed.json + label_review.json; `values` (affected_services / user_symptom / notes) override the a priori."""
    base = a_priori(flag, variant)
    final = {**base, **values}
    differences = []
    if sorted(final["affected_services"]) != sorted(base["affected_services"]):
        differences.append({"field": "affected_services", "reason": "seen"})
    if (sorted(final["user_symptom"]["kinds"]), final["user_symptom"].get("description") or "") != (
            sorted(base["user_symptom"]["kinds"]), base["user_symptom"]["description"] or ""):
        differences.append({"field": "user_symptom", "reason": "seen"})
    if (final["notes"] or "") != (base["notes"] or ""):
        differences.append({"field": "notes", "reason": "seen"})
    d = layout.label_path(inc).parent
    d.mkdir(parents=True, exist_ok=True)
    labeling = {"method": "catalog+review", "labeler": "human:t"}
    if final["notes"]:
        labeling["notes"] = final["notes"]
    (d / "label.reviewed.json").write_text(json.dumps({
        "incident_id": inc, "affected_services": final["affected_services"], "user_symptom": final["user_symptom"],
        "labeling": labeling}))
    (d / "label_review.json").write_text(json.dumps({
        "review_version": 1, "incident_id": inc, "fault_exercised": exercised, "saw_method_outputs": saw,
        "differences": differences}))


def write_audit(layout: DataLayout, inc: str, hits: int = 0) -> None:
    layout.label_path(inc).with_name("leakage_audit.json").write_text(json.dumps(
        {"incident_id": inc, "difficulty": "easy", "lexicon_hits": hits}))


def complete_pilot(layout: DataLayout, faults=None, *, start: int = 1) -> int:
    """One valid, reviewed (exercised, blind) and audited Pilot incident per fault; returns the next free number."""
    n = start
    for e in faults if faults is not None else PILOT:
        write_run(layout, f"RG-{n:03d}", e["flag"], e["variant"], inc=f"INC-{n:03d}", up_at=BEFORE)
        write_review(layout, f"INC-{n:03d}", e["flag"], e["variant"])
        write_audit(layout, f"INC-{n:03d}")
        n += 1
    return n


def plan_doc(entries=None, removed=()) -> dict:
    """A held-out plan in the docs/heldout/plan.json shape: `entries` kept, `removed` (flag, variant) pairs removed."""
    entries = [dict(e) for e in (entries if entries is not None else PILOT)]
    return {"heldout_plan_version": 1, "decision": "023 §1", "source": "PLANS[\"pilot\"] (decision 016)",
            "entries": entries, "amended": [], "not_absorbed": [],
            "removed": [{"flag": f, "variant": v, "basis": "pipeline", "reason": "test", "decision": "docs/decisions/001-x.md",
                         "evidence": {}} for f, v in removed],
            "methods_with_pilot_results": ["stat-anomaly"]}


def write_project(project: Path, plan: dict, *, k: int = 1, freeze: dict | None = None) -> dict:
    """docs/heldout/plan.json, slots.json and freeze.json under a tmp project directory; returns the slots doc."""
    from collect.heldout import FREEZE_FILE, PLAN_FILE, SLOTS_FILE, heldout_slots

    faults = [[e["flag"], e["variant"]] for e in plan["entries"]]
    slots = {"slots_version": 1, "decision": "023 §4", "master_seed": 20261009, "k": k, "plan_sha256": "sha256:p",
             "faults": faults, "slots": heldout_slots(faults, k=k)}
    for path, doc in ((PLAN_FILE, plan), (SLOTS_FILE, slots),
                      (FREEZE_FILE, freeze if freeze is not None else freeze_record())):
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text(json.dumps(doc, indent=2) + "\n")
    return slots


def freeze_record(**overrides) -> dict:
    record = {"freeze_version": 1, "frozen_at": FROZEN_AT, "frozen_from_commit": "a" * 40, "env_lock_sha256": LOCK,
              "policy": dict(POLICY), "k": 1, "master_seed": 20261009,
              "plan": {"path": "docs/heldout/plan.json", "sha256": "sha256:p"},
              "slots": {"path": "docs/heldout/slots.json", "sha256": "sha256:s"}}
    record.update(overrides)
    return record


def passing_freeze(monkeypatch, record: dict | None = None) -> None:
    """collect.freeze.check_freeze passes (the git-facing check has its own tests)."""
    import collect.freeze as freeze

    monkeypatch.setattr(freeze, "check_freeze", lambda project_dir, run=None: (record or freeze_record(), []))


def write_heldout_incident(layout: DataLayout, n: int, slot: dict, *, freeze_sha: str = FREEZE_SHA, entry: dict | None = None,
                           exercised: bool = True, saw: bool = False, hits: int = 0, commit: str = COMMIT,
                           code: dict | None = None, policy: dict | None = None, project: dict | None = None,
                           **run_kw) -> str:
    """A processed, audited and reviewed held-out incident RG-nnn / INC-nnn filling `slot`; returns the incident id."""
    rg, inc = f"RG-{n:03d}", f"INC-{n:03d}"
    flag, variant = slot["flag"], slot["variant"]
    write_run(layout, rg, flag, variant, inc=inc, split="heldout", slot=slot["slot"], freeze_sha=freeze_sha, commit=commit,
              **run_kw)
    e = entry or globals()["entry"](flag, variant)
    labeling = {"method": "catalog", "labeler": "agent:t"}
    if e["notes"]:
        labeling["notes"] = e["notes"]
    layout.label_path(inc).write_text(json.dumps({
        "incident_id": inc, "run_group_id": rg, "origin_service": e["origin"], "affected_services": list(e["affected"]),
        "user_symptom": {"kinds": list(e["symptom_kinds"]), "description": e["description"]}, "labeling": labeling}))
    snap = layout.incident_dir(inc) / "normalized"
    snap.mkdir(parents=True)
    (snap / "snapshot.json").write_text("{}")
    layout.normalize_report_path(inc).write_text(json.dumps({
        "policy": policy or dict(POLICY), "code": code or {"commit": commit, "dirty": False}}))
    layout.manifest_path(inc).write_text(json.dumps({"incident_id": inc, "project": project or {"commit": commit, "dirty": False}}))
    write_review(layout, inc, flag, variant, exercised=exercised, saw=saw)
    write_audit(layout, inc, hits)
    return inc
