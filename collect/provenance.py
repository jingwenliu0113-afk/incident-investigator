"""Facts about *where* and *from what code* an incident was collected.

Records a machine role ("mac" / "gpu-server", see MACHINE_POLICY.md) and
hardware facts, never the hostname, so manifests can be shared as samples.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

MACHINE_ROLES = ("mac", "gpu-server")

Run = Callable[[Sequence[str]], str]


def _run(cmd: Sequence[str]) -> str:
    return subprocess.run(list(cmd), check=True, capture_output=True, text=True).stdout


def host_facts(run: Run = _run) -> dict:
    system, release, arch = run(["uname", "-srm"]).split()
    if system == "Darwin":
        cpu_model = run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        cpu_count = int(run(["sysctl", "-n", "hw.ncpu"]))
        memory = int(run(["sysctl", "-n", "hw.memsize"]))
    else:
        cpu_count = int(run(["nproc", "--all"]))  # machine-wide, like hw.ncpu (plain nproc honours affinity/OMP)
        cpu_model = next((line.split(":", 1)[1].strip() for line in run(["cat", "/proc/cpuinfo"]).splitlines()
                          if line.startswith("model name")), "unknown")
        mem_kb = next(int(line.split()[1]) for line in run(["cat", "/proc/meminfo"]).splitlines()
                      if line.startswith("MemTotal:"))
        memory = mem_kb * 1024
    return {"os": f"{system} {release}", "arch": arch, "cpu_model": cpu_model,
            "cpu_count": cpu_count, "memory_bytes": memory}


_DOCKER_ARCH = {"aarch64": "arm64", "x86_64": "amd64"}


def docker_facts(run: Run = _run) -> dict | None:
    """Docker engine facts, or None when the daemon is not reachable."""
    try:
        info = json.loads(run(["docker", "info", "--format", "{{json .}}"]))
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    if info.get("ServerErrors") or not info.get("ServerVersion"):
        return None
    arch = _DOCKER_ARCH.get(info["Architecture"], info["Architecture"])
    return {
        "server_version": info["ServerVersion"],
        "platform": f"{info['OSType']}/{arch}",
        "operating_system": info.get("OperatingSystem", ""),
        "cpus": info["NCPU"],
        "memory_bytes": info["MemTotal"],
    }


POWER_KEYS = ("powermode", "lowpowermode", "highpowermode")


def power_facts(run: Run = _run) -> dict | None:
    """macOS power source and the power-mode settings in use (`pmset`, read only; decision 025), or None without pmset."""
    try:
        settings, battery = run(["pmset", "-g"]), run(["pmset", "-g", "batt"])
    except (OSError, subprocess.CalledProcessError):
        return None
    found = {}
    for line in settings.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in POWER_KEYS:
            found[parts[0]] = parts[1]
    source = re.search(r"Now drawing from '([^']+)'", battery)
    return {"source": source.group(1) if source else None, "settings": found}


def machine_info(role: str, run: Run = _run) -> dict:
    if role not in MACHINE_ROLES:
        raise ValueError(f"machine role must be one of {MACHINE_ROLES}, got {role!r}")
    host = host_facts(run)
    power = power_facts(run) if host["os"].startswith("Darwin") else None
    return {"role": role, **host, "docker": docker_facts(run), "power": power}


def project_git_state(project_dir: Path, run: Run = _run) -> dict:
    try:
        commit = run(["git", "-C", str(project_dir), "rev-parse", "HEAD"]).strip()
    except subprocess.CalledProcessError:
        commit = None  # repository without commits yet
    dirty = bool(run(["git", "-C", str(project_dir), "status", "--porcelain"]).strip())
    return {"commit": commit, "dirty": dirty}
