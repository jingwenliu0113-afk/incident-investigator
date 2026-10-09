"""heldout_incidents.json (decision 023 §5.5): written once after every slot is filled or closed, processed, audited and
reviewed blind; it pins 8 files per listed incident and every held-out run group, and checks each run group was made by
the frozen code after the freeze."""

import json

import pytest

from collect.heldout import heldout_incidents, heldout_slots, load_heldout_incidents, write_once
from collect.layout import DataLayout
from collect.pilot import PILOT
from heldout_fixtures import (BEFORE, FREEZE_SHA, complete_pilot, freeze_record, plan_doc, write_heldout_incident,
                              write_review, write_run)

KEPT = PILOT[:2]
PLAN = plan_doc(KEPT, removed=[(e["flag"], e["variant"]) for e in PILOT[2:]])
SLOTS = {"k": 1, "faults": [[e["flag"], e["variant"]] for e in KEPT], "slots": heldout_slots([[e["flag"], e["variant"]] for e in KEPT], k=1)}
BAD = "0" * 40
NOW = "2026-10-25T00:00:00Z"


def commit_check(commit):
    return [] if commit != BAD else [f"commit {commit[:12]} differs from the frozen commit outside the allowlist"]


def listing(layout, *, freeze=None, results=None, slots=SLOTS):
    return heldout_incidents(layout, slots, PLAN, freeze=freeze or freeze_record(), freeze_sha=FREEZE_SHA,
                             results_root=results or layout.root / "results", commit_check=commit_check, now=NOW)


def full(tmp_path, **first):
    """A complete Pilot (RG-001, RG-002) and both slots filled by clean held-out incidents (RG-050, RG-051)."""
    layout = DataLayout(tmp_path / "data")
    complete_pilot(layout, KEPT)
    write_heldout_incident(layout, 50, SLOTS["slots"][0], **first)
    write_heldout_incident(layout, 51, SLOTS["slots"][1])
    return layout


def test_a_complete_clean_set_lists_every_slot_with_eight_shas_and_no_method_ran(tmp_path):
    layout = full(tmp_path)
    (layout.root / "results/heldout").mkdir(parents=True)
    (layout.root / "results/heldout/leakage.md").write_text("# audit\n")  # the audit summary alone does not block
    doc = listing(layout)
    assert [(i["slot"], i["incident_id"], i["run_group_id"]) for i in doc["incidents"]] == [("H01", "INC-050", "RG-050"),
                                                                                         ("H02", "INC-051", "RG-051")]
    assert set(doc["incidents"][0]["sha256"]) == {"label", "label_reviewed", "label_review", "leakage_audit", "manifest",
                                                  "normalize_report", "injection", "run"}
    assert doc["excluded"] == doc["closed_slots"] == []
    assert doc["run_groups"] == [["RG-050", "valid"], ["RG-051", "valid"]]
    assert doc["removed_faults"] == [{"flag": r["flag"], "variant": r["variant"], "basis": r["basis"], "reason": r["reason"]}
                                     for r in PLAN["removed"]]
    assert doc["freeze_sha256"] == FREEZE_SHA and doc["by_fault"]["paymentFailure 100%"] == {"listed": 1, "of": 1,
                                                                                            "missing_slots": []}
    path = layout.heldout_incidents_path
    write_once(path, doc)
    with pytest.raises(FileExistsError):
        write_once(path, doc)
    assert load_heldout_incidents(layout, freeze_sha=FREEZE_SHA) == doc


def test_lexicon_hits_are_excluded_unexercised_slots_closed_and_counted_per_fault(tmp_path):
    layout = DataLayout(tmp_path / "data")
    complete_pilot(layout, KEPT)
    write_heldout_incident(layout, 50, SLOTS["slots"][0], hits=3)
    write_heldout_incident(layout, 51, SLOTS["slots"][1], exercised=False)
    write_heldout_incident(layout, 52, SLOTS["slots"][1], exercised=False)
    doc = listing(layout)
    assert doc["incidents"] == []
    assert doc["excluded"] == [
        {"slot": "H01", "incident_id": "INC-050", "run_group_id": "RG-050", "reason": "lexicon_hits=3 (decision 015)"},
        {"slot": "H02", "incident_id": "INC-051", "run_group_id": "RG-051", "reason": "fault not exercised (016 §5, 023 §5.3)"},
        {"slot": "H02", "incident_id": "INC-052", "run_group_id": "RG-052", "reason": "fault not exercised (016 §5, 023 §5.3)"}]
    (closed,) = doc["closed_slots"]
    assert closed["slot"] == "H02" and closed["incident_ids"] == ["INC-051", "INC-052"]
    fault = f"{SLOTS['slots'][1]['flag']} {SLOTS['slots'][1]['variant']}"
    assert doc["by_fault"][fault] == {"listed": 0, "of": 1, "missing_slots": ["H02"]}


def drop(name):
    def apply(layout):
        layout.label_path("INC-050").with_name(name).unlink()
    return apply


@pytest.mark.parametrize("change, needle", [
    (lambda layout: None, None),
    (drop("leakage_audit.json"), "leakage_audit"),
    (drop("label_review.json"), "label_review"),
    (drop("normalize_report.json"), "normalize_report"),
    (lambda layout: (layout.incident_dir("INC-050") / "normalized/snapshot.json").unlink(), "snapshot"),
    (lambda layout: write_review(layout, "INC-050", SLOTS["slots"][0]["flag"], SLOTS["slots"][0]["variant"], saw=True),
     "saw_method_outputs"),
    (lambda layout: (layout.root / "results/heldout/stat-anomaly").mkdir(parents=True), "stat-anomaly"),
], ids=["ok", "unaudited", "unreviewed", "unprocessed", "no-snapshot", "saw", "method-ran"])
def test_the_list_waits_for_processing_audit_blind_review_and_comes_before_any_method(tmp_path, change, needle):
    layout = full(tmp_path)
    change(layout)
    if needle is None:
        assert len(listing(layout)["incidents"]) == 2
        return
    with pytest.raises(ValueError, match=needle):
        listing(layout)


