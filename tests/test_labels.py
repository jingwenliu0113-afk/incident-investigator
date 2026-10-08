"""Incident label (Core §3, decision 006): ground truth per incident, scored per layer (SPEC §8)."""

import copy

import pytest

from collect.labels import FAULT_TYPES, FLAG_FAULT_TYPES, check_label
from collect.layout import DataLayout
from collect.traffic import TRAFFIC_PROFILES
from test_records import injection
from test_records import manifest as _manifest

SERVICES = {"payment", "checkout", "frontend", "frontend-proxy", "load-generator", "ad", "product-catalog"}


def manifest(**overrides):
    m = _manifest(**overrides)
    if "traffic" not in overrides:
        m["traffic"]["settings"] = dict(TRAFFIC_PROFILES["locust-upstream-3.1.0"])
    return m


def label(**overrides):
    lab = {
        "label_version": 1,
        "incident_id": "INC-001",
        "run_group_id": "RG-001",
        "fault_family": "error",
        "injected_fault": {"fault_type": "error_response", "flag": "paymentFailure", "variant": "100%"},
        "origin_service": "payment",
        "affected_services": ["payment", "checkout", "frontend"],
        "user_symptom": {"kinds": ["errors"], "description": "checkout fails with 'failed to charge card'"},
        "fault_start": "2026-10-08T11:50:00Z",
        "fault_end": "2026-10-08T11:55:00Z",
        "traffic_profile": "locust-upstream-3.1.0",
        "seed": 42,
        "telemetry_coverage": {"traces": "origin", "metrics": "symptom_only", "logs": "origin"},
        "labeling": {"method": "catalog+review", "labeled_at": "2026-10-08T13:00:00Z", "labeler": "human:reviewer-1"},
    }
    lab.update(overrides)
    return lab


def check(lab, inj=None, **kw):
    return check_label(lab, injection() if inj is None else inj, services=SERVICES, **kw)


def test_valid_label_passes():
    assert check(label()) == []
    assert check(label(), manifest=manifest()) == []


# ---------------------------------------------------------------- schema

@pytest.mark.parametrize("broken", [
    {"fault_family": "network"},  # not in the vocabulary
    {"injected_fault": {"fault_type": "gremlins", "flag": "paymentFailure", "variant": "100%"}},
    {"incident_id": "INC-1"},
    {"run_group_id": "rg-001"},
    {"affected_services": []},
    {"affected_services": ["payment", "payment"]},
    {"origin_service": "Payment"},
    {"user_symptom": {"kinds": []}},
    {"user_symptom": {"kinds": ["none", "errors"]}},  # "none" excludes every other symptom
    {"telemetry_coverage": {"traces": "origin", "metrics": "origin"}},  # every signal must be labelled
    {"telemetry_coverage": {"traces": "yes", "metrics": "origin", "logs": "none"}},
    {"labeling": {"method": "vibes", "labeled_at": "2026-10-08T13:00:00Z", "labeler": "x"}},
    {"split": "test"},  # split assignment is not part of a label
    {"fault_start": "2026-10-08 11:50:00"},
    {"traffic_profile": "anything-goes"},  # closed: only profiles defined in collect.traffic
    {"labeling": {"method": "catalog", "labeled_at": "2026-10-08T13:00:00Z", "labeler": "x"}},  # coverage needs review
])
def test_schema_rejects(broken):
    assert any(p.startswith("schema:") for p in check(label(**broken))), broken


def test_every_fault_type_maps_to_a_family_in_the_schema_vocabulary():
    import json

    from collect.records import SCHEMAS_DIR

    schema = json.loads((SCHEMAS_DIR / "incident_label.schema.json").read_text())
    assert set(FAULT_TYPES) == set(schema["properties"]["injected_fault"]["properties"]["fault_type"]["enum"])
    assert set(FAULT_TYPES.values()) == set(schema["properties"]["fault_family"]["enum"])


def test_catalog_only_label_has_no_coverage_and_reviewed_label_must_have_it():
    catalog_only = label(labeling={"method": "catalog", "labeled_at": "2026-10-08T13:00:00Z", "labeler": "x"})
    del catalog_only["telemetry_coverage"]  # only knowable by looking at the snapshot
    assert check(catalog_only) == []
    reviewed = label()
    del reviewed["telemetry_coverage"]
    assert any(p.startswith("schema:") for p in check(reviewed))


def test_every_core_flag_maps_into_the_vocabulary_and_every_fault_type_is_reachable():
    assert set(FLAG_FAULT_TYPES.values()) == set(FAULT_TYPES)


# ---------------------------------------------------------------- consistency

