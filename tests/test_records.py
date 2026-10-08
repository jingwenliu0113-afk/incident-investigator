import copy
import json

import pytest

from collect.layout import DataLayout
from collect.records import check_injection, check_manifest, load_flag_catalog

LOCK_SHA = "sha256:" + "1" * 64
COMMIT = "a" * 40


@pytest.fixture
def catalog(tmp_path):
    p = tmp_path / "demo.flagd.json"
    p.write_text(json.dumps({"flags": {
        "paymentFailure": {"state": "ENABLED", "defaultVariant": "off", "description": "Fail payment",
                           "variants": {"off": 0, "10%": 0.1, "100%": 1}},
        "adHighCpu": {"state": "ENABLED", "defaultVariant": "off", "description": "CPU",
                      "variants": {"off": False, "on": True}},
    }}))
    return load_flag_catalog(p)


def manifest(**overrides):
    m = {
        "manifest_version": 1,
        "incident_id": "INC-001",
        "created_at": "2026-10-08T12:00:00Z",
        "project": {"commit": COMMIT, "dirty": False},
        "env_lock": {"path": "env/otel-demo.lock.json", "sha256": LOCK_SHA,
                     "upstream_tag": "3.1.0", "upstream_commit": "dedc0178918e260823323b8d95005a8cb924b007"},
        "machine": {"role": "mac", "os": "Darwin 27.0.0", "arch": "arm64", "cpu_model": "Apple M4 Pro",
                    "cpu_count": 12, "memory_bytes": 51539607552,
                    "docker": {"server_version": "29.8.1", "platform": "linux/arm64",
                               "operating_system": "Docker Desktop", "cpus": 10, "memory_bytes": 16766496768}},
        "startup": {"compose_command": ["docker", "compose", "up"], "started_at": "2026-10-08T11:30:00Z"},
        "traffic": {"generator_service": "load-generator",
                    "settings": {"LOCUST_USERS": "5", "LOCUST_BROWSER_TRAFFIC_ENABLED": "false"},
                    "seed": None, "seed_applied": False},
        "window": {"start": "2026-10-08T11:40:00Z", "end": "2026-10-08T12:00:00Z"},
        "files": [],
    }
    m.update(overrides)
    return m


def injection(**overrides):
    r = {
        "injection_version": 1,
        "run_group_id": "RG-001",
        "incident_ids": ["INC-001"],
        "split": "pilot",
        "seed": 42,
        "fault": {"mechanism": "flagd", "flag": "paymentFailure", "variant": "100%"},
        "schedule": {"normal_start": "2026-10-08T11:40:00Z", "fault_on": "2026-10-08T11:50:00Z",
                     "fault_off": "2026-10-08T11:55:00Z", "end": "2026-10-08T12:00:00Z"},
        "controller": {"method": "flagd-file"},
        # exact flag file served by flagd before / while the fault is on (productCatalogFailure, for
        # example, is switched through its targeting rule, not defaultVariant)
        "flag_file": {"baseline_sha256": "sha256:" + "b" * 64, "injected_sha256": "sha256:" + "c" * 64},
    }
    r.update(overrides)
    return r


# ---------------------------------------------------------------- canonical flag-file hash

def test_canonical_json_sha256_ignores_formatting_and_key_order(tmp_path):
    from collect.records import canonical_json_sha256

    # flagd-ui's API writes compact JSON while its UI pretty-prints: the same flag state can have
    # different bytes. Formatting and key order must not change the hash; content must.
    pretty = '{\n  "flags": {\n    "b": {"defaultVariant": "off"},\n    "a": {"x": 1}\n  }\n}\n'
    compact = '{"flags":{"a":{"x":1},"b":{"defaultVariant":"off"}}}'
    changed = '{"flags":{"a":{"x":1},"b":{"defaultVariant":"on"}}}'
    (tmp_path / "p.json").write_text(pretty)
    (tmp_path / "c.json").write_text(compact)
    (tmp_path / "x.json").write_text(changed)
    hp, hc, hx = (canonical_json_sha256(tmp_path / n) for n in ("p.json", "c.json", "x.json"))
    assert hp == hc != hx
    assert hp.startswith("sha256:") and len(hp) == 71


# ---------------------------------------------------------------- flag catalog

def test_load_flag_catalog(catalog):
    assert catalog["paymentFailure"]["default"] == "off"
    assert set(catalog["paymentFailure"]["variants"]) == {"off", "10%", "100%"}


def test_load_flag_catalog_on_pinned_upstream_has_all_flags_off_by_default():
    from env.lock import PROJECT_DIR
    path = PROJECT_DIR / "env/upstream/opentelemetry-demo/src/flagd/demo.flagd.json"
    if not path.exists():
        pytest.skip("upstream checkout not fetched (python -m env fetch-upstream)")
    cat = load_flag_catalog(path)
    assert len(cat) >= 10
    assert all(f["default"] == "off" for f in cat.values())


# ---------------------------------------------------------------- manifest

