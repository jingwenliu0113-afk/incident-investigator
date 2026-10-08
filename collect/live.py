"""The real Docker-backed stack for collect.rungroup (decision 009), built on the env tooling."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from collect import faults
from env import compose, soak
from env.cli import _engine_platform, _load_lock, cmd_compose_exec, cmd_verify_running
from env.lock import lock_sha256, verify_against_disk


def passing_soak(data_root: Path, lock_sha: str) -> Path | None:
    """A soak report under data_root/soak that passed, tore down cleanly, and was run on exactly this lock."""
    for report_file in sorted((data_root / "soak").glob("*/report.json")):
        try:
            report = json.loads(report_file.read_text())
        except json.JSONDecodeError:
            continue
        if report.get("pass") is True and report.get("env_lock_sha256") == lock_sha \
                and (report.get("teardown") or {}).get("verify") == []:
            return report_file.parent
    return None


def foreign_running(run, env: dict[str, str], *, project: str) -> list[str]:
    """Running containers that do not belong to this project's compose stack (decision 008 §4)."""
    out = run(["docker", "ps", "--format", '{{.Names}}\t{{.Label "com.docker.compose.project"}}'], env)
    names = []
    for line in out.splitlines():
        if not line.strip():
            continue
        name, _, proj = line.partition("\t")
        if proj != project:
            names.append(name)
    return sorted(names)


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def time(self) -> float:
        return time.time()

    def now(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class LiveStack:
    def __init__(self, project_dir: Path, upstream_dir: Path, data_root: Path):
        self.project_dir, self.upstream_dir, self.data_root = project_dir, upstream_dir, data_root
        self.lock = _load_lock(project_dir)
        self.lock_sha256 = lock_sha256(self.lock)
        self.project = self.lock["startup"]["project_name"]
        self.env = compose.sanitized_env(os.environ)
        self.sampler: soak.Sampler | None = None

    def preflight(self) -> list[str]:
        problems = []
        try:
            soak.require_heavy_lock(self.project_dir)
        except soak.LockNotHeld as e:
            problems.append(str(e))
        problems += [f"verify: {p}" for p in verify_against_disk(self.lock, self.upstream_dir, self.project_dir)]
        if not soak.raw_export_expected(self.lock):
            problems.append("the locked stack has no raw pipeline (decision 008)")
        if passing_soak(self.data_root, self.lock_sha256) is None:
            problems.append(f"no passing baseline soak for lock {self.lock_sha256} (decision 009 §2)")
        try:
            if soak.project_container_ids(self.lock, self.env):
                problems.append(f"{self.project} containers already exist; run `python -m env compose down --volumes`")
            if others := foreign_running(soak._run, self.env, project=self.project):
                problems.append(f"other containers are running: {', '.join(others)} (decision 008 §4)")
        except (OSError, subprocess.CalledProcessError) as e:
            problems.append(f"docker unreachable: {str(e)[:200]}")
        return problems

    def provenance(self) -> dict:
        """Facts the incident manifest needs (decision 002), taken before `up`."""
        from collect.provenance import machine_info, project_git_state
        from collect.traffic import traffic_settings
        from env.cli import _compose_kwargs, cmd_compose_cmd
        from env.compose import render_config
        from env.lock import LOCK_PATH

        up = self.lock["upstream"]
        rendered = render_config(**_compose_kwargs(self.lock, self.project_dir, self.upstream_dir))
        return {"project": project_git_state(self.project_dir),
                "env_lock": {"path": str(LOCK_PATH), "sha256": self.lock_sha256, "upstream_tag": up["tag"],
                             "upstream_commit": up["commit"]},
                "machine": machine_info("mac"),
                "compose_command": cmd_compose_cmd(self.project_dir, self.upstream_dir, ["up"]),
                "traffic_settings": traffic_settings(rendered)}

    def compose(self, args: list[str]) -> int:
        return cmd_compose_exec(self.project_dir, self.upstream_dir, args)

    def watch(self, path: Path) -> soak.EventWatch:
        return soak.EventWatch(path, project=self.project, env=self.env)

    def verify_running(self, wait: float) -> list[str]:
        problems, _ = cmd_verify_running(self.project_dir, self.upstream_dir, wait=wait,
                                         expected_platform=_engine_platform())
        self.sampler = soak.Sampler(self.lock, soak.project_container_ids(self.lock, self.env), self.env)
        return problems

    def sample(self, kind: str) -> dict:
        try:
            return getattr(self.sampler, kind)()
        except (subprocess.CalledProcessError, ValueError, KeyError, StopIteration, AttributeError) as e:
            return {"kind": "error", "ts": RealClock().now(), "sampler": kind, "error": str(e)[:300]}

    def _exec_generator(self, code: str) -> str:
        lg = next(i for i, svc in self.sampler.ids.items() if svc == "load-generator")
        return soak._run(["docker", "exec", lg, "python", "-c", code], self.env)

    def ofrep(self, flag: str, context: dict) -> tuple[str, object]:
        try:
            return faults.parse_ofrep(self._exec_generator(faults.ofrep_code(flag, context)))
        except (subprocess.CalledProcessError, ValueError) as e:
            return f"<error: {str(e)[:120]}>", None

    def vm_time(self) -> float:
        return float(self._exec_generator("import time; print(time.time())"))

    def finalize_raw(self, out_dir: Path) -> dict:
        return soak.finalize_raw(self.compose, self.lock, self.env, out_dir)
