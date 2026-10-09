"""The held-out set (decision 023; implementation decision 026): its fault plan, slot list, collection progress and the
verified incident list. No git here (collect.freeze is the only git-facing held-out module).

Paths are relative to an explicit project directory, so tests never reach the real repository. Every committed held-out
file describes only the design: never an incident or run-group id.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

HELDOUT_DIR = Path("docs/heldout")
PLAN_FILE = HELDOUT_DIR / "plan.json"
SLOTS_FILE = HELDOUT_DIR / "slots.json"
FREEZE_FILE = HELDOUT_DIR / "freeze.json"

HELDOUT_K = 5  # user decision 2026-10-09: 5 incidents per fault, each its own seed and run group
HELDOUT_MASTER_SEED = 20261009  # decision 023 §4
MAX_SLOTS_NEEDING_PERSON = 3  # decision 023 §4: three slots waiting for a person stop the collection
FAULT_MINUTES = 10  # decision 023 §3

ID = re.compile(r"(INC|RG)-[0-9]{3,}")


def doc_bytes(doc: dict) -> bytes:
    """How plan, slots, freeze and heldout_incidents are written (keys in construction order)."""
    return (json.dumps(doc, indent=2) + "\n").encode()


def doc_sha256(doc: dict) -> str:
    """sha256 of the bytes write_once writes for `doc` (= env.lock.sha256_path of the written file)."""
    return "sha256:" + hashlib.sha256(doc_bytes(doc)).hexdigest()


def write_once(path: Path, doc: dict) -> str:
    """Exclusive create: a held-out record is written once and never replaced. Returns its sha256."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(doc_bytes(doc))
    return doc_sha256(doc)


def run_split(record: dict) -> str:
    """The set of a run record; a record without a split was collected before `--set` existed: Pilot (decision 010)."""
    return (record.get("plan") or {}).get("split", "pilot")


AMENDABLE = {"affected_services": ("affected",), "user_symptom": ("symptom_kinds", "description"), "notes": ("notes",)}
REMOVAL_BASES = ("not_exercised", "invalid_rate", "lexicon_hits", "pipeline", "label")
DECISION_BASES = ("pipeline", "label")


def _json(path: Path):
    return json.loads(Path(path).read_text())


def _run_groups(layout) -> list[tuple[dict, dict | None]]:
    """(run.json, injection.json or None) of every stored run group. The two records must agree on the set, in either
    direction (SPEC §10: a run group never crosses splits); a run group directory without run.json is an unfinished store
    that a person looks at first. Both raise ValueError."""
    out = []
    root = layout.ground_truth_root / "run_groups"
    for d in sorted(root.glob("RG-*")) if root.exists() else []:
        if not (d / "run.json").exists():
            raise ValueError(f"{d.name} has no run.json (an unfinished store): a person looks at it before any held-out step")
        run = _json(d / "run.json")
        injection = _json(d / "injection.json") if (d / "injection.json").exists() else None
        if injection is not None and injection.get("split") != run_split(run):
            raise ValueError(f"{d.name}: run.json says set {run_split(run)!r} but injection.json says {injection.get('split')!r}")
        out.append((run, injection))
    return out


def heldout_runs(layout) -> list[dict]:
    """Every held-out run record (the only reader of the held-out split in new code, through run_split)."""
    return [run for run, _ in _run_groups(layout) if run_split(run) == "heldout"]


def plan_entries(project_dir: Path) -> tuple[dict, ...]:
    path = Path(project_dir) / PLAN_FILE
    if not path.exists():
        raise LookupError("no fault plan for the 'heldout' set yet (decision 023 §1: written after the Pilot review)")
    return tuple(_json(path)["entries"])


def _review_paths(layout, inc: str) -> tuple[Path, Path]:
    base = layout.label_path(inc)
    return base.with_name("label.reviewed.json"), base.with_name("label_review.json")


def _lexicon_hits(layout, inc: str) -> int | None:
    path = layout.label_path(inc).with_name("leakage_audit.json")
    return _json(path)["lexicon_hits"] if path.exists() else None


def _a_priori_values(entry: dict) -> dict:
    """An entry's values in the review's field names (collect.review._differences)."""
    return {"affected_services": list(entry["affected"]),
            "user_symptom": {"kinds": list(entry["symptom_kinds"]), "description": entry["description"]},
            "notes": entry["notes"]}


def _reviewed_values(label: dict) -> dict:
    return {"affected_services": list(label["affected_services"]), "user_symptom": dict(label["user_symptom"]),
            "notes": (label.get("labeling") or {}).get("notes")}


