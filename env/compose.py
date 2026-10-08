"""Thin, deterministic wrapper around `docker compose` for the pinned OTel Demo.

`docker compose config` is the authority on what a compose file set resolves
to (interpolation, merging); it needs only the CLI, not a running daemon.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from env.imageref import parse_image_ref


class ComposeError(RuntimeError):
    pass


# Compose lets the process environment override --env-file values, and reads
# COMPOSE_* variables itself. Only pass through what is needed to reach Docker.
_ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL",
    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY",
)

Runner = Callable[[list[str], dict[str, str]], str]


def sanitized_env(base: Mapping[str, str]) -> dict[str, str]:
    return {k: base[k] for k in _ENV_ALLOWLIST if k in base}


def compose_command(
    *,
    upstream_dir: Path,
    project_name: str,
    env_files: Sequence[Path],
    compose_files: Sequence[Path],
    args: Sequence[str],
) -> list[str]:
    for p in [upstream_dir, *env_files, *compose_files]:
        if not Path(p).is_absolute():
            raise ComposeError(f"compose paths must be absolute, got {p}")
    cmd = ["docker", "compose", "--project-directory", str(upstream_dir), "--project-name", project_name]
    for f in env_files:
        cmd += ["--env-file", str(f)]
    for f in compose_files:
        cmd += ["-f", str(f)]
    return cmd + list(args)


def _run(cmd: list[str], env: dict[str, str]) -> str:
    return subprocess.run(cmd, env=env, check=True, capture_output=True, text=True).stdout


def render_config(
    *,
    upstream_dir: Path,
    project_name: str,
    env_files: Sequence[Path],
    compose_files: Sequence[Path],
    runner: Runner = _run,
    base_env: Mapping[str, str] | None = None,
) -> dict:
    cmd = compose_command(
        upstream_dir=upstream_dir, project_name=project_name, env_files=env_files,
        compose_files=compose_files, args=["config", "--format", "json"],
    )
    env = sanitized_env(os.environ if base_env is None else base_env)
    try:
        return json.loads(runner(cmd, env))
    except subprocess.CalledProcessError as e:
        raise ComposeError(f"docker compose config failed: {e.stderr or e.output}") from e


def service_images(rendered: dict) -> dict[str, str]:
    services = rendered.get("services") or {}
    if not services:
        raise ComposeError("rendered compose config has no services")
    out = {}
    for name, svc in sorted(services.items()):
        image = svc.get("image")
        if not image:
            raise ComposeError(f"service {name!r} has no image (build-only services cannot be digest-pinned)")
        out[name] = image
    return out


def pinned_override_yaml(images: Mapping[str, str], *, source: str) -> str:
    lines = [f"# GENERATED from {source} by `python -m env pin` — do not edit by hand.", "services:"]
    for name in sorted(images):
        ref = images[name]
        if parse_image_ref(ref).digest is None:
            raise ComposeError(f"image for {name!r} is not digest-pinned: {ref}")
        lines += [f"  {name}:", f'    image: "{ref}"']
    return "\n".join(lines) + "\n"
