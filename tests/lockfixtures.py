"""Shared builders for env-lock tests (a tiny fake upstream checkout + project)."""

import hashlib
from pathlib import Path

import pytest

from env.compose import pinned_override_yaml
from env.lock import GitState, build_lock, pinned_images
from env.registry import ResolvedImage

COMMIT = "dedc0178918e260823323b8d95005a8cb924b007"
DEMO = "ghcr.io/open-telemetry/demo"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"


def d(ch):
    return "sha256:" + ch * 64


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def tree(tmp_path):
    up = tmp_path / "upstream"
    proj = tmp_path / "project"
    (up / "src" / "flagd").mkdir(parents=True)
    (up / "src" / "otel-collector").mkdir(parents=True)
    (proj / "env").mkdir(parents=True)
    (up / "compose.yaml").write_text("services: {}\n")
    (up / ".env").write_text("IMAGE_NAME=ghcr.io/open-telemetry/demo\n")
    (up / "src" / "flagd" / "demo.flagd.json").write_text('{"flags": {}}\n')
    (up / "src" / "otel-collector" / "otelcol-config.yml").write_text("receivers: {}\n")
    (proj / "env" / "otel-demo.overrides.env").write_text("DEMO_VERSION=3.1.0\n")
    return up, proj


def rendered_for(up: Path):
    return {"services": {
        "ad": {"image": f"{DEMO}:3.1.0-ad"},
        "flagd": {"image": "ghcr.io/open-feature/flagd:v0.16.0", "volumes": [
            {"type": "bind", "source": str(up / "src" / "flagd"), "target": "/etc/flagd"},
        ]},
        "flagd-ui": {"image": f"{DEMO}:3.1.0-flagd-ui", "volumes": [
            {"type": "bind", "source": str(up / "src" / "flagd"), "target": "/app/data"},
        ]},
        "otel-collector": {"image": "otel/collector:0.159.0", "volumes": [
            {"type": "bind", "source": "/", "target": "/hostfs", "read_only": True},
            {"type": "bind", "source": str(up / "src" / "otel-collector" / "otelcol-config.yml"),
             "target": "/etc/otelcol-config.yml"},
            {"type": "volume", "source": "data", "target": "/data"},
        ]},
    }}


def resolved_all():
    def r(ref, ch):
        return ResolvedImage(ref=ref, index_digest=d(ch), media_type=OCI_INDEX,
                             platforms={"linux/amd64": d("a"), "linux/arm64": d("b")})
    return {
        f"{DEMO}:3.1.0-ad": r(f"{DEMO}:3.1.0-ad", "1"),
        "ghcr.io/open-feature/flagd:v0.16.0": r("ghcr.io/open-feature/flagd:v0.16.0", "2"),
        f"{DEMO}:3.1.0-flagd-ui": r(f"{DEMO}:3.1.0-flagd-ui", "3"),
        "otel/collector:0.159.0": r("otel/collector:0.159.0", "4"),
    }


def make_lock(up, proj, **overrides):
    kwargs = dict(
        upstream={"repo": "https://github.com/open-telemetry/opentelemetry-demo", "tag": "3.1.0",
                  "commit": COMMIT, "demo_image_repo": DEMO},
        project_name="ii-otel-demo",
        compose_files=[("upstream", "compose.yaml")],
        env_files=[("upstream", ".env"), ("project", "env/otel-demo.overrides.env")],
        pinned_override="env/compose.pinned.yaml",
        up_args=["up", "--detach", "--no-build"],
        rendered=rendered_for(up),
        resolved=resolved_all(),
        required_platforms=["linux/arm64", "linux/amd64"],
        upstream_dir=up,
        project_dir=proj,
        generated_at="2026-10-08T00:00:00Z",
    )
    kwargs.update(overrides)
    return build_lock(**kwargs)


def write_pinned(lock, proj):
    (proj / "env" / "compose.pinned.yaml").write_text(
        pinned_override_yaml(pinned_images(lock), source="env/otel-demo.lock.json"))


def git_at(commit, dirty=()):
    """Fake upstream git probe: HEAD at `commit`, `dirty` = porcelain lines of local changes."""
    return lambda upstream_dir: GitState(head=commit, dirty=tuple(dirty))