def _canon(field: str, value):
    """Comparable form of a review field value: lists sorted, user_symptom as a whole object. TypeError when malformed."""
    if field == "affected_services":
        if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
            raise TypeError("affected_services must be a list of service names")
        return tuple(sorted(value))
    if field == "user_symptom":
        if not isinstance(value, dict) or not set(value) <= {"kinds", "description"} or "kinds" not in value:
            raise TypeError("user_symptom must be a whole {kinds, description} object")
        kinds, description = value["kinds"], value.get("description") or ""
        if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds) or not isinstance(description, str):
            raise TypeError("user_symptom.kinds must be a list and user_symptom.description a string")
        return tuple(sorted(kinds)), description
    if value is not None and not isinstance(value, str):
        raise TypeError("notes must be a string or null")
    return value or None


def pilot_evidence(layout) -> dict:
    """Per Pilot fault (PILOT order): valid incidents, non-valid run groups, reviewed incidents (exercised, saw method
    outputs, final review-field values, recorded differences, lexicon hits), unreviewed incidents and audits. The ids
    stay here: what goes into plan.json is counts only. A withdrawn incident is no evidence and no invalid attempt
    (decision 025 revision 3)."""
    from collect.pilot import PILOT, withdrawn

    ev = {(e["flag"], e["variant"]): {"valid": [], "non_valid": [], "reviews": [], "unreviewed": [], "audits": {}}
          for e in PILOT}
    gone = withdrawn(layout)
    for run, _ in _run_groups(layout):
        plan = run.get("plan") or {}
        key = (plan.get("flag"), plan.get("variant"))
        if run_split(run) != "pilot" or key not in ev:
            continue
        if run.get("status") != "valid":
            ev[key]["non_valid"].append(run["run_group_id"])
            continue
        for inc in run.get("incident_ids") or []:
            if inc in gone:
                continue
            ev[key]["valid"].append(inc)
            ev[key]["audits"][inc] = _lexicon_hits(layout, inc)
            label_path, record_path = _review_paths(layout, inc)
            if not (label_path.exists() and record_path.exists()):
                ev[key]["unreviewed"].append(inc)
                continue
            record = _json(record_path)
            ev[key]["reviews"].append({
                "incident_id": inc, "exercised": record.get("fault_exercised") is True,
                "saw": record.get("saw_method_outputs") is not False, "values": _reviewed_values(_json(label_path)),
                "differs": sorted({d["field"] for d in record.get("differences") or []}),
                "lexicon_hits": ev[key]["audits"][inc]})
    return ev


def pilot_problems(layout, removed: set) -> list[str]:
    """decision 023 §4 "Pilot or its review not complete": every valid Pilot incident has label.reviewed.json and
    label_review.json; every Pilot fault not removed has a reviewed incident with fault_exercised = true (§1). A withdrawn
    incident counts for no set (decision 025 revision 3)."""
    from collect.pilot import PILOT, withdrawn

    problems, gone = [], withdrawn(layout)
    for run, _ in _run_groups(layout):
        if run_split(run) == "pilot" and run.get("status") == "valid":
            for inc in run.get("incident_ids") or []:
                if inc not in gone and not all(p.exists() for p in _review_paths(layout, inc)):
                    problems.append(f"Pilot incident {inc} is not reviewed yet (label.reviewed.json and label_review.json, "
                                    "decision 018)")
    ev = pilot_evidence(layout)
    for e in PILOT:
        key = (e["flag"], e["variant"])
        if key not in removed and not any(r["exercised"] for r in ev[key]["reviews"]):
            problems.append(f"{e['flag']} {e['variant']}: no reviewed Pilot incident with fault_exercised = true "
                            "(decision 023 §1)")
    return problems


def removal_evidence(ev: dict) -> dict:
    """The counts plan.json records for a removed fault (never ids)."""
    return {"reviewed_exercised": sum(r["exercised"] for r in ev["reviews"]),
            "reviewed_unexercised": sum(not r["exercised"] for r in ev["reviews"]),
            "non_valid_run_groups": len(ev["non_valid"]),
            "lexicon_hit_incidents": sum(1 for h in ev["audits"].values() if h)}


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _text_problems(where: str, reason, *values) -> list[str]:
    problems = []
    if not isinstance(reason, str) or not reason.strip():
        problems.append(f"{where}: a reason is required (decision 023 §1)")
    if any(ID.search(s) for s in _strings([reason, *values])):
        problems.append(f"{where}: no incident or run-group id may appear in committed text (plan.json describes the design)")
    return problems


