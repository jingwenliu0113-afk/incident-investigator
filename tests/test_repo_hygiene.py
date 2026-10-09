"""What may enter git: never telemetry dumps, Docker artifacts or large data (SPEC Core §2)."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from env.lock import PROJECT_DIR

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


def test_data_samples_hold_only_the_synthetic_files_their_manifest_lists():
    """decision 027: a real snapshot never enters git. Under data/samples/<name>/ there are only files that the sample's
    sample.json (synthetic: true) lists with their exact sha256, and all samples together stay under 1 MiB."""
    files = [f for f in git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", str(SAMPLES)).stdout.split("\0")
             if f and (PROJECT_DIR / f).is_file()]
    problems, total = [], 0
    for f in files:
        total += (PROJECT_DIR / f).stat().st_size
        parts = Path(f).parts
        if len(parts) < 4:
            problems.append(f"{f}: not inside a sample directory data/samples/<name>/")
            continue
        root = Path(*parts[:3])
        try:
            manifest = json.loads((PROJECT_DIR / root / "sample.json").read_text())
        except (OSError, ValueError):
            problems.append(f"{f}: {root}/sample.json is missing or not JSON")
            continue
        if manifest.get("synthetic") is not True:
            problems.append(f"{f}: {root}/sample.json does not say synthetic: true")
            continue
        rel = Path(f).relative_to(root).as_posix()
        listed = {e.get("path"): e.get("sha256") for e in manifest.get("files", [])}
        digest = "sha256:" + hashlib.sha256((PROJECT_DIR / f).read_bytes()).hexdigest()
        if rel != "sample.json" and listed.get(rel) != digest:
            problems.append(f"{f}: not listed with this sha256 in {root}/sample.json")
    assert not problems, "\n".join(problems)
    assert total <= MAX_SAMPLES_BYTES, f"data/samples holds {total} bytes"


def test_the_sample_manifest_check_refuses_an_unlisted_file(tmp_path, monkeypatch):
    """The check above would catch a copied real snapshot (it is not listed in any synthetic manifest)."""
    import test_repo_hygiene as me

    project = tmp_path / "p"
    sample = project / "data/samples/synthetic"
    sample.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (sample / "sample.json").write_text(json.dumps({"synthetic": True, "files": []}))
    (project / "data/samples/INC-002").mkdir()  # a copied real incident: no synthetic manifest
    (project / "data/samples/INC-002/spans.jsonl").write_text("{}\n")
    (sample / "spans.jsonl").write_text("{}\n")
    monkeypatch.setattr(me, "PROJECT_DIR", project)
    with pytest.raises(AssertionError) as e:
        me.test_data_samples_hold_only_the_synthetic_files_their_manifest_lists()
    assert "INC-002/sample.json is missing" in str(e.value) and "synthetic/spans.jsonl: not listed" in str(e.value)
