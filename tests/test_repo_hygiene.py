"""What may enter git: never telemetry dumps, Docker artifacts or large data (SPEC Core §2)."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from env.lock import PROJECT_DIR

IDS = re.compile(r"\b(?:INC|RG)-[0-9]{3,}\b")

MAX_TRACKED_BYTES = 1 << 20  # 1 MiB; small samples only
SAMPLES = Path("data/samples")
MAX_SAMPLES_BYTES = 1 << 20  # every sample together (decision 027)


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(PROJECT_DIR), *args], capture_output=True, text=True)


pytestmark = pytest.mark.skipif(git("rev-parse", "--git-dir").returncode != 0, reason="not a git checkout")


@pytest.mark.parametrize("path", [
    "data/external/incidents/INC-001/raw/traces.jsonl",  # raw telemetry
    "data/external/incidents/INC-001/normalized/spans.parquet",
    "data/external/ground_truth/run_groups/RG-001/injection.json",
    "data/external/smoke/2026-10-08/docker-inspect.json",
    "data/external/raw/RG-001/traces.jsonl",  # raw telemetry per run group (decision 008)
    "data/external/soak/20261008T095930Z/samples.jsonl",
    "data/samples/synthetic/raw/RG-000/traces.jsonl",  # decision 027: no raw telemetry under data/samples either
    "data/samples/INC-002/raw/logs.jsonl",
    "env/upstream/opentelemetry-demo/compose.yaml",  # upstream checkout
    "otel-demo-images.tar",  # docker save / image archives
    "snapshots/INC-001.tar.zst",
    "snapshot.tgz",
    "compose.override.yaml",  # local compose overrides
    "docker-compose.override.yml",
    "collector.log",
    ".venv/bin/python",
    ".DS_Store",
    # secrets / credentials never go into git
    ".env",
    "tools/.env.local",
    ".envrc",
    ".netrc",
    "secrets/registry-token.txt",
    "server.pem",
    "remote.key",
    "id_ed25519",
    "id_rsa.pub",
])
def test_heavy_or_local_artifacts_are_ignored(path):
    assert git("check-ignore", "-q", "--no-index", path).returncode == 0, f"{path} would be committed"


@pytest.mark.parametrize("path", [
    "env/otel-demo.lock.json",
    "env/compose.pinned.yaml",
    "env/compose.overrides.yaml",  # project overlay: reproducible config, not a local override
    "env/otel-demo.overrides.env",  # locked env overrides (no secrets)
    "uv.lock",
    "schemas/run_manifest.schema.json",
    "data/samples/synthetic/sample.json",  # the synthetic sample is meant to be committed (decision 027)
    "data/samples/synthetic/incidents/INC-000/normalized/spans.jsonl",
    "data/samples/synthetic/ground_truth/incidents/INC-000/label.json",
    "docs/smoke-tests/2026-10-08-m1-mac-smoke.md",
    "docs/heldout/plan.json",  # decision 023: the held-out plan, slot list and freeze record are committed
    "docs/heldout/slots.json",
    "docs/heldout/freeze.json",
])
def test_project_files_are_not_ignored(path):
    assert git("check-ignore", "-q", "--no-index", path).returncode == 1, f"{path} is ignored"


def test_every_file_git_would_track_is_small():
    files = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout.split("\0")
    big = [(f, (PROJECT_DIR / f).stat().st_size) for f in files
           if f and (PROJECT_DIR / f).is_file() and (PROJECT_DIR / f).stat().st_size > MAX_TRACKED_BYTES]
    assert big == [], f"files over {MAX_TRACKED_BYTES} bytes would be committed: {big}"


def test_committed_heldout_files_describe_only_the_design():
    # decision 023 / 026: plan, slots and freeze never name an incident or run group (ids would map to faults)
    from pathlib import Path

    from collect.freeze import CODE_DIRS
    from collect.heldout import FREEZE_FILE, HELDOUT_DIR, ID, PLAN_FILE, SLOTS_FILE

    assert HELDOUT_DIR == Path("docs/heldout") and all(f.parent == HELDOUT_DIR for f in (PLAN_FILE, SLOTS_FILE, FREEZE_FILE))
    assert not any(f.parts[0] in CODE_DIRS for f in (PLAN_FILE, SLOTS_FILE, FREEZE_FILE))
    for path in sorted((PROJECT_DIR / HELDOUT_DIR).glob("*.json")):
        assert not ID.search(path.read_text()), f"{path} names an incident or run group"


def sample_problems() -> list[str]:
    """decision 027 §6: data/samples/ holds one directory, data/samples/synthetic/ (the one tests/test_sample.py regenerates
    and compares byte for byte), and in it only files that its sample.json (synthetic: true, generator collect.sample)
    lists with their exact sha256 and that name no incident or run group but the sample's; 1 MiB at most in all."""
    from collect.sample import GENERATOR, INCIDENT, RUN_GROUP, SAMPLE_DIR, SAMPLE_FILE

    files = [f for f in git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", str(SAMPLES)).stdout.split("\0")
             if f and (PROJECT_DIR / f).is_file()]
    try:
        manifest = json.loads((PROJECT_DIR / SAMPLE_DIR / SAMPLE_FILE).read_text())
    except (OSError, ValueError):
        manifest = None
    problems, total = [], 0
    if files and manifest is None:
        problems.append(f"{SAMPLE_DIR}/{SAMPLE_FILE} is missing or not JSON")
    elif manifest is not None and manifest.get("synthetic") is not True:
        problems.append(f"{SAMPLE_DIR}/{SAMPLE_FILE} does not say synthetic: true")
    elif manifest is not None and (manifest.get("generator") or {}).get("name") != GENERATOR["name"]:
        problems.append(f"{SAMPLE_DIR}/{SAMPLE_FILE} does not name the generator {GENERATOR['name']}")
    listed = {e.get("path"): e.get("sha256") for e in (manifest or {}).get("files", [])}
    for f in files:
        data = (PROJECT_DIR / f).read_bytes()
        total += len(data)
        if SAMPLE_DIR not in Path(f).parents:
            problems.append(f"{f}: outside {SAMPLE_DIR}/, the only sample directory (decision 027)")
            continue
        rel = Path(f).relative_to(SAMPLE_DIR).as_posix()
        if rel != SAMPLE_FILE and listed.get(rel) != "sha256:" + hashlib.sha256(data).hexdigest():
            problems.append(f"{f}: not listed with this sha256 in {SAMPLE_DIR}/{SAMPLE_FILE}")
        if other := sorted(set(IDS.findall(f + "\n" + data.decode(errors="replace"))) - {INCIDENT, RUN_GROUP}):
            problems.append(f"{f}: names {other}, not the sample's {INCIDENT} / {RUN_GROUP}")
    if total > MAX_SAMPLES_BYTES:
        problems.append(f"data/samples holds {total} bytes (at most {MAX_SAMPLES_BYTES})")
    return problems