def symptom_kinds() -> tuple[str, ...]:
    schema = _json(Path(__file__).resolve().parent.parent / "schemas" / "incident_label.schema.json")
    return tuple(schema["properties"]["user_symptom"]["properties"]["kinds"]["items"]["enum"])


def entry_problems(entry: dict, services) -> list[str]:
    """The PILOT entry rules (tests/test_pilot.py): origin ∈ affected ⊆ the SUT services; kinds in the vocabulary,
    unique, and ["none"] alone."""
    name, kinds, affected = f"{entry['flag']} {entry['variant']}", entry["symptom_kinds"], entry["affected"]
    problems = []
    if entry["origin"] not in affected:
        problems.append(f"{name}: the origin {entry['origin']!r} must stay in affected (decision 006 §5)")
    if unknown := sorted(set(affected) - set(services)):
        problems.append(f"{name}: {unknown} are not services of the snapshot (decision 011)")
    if len(set(affected)) != len(affected):
        problems.append(f"{name}: affected lists a service twice")
    if not kinds or len(set(kinds)) != len(kinds) or not set(kinds) <= set(symptom_kinds()):
        problems.append(f"{name}: symptom kinds {kinds} are not unique kinds of {symptom_kinds()}")
    if "none" in kinds and kinds != ["none"]:
        problems.append(f"{name}: symptom kind 'none' stands alone")
    return problems


def _removal_problems(name: str, basis, decision, e: dict, ev: dict, decision_files: set) -> list[str]:
    """User decision 5: removal only on Pilot validation evidence, checked against the Pilot data; never a score."""
    from collect.pilot import MAX_INVALID_ATTEMPTS

    exercised = [r for r in ev["reviews"] if r["exercised"]]
    if basis not in REMOVAL_BASES:
        return [f"{name}: removal basis {basis!r} is not one of {REMOVAL_BASES} (a method score is never a basis)"]
    if basis in DECISION_BASES:
        if not isinstance(decision, str) or decision not in decision_files:
            return [f"{name}: a {basis} removal names its decision file at HEAD (got {decision!r})"]
        return []
    if decision is not None:
        return [f"{name}: only a pipeline or label removal names a decision"]
    if basis == "not_exercised" and not (e["reviewed_exercised"] == 0 and e["reviewed_unexercised"] >= 2):
        return [f"{name}: not_exercised needs no exercised review and two unexercised ones (016 §5: one recollection), "
                f"found {e['reviewed_exercised']} / {e['reviewed_unexercised']}"]
    if basis == "invalid_rate" and not (e["non_valid_run_groups"] >= MAX_INVALID_ATTEMPTS and not exercised):
        return [f"{name}: invalid_rate needs {MAX_INVALID_ATTEMPTS} non-valid Pilot run groups and no exercised review, "
                f"found {e['non_valid_run_groups']} / {len(exercised)}"]
    if basis == "lexicon_hits" and not (e["lexicon_hit_incidents"] and all(r["lexicon_hits"] for r in exercised)):
        return [f"{name}: lexicon_hits needs a Pilot incident with lexicon hits and no clean exercised incident"]
    return []