def test_fault_type_must_follow_the_injected_flag():
    wrong = label(fault_family="resource",
                  injected_fault={"fault_type": "cpu_saturation", "flag": "paymentFailure", "variant": "100%"})
    assert any("fault_type" in p and "paymentFailure" in p for p in check(wrong))


def test_flags_that_are_not_core_faults_cannot_be_labelled():
    inj = injection(fault={"mechanism": "flagd", "flag": "emitRawPii", "variant": "on"})
    lab = label(injected_fault={"fault_type": "error_response", "flag": "emitRawPii", "variant": "on"})
    assert any("not a Core fault" in p for p in check(lab, inj))


def test_fault_interval_must_be_ordered_even_without_a_manifest():
    sched = {"normal_start": "2026-10-08T11:40:00Z", "fault_on": "2026-10-08T11:56:00Z",
             "fault_off": "2026-10-08T11:55:00Z", "end": "2026-10-08T12:00:00Z"}
    lab = label(fault_start="2026-10-08T11:56:00Z", fault_end="2026-10-08T11:55:00Z")
    assert any("fault_start must be before fault_end" in p for p in check(lab, injection(schedule=sched)))


def test_impossible_labeled_at_is_reported():
    lab = label(labeling={"method": "catalog+review", "labeled_at": "2026-02-30T13:00:00Z", "labeler": "h"})
    assert any("labeled_at" in p for p in check(lab))


def test_malformed_injection_or_manifest_are_problems_not_exceptions():
    assert any(p.startswith("injection schema:") for p in check(label(), {}))
    assert any(p.startswith("injection schema:") for p in check(label(), injection(incident_ids="INC-001")))
    assert any(p.startswith("manifest schema:") for p in check(label(), manifest={}))


def test_traffic_profile_must_be_what_the_manifest_recorded():
    changed = manifest(traffic={"generator_service": "load-generator", "seed": 42, "seed_applied": False,
                                "settings": {**TRAFFIC_PROFILES["locust-upstream-3.1.0"], "LOCUST_USERS": "500"}})
    assert any("traffic_profile" in p for p in check(label(), manifest=changed))

def test_family_must_follow_the_fault_type():
    assert any("fault_family" in p for p in check(label(fault_family="latency")))


@pytest.mark.parametrize("field, value, word", [
    ("run_group_id", "RG-002", "run_group_id"),
    ("incident_id", "INC-009", "incident_ids"),
    ("seed", 7, "seed"),
    ("fault_start", "2026-10-08T11:50:01Z", "fault_on"),
    ("fault_end", "2026-10-08T11:54:00Z", "fault_off"),
])
def test_label_must_agree_with_the_injection_record(field, value, word):
    assert any(word in p for p in check(label(**{field: value}))), (field, value)


def test_injected_flag_and_variant_must_be_the_ones_injected():
    wrong = label(injected_fault={"fault_type": "error_response", "flag": "adFailure", "variant": "on"})
    assert any("flag" in p for p in check(wrong))
    wrong = label(injected_fault={"fault_type": "error_response", "flag": "paymentFailure", "variant": "10%"})
    assert any("variant" in p for p in check(wrong))


def test_services_must_exist_and_origin_must_be_affected():
    assert any("unknown service" in p for p in check(label(affected_services=["payment", "paymnet"])))
    assert any("unknown service" in p for p in check(label(origin_service="billing",
                                                           affected_services=["billing", "payment"])))
    assert any("origin_service" in p for p in check(label(affected_services=["checkout", "frontend"])))


def test_label_must_agree_with_the_incident_manifest():
    assert any("incident_id" in p for p in check(label(), manifest=manifest(incident_id="INC-002")))
    assert any("seed" in p for p in check(label(), manifest=manifest(seed=1)))
    # the fault must overlap the telemetry window of this incident, or there is nothing to diagnose
    early = manifest(window={"start": "2026-10-08T11:30:00Z", "end": "2026-10-08T11:45:00Z"})
    assert any("window" in p for p in check(label(), manifest=early))


def test_label_check_does_not_mutate_inputs():
    lab, inj = label(), injection()
    before = copy.deepcopy((lab, inj))
    check(lab, inj, manifest=manifest())
    assert (lab, inj) == before


# ---------------------------------------------------------------- layout

def test_label_lives_in_the_ground_truth_tree(tmp_path):
    layout = DataLayout(tmp_path)
    path = layout.label_path("INC-001")
    assert path == tmp_path / "ground_truth" / "incidents" / "INC-001" / "label.json"
    assert layout.is_ground_truth(path)
    assert not layout.is_ground_truth(layout.incident_dir("INC-001") / "normalized")
    with pytest.raises(ValueError):
        layout.label_path("../INC-001")
