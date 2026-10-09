"""The synthetic sample and the 2-minute demo (decision 027): generated raw OTLP JSON through the real normalize, committed
byte for byte under data/samples/synthetic/, with the agent-readable and ground-truth trees kept apart."""

import hashlib
import json
import shutil

import pytest

from collect.layout import DataLayout
from collect.normalize import FILES, host_to_data_ns
from collect.rungroup import next_id
from collect.snapshot import open_snapshot
from env.lock import PROJECT_DIR

COMMITTED = PROJECT_DIR / "data/samples/synthetic"


def tree(root) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    from collect.sample import generate

    out = tmp_path_factory.mktemp("sample") / "synthetic"
    generate(out)
    return out


def test_the_committed_sample_is_exactly_what_the_generator_writes(generated):
    mine, committed = tree(generated), tree(COMMITTED)
    assert sorted(committed) == sorted(mine), "regenerate: uv run python -m collect sample --out data/samples/synthetic --replace"
    assert [p for p in mine if mine[p] != committed[p]] == []


def test_generation_is_reproducible(generated, tmp_path):
    from collect.sample import generate

    generate(tmp_path / "again")
    assert tree(tmp_path / "again") == tree(generated)


def test_the_sample_ids_are_reserved_and_never_given_to_a_collected_incident(tmp_path):
    from collect.sample import INCIDENT, RUN_GROUP

    assert (INCIDENT, RUN_GROUP) == ("INC-000", "RG-000")
    layout = DataLayout(tmp_path)
    assert (next_id(layout, "INC"), next_id(layout, "RG")) == ("INC-001", "RG-001")  # counters start at 001


def test_the_sample_keeps_the_isolation_layout(generated):
    layout = DataLayout(generated)
    normalized = layout.incident_dir("INC-000") / "normalized"
    assert sorted(p.name for p in normalized.iterdir()) == sorted(FILES)
    assert all(layout.is_agent_readable(p) for p in normalized.iterdir())
    for path in (layout.label_path("INC-000"), layout.injection_path("RG-000"), layout.normalize_report_path("INC-000")):
        assert path.is_file() and layout.is_ground_truth(path) and not layout.is_agent_readable(path)
    readable = "".join(p.read_text() for p in normalized.iterdir())
    for answer in ("paymentFailure", "INC-000", "RG-000", "origin_service", "fault_on", "SYNTHETIC sample"):
        assert answer not in readable
    open_snapshot(normalized, layout)  # the one reader every method uses accepts it


def test_the_label_is_a_catalog_label_that_passes_its_checks_and_says_it_is_synthetic(generated):
    from collect.labels import check_label
    from collect.pilot import planned
    from collect.policy import load_policy

    layout = DataLayout(generated)
    label = json.loads(layout.label_path("INC-000").read_text())
    injection = json.loads(layout.injection_path("RG-000").read_text())
    assert check_label(label, injection, services=load_policy().sut_services) == []
    assert label["labeling"]["method"] == "catalog" and "SYNTHETIC" in label["labeling"]["notes"]
    assert "SYNTHETIC" in injection["controller"]["notes"]
    entry = planned("pilot", "paymentFailure", "100%")  # decision 016's catalog entry, never typed afresh
    assert (label["origin_service"], label["affected_services"], label["user_symptom"]["kinds"]) == (
        entry["origin"], entry["affected"], entry["symptom_kinds"])


def test_the_sample_is_tiny_and_every_file_is_listed_in_a_synthetic_manifest(generated):
    files = tree(generated)
    assert sum(len(b) for b in files.values()) < 512 * 1024
    manifest = json.loads(files["sample.json"])
    assert manifest["synthetic"] is True and manifest["incident_id"] == "INC-000"
    listed = {e["path"]: e for e in manifest["files"]}
    assert sorted(listed) == sorted(set(files) - {"sample.json"})
    for path, entry in listed.items():
        assert entry == {"path": path, "bytes": len(files[path]), "sha256": "sha256:" + hashlib.sha256(files[path]).hexdigest()}
    assert "SYNTHETIC" in files["README.md"].decode()
    snapshot = json.loads(files["incidents/INC-000/normalized/snapshot.json"])
    assert 100 <= sum(f["records"] for f in snapshot["files"]) <= 500  # a few hundred records
    for name in ("resources.jsonl", "spans.jsonl", "logs.jsonl", "metric_series.jsonl"):  # the formats with room for it
        lines = files[f"incidents/INC-000/normalized/{name}"].decode().splitlines()
        assert lines and all("synthetic-sample" in line for line in lines), name