def build_heldout_plan(evidence: dict, amendments: dict, *, decision_files: set, methods_with_results) -> dict:
    """PLANS["heldout"] (decision 023 §1): the Pilot plan, absorbing only differences that every exercised blind review of
    a fault found, and removing faults only on Pilot validation evidence. Raises ValueError listing every problem."""
    from collect.pilot import PILOT
    from collect.policy import load_policy

    pilot = {(e["flag"], e["variant"]): e for e in PILOT}
    problems: list[str] = []
    if not isinstance(amendments, dict) or set(amendments) - {"amend", "remove"}:
        raise ValueError("held-out plan refused: the amendments file has only 'amend' and 'remove' lists")
    amend, remove = list(amendments.get("amend") or []), list(amendments.get("remove") or [])
    if not all(isinstance(a, dict) for a in amend + remove):
        raise ValueError("held-out plan refused: every amendment and removal is an object")

    removed, seen_fields = {}, set()
    for r in remove:
        key, name = (r.get("flag"), r.get("variant")), f"{r.get('flag')} {r.get('variant')}"
        if extra := sorted(set(r) - {"flag", "variant", "basis", "reason", "decision"}):
            problems.append(f"remove {name}: unknown keys {extra}")
        if key not in pilot:
            problems.append(f"remove {name}: not a Pilot fault (decision 023 §1: only the 016 faults and variants)")
            continue
        if key in removed:
            problems.append(f"remove {name}: removed twice")
        problems += _text_problems(f"remove {name}", r.get("reason"), r.get("decision"))
        e = removal_evidence(evidence[key])
        problems += _removal_problems(name, r.get("basis"), r.get("decision"), e, evidence[key], decision_files)
        removed[key] = {"flag": key[0], "variant": key[1], "basis": r.get("basis"), "reason": r.get("reason"),
                        "decision": r.get("decision"), "evidence": e}

    entries = {key: dict(e) for key, e in pilot.items()}
    amended = []
    for a in amend:
        key, field, name = (a.get("flag"), a.get("variant")), a.get("field"), f"{a.get('flag')} {a.get('variant')}"
        if extra := sorted(set(a) - {"flag", "variant", "field", "value", "reason"}):
            problems.append(f"amend {name}: unknown keys {extra}")
        if key not in pilot:
            problems.append(f"amend {name}: not a Pilot fault (decision 023 §1: only the 016 faults and variants)")
            continue
        if field not in AMENDABLE:
            problems.append(f"amend {name}: {field!r} cannot be amended (only {sorted(AMENDABLE)}; origin, flag and variant "
                            "never change, 018 §2)")
            continue
        if key in removed:
            problems.append(f"{name} is both amended and removed")
            continue
        if (key, field) in seen_fields:
            problems.append(f"amend {name}: {field} amended twice")
            continue
        seen_fields.add((key, field))
        problems += _text_problems(f"amend {name} {field}", a.get("reason"), a.get("value"))
        eligible = [r for r in evidence[key]["reviews"] if r["exercised"] and not r["saw"]]
        try:
            value = _canon(field, a.get("value"))
            agreed = {_canon(field, r["values"][field]) for r in eligible}
        except TypeError as err:
            problems.append(f"amend {name} {field}: {err}")
            continue
        before = _canon(field, _a_priori_values(pilot[key])[field])
        if not eligible:
            problems.append(f"amend {name} {field}: no review with fault_exercised = true and saw_method_outputs = false")
        elif len(agreed) > 1:
            problems.append(f"amend {name} {field}: the exercised blind reviews disagree ({len(agreed)} values)")
        elif agreed == {before}:
            problems.append(f"amend {name} {field}: the reviews found no difference from the a priori label")
        elif value != next(iter(agreed)):
            problems.append(f"amend {name} {field}: the value is not the one the reviews found")
        else:
            v = a["value"]
            entry = entries[key]
            if field == "affected_services":
                entry["affected"] = list(v)
            elif field == "user_symptom":
                entry["symptom_kinds"], entry["description"] = list(v["kinds"]), v.get("description") or ""
            else:
                entry["notes"] = v or None
            amended.append({"flag": key[0], "variant": key[1], "field": field,
                            "a_priori": _a_priori_values(pilot[key])[field], "heldout": v, "reason": a["reason"],
                            "reviews": len(eligible)})

    services = load_policy().sut_services
    kept = [entries[key] for key in pilot if key not in removed]
    for entry in kept:
        problems += entry_problems(entry, services)
        if not any(r["exercised"] for r in evidence[(entry["flag"], entry["variant"])]["reviews"]):
            problems.append(f"{entry['flag']} {entry['variant']}: no reviewed Pilot incident with fault_exercised = true; "
                            "it is kept only with one, or removed on its evidence (decision 023 §1)")
    if problems:
        raise ValueError("held-out plan refused: " + "; ".join(problems))

    not_absorbed = []
    for key in pilot:
        reviews = evidence[key]["reviews"]
        eligible = [r for r in reviews if r["exercised"] and not r["saw"]]
        for field in AMENDABLE:
            differing = [r for r in reviews if field in r["differs"]]
            if not differing or (key, field) in seen_fields:
                continue
            if not any(r["exercised"] for r in differing):
                why = "not_exercised"
            elif all(r["saw"] for r in differing if r["exercised"]):
                why = "saw_method_outputs"
            elif len({_canon(field, r["values"][field]) for r in eligible}) > 1:
                why = "reviews disagree"
            else:
                why = "not absorbed"
            not_absorbed.append({"flag": key[0], "variant": key[1], "field": field, "reviews": len(differing), "why": why})

    return {"heldout_plan_version": 1, "decision": "023 §1", "source": "PLANS[\"pilot\"] (decision 016)",
            "entries": kept, "amended": amended, "not_absorbed": not_absorbed,
            "removed": [removed[key] for key in pilot if key in removed],
            "methods_with_pilot_results": sorted(methods_with_results)}


