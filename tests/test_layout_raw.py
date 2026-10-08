"""Raw telemetry tree and the agent-readable allow-list (decision 008 §5)."""

import os

import pytest

from collect.layout import DataLayout


@pytest.fixture
def layout(tmp_path):
    lay = DataLayout(tmp_path / "data")
    norm = lay.incident_dir("INC-001") / "normalized"
    norm.mkdir(parents=True)
    (norm / "spans.jsonl").write_text("{}\n")
    (lay.incident_dir("INC-001") / "manifest.json").write_text("{}")
    raw = lay.raw_dir("RG-001")
    raw.mkdir(parents=True)
    (raw / "traces.jsonl").write_text("{}\n")
    truth = lay.injection_path("RG-001")
    truth.parent.mkdir(parents=True)
    truth.write_text("{}")
    return lay


def test_raw_lives_per_run_group_outside_incidents_and_ground_truth(layout):
    raw = layout.raw_dir("RG-001")
    assert raw == layout.root / "raw" / "RG-001"
    assert layout.raw_export_path("RG-001") == raw / "raw_export.json"
    for other in (layout.incidents_root, layout.ground_truth_root):
        assert other not in raw.parents
    with pytest.raises(ValueError):
        layout.raw_dir("INC-001")
    with pytest.raises(ValueError):
        layout.raw_dir("../RG-001")


def test_only_normalized_snapshot_files_are_agent_readable(layout):
    inc = layout.incident_dir("INC-001")
    assert layout.is_agent_readable(inc / "normalized" / "spans.jsonl")
    assert layout.is_agent_readable(inc / "normalized")
    for denied in (
        inc / "manifest.json",  # provenance is for people and eval, not for agents
        inc / "raw" / "traces.jsonl",
        inc,
        layout.incidents_root,
        layout.raw_dir("RG-001") / "traces.jsonl",
        layout.injection_path("RG-001"),
        layout.root,
        layout.root.parent,
        inc / "normalized" / ".." / "manifest.json",  # traversal out of normalized/
        layout.incidents_root / "INC-payment" / "normalized" / "x",  # not an opaque id
    ):
        assert not layout.is_agent_readable(denied), denied


def test_agent_readable_is_decided_by_file_identity(layout):
    inc = layout.incident_dir("INC-001")
    norm = inc / "normalized"
    # symlinks out of normalized/ to raw or ground truth are refused
    (norm / "sneaky-raw.jsonl").symlink_to(layout.raw_dir("RG-001") / "traces.jsonl")
    (norm / "sneaky-truth.json").symlink_to(layout.injection_path("RG-001"))
    assert not layout.is_agent_readable(norm / "sneaky-raw.jsonl")
    assert not layout.is_agent_readable(norm / "sneaky-truth.json")
    # a hard link may alias anything outside normalized/
    os.link(layout.raw_dir("RG-001") / "traces.jsonl", norm / "hard.jsonl")
    assert not layout.is_agent_readable(norm / "hard.jsonl")
    # letter case does not matter on APFS: the same directory is still readable
    assert layout.is_agent_readable(layout.root / "INCIDENTS" / "INC-001" / "Normalized" / "spans.jsonl")