def test_data_samples_hold_only_the_generated_synthetic_sample():
    assert sample_problems() == []


def _project(tmp_path, monkeypatch, files: dict[str, bytes], **manifest) -> Path:
    """A scratch git checkout whose data/samples/ holds `files`, each listed with its sha256 in a sample.json that says
    synthetic and names collect.sample unless `manifest` says otherwise; the check above then looks at it."""
    import test_repo_hygiene as me

    project = tmp_path / "p"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    for path, data in files.items():
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_bytes(data)
    listed = {}
    for path, data in files.items():  # every file listed in the manifest of its own directory data/samples/<name>/
        root = Path(*Path(path).parts[:3])
        listed.setdefault(root, []).append({"path": Path(path).relative_to(root).as_posix(),
                                            "sha256": "sha256:" + hashlib.sha256(data).hexdigest()})
    for root, entries in listed.items():
        doc = {"synthetic": True, "generator": {"name": "collect.sample", "version": 1}, "files": entries, **manifest}
        (project / root / "sample.json").write_text(json.dumps(doc))
    monkeypatch.setattr(me, "PROJECT_DIR", project)
    return project


LABEL = json.dumps({"incident_id": "INC-000", "run_group_id": "RG-000"}).encode()


@pytest.mark.parametrize("files, manifest, problem", [
    ({"data/samples/synthetic/ground_truth/incidents/INC-000/label.json": LABEL}, {}, None),
    # a real incident copied in next to the sample, with a hand-written manifest of its own that says synthetic
    ({"data/samples/real/ground_truth/incidents/INC-003/label.json": b'{"incident_id": "INC-003"}'}, {},
     "outside data/samples/synthetic/"),
    ({"data/samples/INC-002/spans.jsonl": b"{}\n"}, {}, "outside data/samples/synthetic/"),
    ({"data/samples/synthetic/label.json": LABEL}, {"synthetic": False}, "does not say synthetic: true"),
    ({"data/samples/synthetic/label.json": LABEL}, {"generator": {"name": "by-hand", "version": 1}},
     "does not name the generator collect.sample"),
    ({"data/samples/synthetic/ground_truth/incidents/INC-003/label.json": b'{"incident_id": "INC-003"}'}, {},
     "names ['INC-003']"),
    ({"data/samples/synthetic/spans.jsonl": b"x" * (MAX_SAMPLES_BYTES + 1)}, {}, "bytes (at most"),
])
def test_the_sample_check_refuses_anything_but_the_generated_sample(tmp_path, monkeypatch, files, manifest, problem):
    _project(tmp_path, monkeypatch, files, **manifest)
    problems = sample_problems()
    assert problems == [] if problem is None else any(problem in p for p in problems), problems


def test_the_sample_check_refuses_an_unlisted_file_and_a_missing_manifest(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, {"data/samples/synthetic/label.json": LABEL})
    (project / "data/samples/synthetic/spans.jsonl").write_text("{}\n")
    assert sample_problems() == ["data/samples/synthetic/spans.jsonl: not listed with this sha256 in "
                                 "data/samples/synthetic/sample.json"]
    (project / "data/samples/synthetic/sample.json").unlink()
    assert "data/samples/synthetic/sample.json is missing or not JSON" in sample_problems()