def heldout_slots(faults, k: int = HELDOUT_K, seed: int = HELDOUT_MASTER_SEED) -> list[dict]:
    """decision 023 §4: k blocks, each a Fisher–Yates permutation of the plan-ordered faults driven only by
    Random(seed).random() (its sequence is fixed for an int seed; random.shuffle's algorithm is not); slots H01.."""
    rng = random.Random(seed)
    slots = []
    for block in range(1, k + 1):
        order = [list(f) for f in faults]
        for i in range(len(order) - 1, 0, -1):
            j = int(rng.random() * (i + 1))
            order[i], order[j] = order[j], order[i]
        for flag, variant in order:
            slots.append({"slot": f"H{len(slots) + 1:02d}", "block": block, "flag": flag, "variant": variant})
    return slots


def _slot_detail(layout, slots_doc: dict, *, freeze_sha: str) -> list[dict]:
    """Per slot, in slot order: its state and, internally, the ids behind it. Raises ValueError on any corrupt or
    mismatched held-out record, including one collected under another freeze record (fail closed, never filtered).
    A withdrawn run group (decision 025 revision 3) fills nothing and is no invalid attempt: its slot is collected again."""
    from collect.pilot import MAX_INVALID_ATTEMPTS, withdrawals

    slots = {s["slot"]: s for s in slots_doc["slots"]}
    detail = {name: {"usable": [], "unexercised": [], "non_valid": [], "valid": [], "power": [], "withdrawn": []}
              for name in slots}
    gone = withdrawals(layout)
    for run, injection in _run_groups(layout):
        if run_split(run) != "heldout":
            continue
        rg, plan = run["run_group_id"], run.get("plan") or {}
        slot = plan.get("slot")
        if slot not in slots:
            raise ValueError(f"{rg} is a held-out run group with {'no' if slot is None else 'an unknown'} slot {slot!r}")
        s = slots[slot]
        if (plan.get("flag"), plan.get("variant")) != (s["flag"], s["variant"]):
            raise ValueError(f"{rg}: {plan.get('flag')} {plan.get('variant')} is not slot {slot}'s fault")
        if plan.get("freeze_sha256") != freeze_sha:
            raise ValueError(f"{rg} was collected under freeze record {plan.get('freeze_sha256')}, not the one in force "
                             f"({freeze_sha}): held-out work stops until a person decides (decision 023 §6)")
        d = detail[slot]
        w = gone.get(rg)
        if w is not None and (run.get("status") != "valid" or w.get("run_group_id") != rg
                              or w.get("incident_ids") != (run.get("incident_ids") or [])):
            raise ValueError(f"{rg}: its withdrawal record does not match its run record (decision 025 revision 3)")
        if run.get("status") != "valid":
            d["non_valid"].append(rg)  # invalid and every aborted_* status, counted cumulatively (decision 009 §4)
            continue
        fault = (injection or {}).get("fault") or {}
        if (fault.get("flag"), fault.get("variant")) != (s["flag"], s["variant"]):
            raise ValueError(f"{rg}: its injection record does not name slot {slot}'s fault")
        if w is not None:  # kept on disk, counted for no set, not an invalid attempt
            d["withdrawn"].append({"run_group_id": rg, "incident_ids": w["incident_ids"], "reason": w["reason"]})
            continue
        d["valid"].append(rg)
        d["power"].append(((run.get("provenance") or {}).get("machine") or {}).get("power"))  # decision 025
        for inc in run.get("incident_ids") or []:
            review = _review_paths(layout, inc)[1]
            unexercised = review.exists() and _json(review).get("fault_exercised") is False
            d["unexercised" if unexercised else "usable"].append(inc)
    out = []
    for s in slots_doc["slots"]:
        d = detail[s["slot"]]
        if len(d["usable"]) > 1 or len(d["unexercised"]) > 2:
            raise ValueError(f"{s['slot']} holds {len(d['usable'])} usable and {len(d['unexercised'])} unexercised incidents: "
                             "a slot holds one incident, recollected at most once (decision 023 §4, §5.3)")
        state = ("filled" if d["usable"] else "needs_person" if len(d["non_valid"]) >= MAX_INVALID_ATTEMPTS
                 else "closed" if len(d["unexercised"]) == 2 else "open")
        out.append({**s, "state": state, **d})
    return out


def slot_status(layout, slots_doc: dict, *, freeze_sha: str) -> list[dict]:
    """Public per-slot progress: slot, fault, state, counts, non-valid run-group ids and the power settings of valid run
    groups (decision 025). Never an incident id or a valid (or withdrawn) run-group id (held-out ids would map to faults)."""
    return [{"slot": d["slot"], "block": d["block"], "flag": d["flag"], "variant": d["variant"], "state": d["state"],
             "counts": {"usable": len(d["usable"]), "unexercised": len(d["unexercised"]), "non_valid": len(d["non_valid"]),
                        "withdrawn": len(d["withdrawn"])},
             "non_valid_run_groups": d["non_valid"], "power": d["power"]}
            for d in _slot_detail(layout, slots_doc, freeze_sha=freeze_sha)]


