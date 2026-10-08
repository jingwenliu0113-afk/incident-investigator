import json
import shutil
import subprocess
from pathlib import Path

import pytest

from env.compose import (
    ComposeError,
    compose_command,
    pinned_override_yaml,
    render_config,
    sanitized_env,
    service_images,
)

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


def test_service_images_maps_every_service():
    rendered = {"services": {
        "ad": {"image": "ghcr.io/open-telemetry/demo:3.1.0-ad", "build": {"context": "/x"}},
        "astronomy-db": {"image": "postgres:18.4"},
    }}
    assert service_images(rendered) == {
        "ad": "ghcr.io/open-telemetry/demo:3.1.0-ad",
        "astronomy-db": "postgres:18.4",
    }


def test_service_images_rejects_build_only_service():
    # A service without a published image cannot be pinned by digest.
    with pytest.raises(ComposeError, match="opensearch"):
        service_images({"services": {"opensearch": {"build": {"context": "/x"}}}})


def test_service_images_rejects_empty_config():
    with pytest.raises(ComposeError):
        service_images({"services": {}})


def test_pinned_override_yaml_is_sorted_quoted_and_marked_generated():
    text = pinned_override_yaml(
        {"frontend": f"ghcr.io/open-telemetry/demo:3.1.0-frontend@{D2}", "ad": f"ghcr.io/open-telemetry/demo:3.1.0-ad@{D1}"},
        source="env/otel-demo.lock.json",
    )
    lines = text.splitlines()
    assert lines[0].startswith("# GENERATED")
    assert "env/otel-demo.lock.json" in lines[0]
    body = [line for line in lines if not line.startswith("#")]
    assert body == [
        "services:",
        "  ad:",
        f'    image: "ghcr.io/open-telemetry/demo:3.1.0-ad@{D1}"',
        "  frontend:",
        f'    image: "ghcr.io/open-telemetry/demo:3.1.0-frontend@{D2}"',
    ]
    assert text.endswith("\n")


def test_pinned_override_yaml_requires_digest_refs():
    with pytest.raises(ComposeError, match="not digest-pinned"):
        pinned_override_yaml({"ad": "ghcr.io/open-telemetry/demo:3.1.0-ad"}, source="x")


def test_compose_command_uses_absolute_paths_in_order(tmp_path):
    up = tmp_path / "upstream"
    cmd = compose_command(
        upstream_dir=up,
        project_name="ii-otel-demo",
        env_files=[up / ".env", tmp_path / "overrides.env"],
        compose_files=[up / "compose.yaml", up / "compose.full.yaml", tmp_path / "pinned.yaml"],
        args=["config", "--format", "json"],
    )
    assert cmd == [
        "docker", "compose",
        "--project-directory", str(up),
        "--project-name", "ii-otel-demo",
        "--env-file", str(up / ".env"),
        "--env-file", str(tmp_path / "overrides.env"),
        "-f", str(up / "compose.yaml"),
        "-f", str(up / "compose.full.yaml"),
        "-f", str(tmp_path / "pinned.yaml"),
        "config", "--format", "json",
    ]


def test_compose_command_rejects_relative_paths(tmp_path):
    with pytest.raises(ComposeError, match="absolute"):
        compose_command(upstream_dir=tmp_path, project_name="p", env_files=[Path(".env")],
                        compose_files=[tmp_path / "c.yaml"], args=["config"])


def test_sanitized_env_drops_shell_variables_that_would_override_env_files():
    # Compose gives the process environment precedence over --env-file, so a stray
    # IMAGE_NAME / DEMO_VERSION in the user's shell would silently change the stack.
    env = sanitized_env({"PATH": "/bin", "HOME": "/h", "DOCKER_CONTEXT": "desktop-linux",
                         "DEMO_VERSION": "latest", "IMAGE_NAME": "evil/x", "COMPOSE_FILE": "x.yaml",
                         "COMPOSE_PROFILES": "p"})
    assert env == {"PATH": "/bin", "HOME": "/h", "DOCKER_CONTEXT": "desktop-linux"}


def test_render_config_runs_compose_with_sanitized_env(tmp_path):
    seen = {}

    def runner(cmd, env):
        seen["cmd"], seen["env"] = cmd, env
        return json.dumps({"services": {"ad": {"image": "x"}}})

    out = render_config(
        upstream_dir=tmp_path, project_name="p", env_files=[tmp_path / ".env"],
        compose_files=[tmp_path / "compose.yaml"], runner=runner,
        base_env={"PATH": "/bin", "DEMO_VERSION": "latest"},
    )
    assert out == {"services": {"ad": {"image": "x"}}}
    assert seen["cmd"][-3:] == ["config", "--format", "json"]
    assert "DEMO_VERSION" not in seen["env"]


def test_render_config_wraps_failures(tmp_path):
    def runner(cmd, env):
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="no such file")

    with pytest.raises(ComposeError, match="no such file"):
        render_config(upstream_dir=tmp_path, project_name="p", env_files=[], compose_files=[tmp_path / "c.yaml"],
                      runner=runner, base_env={})


@pytest.mark.docker_cli
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
def test_pinned_override_really_overrides_images_with_docker_compose(tmp_path):
    (tmp_path / "compose.yaml").write_text(
        "services:\n  ad:\n    image: ${IMAGE_NAME}:${DEMO_VERSION}-ad\n    build: {context: .}\n"
    )
    (tmp_path / ".env").write_text("IMAGE_NAME=ghcr.io/open-telemetry/demo\nDEMO_VERSION=latest\n")
    (tmp_path / "pinned.yaml").write_text(
        pinned_override_yaml({"ad": f"ghcr.io/open-telemetry/demo:3.1.0-ad@{D1}"}, source="test")
    )
    rendered = render_config(upstream_dir=tmp_path, project_name="p", env_files=[tmp_path / ".env"],
                             compose_files=[tmp_path / "compose.yaml", tmp_path / "pinned.yaml"])
    assert service_images(rendered) == {"ad": f"ghcr.io/open-telemetry/demo:3.1.0-ad@{D1}"}
