"""decision 029 revision 1 (user decision 2026-10-11): the LLM methods' model runs on the user's RTX 5070 Ti desktop
(inference host "gpu-server") through tools/with-remote-ollama, while the eval stays on this Mac. A gpu-server run needs
the wrapper (II_INFERENCE_HOST / II_INFERENCE_TUNNEL_PID) instead of the Mac heavy lock, never reads the Mac's power mode
and records the GPU state (nvidia-smi through `ssh gpu-server`) before and after each incident in power.jsonl.

Nothing here runs ssh or nvidia-smi: the GPU state is monkeypatched (or a fake `run` is passed) and the scripted
transport stands in for Ollama."""

import json
import os
import subprocess

import pytest

import agent.ollama as ollama
import collect.provenance as provenance
import env.soak as soak
import eval.inference_host as inference_host
import eval.runner as runner
from eval.runner import LLM_CONFIG, LLM_METHODS, POWER_LOG, audit_set, pilot_llm_problems, run_method, score_method
from ollama_fixtures import MODEL, FakeOllama, answering, approved_config
from test_eval_runner import stored
from test_local_llm import power_lines, write

CARD = {"name": "NVIDIA GeForce RTX 5070 Ti", "driver_version": "581.57", "power_limit_w": 300.0, "power_draw_w": 21.5,
        "clocks_sm_mhz": 210, "temperature_c": 38, "memory_used_mib": 1530,
        "raw": "NVIDIA GeForce RTX 5070 Ti, 581.57, 300.00 W, 21.50 W, 210 MHz, 38, 1530 MiB"}
GPU = {"gpus": [CARD]}
OTHER = {"gpus": [{**CARD, "name": "NVIDIA GeForce RTX 4060"}]}
SEEN = [{"name": "NVIDIA GeForce RTX 5070 Ti", "driver_version": "581.57", "power_limit_w": 300.0}]


def gpu(monkeypatch, *states):
    """The GPU state of each nvidia-smi read, in order, the last one repeating (None: unreadable)."""
    states, reads = list(states) or [GPU], []

    def facts(*args, **kwargs):
        reads.append(len(reads))
        return states[min(len(reads), len(states)) - 1]

    monkeypatch.setattr(inference_host, "gpu_facts", facts)
    return reads


def wrapped(monkeypatch, pid=None):
    """What tools/with-remote-ollama exports to its command (the pid of its live ssh session)."""
    monkeypatch.setenv("II_INFERENCE_HOST", "gpu-server")
    monkeypatch.setenv("II_INFERENCE_TUNNEL_PID", str(os.getpid() if pid is None else pid))


def mac_untouched(monkeypatch):
    def no_lock(project_dir):
        raise AssertionError("the Mac heavy lock was asked for")

    def no_pmset(*args, **kwargs):
        raise AssertionError("the Mac power mode was read")

    monkeypatch.setattr(soak, "require_heavy_lock", no_lock)
    monkeypatch.setattr(provenance, "power_facts", no_pmset)


def remote(monkeypatch, tmp_path, fake, config=None):
    """The committed inference host under the wrapper: the scripted Ollama behind the tunnel's loopback endpoint."""
    monkeypatch.setattr(runner, "LLM_CONFIG", write(tmp_path, config or approved_config(host="gpu-server")))
    monkeypatch.setattr(ollama, "default_transport", lambda url, timeout: fake)
    mac_untouched(monkeypatch)
    wrapped(monkeypatch)
    return gpu(monkeypatch)


def dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


# ---------------------------------------------------------------- the GPU state and the wrapper check

def test_the_gpu_state_is_one_nvidia_smi_query_through_the_users_ssh_alias():
    assert inference_host.gpu_command() == [
        "ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ControlPath=none", "gpu-server",
        "wsl.exe -d Ubuntu-22.04 -- nvidia-smi --query-gpu=name,driver_version,power.limit,power.draw,clocks.sm,"
        "temperature.gpu,memory.used --format=csv,noheader"]
    seen = []

    def run(cmd):
        seen.append(cmd)
        return CARD["raw"] + "\r\n"  # the Windows side may end lines with CRLF

    assert inference_host.gpu_facts(run) == GPU and seen == [inference_host.gpu_command()]
    na = inference_host.gpu_facts(lambda cmd: "NVIDIA GeForce RTX 5070 Ti, 581.57, [N/A], [N/A], 210 MHz, 38, 1530 MiB\n")
    assert na["gpus"][0]["power_limit_w"] is None and na["gpus"][0]["power_draw_w"] is None
    assert na["gpus"][0]["clocks_sm_mhz"] == 210


