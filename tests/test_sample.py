"""The synthetic sample and the 2-minute demo (decision 027): generated raw OTLP JSON through the real normalize, committed
byte for byte under data/samples/synthetic/, with the agent-readable and ground-truth trees kept apart."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from collect.layout import DataLayout
from collect.normalize import FILES, host_to_data_ns
from collect.rungroup import next_id
from collect.snapshot import open_snapshot
from env.lock import PROJECT_DIR

COMMITTED = PROJECT_DIR / "data/samples/synthetic"


def tree(root) -> dict[str, bytes]:
    from collect.sample import OS_FILES

    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and p.name not in OS_FILES}


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


def test_next_id_never_gives_000_and_only_calibrate_shares_the_sample_incident_id(tmp_path):
    """decision 027 §3: next_id never assigns 000 to a run group or incident, but collect calibrate also writes its soak
    snapshots (no fault, in no set, under data/external/calibration/) as INC-000: the id alone does not mean synthetic.
    A new use of either id in the code is noticed here."""
    from collect.freeze import CODE_DIRS
    from collect.sample import INCIDENT, RUN_GROUP

    assert (INCIDENT, RUN_GROUP) == ("INC-000", "RG-000")
    layout = DataLayout(tmp_path)
    assert (next_id(layout, "INC"), next_id(layout, "RG")) == ("INC-001", "RG-001")  # counters start at 001
    users = sorted({p.relative_to(PROJECT_DIR).as_posix() for d in CODE_DIRS for p in (PROJECT_DIR / d).rglob("*.py")
                    if re.search(r"\b(INC|RG)-000\b", p.read_text())})
    assert users == ["collect/calibrate.py", "collect/sample.py"]
    assert "保留" not in json.loads((PROJECT_DIR / "data/samples/synthetic/sample.json").read_text())["note"]
    assert "保留給範例" not in (PROJECT_DIR / "data/samples/synthetic/README.md").read_text()


def test_the_formal_set_listing_refuses_the_sample(generated, tmp_path):
    """The sample's injection says split pilot (the schema needs a set): if it ever lands in a formal root, every
    Pilot step that lists the set stops instead of scoring it (decision 027)."""
    from eval.runner import incidents_in

    root = tmp_path / "external"
    shutil.copytree(generated, root)
    with pytest.raises(ValueError, match="decision 027"):
        incidents_in(DataLayout(root), "pilot")


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


def test_the_sample_uses_the_attribute_keys_of_real_snapshots(generated):
    """Span and resource attribute keys come from the frozen policy's inventory (real soaks); the one new key is the
    deliberate synthetic marker on every resource (decision 027 §4)."""
    report = json.loads(DataLayout(generated).normalize_report_path("INC-000").read_text())
    new = report["new_attribute_keys"]
    assert new and all(group.startswith("resources/") for group in new)
    assert all(keys == ["deployment.environment.name"] for keys in new.values())


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


def test_replace_refuses_a_sample_of_another_generator_or_with_unlisted_files(generated, tmp_path):
    from collect.sample import generate

    other = tmp_path / "other"
    shutil.copytree(generated, other)
    _edit_manifest(other, generator={"name": "someone-else", "version": 1})
    with pytest.raises(FileExistsError, match="collect.sample"):
        generate(other, replace=True)
    for extra in ("notes.txt", "raw/RG-000/traces.jsonl"):  # raw/ is gitignored: git could not bring it back
        copy = tmp_path / extra.replace("/", "-")
        shutil.copytree(generated, copy)
        (copy / extra).parent.mkdir(parents=True, exist_ok=True)
        (copy / extra).write_text("mine")
        with pytest.raises(FileExistsError, match="not listed"):
            generate(copy, replace=True)
        assert (copy / extra).read_text() == "mine"


def test_replace_keeps_the_old_sample_when_writing_the_new_one_fails(generated, tmp_path, monkeypatch):
    import baselines.statistical as stat
    from collect.sample import generate

    copy = tmp_path / "copy"
    shutil.copytree(generated, copy)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(stat, "predict", boom)
    with pytest.raises(RuntimeError):
        generate(copy, replace=True)
    assert tree(copy) == tree(generated) and sorted(p.name for p in tmp_path.iterdir()) == ["copy"]


def test_replace_restores_the_old_sample_when_the_swap_fails(generated, tmp_path, monkeypatch):
    import collect.sample as sample

    copy = tmp_path / "copy"
    shutil.copytree(generated, copy)
    real = os.replace

    def replace(src, dst):
        if Path(dst) == copy and ".tmp-" in Path(src).name:
            raise OSError("the swap failed")
        return real(src, dst)

    monkeypatch.setattr(sample.os, "replace", replace)
    with pytest.raises(OSError, match="the swap failed"):
        sample.generate(copy, replace=True)
    assert tree(copy) == tree(generated) and sorted(p.name for p in tmp_path.iterdir()) == ["copy"]


def test_the_sample_is_normalized_with_the_frozen_policy_only(tmp_path, monkeypatch):
    import collect.policy as pol
    from collect.sample import generate

    real = pol.load_policy

    def draft(*args, **kwargs):
        policy = real(*args, **kwargs)
        return pol.Policy({**policy.raw, "status": "draft"}, policy.sha256)

    monkeypatch.setattr(pol, "load_policy", draft)
    with pytest.raises(PermissionError, match="frozen"):
        generate(tmp_path / "s")
    assert list(tmp_path.iterdir()) == []


def test_collect_sample_writes_the_sample_and_never_into_data_external(tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli

    assert cli.main(["sample", "--out", str(tmp_path / "s")]) == 0
    assert json.loads((tmp_path / "s" / "sample.json").read_text())["synthetic"] is True
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    assert cli.main(["sample", "--out", str(tmp_path / "data" / "external" / "s")]) == 2
    assert "data/external" in capsys.readouterr().err and not (tmp_path / "data" / "external").exists()


@pytest.mark.parametrize("parts", [("data", "external"), ("data", "EXTERNAL"), ("data", "EXTERNAL", "s"),
                                   ("Data", "External", "s")])
def test_collect_sample_refuses_the_formal_root_in_any_spelling(tmp_path, monkeypatch, capsys, parts):
    """APFS ignores case and resolve() keeps it: data/EXTERNAL is data/external on a Mac (and is refused everywhere)."""
    import collect.__main__ as cli

    project = tmp_path / "p"
    project.mkdir()
    monkeypatch.setattr(cli, "PROJECT_DIR", project)
    assert cli.main(["sample", "--out", str(project.joinpath(*parts))]) == 2
    assert "data/external" in capsys.readouterr().err and list(project.iterdir()) == []


def test_another_case_is_refused_even_where_the_file_system_tells_the_names_apart(tmp_path, monkeypatch):
    """On a case-sensitive file system data/EXTERNAL is another directory; it is still refused (conservative)."""
    import collect.sample as sample

    formal = tmp_path / "data" / "external"
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(sample.os.path, "samefile", lambda a, b: False)  # what a case-sensitive file system answers
    assert sample.inside(tmp_path / "data" / "EXTERNAL" / "s", formal)
    assert sample.inside(tmp_path / "Data" / "External", formal)
    assert not sample.inside(tmp_path / "data" / "external-copy", formal)
    assert not sample.inside(tmp_path / "data", formal)


def test_generate_itself_refuses_the_formal_root_through_a_link_or_another_case(tmp_path):
    from collect.sample import generate

    formal = tmp_path / "data" / "external"
    formal.mkdir(parents=True)
    (tmp_path / "link").symlink_to(formal)
    for out in (formal, formal / "s", tmp_path / "link" / "s", tmp_path / "data" / "External" / "s"):
        with pytest.raises(PermissionError, match="data/external"):
            generate(out, project_dir=tmp_path)
    assert list(formal.iterdir()) == [] and sorted(p.name for p in tmp_path.iterdir()) == ["data", "link"]


# ------------------------------------------------------------------ the 2-minute demo


def test_eval_demo_scores_the_baseline_on_the_committed_sample_and_says_the_numbers_are_not_results(capsys):
    import eval.__main__ as cli

    assert cli.main(["demo"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("SYNTHETIC")
    for needle in ("not results", "INC-000", "stat-anomaly", "fault_type", "origin_top1", "affected_f1", "symptom_exact",
                   "existence", "weak: temporal", "leakage audit", "difficulty", "lexicon hits",
                   "matches the committed example prediction: yes"):
        assert needle in out
    assert out.rstrip().splitlines()[-1].startswith("SYNTHETIC")  # said again at the end, under the table
    table = [line for line in out.splitlines() if line.startswith("|")]
    assert "SYNTHETIC" in table[0] and "not a result" in table[0]  # a copied table still says it


def test_the_demo_reports_every_layer_on_its_own(generated):
    from eval.demo import run_demo
    from eval.score import score_incident

    result = run_demo(generated)
    label = json.loads(DataLayout(generated).label_path("INC-000").read_text())
    assert result["synthetic"] is True and result["scores"] == score_incident(result["prediction"], label)
    assert result["evidence"]["existence"]["cited"] == len(result["prediction"]["evidence"])
    assert set(result["evidence"]["weak"]) == {"n", "temporal", "service", "origin", "weak"}
    assert result["matches_example"] is True


def test_the_demo_runs_the_leakage_audit_in_memory_like_the_runner(generated):
    from collect.snapshot import open_snapshot as opened
    from eval.demo import run_demo
    from eval.leakage import audit

    layout = DataLayout(generated)
    result = run_demo(generated)
    report = json.loads(layout.normalize_report_path("INC-000").read_text())
    expected = audit(opened(layout.incident_dir("INC-000") / "normalized", layout), result["label"],
                     clock_offset_s=report["window"]["clock_offsets"][0], new_attribute_keys=report["new_attribute_keys"])
    assert result["leakage"] == expected and expected["lexicon_hits"] == 0
    assert not layout.label_path("INC-000").with_name("leakage_audit.json").exists()  # nothing written


def test_the_demo_refuses_a_sample_with_lexicon_hits(generated, monkeypatch):
    import eval.leakage
    from eval.demo import run_demo

    real = eval.leakage.audit
    monkeypatch.setattr(eval.leakage, "audit", lambda *a, **k: {**real(*a, **k), "lexicon_hits": 1})
    with pytest.raises(ValueError, match="lexicon_hits"):
        run_demo(generated)


def test_the_demo_reads_the_label_only_after_the_prediction_exists(generated, monkeypatch):
    """decision 013: check_sample hashes every file's bytes, but the label is parsed only once predict has returned."""
    import pathlib

    import baselines.statistical as stat
    from eval.demo import run_demo

    events, real_predict = [], stat.predict
    real_text, real_bytes = pathlib.Path.read_text, pathlib.Path.read_bytes

    def predict(*args, **kwargs):
        out = real_predict(*args, **kwargs)
        events.append("predicted")
        return out

    def read(real):
        def reader(self, *args, **kwargs):
            if self.name == "label.json":
                events.append("label")
            return real(self, *args, **kwargs)
        return reader

    monkeypatch.setattr(stat, "predict", predict)
    monkeypatch.setattr(pathlib.Path, "read_text", read(real_text))
    monkeypatch.setattr(pathlib.Path, "read_bytes", read(real_bytes))
    run_demo(generated)
    assert "label" in events and events.index("predicted") < events.index("label")


def test_finder_files_break_neither_the_demo_nor_a_replace(generated, tmp_path):
    from collect.sample import generate
    from eval.demo import run_demo

    copy = tmp_path / "copy"
    shutil.copytree(generated, copy)
    for d in (copy, copy / "incidents/INC-000/normalized"):
        (d / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    assert run_demo(copy)["synthetic"] is True
    generate(copy, replace=True)
    assert tree(copy) == tree(generated)


@pytest.mark.parametrize("change, message", [
    (lambda root: _edit_manifest(root, synthetic=False), "synthetic"),
    (lambda root: _append(root / "incidents/INC-000/normalized/logs.jsonl"), "sha256"),
    (lambda root: _append(root / "ground_truth/incidents/INC-000/label.json"), "sha256"),
    (lambda root: (root / "incidents/INC-000/normalized/extra.jsonl").write_text("{}\n"), "not listed"),
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