def next_slot(layout, slots_doc: dict, *, freeze_sha: str) -> dict | None:
    """The first open slot (with the needs-person slots skipped), or None when every slot is filled or closed. RuntimeError
    when MAX_SLOTS_NEEDING_PERSON slots wait for a person, or when nothing else is open (decision 023 §4)."""
    status = slot_status(layout, slots_doc, freeze_sha=freeze_sha)
    needs = [{"slot": s["slot"], "non_valid_run_groups": s["non_valid_run_groups"]} for s in status
             if s["state"] == "needs_person"]
    if len(needs) >= MAX_SLOTS_NEEDING_PERSON:
        raise RuntimeError(f"{len(needs)} slots need a person ({needs}): every held-out collection stops, the stack itself "
                           "may be the problem (decision 023 §4)")
    first = next((s for s in status if s["state"] == "open"), None)
    if first is None:
        if needs:
            raise RuntimeError(f"no slot is open and {needs} need a person: the set is not complete (decision 023 §4)")
        return None
    return {**first, "skipped": needs}


def fresh_seed(layout, rng=None) -> int:
    """decision 023 §4: SystemRandom, redrawn until no run group of any set used it (009 §4: new run group, new seed)."""
    used = {(run.get("plan") or {}).get("seed") for run, _ in _run_groups(layout)}
    rng = rng or random.SystemRandom()
    while (seed := rng.randrange(2**31)) in used:
        pass
    return seed


TIMING = ("normal_base_minutes", "normal_jitter_minutes", "recovery_base_minutes", "recovery_jitter_minutes")
NOT_EXERCISED = "fault not exercised (016 §5, 023 §5.3)"


def pinned_paths(layout, incident_id: str, run_group_id: str) -> dict[str, Path]:
    """The 8 files heldout_incidents.json pins per listed incident (decision 023 §5.5)."""
    base = layout.label_path(incident_id)
    return {"label": base, "label_reviewed": base.with_name("label.reviewed.json"),
            "label_review": base.with_name("label_review.json"), "leakage_audit": base.with_name("leakage_audit.json"),
            "manifest": layout.manifest_path(incident_id), "normalize_report": layout.normalize_report_path(incident_id),
            "injection": layout.injection_path(run_group_id), "run": layout.run_group_truth_dir(run_group_id) / "run.json"}


def _number(run_group_id: str) -> int:
    return int(run_group_id.split("-")[1])


def _after(ts, frozen_at: str) -> bool:
    from datetime import datetime

    try:
        return datetime.fromisoformat(ts) > datetime.fromisoformat(frozen_at)
    except (TypeError, ValueError):
        return False


def _run_group_problems(run: dict, freeze: dict, commit_check, pilot_max: int) -> list[str]:
    """Is this held-out run group from the frozen code, after the freeze, with 023 §3's timing? (§4, §6; SPEC §10)"""
    from dataclasses import fields

    from collect.rungroup import Plan

    defaults = {f.name: f.default for f in fields(Plan)}
    rg, plan = run["run_group_id"], run.get("plan") or {}
    project = (run.get("provenance") or {}).get("project") or {}
    problems = []
    if run.get("env_lock_sha256") != freeze["env_lock_sha256"]:
        problems.append(f"{rg}: collected under another env lock than the freeze record (user decision 6: excluded, never mixed)")
    if project.get("dirty") is not False:
        problems.append(f"{rg}: collected from a checkout that was not clean")
    problems += [f"{rg}: {p}" for p in commit_check(project.get("commit"))]
    if not _after(run.get("up_at"), freeze["frozen_at"]):
        problems.append(f"{rg}: started before the freeze record or without a start time ({run.get('up_at')} vs "
                        f"{freeze['frozen_at']})")
    if _number(rg) <= pilot_max:
        problems.append(f"{rg}: numbered below a Pilot run group (held-out run groups come after the Pilot)")
    if plan.get("fault_minutes") != FAULT_MINUTES or any(plan.get(k) != defaults[k] for k in TIMING):
        problems.append(f"{rg}: its fault, normal or recovery lengths are not 023 §3's")
    return problems