@pytest.mark.parametrize("fails", [
    subprocess.CalledProcessError(255, ["ssh"]), subprocess.TimeoutExpired(["ssh"], 60), FileNotFoundError("ssh"),
    "", "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\n", "a, b, c\n",
], ids=["ssh-fails", "timeout", "no-ssh", "empty", "driver-error", "short-line"])
def test_an_unreadable_gpu_state_is_none_never_a_guess(fails):
    def run(cmd):
        if isinstance(fails, BaseException):
            raise fails
        return fails

    facts = inference_host.gpu_facts(run)
    assert facts is None
    assert inference_host.gpu_problems(facts) == [
        "GPU state unreadable (nvidia-smi on gpu-server through ssh; decision 029 revision 1)"]
    assert inference_host.wrong_gpu(facts) == []  # unreadable is not a wrong GPU
    assert inference_host.gpu_problems(GPU) == [] and inference_host.wrong_gpu(GPU) == []
    assert inference_host.wrong_gpu(OTHER) == ["the GPU is 'NVIDIA GeForce RTX 4060', not an RTX 5070 Ti"]
    assert inference_host.gpu_problems(OTHER) == inference_host.wrong_gpu(OTHER)


def test_the_wrapper_check_needs_the_host_and_a_live_tunnel(monkeypatch):
    monkeypatch.delenv("II_INFERENCE_HOST", raising=False)
    monkeypatch.delenv("II_INFERENCE_TUNNEL_PID", raising=False)
    with pytest.raises(RuntimeError, match=r"\./tools/with-remote-ollama uv run python -m eval"):
        inference_host.require_remote()
    monkeypatch.setenv("II_INFERENCE_HOST", "local")
    with pytest.raises(RuntimeError, match="with-remote-ollama"):
        inference_host.require_remote()
    wrapped(monkeypatch, dead_pid())  # e.g. an exported variable left from an earlier session
    with pytest.raises(RuntimeError, match="not alive"):
        inference_host.require_remote()
    wrapped(monkeypatch, "x")
    with pytest.raises(RuntimeError, match="tunnel"):
        inference_host.require_remote()
    wrapped(monkeypatch)
    assert inference_host.require_remote() == {"host": "gpu-server", "tunnel_pid": os.getpid()}


# ---------------------------------------------------------------- runs on gpu-server

def test_the_committed_host_is_gpu_server_and_part_of_the_pinned_record():
    config = json.loads(LLM_CONFIG.read_text())
    assert config["ollama"]["host"] == "gpu-server"
    assert ollama.pinned_record(config)["host"] == "gpu-server"  # so the freeze compares it (decision 026 #32)
    assert ollama.pinned_record(approved_config())["host"] == "local"


