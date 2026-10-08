"""What may enter git: never telemetry dumps, Docker artifacts or large data (SPEC Core §2)."""

import subprocess

import pytest

from env.lock import PROJECT_DIR

MAX_TRACKED_BYTES = 1 << 20  # 1 MiB; small samples only


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
    "data/samples/INC-001/manifest.json",  # small, shareable samples are meant to be committed
    "docs/smoke-tests/2026-10-08-m1-mac-smoke.md",
])
def test_project_files_are_not_ignored(path):
    assert git("check-ignore", "-q", "--no-index", path).returncode == 1, f"{path} is ignored"


def test_every_file_git_would_track_is_small():
    files = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout.split("\0")
    big = [(f, (PROJECT_DIR / f).stat().st_size) for f in files
           if f and (PROJECT_DIR / f).is_file() and (PROJECT_DIR / f).stat().st_size > MAX_TRACKED_BYTES]
    assert big == [], f"files over {MAX_TRACKED_BYTES} bytes would be committed: {big}"