def _power_evidence_problems(run: dict) -> list[str]:
    """decision 025 revisions 2, 3 hold for every formal set: a valid held-out run group started on the formal power and
    _judge found its whole window on it (power samples taken, none off). A withdrawn run group is not checked."""
    from collect.provenance import power_problems

    rg = run["run_group_id"]
    start = ((run.get("provenance") or {}).get("machine") or {}).get("power")
    problems = [f"{rg}: started off the formal power: {p}" for p in power_problems(start)]
    if not run.get("power_samples") or run.get("power_not_formal") or "power_not_formal" in (run.get("reasons") or []):
        problems.append(f"{rg}: valid without window power samples all on the formal power (decision 025 revision 2)")
    return problems


def _incident_problems(layout, inc: str, rg: str, run: dict, entry: dict | None, freeze: dict, commit_check) -> list[str]:
    paths = pinned_paths(layout, inc, rg)
    missing = [name for name, p in paths.items() if not p.exists()]
    if not (layout.incident_dir(inc) / "normalized" / "snapshot.json").exists():
        missing.append("snapshot")
    if missing:
        return [f"{inc}: no {missing} yet (process, leakage audit and blind review come first, decision 023 §5)"]
    problems = []
    report = _json(paths["normalize_report"])
    if report.get("policy") != freeze["policy"]:
        problems.append(f"{inc}: normalized with policy {report.get('policy')}, not the frozen {freeze['policy']}")
    code = report.get("code") or {}
    if code.get("dirty") is not False:
        problems.append(f"{inc}: normalized from a checkout that was not clean")
    problems += [f"{inc} normalize: {p}" for p in commit_check(code.get("commit"))]
    if _json(paths["manifest"]).get("project") != ((run.get("provenance") or {}).get("project")):
        problems.append(f"{inc}: the manifest's project is not its run's")
    label = _json(paths["label"])
    if entry is None or (label.get("origin_service"), label.get("affected_services"), label.get("user_symptom"),
                         (label.get("labeling") or {}).get("notes")) != (
            entry["origin"], entry["affected"], {"kinds": entry["symptom_kinds"], "description": entry["description"]},
            entry["notes"]):
        problems.append(f"{inc}: its a priori label is not the plan entry (decision 023 §1)")
    if _json(paths["label_review"]).get("saw_method_outputs") is not False:
        problems.append(f"{inc}: reviewed with saw_method_outputs not false (decision 023 §5.2, 018 §7)")
    return problems