def test_a_gpu_server_run_outside_the_wrapper_runs_nothing(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    fake = FakeOllama(chat=answering)
    reads = remote(monkeypatch, tmp_path, fake)
    for unwrapped in ({"II_INFERENCE_HOST": None}, {"II_INFERENCE_TUNNEL_PID": str(dead_pid())}):
        for key, value in unwrapped.items():
            if value is None:
                monkeypatch.delenv(key)
            else:
                monkeypatch.setenv(key, value)
        for method in LLM_METHODS:
            with pytest.raises(RuntimeError, match="with-remote-ollama"):
                run_method(layout, method, "pilot", out)
        wrapped(monkeypatch)
    assert not out.exists() and fake.requests == [] and reads == []  # refused before the GPU or the server is asked


def test_a_pilot_run_on_gpu_server_records_the_host_and_the_gpu_state_and_never_the_mac_power(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    fake = FakeOllama(chat=answering)
    reads = remote(monkeypatch, tmp_path, fake)
    for method in LLM_METHODS:
        run_method(layout, method, "pilot", out)
        assert json.loads((out / "pilot" / method / "run_config.json").read_text())["llm"]["host"] == "gpu-server"
        (line,) = power_lines(out, "pilot", method)
        assert (line["incident_id"], line["attempt"], line["host"], line["formal"], line["problems"]) == (
            "INC-001", None, "gpu-server", True, [])
        assert line["before"]["gpu"] == line["after"]["gpu"] == GPU and "power" not in line["before"]
        assert "gpu" not in json.loads((out / "pilot" / method / "INC-001.json").read_text())  # decision 013 format
    assert len(reads) == 9  # per run: at the start, before and after the one incident
    audit_set(layout, "pilot", out)
    result = score_method(layout, "agent", "pilot", out)
    assert result["usage"]["latency_power"] == {"host": "gpu-server", "condition": inference_host.GPU_CONDITION,
                                               "incidents_timed": 1, "not_formal": [], "gpus": SEEN}
    table = (out / "pilot" / "agent" / "table.md").read_text()
    assert "Inference host: gpu-server" in table and "RTX 5070 Ti desktop" in table
    assert "GPU (nvidia-smi before and after each incident): NVIDIA GeForce RTX 5070 Ti, driver 581.57, power limit 300 W" in table
    assert "AC power" not in table and "on this Mac" not in table and "high power mode" not in table
    assert pilot_llm_problems(out, approved_config(host="gpu-server"), LLM_METHODS)[0] == []
    # the Pilot of another host is not the Pilot of this one (decision 026 #32): the llm records differ in host
    problems = pilot_llm_problems(out, approved_config(), LLM_METHODS)[0]
    assert len(problems) == 3 and all("llm" in p for p in problems)


def test_one_unreadable_gpu_sample_is_recorded_as_null_and_the_run_goes_on(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    stored(tmp_path / "data", inc="INC-002", rg="RG-002")
    out = tmp_path / "results"
    remote(monkeypatch, tmp_path, FakeOllama(chat=answering))
    gpu(monkeypatch, GPU, None, GPU, GPU, GPU)  # start, before INC-001 (unreadable), after it, before / after INC-002
    run_method(layout, "dump-all", "pilot", out)
    first, second = power_lines(out, "pilot", "dump-all")
    assert first["before"]["gpu"] is None and first["after"]["gpu"] == GPU and first["formal"] is False
    assert first["problems"] == ["before: GPU state unreadable (nvidia-smi on gpu-server through ssh; decision 029 revision 1)"]
    assert second["formal"] is True
    audit_set(layout, "pilot", out)
    power = score_method(layout, "dump-all", "pilot", out)["usage"]["latency_power"]
    assert [e["incident_id"] for e in power["not_formal"]] == ["INC-001"] and power["gpus"] == SEEN
    table = (out / "pilot/dump-all/table.md").read_text()
    assert "Latency NOT measured with a readable RTX 5070 Ti state before and after the incident" in table
    assert "INC-001 (before: GPU state unreadable" in table


@pytest.mark.parametrize("states, stops, written", [
    ((GPU, GPU, None, None), "before INC-002", ["INC-001"]),  # after INC-001 and before INC-002: two in a row
    ((GPU, None, None), "after INC-001", ["INC-001"]),  # before and after INC-001: stopped after it, its result stands
    ((None, None), "before INC-001", []),  # at the start and before the first incident
], ids=["after-then-before", "before-then-after", "start-then-before"])
def test_two_unreadable_gpu_samples_in_a_row_stop_the_run(tmp_path, monkeypatch, states, stops, written):
    layout = stored(tmp_path / "data")
    stored(tmp_path / "data", inc="INC-002", rg="RG-002")
    out = tmp_path / "results"
    fake = FakeOllama(chat=answering)
    remote(monkeypatch, tmp_path, fake)
    reads = gpu(monkeypatch, *states)
    with pytest.raises(ValueError, match=f"GPU state {stops}.*2 GPU samples in a row could not be read.*029 revision 1"):
        run_method(layout, "dump-all", "pilot", out)
    assert len(reads) == len(states) and len(fake.chats()) == len(written)
    assert sorted(p.stem for p in (out / "pilot/dump-all").glob("INC-*.json") if "transcript" not in p.name) == written
    assert [e["incident_id"] for e in power_lines(out, "pilot", "dump-all")] == written


def test_a_gpu_that_is_not_the_rtx_5070_ti_stops_the_run(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    stored(tmp_path / "data", inc="INC-002", rg="RG-002")
    out = tmp_path / "results"
    fake = FakeOllama(chat=answering)
    remote(monkeypatch, tmp_path, fake)
    gpu(monkeypatch, OTHER)
    with pytest.raises(ValueError, match="at the start of the run.*RTX 4060.*not an RTX 5070 Ti"):
        run_method(layout, "agent", "pilot", out)
    assert not out.exists() and fake.requests == []  # before the pin check: the server was not even asked
    gpu(monkeypatch, GPU, OTHER)
    with pytest.raises(ValueError, match="before INC-001.*not an RTX 5070 Ti.*nothing of it is written"):
        run_method(layout, "agent", "pilot", out)
    assert fake.chats() == [] and power_lines(out, "pilot", "agent") == []
    gpu(monkeypatch, GPU, GPU, OTHER)
    with pytest.raises(ValueError, match="after INC-001.*not an RTX 5070 Ti.*stands"):
        run_method(layout, "agent", "pilot", out)
    assert (out / "pilot/agent/INC-001.json").exists() and not (out / "pilot/agent/INC-002.json").exists()
    (line,) = power_lines(out, "pilot", "agent")
    assert line["formal"] is False and line["problems"] == ["after: the GPU is 'NVIDIA GeForce RTX 4060', not an RTX 5070 Ti"]


def test_held_out_gpu_samples_stop_before_an_attempt_without_using_it_and_failed_attempts_are_listed(tmp_path, monkeypatch):
    from test_eval_heldout import heldout_set, ledger

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering)
    remote(monkeypatch, tmp_path, fake)
    gpu(monkeypatch, None, None)  # at the start and before INC-050's first attempt
    with pytest.raises(ValueError, match="before INC-050's attempt 1.*no attempt is used"):
        run_method(layout, "agent", "heldout", out, project_dir=project)
    assert ledger(out, "agent") == [] and fake.chats() == [] and not (out / "heldout/agent/run.lock").exists()
    fake = FakeOllama(chat=answering, down_after=6)  # INC-050's first call fails (retryable), then the server is down
    remote(monkeypatch, tmp_path, fake)
    gpu(monkeypatch, GPU, GPU, None, GPU)  # the failed attempt's after-sample cannot be read: recorded, not fatal
    with pytest.raises(ValueError, match="cannot reach"):
        run_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert [(e["attempt"], e.get("outcome")) for e in ledger(out, "dump-all")] == [(1, None), (1, "transport_error")]
    fake.down_after = None
    gpu(monkeypatch, GPU)
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []
    assert [(e["incident_id"], e["attempt"], e["formal"], e["host"]) for e in power_lines(out, "heldout", "dump-all")] == [
        ("INC-050", 1, False, "gpu-server"), ("INC-050", 2, True, "gpu-server"), ("INC-051", 1, True, "gpu-server")]
    result = score_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert result["usage"]["latency_power"]["not_formal"] == []
    (failed,) = result["usage"]["latency_power"]["failed_not_formal"]
    assert (failed["incident_id"], failed["attempt"]) == ("INC-050", 1) and "unreadable" in failed["reason"]
    table = (out / "heldout/dump-all/table.md").read_text()
    assert "Latency of failed attempts NOT measured with a readable RTX 5070 Ti state" in table
    assert "AC power" not in table


def test_a_latest_sample_from_another_host_is_listed(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    remote(monkeypatch, tmp_path, FakeOllama(chat=answering))
    run_method(layout, "agent", "pilot", out)
    path = out / "pilot/agent" / POWER_LOG
    path.write_text(json.dumps({**json.loads(path.read_text()), "host": "local"}) + "\n")
    audit_set(layout, "pilot", out)
    (entry,) = score_method(layout, "agent", "pilot", out)["usage"]["latency_power"]["not_formal"]
    assert entry["reason"] == "sampled on inference host local, not gpu-server"


def test_a_local_run_still_needs_the_heavy_lock_and_the_mac_power_and_ignores_the_wrapper(tmp_path, monkeypatch):
    # host "local" is unchanged by revision 1: the wrapper's variables do not stand in for the Mac heavy lock
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    fake = FakeOllama(chat=answering)
    monkeypatch.setattr(runner, "LLM_CONFIG", write(tmp_path, approved_config()))
    monkeypatch.setattr(ollama, "default_transport", lambda url, timeout: fake)
    wrapped(monkeypatch)
    reads = gpu(monkeypatch)

    def busy(project_dir):
        raise soak.LockNotHeld("Mac heavy lock not held; run via ./tools/with-mac-lock (MACHINE_POLICY.md)")

    monkeypatch.setattr(soak, "require_heavy_lock", busy)
    with pytest.raises(soak.LockNotHeld):
        run_method(layout, "agent", "pilot", out)
    assert not out.exists() and fake.requests == [] and reads == []


# ---------------------------------------------------------------- the probe

def test_the_probe_on_gpu_server_needs_the_wrapper_records_the_gpu_and_never_the_mac(tmp_path, monkeypatch):
    from eval.probe import run_probe

    mac_untouched(monkeypatch)
    reads = gpu(monkeypatch)
    monkeypatch.delenv("II_INFERENCE_HOST", raising=False)
    untouched = FakeOllama(chat=answering)
    with pytest.raises(RuntimeError, match="with-remote-ollama"):
        run_probe(MODEL, host="gpu-server", num_ctx=65_536, transport=untouched)
    assert untouched.requests == [] and reads == []
    wrapped(monkeypatch)
    fake = FakeOllama(chat=answering)
    report = run_probe(MODEL, host="gpu-server", num_ctx=65_536, transport=fake)
    assert report["host"] == "gpu-server" and report["gpu"] == GPU and "power" not in report
    assert report["methods"]["agent"]["valid_prediction"] is True and report["unloaded"] is True
    gpu(monkeypatch, OTHER)
    report = run_probe(MODEL, host="gpu-server", num_ctx=65_536, transport=FakeOllama(chat=answering))
    assert report["gpu"] == OTHER and any("not an RTX 5070 Ti" in w for w in report["warnings"])  # recorded, reported


def test_the_probe_host_defaults_to_the_configs(tmp_path, monkeypatch):
    from eval.probe import run_probe

    mac_untouched(monkeypatch)
    gpu(monkeypatch)
    wrapped(monkeypatch)
    remote_config = write(tmp_path, approved_config(host="gpu-server"), "remote.json")
    report = run_probe(MODEL, num_ctx=65_536, transport=FakeOllama(chat=answering), config_path=remote_config)
    assert report["host"] == "gpu-server"
    assert run_probe(MODEL, num_ctx=65_536, transport=FakeOllama(chat=answering))["host"] == "gpu-server"  # committed

    def busy(project_dir):
        raise soak.LockNotHeld("Mac heavy lock not held; run via ./tools/with-mac-lock (MACHINE_POLICY.md)")

    local_config = write(tmp_path, approved_config(), "local.json")
    untouched = FakeOllama(chat=answering)
    with pytest.raises(soak.LockNotHeld):  # host local: the heavy lock, whatever the wrapper's variables say
        run_probe(MODEL, num_ctx=65_536, transport=untouched, config_path=local_config, require_lock=busy)
    with pytest.raises(ValueError, match="host"):
        run_probe(MODEL, host="desktop", transport=untouched)
    assert untouched.requests == []


def test_the_probe_cli_takes_the_host(tmp_path, monkeypatch, capsys):
    from eval.__main__ import main

    fake = FakeOllama(chat=answering)
    monkeypatch.setattr(ollama, "default_transport", lambda url, timeout: fake)
    mac_untouched(monkeypatch)
    gpu(monkeypatch)
    monkeypatch.delenv("II_INFERENCE_HOST", raising=False)
    out = tmp_path / "probe.json"
    assert main(["local-probe", "--model", MODEL, "--num-ctx", "65536", "--out", str(out)]) == 2  # committed: gpu-server
    assert "with-remote-ollama" in capsys.readouterr().err and not out.exists()
    wrapped(monkeypatch)
    assert main(["local-probe", "--model", MODEL, "--host", "gpu-server", "--num-ctx", "65536", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["host"] == "gpu-server"
    with pytest.raises(SystemExit):
        main(["local-probe", "--model", MODEL, "--host", "desktop"])
