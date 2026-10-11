"""The inference host "gpu-server" of the LLM methods (decision 029 revision 1, user decision 2026-10-11).

The eval runs on this Mac (snapshots and ground truth never leave it); only the model calls go to the user's RTX 5070 Ti
desktop, through the SSH tunnel of tools/with-remote-ollama (Mac 127.0.0.1:11434 -> gpu-server 127.0.0.1:11434, Ollama
inside WSL Ubuntu-22.04 under the shared GPU lock). This module holds what the Python side needs for that host:

- require_remote(): a run or probe with host "gpu-server" runs only under the wrapper, which exports
  II_INFERENCE_HOST=gpu-server and II_INFERENCE_TUNNEL_PID (its ssh session's pid, which must be alive). It replaces the
  Mac heavy lock for that host: the Mac only runs the light eval loop.
- gpu_facts(): the GPU state, read only, by one `ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- nvidia-smi --query-gpu=...'`
  (the user's existing alias; no credential is read or passed). None when it cannot be read; never a guess.
- the rule of decision 029 revision 1 (eval/runner.py applies it): a sample that cannot be read is recorded as null; the
  run stops only when a GPU that is read is not an RTX 5070 Ti, or when two samples in a row cannot be read.
"""

from __future__ import annotations

import os
import subprocess

from agent.ollama import HOSTS

LOCAL, REMOTE = HOSTS
ENV_HOST, ENV_TUNNEL = "II_INFERENCE_HOST", "II_INFERENCE_TUNNEL_PID"
WRAPPER = "./tools/with-remote-ollama"
SSH = ("ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ControlPath=none", REMOTE)
WSL = "wsl.exe -d Ubuntu-22.04 --"
GPU_QUERY = "name,driver_version,power.limit,power.draw,clocks.sm,temperature.gpu,memory.used"
GPU_KEYS = ("name", "driver_version", "power_limit_w", "power_draw_w", "clocks_sm_mhz", "temperature_c", "memory_used_mib")
GPU_UNITS = (None, None, "W", "W", "MHz", "", "MiB")  # None: text; otherwise a number with this unit suffix
EXPECTED_GPU = "RTX 5070 Ti"
GPU_TIMEOUT_S = 60
UNREADABLE = "GPU state unreadable (nvidia-smi on gpu-server through ssh; decision 029 revision 1)"
GPU_CONDITION = ("inference host gpu-server: the user's RTX 5070 Ti desktop on mains power, its GPU state (nvidia-smi) "
                 "read before and after the incident (decision 029 revision 1)")


class NotWrapped(RuntimeError):
    """A gpu-server run or probe outside tools/with-remote-ollama (the CLI prints it and exits 2)."""


def require_remote(environ=None) -> dict:
    """The run is under tools/with-remote-ollama: II_INFERENCE_HOST is gpu-server and II_INFERENCE_TUNNEL_PID names a
    live process (the wrapper's ssh session; a variable left in a shell from an earlier session names a dead one)."""
    env = os.environ if environ is None else environ
    usage = (f"the LLM methods' inference host is gpu-server (eval/llm_methods.json ollama.host, decision 029 revision 1): "
             f"run under {WRAPPER}, e.g. `{WRAPPER} uv run python -m eval run --method agent --set pilot`")
    if env.get(ENV_HOST) != REMOTE:
        raise NotWrapped(f"{usage} ({ENV_HOST} is {env.get(ENV_HOST)!r})")
    pid = env.get(ENV_TUNNEL, "")
    if not pid.isdigit():
        raise NotWrapped(f"{usage} ({ENV_TUNNEL} is {pid!r}: no tunnel)")
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        raise NotWrapped(f"{usage} (the tunnel's ssh pid {pid} is not alive)") from None
    except PermissionError:
        pass  # alive, owned by someone else: not ours to judge here
    return {"host": REMOTE, "tunnel_pid": int(pid)}


def gpu_command() -> list[str]:
    return [*SSH, f"{WSL} nvidia-smi --query-gpu={GPU_QUERY} --format=csv,noheader"]


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=GPU_TIMEOUT_S).stdout


def _value(text: str, unit: str | None):
    if unit is None:
        return text
    if text.startswith("["):  # [N/A], [Not Supported]
        return None
    number = text[: -len(unit)].strip() if unit and text.endswith(unit) else text
    return float(number) if unit == "W" else int(float(number))


def parse_gpus(text: str) -> dict | None:
    """nvidia-smi's csv,noheader lines as {"gpus": [...]}; None if any line is not the queried 7 fields."""
    gpus = []
    for line in [x.strip() for x in text.replace("\r", "").splitlines() if x.strip()]:
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != len(GPU_KEYS) or not parts[0]:
            return None
        try:
            gpus.append({**{k: _value(v, u) for k, v, u in zip(GPU_KEYS, parts, GPU_UNITS)}, "raw": line})
        except ValueError:
            return None
    return {"gpus": gpus} if gpus else None


def gpu_facts(run=_run) -> dict | None:
    """The GPU state of gpu-server (read only), or None when it cannot be read (ssh or nvidia-smi fails or times out, or
    the output is not the queried fields)."""
    try:
        return parse_gpus(run(gpu_command()))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def wrong_gpu(facts: dict | None) -> list[str]:
    """A GPU that was read and is not an RTX 5070 Ti (an unreadable state is not a wrong GPU)."""
    if facts is None:
        return []
    return [f"the GPU is {g['name']!r}, not an RTX 5070 Ti" for g in facts["gpus"] if EXPECTED_GPU not in g["name"]]


def gpu_problems(facts: dict | None) -> list[str]:
    return [UNREADABLE] if facts is None else wrong_gpu(facts)