def test_valid_manifest_passes_formal_check():
    assert check_manifest(manifest(), formal=True, lock_sha256=LOCK_SHA) == []


def test_manifest_must_not_carry_ground_truth_fields():
    for leaked in ({"fault": {"flag": "paymentFailure"}}, {"run_group_id": "RG-001"},
                   {"fault_start": "2026-10-08T11:50:00Z"}, {"origin_service": "payment"},
                   {"seed": 42}):  # decision 002 amendment: the seed fixes normal / recovery lengths -> fault_on / fault_off
        assert check_manifest(manifest(**leaked), formal=False), leaked
    traffic = {"generator_service": "load-generator", "settings": {"LOCUST_USERS": "5"}, "seed": 42, "seed_applied": False}
    assert check_manifest(manifest(traffic=traffic), formal=False)


def test_manifest_traffic_settings_must_not_mention_fault_flags(catalog):
    m = manifest(traffic={"generator_service": "load-generator", "seed": None, "seed_applied": False,
                          "settings": {"LOCUST_USERS": "5", "NOTE": "paymentFailure on"}})
    assert any("paymentFailure" in p for p in check_manifest(m, formal=False, flag_catalog=catalog))


def test_formal_manifest_requires_clean_committed_project():
    assert any("commit" in p for p in
               check_manifest(manifest(project={"commit": None, "dirty": True}), formal=True, lock_sha256=LOCK_SHA))
    assert any("dirty" in p for p in
               check_manifest(manifest(project={"commit": COMMIT, "dirty": True}), formal=True, lock_sha256=LOCK_SHA))
    # informal (smoke) runs may be dirty
    assert check_manifest(manifest(project={"commit": None, "dirty": True}), formal=False) == []


def test_formal_manifest_requires_matching_lock_and_docker_facts():
    assert any("lock" in p for p in check_manifest(manifest(), formal=True, lock_sha256="sha256:" + "2" * 64))
    m = manifest()
    m["machine"]["docker"] = None
    assert any("docker" in p for p in check_manifest(m, formal=True, lock_sha256=LOCK_SHA))


def test_manifest_window_must_be_ordered():
    m = manifest(window={"start": "2026-10-08T12:00:00Z", "end": "2026-10-08T11:00:00Z"})
    assert any("window" in p for p in check_manifest(m, formal=False))


def test_manifest_ids_are_opaque():
    assert check_manifest(manifest(incident_id="INC-paymentFailure-1"), formal=False)


def test_manifest_schema_rejects_bad_digest_and_role():
    m = manifest()
    m["env_lock"]["sha256"] = "abc"
    assert check_manifest(m, formal=False)
    m = manifest()
    m["machine"]["role"] = "someones-laptop"
    assert check_manifest(m, formal=False)


def test_manifest_file_checksums():
    m = manifest(files=[{"path": "raw/traces.jsonl", "sha256": LOCK_SHA, "bytes": 10}])
    assert check_manifest(m, formal=False) == []
    m = manifest(files=[{"path": "/abs/traces.jsonl", "sha256": LOCK_SHA, "bytes": 10}])
    assert check_manifest(m, formal=False)
    m = manifest(files=[{"path": "../escape", "sha256": LOCK_SHA, "bytes": 10}])
    assert check_manifest(m, formal=False)


# ---------------------------------------------------------------- injection record

def test_valid_injection(catalog):
    assert check_injection(injection(), catalog) == []


def test_injection_unknown_flag_or_variant(catalog):
    assert any("nope" in p for p in check_injection(
        injection(fault={"mechanism": "flagd", "flag": "nope", "variant": "on"}), catalog))
    assert any("50%" in p for p in check_injection(
        injection(fault={"mechanism": "flagd", "flag": "paymentFailure", "variant": "50%"}), catalog))


def test_injection_variant_must_differ_from_baseline(catalog):
    assert any("baseline" in p for p in check_injection(
        injection(fault={"mechanism": "flagd", "flag": "paymentFailure", "variant": "off"}), catalog))


def test_injection_schedule_must_be_strictly_ordered(catalog):
    sched = {"normal_start": "2026-10-08T11:40:00Z", "fault_on": "2026-10-08T11:39:00Z",
             "fault_off": "2026-10-08T11:55:00Z", "end": "2026-10-08T12:00:00Z"}
    assert any("schedule" in p for p in check_injection(injection(schedule=sched), catalog))
    sched = {"normal_start": "2026-10-08T11:40:00Z", "fault_on": "2026-10-08T11:50:00Z",
             "fault_off": "2026-10-08T12:05:00Z", "end": "2026-10-08T12:00:00Z"}
    assert any("schedule" in p for p in check_injection(injection(schedule=sched), catalog))


def test_injection_requires_flag_file_digests_that_differ(catalog):
    bad = injection()
    del bad["flag_file"]
    assert check_injection(bad, catalog)
    same = {"baseline_sha256": "sha256:" + "b" * 64, "injected_sha256": "sha256:" + "b" * 64}
    assert any("flag file" in p for p in check_injection(injection(flag_file=same), catalog))