def test_the_fault_pattern_is_clear_and_starts_after_the_first_ten_minutes(generated):
    layout = DataLayout(generated)
    snap = open_snapshot(layout.incident_dir("INC-000") / "normalized", layout)
    start, end = snap.window["start_ns"], snap.window["end_ns"]
    assert 25 <= (end - start) / 60e9 <= 30
    label = json.loads(layout.label_path("INC-000").read_text())
    on, off = host_to_data_ns(label["fault_start"], 0.0), host_to_data_ns(label["fault_end"], 0.0)
    assert on - start >= 10 * 60 * 10**9 and off < end
    payment = [s for s in snap.spans() if s["service"] == "payment"]
    during = [s for s in payment if on <= s["start_time_unix_nano"] < off]
    assert during and all(s["status_code"] == "error" for s in during)
    assert all(s["status_code"] != "error" for s in payment if not on <= s["start_time_unix_nano"] < off)


def test_the_example_prediction_is_the_statistical_baseline_on_the_sample(generated):
    from baselines.statistical import predict
    from eval.score import check_prediction

    layout = DataLayout(generated)
    example = json.loads((generated / "predictions/stat-anomaly/INC-000.json").read_text())
    assert check_prediction(example) == []
    fresh = predict(open_snapshot(layout.incident_dir("INC-000") / "normalized", layout), "INC-000")
    assert example == {**fresh, "usage": {**fresh["usage"], "latency_s": None}}  # wall time is not reproducible


def test_generate_never_overwrites_anything_but_a_sample(generated, tmp_path):
    from collect.sample import generate

    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("not a sample")
    for replace in (False, True):
        with pytest.raises(FileExistsError):
            generate(other, replace=replace)
    assert (other / "keep.txt").read_text() == "not a sample"
    copy = tmp_path / "copy"
    shutil.copytree(generated, copy)
    with pytest.raises(FileExistsError):
        generate(copy)
    generate(copy, replace=True)
    assert tree(copy) == tree(generated)


def test_collect_sample_writes_the_sample_and_never_into_data_external(tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli

    assert cli.main(["sample", "--out", str(tmp_path / "s")]) == 0
    assert json.loads((tmp_path / "s" / "sample.json").read_text())["synthetic"] is True
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    assert cli.main(["sample", "--out", str(tmp_path / "data" / "external" / "s")]) == 2
    assert "data/external" in capsys.readouterr().err and not (tmp_path / "data" / "external").exists()


# ------------------------------------------------------------------ the 2-minute demo


def test_eval_demo_scores_the_baseline_on_the_committed_sample_and_says_the_numbers_are_not_results(capsys):
    import eval.__main__ as cli

    assert cli.main(["demo"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("SYNTHETIC")
    for needle in ("not results", "INC-000", "stat-anomaly", "fault_type", "origin_top1", "affected_f1", "symptom_exact",
                   "existence", "weak: temporal", "matches the committed example prediction: yes"):
        assert needle in out
    assert out.rstrip().splitlines()[-1].startswith("SYNTHETIC")  # said again at the end, under the table


def test_the_demo_reports_every_layer_on_its_own(generated):
    from eval.demo import run_demo
    from eval.score import score_incident

    result = run_demo(generated)
    label = json.loads(DataLayout(generated).label_path("INC-000").read_text())
    assert result["synthetic"] is True and result["scores"] == score_incident(result["prediction"], label)
    assert result["evidence"]["existence"]["cited"] == len(result["prediction"]["evidence"])
    assert set(result["evidence"]["weak"]) == {"n", "temporal", "service", "origin", "weak"}
    assert result["matches_example"] is True


@pytest.mark.parametrize("change, message", [
    (lambda root: _edit_manifest(root, synthetic=False), "synthetic"),
    (lambda root: _append(root / "incidents/INC-000/normalized/logs.jsonl"), "sha256"),
    (lambda root: _append(root / "ground_truth/incidents/INC-000/label.json"), "sha256"),
])
def test_the_demo_refuses_a_sample_that_is_not_marked_synthetic_or_was_changed(generated, tmp_path, change, message):
    from eval.demo import run_demo

    copy = tmp_path / "copy"
    shutil.copytree(generated, copy)
    change(copy)
    with pytest.raises(ValueError, match=message):
        run_demo(copy)


def _edit_manifest(root, **fields):
    path = root / "sample.json"
    path.chmod(0o644)
    path.write_text(json.dumps({**json.loads(path.read_text()), **fields}))


def _append(path):
    path.chmod(0o644)
    with path.open("a") as f:
        f.write("\n")