def test_the_list_waits_for_every_slot(tmp_path):
    layout = DataLayout(tmp_path / "data")
    complete_pilot(layout, KEPT)
    write_heldout_incident(layout, 50, SLOTS["slots"][0])
    with pytest.raises(ValueError, match="H02 is open"):
        listing(layout)
    for n in (51, 52, 53):
        write_run(layout, f"RG-{n:03d}", SLOTS["slots"][1]["flag"], SLOTS["slots"][1]["variant"], "invalid", split="heldout",
                  slot="H02", freeze_sha=FREEZE_SHA)
    with pytest.raises(ValueError, match="H02 is needs_person"):
        listing(layout)


def forge_pilot_run_group(layout):
    """RG-001 was a Pilot run of slot H01's fault: rewrite every held-out field of its records."""
    truth = layout.run_group_truth_dir("RG-001")
    run = json.loads((truth / "run.json").read_text())
    run["plan"].update(split="heldout", slot="H01", freeze_sha256=FREEZE_SHA)
    (truth / "run.json").write_text(json.dumps(run))
    inj = json.loads((truth / "injection.json").read_text())
    (truth / "injection.json").write_text(json.dumps({**inj, "split": "heldout"}))


@pytest.mark.parametrize("first, needle", [
    ({"dirty": True}, "not clean"),
    ({"commit": BAD}, "allowlist"),
    ({"up_at": BEFORE}, "before the freeze"),
    ({"fault_minutes": 5}, "023 §3"),
    ({"normal_jitter_minutes": 0}, "023 §3"),
    ({"entry": {**PILOT[0], "affected": ["payment"]}}, "plan entry"),
    ({"project": {"commit": "e" * 40, "dirty": False}}, "manifest"),
    ({"lock": "sha256:" + "2" * 64}, "env lock"),
    ({"policy": {"version": 2, "sha256": "sha256:x"}}, "policy"),
    ({"code": {"commit": BAD, "dirty": False}}, "normalize"),
    ({"freeze_sha": "sha256:" + "a" * 64}, "freeze"),
    ({"seed": 1}, "seed"),  # RG-001 (Pilot) used seed 1
], ids=["dirty", "commit", "early", "fault-minutes", "jitter", "label", "manifest", "lock", "policy", "normalize-commit",
        "freeze", "seed"])
def test_each_heldout_run_group_must_come_from_the_frozen_code_after_the_freeze(tmp_path, first, needle):
    with pytest.raises(ValueError, match=needle):
        listing(full(tmp_path, **first))


def test_a_pilot_run_group_with_every_heldout_field_forged_is_refused_by_its_commit_number_and_time(tmp_path):
    layout = DataLayout(tmp_path / "data")
    write_run(layout, "RG-001", SLOTS["slots"][0]["flag"], SLOTS["slots"][0]["variant"], inc="INC-001", up_at=BEFORE,
              commit=BAD)
    complete_pilot(layout, KEPT, start=2)
    write_heldout_incident(layout, 51, SLOTS["slots"][1])
    forge_pilot_run_group(layout)
    with pytest.raises(ValueError) as e:
        listing(layout)
    for needle in ("RG-001: commit", "RG-001: started before the freeze", "RG-001: numbered"):
        assert needle in str(e.value)


def test_incident_ids_repeat_nowhere(tmp_path):
    layout = full(tmp_path)
    run = layout.run_group_truth_dir("RG-001") / "run.json"
    run.write_text(json.dumps({**json.loads(run.read_text()), "incident_ids": ["INC-001", "INC-050"]}))
    with pytest.raises(ValueError, match="INC-050"):
        listing(layout)


@pytest.mark.parametrize("change", [
    lambda layout: layout.label_path("INC-050").with_name("label.reviewed.json").write_text("{}"),
    lambda layout: layout.label_path("INC-050").with_name("leakage_audit.json").write_text("{}"),
    lambda layout: layout.normalize_report_path("INC-050").write_text("{}"),
    lambda layout: layout.injection_path("RG-050").write_text("{}"),
    lambda layout: (layout.run_group_truth_dir("RG-051") / "run.json").write_text(
        (layout.run_group_truth_dir("RG-051") / "run.json").read_text() + " "),
    lambda layout: write_run(layout, "RG-060", SLOTS["slots"][0]["flag"], SLOTS["slots"][0]["variant"], "invalid",
                             split="heldout", slot="H01", freeze_sha=FREEZE_SHA),
], ids=["reviewed-label", "audit", "normalize-report", "injection", "run", "later-run-group"])
def test_the_loader_refuses_once_anything_pinned_changed(tmp_path, change):
    layout = full(tmp_path)
    write_once(layout.heldout_incidents_path, listing(layout))
    load_heldout_incidents(layout, freeze_sha=FREEZE_SHA)
    change(layout)
    with pytest.raises(PermissionError):
        load_heldout_incidents(layout, freeze_sha=FREEZE_SHA)


def test_the_loader_needs_the_list_of_this_freeze(tmp_path):
    layout = full(tmp_path)
    with pytest.raises(PermissionError, match="heldout-list"):
        load_heldout_incidents(layout, freeze_sha=FREEZE_SHA)
    write_once(layout.heldout_incidents_path, listing(layout))
    with pytest.raises(PermissionError, match="freeze"):
        load_heldout_incidents(layout, freeze_sha="sha256:" + "b" * 64)