def test_injection_baseline_must_match_pinned_flag_file(catalog):
    problems = check_injection(injection(), catalog, baseline_flag_sha256="sha256:" + "d" * 64)
    assert any("baseline" in p for p in problems)
    assert check_injection(injection(), catalog, baseline_flag_sha256="sha256:" + "b" * 64) == []


def test_injection_requires_run_group_and_incidents(catalog):
    bad = injection()
    del bad["run_group_id"]
    assert check_injection(bad, catalog)
    assert check_injection(injection(incident_ids=[]), catalog)


# ---------------------------------------------------------------- physical layout

def test_layout_separates_agent_readable_data_from_ground_truth(tmp_path):
    layout = DataLayout(tmp_path / "data" / "external")
    inc = layout.incident_dir("INC-001")
    truth = layout.run_group_truth_dir("RG-001")
    assert layout.incidents_root in inc.parents
    assert layout.ground_truth_root in truth.parents
    for a, b in [(layout.incidents_root, layout.ground_truth_root), (layout.ground_truth_root, layout.incidents_root)]:
        assert a != b and a not in b.parents
    assert layout.manifest_path("INC-001") == inc / "manifest.json"
    assert layout.injection_path("RG-001") == truth / "injection.json"


def test_layout_rejects_non_opaque_or_traversal_ids(tmp_path):
    layout = DataLayout(tmp_path)
    for bad in ["../RG-001", "INC-001/..", "INC-payment", "RG-001"]:
        with pytest.raises(ValueError):
            layout.incident_dir(bad)
    with pytest.raises(ValueError):
        layout.run_group_truth_dir("INC-001")


def test_layout_flags_ground_truth_paths(tmp_path):
    layout = DataLayout(tmp_path)
    assert layout.is_ground_truth(layout.injection_path("RG-001"))
    assert not layout.is_ground_truth(layout.manifest_path("INC-001"))
    assert layout.is_ground_truth(layout.incidents_root / ".." / "ground_truth" / "x")


def test_injection_records_are_deep_copied_not_mutated(catalog):
    rec = injection()
    snapshot = copy.deepcopy(rec)
    check_injection(rec, catalog)
    assert rec == snapshot


# ---------------------------------------------------------------- strictness of formats

def test_digest_with_trailing_newline_is_rejected_by_schema(catalog):
    ff = {"baseline_sha256": "sha256:" + "b" * 64 + "\n", "injected_sha256": "sha256:" + "b" * 64}
    assert any(p.startswith("schema:") for p in check_injection(injection(flag_file=ff), catalog))
    m = manifest()
    m["env_lock"]["sha256"] = LOCK_SHA + "\n"
    assert check_manifest(m, formal=False)


@pytest.mark.parametrize("bad", ["2026-13-45T00:00:00Z", "2026-10-08T25:00:00Z", "２０２６-10-08T00:00:00Z",
                                 "2026-10-08T00:00:00Z\n"])
def test_impossible_timestamps_are_reported_not_raised(catalog, bad):
    for field in ("created_at",):
        problems = check_manifest(manifest(**{field: bad}), formal=False)
        assert problems, (field, bad)
    m = manifest()
    m["startup"]["started_at"] = bad
    assert check_manifest(m, formal=False)
    sched = dict(injection()["schedule"], fault_on=bad)
    assert check_injection(injection(schedule=sched), catalog)


def test_ids_with_trailing_newline_are_rejected(catalog, tmp_path):
    assert check_manifest(manifest(incident_id="INC-001\n"), formal=False)
    assert check_injection(injection(run_group_id="RG-001\n"), catalog)
    with pytest.raises(ValueError):
        DataLayout(tmp_path).incident_dir("INC-001\n")
    with pytest.raises(ValueError):
        DataLayout(tmp_path).incident_dir("INC-٠٠١")  # non-ASCII digits


# ---------------------------------------------------------------- ground-truth guard on macOS

def test_is_ground_truth_by_file_identity_not_spelling(tmp_path):
    import os

    layout = DataLayout(tmp_path / "data")
    truth = layout.injection_path("RG-001")
    truth.parent.mkdir(parents=True)
    truth.write_text("{}")
    inc = layout.incident_dir("INC-001")
    inc.mkdir(parents=True)

    # different letter case (resolves to the same file on case-insensitive APFS)
    variant = tmp_path / "data" / "GROUND_TRUTH" / "run_groups" / "RG-001" / "injection.json"
    assert layout.is_ground_truth(variant)

    # a hard link placed on the agent-readable side
    link = inc / "looks-innocent.json"
    os.link(truth, link)
    assert layout.is_ground_truth(link)

    # a symlink placed on the agent-readable side
    sym = inc / "sym.json"
    sym.symlink_to(truth)
    assert layout.is_ground_truth(sym)

    normal = inc / "manifest.json"
    normal.write_text("{}")
    assert not layout.is_ground_truth(normal)