def heldout_incidents(layout, slots_doc: dict, plan_doc: dict, *, freeze: dict, freeze_sha: str, results_root: Path,
                      commit_check, now: str) -> dict:
    """The held-out incident list (decision 023 §5.5), or ValueError listing every problem. `commit_check(commit)` names
    why a run's or a normalize's commit is not the frozen code (the CLI passes collect.freeze.commit_problems)."""
    detail = _slot_detail(layout, slots_doc, freeze_sha=freeze_sha)  # raises on a corrupt or foreign record
    problems = [f"{d['slot']} is {d['state']}: every slot is filled or closed first (decision 023 §5)" for d in detail
                if d["state"] in ("open", "needs_person")]
    out_dir = Path(results_root) / "heldout"
    if out_dir.exists() and (ran := sorted(p.name for p in out_dir.iterdir() if p.name != "leakage.md")):
        problems.append(f"results/heldout already holds {ran}: no method runs before the list exists (decision 023 §5.5)")
    groups = _run_groups(layout)
    entries = {(e["flag"], e["variant"]): e for e in plan_doc["entries"]}
    pilot_max = max((_number(r["run_group_id"]) for r, _ in groups if run_split(r) == "pilot"), default=0)
    runs = {r["run_group_id"]: r for r, _ in groups if run_split(r) == "heldout"}
    of = {inc: rg for rg, r in runs.items() for inc in r.get("incident_ids") or []}
    for run in runs.values():
        problems += _run_group_problems(run, freeze, commit_check, pilot_max)  # withdrawn ones too: no check is excused
    for d in detail:
        for rg in d["valid"]:
            problems += _power_evidence_problems(runs[rg])
        for inc in d["usable"] + d["unexercised"]:
            problems += _incident_problems(layout, inc, of[inc], runs[of[inc]], entries.get((d["flag"], d["variant"])),
                                           freeze, commit_check)
    seeds = [(r.get("plan") or {}).get("seed") for r, _ in groups]
    if repeated := sorted({s for s in seeds if seeds.count(s) > 1}, key=str):
        problems.append(f"seeds {repeated} are used by more than one run group (decision 009 §4)")
    incs = [i for r, _ in groups for i in r.get("incident_ids") or []]
    if repeated := sorted({i for i in incs if incs.count(i) > 1}):
        problems.append(f"incident ids {repeated} belong to more than one run group")
    if problems:
        raise ValueError("held-out list refused: " + "; ".join(problems))

    from env.lock import sha256_path

    listed, excluded, closed = [], [], []
    for d in detail:
        excluded += [{"slot": d["slot"], "incident_id": inc, "run_group_id": w["run_group_id"],
                      "reason": f"withdrawn: {w['reason']}"}
                     for w in d["withdrawn"] for inc in w["incident_ids"]]  # decision 025 revision 3
        excluded += [{"slot": d["slot"], "incident_id": inc, "run_group_id": of[inc], "reason": NOT_EXERCISED}
                     for inc in d["unexercised"]]
        if d["state"] == "filled":
            inc = d["usable"][0]
            hits = _json(pinned_paths(layout, inc, of[inc])["leakage_audit"])["lexicon_hits"]
            if hits:  # decision 015: no score; 023 gives no recollection for it
                excluded.append({"slot": d["slot"], "incident_id": inc, "run_group_id": of[inc],
                                 "reason": f"lexicon_hits={hits} (decision 015)"})
            else:
                listed.append({"slot": d["slot"], "incident_id": inc, "run_group_id": of[inc], "flag": d["flag"],
                               "variant": d["variant"],
                               "sha256": {k: sha256_path(p) for k, p in pinned_paths(layout, inc, of[inc]).items()}})
        elif d["state"] == "closed":
            closed.append({"slot": d["slot"], "flag": d["flag"], "variant": d["variant"], "incident_ids": d["unexercised"],
                           "reason": "fault not exercised twice: closed by default (decision 023 §5.3)"})
    by_fault = {}
    for flag, variant in slots_doc["faults"]:
        mine = [d["slot"] for d in detail if (d["flag"], d["variant"]) == (flag, variant)]
        have = {i["slot"] for i in listed}
        by_fault[f"{flag} {variant}"] = {"listed": len(set(mine) & have), "of": len(mine),
                                         "missing_slots": [s for s in mine if s not in have]}
    return {"heldout_incidents_version": 1, "created_at": now, "freeze_sha256": freeze_sha,
            "slots_sha256": freeze["slots"]["sha256"], "plan_sha256": freeze["plan"]["sha256"],
            "incidents": listed, "excluded": excluded, "closed_slots": closed,
            "removed_faults": [{k: r[k] for k in ("flag", "variant", "basis", "reason")} for r in plan_doc["removed"]],
            "run_groups": [[rg, runs[rg].get("status")] for rg in sorted(runs)],
            "withdrawn_run_groups": sorted(w["run_group_id"] for d in detail for w in d["withdrawn"]), "by_fault": by_fault}


def load_heldout_incidents(layout, *, freeze_sha: str) -> dict:
    """The verified list: PermissionError when it is missing, belongs to another freeze, a pinned file changed, or the
    held-out run groups on disk, or the withdrawn ones, are not those it recorded (decision 023 §5: no method without the
    list; decision 025 revision 3)."""
    from collect.pilot import withdrawals
    from env.lock import sha256_path

    path = layout.heldout_incidents_path
    if not path.exists():
        raise PermissionError("no heldout_incidents.json: run `collect heldout-list` once every slot is filled or closed, "
                              "processed, audited and reviewed (decision 023 §5.5)")
    doc = _json(path)
    if doc.get("freeze_sha256") != freeze_sha:
        raise PermissionError(f"heldout_incidents.json belongs to freeze record {doc.get('freeze_sha256')}, not {freeze_sha}")
    problems = [f"{i['incident_id']}: {name} changed since the list was written"
                for i in doc["incidents"] for name, p in pinned_paths(layout, i["incident_id"], i["run_group_id"]).items()
                if not p.exists() or sha256_path(p) != i["sha256"].get(name)]
    try:
        runs = sorted(heldout_runs(layout), key=lambda r: r["run_group_id"])
    except ValueError as e:
        raise PermissionError(str(e)) from e
    if [[r["run_group_id"], r.get("status")] for r in runs] != doc["run_groups"]:
        problems.append("the held-out run groups on disk are not those the list recorded (one was added or changed after it)")
    held = {r["run_group_id"] for r in runs}
    if sorted(rg for rg in withdrawals(layout) if rg in held) != doc.get("withdrawn_run_groups"):
        problems.append("the withdrawn held-out run groups on disk are not those the list recorded (a withdrawal was added or "
                        "taken back after it; decision 023 §5.5, §6)")
    if problems:
        raise PermissionError("heldout_incidents.json no longer verifies: " + "; ".join(problems))
    return doc
