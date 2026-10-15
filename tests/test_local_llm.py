"""The LLM methods on a local Ollama model (decision 029): the approval guard, the pinned fields, the context fit check,
the heavy lock and the runtime record in run_config.json. The scripted transport stands in for Ollama."""

import json

import pytest

import agent.ollama as ollama
import collect.provenance as provenance
import env.soak as soak
import eval.runner as runner
from eval.runner import (LLM_CONFIG, LLM_METHODS, POWER_LOG, audit_set, llm_fit, load_llm_config, pilot_llm_problems,
                         run_method, score_method)
from ollama_fixtures import DIGEST, MODEL, VERSION, FakeOllama, answering, approved_config
from test_eval_runner import stored

COMMITTED_BUDGETS = {"dump_all_proxy_tokens": 120_000, "retrieval_queries": 8, "retrieval_k": 25,
                     "agent_max_tool_calls": 40, "agent_max_proxy_tokens": 120_000, "agent_max_turns": 30}
RECORD = {"provider": "ollama", "model": MODEL, "model_version": DIGEST, "ollama_version": VERSION, "num_ctx": 196_608,
          "num_predict": 8192, "temperature": 0, "seed": 42, "think": False, "host": "local"}


def write(tmp_path, config, name="llm.json"):
    path = tmp_path / name
    path.write_text(json.dumps(config))
    return path


FORMAL = {"source": "AC Power", "settings": {"powermode": "2"}}  # decision 025 revision 3
BATTERY = {"source": "Battery Power", "settings": {"powermode": "2"}}


def power(monkeypatch, *states):
    """The power state of each pmset read, in order, the last one repeating (the real pmset is never run)."""
    states, reads = list(states) or [FORMAL], []

    def facts(*args, **kwargs):
        reads.append(len(reads))
        return states[min(len(reads), len(states)) - 1]

    monkeypatch.setattr(provenance, "power_facts", facts)
    return reads


def local(monkeypatch, tmp_path, fake, config=None, locks=None):
    """An approved local config, the scripted Ollama behind the default transport, a held heavy lock and the formal power
    state (high power mode on AC power)."""
    monkeypatch.setattr(runner, "LLM_CONFIG", write(tmp_path, config or approved_config()))
    monkeypatch.setattr(ollama, "default_transport", lambda url, timeout: fake)
    held = [] if locks is None else locks
    monkeypatch.setattr(soak, "require_heavy_lock", lambda project_dir: held.append(project_dir) or {})
    power(monkeypatch)
    return held


def power_lines(out, split, method):
    path = out / split / method / POWER_LOG
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


APPROVED = {"provider": "ollama", "model": "qwen3.5:9b-q4_K_M",
            "model_version": "sha256:6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7",
            "temperature": 0, "price_per_mtok": {"input": 0, "output": 0}}


def test_the_committed_config_is_the_model_the_user_approved_with_unchanged_budgets():
    # user decision 2026-10-10 「照建議」 (decision 029): qwen3.5 9B, num_ctx 262,144 (its maximum), think off, Ollama 0.35.0
    # pinned, num_predict 8192; the budgets are unchanged; timeout_s stays the proposed 3600 (not one of the eight items:
    # the probe's estimate for a call near the full context is below it, review 2026-10-10)
    config = json.loads(LLM_CONFIG.read_text())
    assert config["status"] == "approved" and {k: config[k] for k in APPROVED} == APPROVED
    # decision 029 revision 1 (user decision 2026-10-11): the model runs on the RTX 5070 Ti desktop (host gpu-server,
    # tools/with-remote-ollama); nothing else of the approved settings changes
    assert config["ollama"] == {"url": "http://127.0.0.1:11434", "host": "gpu-server", "version": "0.35.0",
                                "num_ctx": 262_144, "num_predict": 8192, "seed": 42, "think": False, "timeout_s": 3600}
    assert "029 revision 1" in config["note"] and "同意" in config["note"]
    assert config["budgets"] == COMMITTED_BUDGETS and "029" in config["note"] and "照建議" in config["note"]
    assert "7200" not in config["note"]  # the note records only what the user approved
    assert load_llm_config() == config  # every pinned field and the context fit pass; no server is asked
    fit = llm_fit(config["budgets"], 262_144, 8192)
    assert fit["dump-all"]["fits"] and fit["agent"]["fits"]


def test_the_committed_config_runs_nothing_outside_its_wrapper(tmp_path, monkeypatch):
    # what `python -m eval run --method retrieval --set pilot` does outside tools/with-remote-ollama (the committed
    # inference host is gpu-server, decision 029 revision 1): past the approval, refused before the power or GPU state or
    # the server is read and before anything is written; the Mac heavy lock is not what it asks for
    import eval.inference_host as inference_host

    layout = stored(tmp_path / "data")
    out = tmp_path / "results"

    def no_server(url, timeout):
        raise AssertionError("the local server was reached")

    def no_gpu(*args, **kwargs):
        raise AssertionError("the GPU state was read")

    def busy(project_dir):
        raise soak.LockNotHeld("Mac heavy lock not held; run via ./tools/with-mac-lock (MACHINE_POLICY.md)")

    monkeypatch.setattr(ollama, "default_transport", no_server)
    monkeypatch.setattr(inference_host, "gpu_facts", no_gpu)
    monkeypatch.setattr(soak, "require_heavy_lock", busy)
    monkeypatch.delenv("II_INFERENCE_HOST", raising=False)
    monkeypatch.delenv("II_INFERENCE_TUNNEL_PID", raising=False)
    reads = power(monkeypatch)
    for method in LLM_METHODS:
        with pytest.raises(inference_host.NotWrapped, match="with-remote-ollama"):
            run_method(layout, method, "pilot", out)
    assert not out.exists() and reads == []


@pytest.mark.parametrize("change, says", [
    ({"model_version": "500a1f067a9f"}, "model_version"),
    ({"price_per_mtok": None}, "price_per_mtok"),
    ({"price_per_mtok": {"input": 0.1, "output": 0}}, "price_per_mtok"),
    ({"temperature": None}, "temperature"),
    ({"model": "gpt-oss:120b-cloud"}, "local Ollama model"),
    ({"ollama": {**approved_config()["ollama"], "url": "http://192.168.1.20:11434"}}, "loopback"),
    ({"ollama": {**approved_config()["ollama"], "version": None}}, "ollama.version"),
    ({"ollama": {**approved_config()["ollama"], "num_ctx": None}}, "num_ctx"),
    ({"ollama": {**approved_config()["ollama"], "num_predict": 300_000}}, "num_predict"),
    ({"ollama": {**approved_config()["ollama"], "seed": 0}}, "seed"),
    ({"ollama": {**approved_config()["ollama"], "think": None}}, "think"),
    ({"ollama": {k: v for k, v in approved_config()["ollama"].items() if k != "host"}}, "ollama.host"),
    ({"ollama": {**approved_config()["ollama"], "host": "192.168.1.20"}}, "ollama.host"),
])
def test_an_approved_local_config_must_pin_every_field(tmp_path, change, says):
    assert load_llm_config(write(tmp_path, approved_config()))["provider"] == "ollama"
    with pytest.raises(ValueError, match=says):
        load_llm_config(write(tmp_path, {**approved_config(), **change}))


@pytest.mark.parametrize("provider", [None, "anthropic", "openai"])
def test_every_other_provider_still_has_no_adapter(tmp_path, provider):
    with pytest.raises(ValueError, match="no model API adapter is installed yet"):
        load_llm_config(write(tmp_path, {**approved_config(), "provider": provider}))
    assert load_llm_config(write(tmp_path, {**approved_config(), "provider": provider}), need_client=False)["model"] == MODEL


def test_a_budget_that_cannot_fit_num_ctx_is_refused_and_no_budget_changes(tmp_path):
    fit = llm_fit(COMMITTED_BUDGETS, 40_960, 8192)
    assert fit["dump-all"]["fits"] is False and fit["agent"]["fits"] is False
    assert fit["retrieval"] == {"need": None, "worst_case": None, "fits": None}  # q x k records: no proxy-token budget
    assert fit["dump-all"]["need"] > 120_000 + 8192 and fit["dump-all"]["worst_case"] > fit["dump-all"]["need"]
    assert fit["agent"]["worst_case"] > fit["agent"]["need"] > 120_000
    path = write(tmp_path, approved_config(num_ctx=40_960, num_predict=8192))
    with pytest.raises(ValueError, match="dump-all: .* cannot run unchanged.*agent: "):
        load_llm_config(path)
    assert json.loads(path.read_text())["budgets"] == COMMITTED_BUDGETS  # refused, never shrunk
    fit = llm_fit(COMMITTED_BUDGETS, 196_608, 8192)
    assert fit["dump-all"]["fits"] and fit["agent"]["fits"]
    assert load_llm_config(write(tmp_path, approved_config()))["budgets"] == COMMITTED_BUDGETS


def test_a_pilot_run_on_the_local_model_pins_it_and_records_the_runtime(tmp_path, monkeypatch, capsys):
    layout = stored(tmp_path / "data")
    fake = FakeOllama(chat=answering)
    locks = local(monkeypatch, tmp_path, fake)
    out = tmp_path / "results"
    for method in LLM_METHODS:
        run_method(layout, method, "pilot", out)
        run_config = json.loads((out / "pilot" / method / "run_config.json").read_text())
        assert run_config["model"] == MODEL and run_config["llm"] == RECORD
        pred = json.loads((out / "pilot" / method / "INC-001.json").read_text())
        version = {"dump-all": "2", "retrieval": "2", "agent": "1"}[method]  # 2: decision 021's Pilot revision (2026-10-11)
        assert pred["method"] == {"name": method, "version": version} and pred["origin_candidates"] == ["payment", "checkout"]
        assert pred["usage"]["cost_usd"] == 0.0 and pred["usage"]["tokens_in"] > 0  # local: zero, not unknown
        transcript = json.loads((out / "pilot" / method / "INC-001.transcript.json").read_text())
        assert transcript["stop_reason"] == "submitted"
    assert len(locks) == 3  # the heavy lock, once per run
    assert (tmp_path / "data" / "cache").is_dir()  # the derived indexes, as the Agent tools' cache (decision 019)
    tags = [p for _, p, _ in fake.requests if p == "/api/tags"]
    assert len(tags) == 6  # the pin is checked at the start of each run and again before its one incident
    chats = fake.chats()
    assert all(c["options"] == {"temperature": 0, "seed": 42, "num_ctx": 196_608, "num_predict": 8192} for c in chats)
    assert "worst case" in capsys.readouterr().err  # reported loudly before any call (agent: 30 turns of replies)
    audit_set(layout, "pilot", out)
    result = score_method(layout, "agent", "pilot", out)
    table = (out / "pilot" / "agent" / "table.md").read_text()
    assert f"ollama {VERSION}" in table and DIGEST in table and "num_ctx 196608" in table and "local" in table
    # decision 029, user decision 2026-10-10 (item 5): a power sample before and after each incident, in a sidecar only
    for method in LLM_METHODS:
        lines = power_lines(out, "pilot", method)
        assert [(e["incident_id"], e["attempt"], e["formal"], e["host"]) for e in lines] == [("INC-001", None, True, "local")]
        assert lines[0]["before"]["power"] == lines[0]["after"]["power"] == FORMAL and lines[0]["problems"] == []
        assert "power" not in json.dumps(json.loads((out / "pilot" / method / "run_config.json").read_text()))
        assert "power" not in json.loads((out / "pilot" / method / "INC-001.json").read_text())  # decision 013 format
    assert result["usage"]["latency_power"] == {"host": "local", "condition": "AC Power, powermode 2 (decision 025 revision 3)",
                                               "incidents_timed": 1, "not_formal": []}
    assert "latency of all 1 timed incidents was measured on AC power in the high power mode" in table
    assert pilot_llm_problems(out, approved_config(), LLM_METHODS)[0] == []  # what the freeze check reads (026 #32)
    assert runner.method_version_problems(out, "pilot", LLM_METHODS) == []  # and the version check (021 Pilot revision)


def test_a_pin_mismatch_or_a_missing_lock_refuses_before_anything_is_written(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    fake = FakeOllama(digest="cd" * 32)
    local(monkeypatch, tmp_path, fake)
    with pytest.raises(ValueError, match="digest"):
        run_method(layout, "agent", "pilot", out)
    assert not (out / "pilot" / "agent").exists() and fake.chats() == []

    def busy(project_dir):
        raise soak.LockNotHeld("Mac heavy lock not held; run via ./tools/with-mac-lock (MACHINE_POLICY.md)")

    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(soak, "require_heavy_lock", busy)
    with pytest.raises(soak.LockNotHeld):
        run_method(layout, "dump-all", "pilot", out)
    assert not (out / "pilot").exists() and fake.requests == []


def test_a_model_swapped_during_a_run_stops_it(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    real = ollama.server_facts
    seen = []

    def swapped(transport, model):
        seen.append(model)
        facts = real(transport, model)
        return {**facts, "digest": "sha256:" + "cd" * 32} if len(seen) > 1 else facts

    monkeypatch.setattr(ollama, "server_facts", swapped)
    with pytest.raises(ValueError, match="digest"):
        run_method(layout, "dump-all", "pilot", tmp_path / "results")
    assert fake.chats() == [] and not (tmp_path / "results" / "pilot" / "dump-all" / "INC-001.json").exists()


def test_a_held_out_run_records_the_same_runtime_and_resumes_only_with_it(tmp_path, monkeypatch):
    from test_eval_heldout import heldout_set

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering)
    locks = local(monkeypatch, tmp_path, fake)
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []
    run_config = json.loads((out / "heldout" / "dump-all" / "run_config.json").read_text())
    assert run_config["llm"] == RECORD and locks == [project]
    monkeypatch.setattr(runner, "LLM_CONFIG", write(tmp_path, approved_config(num_predict=4096), "other.json"))
    with pytest.raises(ValueError, match="run_config"):  # another runtime is another run (decision 023 §5, 024)
        run_method(layout, "dump-all", "heldout", out, project_dir=project)


def test_an_llm_method_runs_only_through_run_method():
    from eval.runner import METHODS

    for method in LLM_METHODS:  # the heavy lock and the pin check come with the run, never with a bare call
        with pytest.raises(ValueError, match="run_method"):
            METHODS[method](None, "INC-001")


def test_a_run_uses_the_configuration_it_read_at_its_start(tmp_path, monkeypatch):
    # a config file changed during a run (e.g. a merge in the checkout) changes nothing in that run (decision 024 / 029)
    layout = stored(tmp_path / "data")
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    real, calls = runner.llm_fit, []

    def rewriting(*args):
        calls.append(args)
        if len(calls) == 2:  # the worst-case report at the end of start_llm: the start is done, no incident has run
            runner.LLM_CONFIG.write_text(json.dumps(approved_config(think=True, num_ctx=139_264)))
        return real(*args)

    monkeypatch.setattr(runner, "llm_fit", rewriting)
    run_method(layout, "agent", "pilot", tmp_path / "results")
    run_config = json.loads((tmp_path / "results" / "pilot" / "agent" / "run_config.json").read_text())
    assert run_config["llm"] == RECORD and len(calls) == 2 and fake.chats()
    assert all(c["options"]["num_ctx"] == 196_608 and c["think"] is False for c in fake.chats())


def test_a_server_down_before_a_held_out_attempt_stops_the_run_without_using_the_attempt(tmp_path, monkeypatch):
    # decision 029 / 026 #17: the pin check runs before the attempt starts; an unreachable server or another model stops
    # the run with no start event, so no held-out slot is closed by an infrastructure fault
    from test_eval_heldout import heldout_set, ledger

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering, down_after=3)  # up for the check at the start of the run, down before INC-050
    local(monkeypatch, tmp_path, fake)
    with pytest.raises(ValueError, match="cannot reach the local Ollama server.*no attempt"):
        run_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert ledger(out, "dump-all") == [] and not (out / "heldout" / "dump-all" / "run.lock").exists()
    fake.down_after = None  # the server is back
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []
    assert [(e["incident_id"], e["attempt"], e["event"], e.get("outcome")) for e in ledger(out, "dump-all")] == [
        ("INC-050", 1, "start", None), ("INC-050", 1, "end", "ok"), ("INC-051", 1, "start", None), ("INC-051", 1, "end", "ok")]


def test_a_server_that_dies_during_a_held_out_call_leaves_the_retry_for_when_it_is_back(tmp_path, monkeypatch):
    from test_eval_heldout import heldout_set, ledger

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering, down_after=6)  # start check (3) and INC-050's check (3) answer; its call fails
    local(monkeypatch, tmp_path, fake)
    with pytest.raises(ValueError, match="cannot reach"):
        run_method(layout, "dump-all", "heldout", out, project_dir=project)
    events = [(e["incident_id"], e["attempt"], e["event"], e.get("outcome")) for e in ledger(out, "dump-all")]
    assert events == [("INC-050", 1, "start", None), ("INC-050", 1, "end", "transport_error")]  # attempt 2 not started
    fake.down_after = None
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []
    assert [(e["attempt"], e.get("outcome")) for e in ledger(out, "dump-all") if e["incident_id"] == "INC-050"] == [
        (1, None), (1, "transport_error"), (2, None), (2, "ok")]


def test_a_model_swapped_between_held_out_incidents_stops_the_run_and_closes_no_incident(tmp_path, monkeypatch):
    from test_eval_heldout import heldout_set, ledger

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    real, seen = ollama.server_facts, []

    def swapped(transport, model):
        seen.append(model)
        facts = real(transport, model)
        return {**facts, "digest": "sha256:" + "cd" * 32} if len(seen) == 3 else facts  # before INC-051

    monkeypatch.setattr(ollama, "server_facts", swapped)
    with pytest.raises(ValueError, match="digest"):
        run_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert [e["incident_id"] for e in ledger(out, "dump-all")] == ["INC-050", "INC-050"]  # INC-051: no attempt used
    monkeypatch.setattr(ollama, "server_facts", real)
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []


def test_the_local_model_is_unloaded_when_a_run_ends(tmp_path, monkeypatch, capsys):
    # the model and its num_ctx KV cache leave memory before the run (and with it the heavy lock) ends (decision 029)
    from test_eval_heldout import heldout_set

    layout = stored(tmp_path / "data")
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    run_method(layout, "dump-all", "pilot", tmp_path / "results")
    assert len(fake.unloads()) == 1 and fake.loaded is None
    failing = FakeOllama(chat=lambda body, prompt: (400, {"error": "the input length exceeds the context length"}))
    local(monkeypatch, tmp_path, failing)
    with pytest.raises(ollama.CallError):
        run_method(layout, "agent", "pilot", tmp_path / "results")
    assert len(failing.unloads()) == 1  # also when the run stops
    sticky = FakeOllama(chat=answering, sticky=True)
    local(monkeypatch, tmp_path, sticky)
    monkeypatch.setattr(ollama, "UNLOAD_WAIT_S", 0)
    run_method(layout, "retrieval", "pilot", tmp_path / "results")
    assert "still loaded" in capsys.readouterr().err  # reported loudly, the run's results stand
    project, layout, out = heldout_set(tmp_path / "h", monkeypatch)
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []
    assert len(fake.unloads()) == 1 and fake.loaded is None


# ---------------------------------------------------------------- the power state (decision 029, user decision 2026-10-10)

def test_a_run_outside_the_formal_power_state_never_starts(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    for state in (BATTERY, {"source": "AC Power", "settings": {"powermode": "0"}}, None):
        power(monkeypatch, state)
        with pytest.raises(ValueError, match="power.*high power mode on AC power.*decision 029"):
            run_method(layout, "agent", "pilot", out)
    assert not out.exists() and fake.requests == []  # checked before the pin check: the server was not even asked


def test_power_before_a_pilot_incident_stops_the_run_before_its_call(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    stored(tmp_path / "data", inc="INC-002", rg="RG-002")
    out = tmp_path / "results"
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    reads = power(monkeypatch, FORMAL, FORMAL, FORMAL, BATTERY)  # start, before INC-001, after INC-001, before INC-002
    with pytest.raises(ValueError, match="before INC-002.*nothing of it is written"):
        run_method(layout, "dump-all", "pilot", out)
    assert len(reads) == 4 and len(fake.chats()) == 1  # INC-002 was never sent
    assert (out / "pilot/dump-all/INC-001.json").exists() and not (out / "pilot/dump-all/INC-002.json").exists()
    assert [e["incident_id"] for e in power_lines(out, "pilot", "dump-all")] == ["INC-001"]


def test_power_after_a_pilot_incident_stops_the_run_keeps_the_result_and_the_score_lists_it(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    power(monkeypatch, FORMAL, FORMAL, BATTERY)
    with pytest.raises(ValueError, match="after INC-001.*stands.*latency.*non-formal power"):
        run_method(layout, "retrieval", "pilot", out)
    assert (out / "pilot/retrieval/INC-001.json").exists()  # reported, never discarded
    (line,) = power_lines(out, "pilot", "retrieval")
    assert line["formal"] is False and line["after"]["power"] == BATTERY and "Battery Power" in line["problems"][0]
    audit_set(layout, "pilot", out)
    result = score_method(layout, "retrieval", "pilot", out)
    assert result["aggregate"]["n_incidents"] == 1  # still scored, latency still in the usage numbers
    assert result["usage"]["fields"]["latency_s"]["n"] == 1
    assert [e["incident_id"] for e in result["usage"]["latency_power"]["not_formal"]] == ["INC-001"]
    table = (out / "pilot/retrieval/table.md").read_text()
    assert "Latency NOT measured under the formal power condition" in table and "INC-001 (power source is" in table


def test_a_scored_llm_incident_without_a_power_sample_is_listed(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    local(monkeypatch, tmp_path, FakeOllama(chat=answering))
    run_method(layout, "agent", "pilot", out)
    (out / "pilot/agent" / POWER_LOG).unlink()
    audit_set(layout, "pilot", out)
    not_formal = score_method(layout, "agent", "pilot", out)["usage"]["latency_power"]["not_formal"]
    assert not_formal == [{"incident_id": "INC-001", "attempt": None, "reason": f"no power sample in {POWER_LOG}"}]


def test_the_statistical_baseline_has_no_power_rule(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    reads = power(monkeypatch)
    run_method(layout, "stat-anomaly", "pilot", out)
    audit_set(layout, "pilot", out)
    assert score_method(layout, "stat-anomaly", "pilot", out)["usage"]["latency_power"] is None
    assert reads == [] and not (out / "pilot/stat-anomaly" / POWER_LOG).exists()


def test_power_before_a_held_out_attempt_stops_the_run_without_using_the_attempt(tmp_path, monkeypatch):
    from test_eval_heldout import heldout_set, ledger

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    power(monkeypatch, FORMAL, BATTERY)  # the start of the run, then before INC-050's first attempt
    with pytest.raises(ValueError, match="before INC-050.*no attempt is used"):
        run_method(layout, "agent", "heldout", out, project_dir=project)
    assert ledger(out, "agent") == [] and power_lines(out, "heldout", "agent") == [] and fake.chats() == []
    assert not (out / "heldout/agent/run.lock").exists()
    power(monkeypatch, FORMAL)  # the power state is back
    assert run_method(layout, "agent", "heldout", out, project_dir=project) == []
    assert [(e["incident_id"], e["attempt"], e["formal"]) for e in power_lines(out, "heldout", "agent")] == [
        ("INC-050", 1, True), ("INC-051", 1, True)]


def test_power_after_a_held_out_incident_stops_the_run_and_the_incident_is_never_run_again(tmp_path, monkeypatch):
    from test_eval_heldout import heldout_set, ledger

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering)
    local(monkeypatch, tmp_path, fake)
    power(monkeypatch, FORMAL, FORMAL, BATTERY)  # start, before INC-050, after INC-050
    with pytest.raises(ValueError, match="after INC-050.*never run again"):
        run_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert [(e["incident_id"], e["event"], e.get("outcome")) for e in ledger(out, "dump-all")] == [
        ("INC-050", "start", None), ("INC-050", "end", "ok")]
    assert (out / "heldout/dump-all/INC-050.json").exists() and not (out / "heldout/dump-all/run.lock").exists()
    sent = len(fake.chats())
    power(monkeypatch, FORMAL)
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []
    assert len(fake.chats()) == sent + 1  # only INC-051: a held-out incident runs once (decision 023 §5)
    assert [(e["incident_id"], e["formal"]) for e in power_lines(out, "heldout", "dump-all")] == [
        ("INC-050", False), ("INC-051", True)]
    result = score_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert [(e["incident_id"], e["attempt"]) for e in result["usage"]["latency_power"]["not_formal"]] == [("INC-050", 1)]
    assert "INC-050 (power source is" in (out / "heldout/dump-all/table.md").read_text()


def test_power_after_a_retryable_held_out_attempt_stops_the_run_and_the_retry_waits(tmp_path, monkeypatch):
    from test_eval_heldout import heldout_set, ledger

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering, down_after=6)  # the start and INC-050's pin checks answer; its call fails
    local(monkeypatch, tmp_path, fake)
    power(monkeypatch, FORMAL, FORMAL, BATTERY)
    with pytest.raises(ValueError, match="after INC-050"):
        run_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert [(e["attempt"], e.get("outcome")) for e in ledger(out, "dump-all")] == [(1, None), (1, "transport_error")]
    fake.down_after = None
    power(monkeypatch, FORMAL)
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []
    assert [(e["incident_id"], e["attempt"], e["formal"]) for e in power_lines(out, "heldout", "dump-all")] == [
        ("INC-050", 1, False), ("INC-050", 2, True), ("INC-051", 1, True)]
    result = score_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert result["usage"]["latency_power"]["not_formal"] == []  # the prediction's own attempt was formal
    # review 2026-10-10: the failed attempt's latency is in "Failed attempts" and was measured on battery: listed too
    (failed,) = result["usage"]["latency_power"]["failed_not_formal"]
    assert (failed["incident_id"], failed["attempt"]) == ("INC-050", 1) and "Battery Power" in failed["reason"]
    assert result["usage"]["failed_attempts"]["latency_s"] is not None  # reported, never removed
    table = (out / "heldout/dump-all/table.md").read_text()
    assert "Failed attempts: 1" in table
    assert "Latency of failed attempts NOT measured under the formal power condition" in table
    assert "INC-050 attempt 1 (power source is" in table


def test_failed_held_out_attempts_under_the_formal_power_state_are_not_listed(tmp_path, monkeypatch):
    from test_eval_heldout import heldout_set

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = FakeOllama(chat=answering, down_after=6)
    local(monkeypatch, tmp_path, fake)
    with pytest.raises(ValueError, match="cannot reach"):
        run_method(layout, "dump-all", "heldout", out, project_dir=project)
    fake.down_after = None
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == []
    result = score_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert result["usage"]["failed_attempts"]["count"] == 1
    assert result["usage"]["latency_power"]["failed_not_formal"] == []
    assert "Latency of failed attempts NOT" not in (out / "heldout/dump-all/table.md").read_text()


def overflowing(monkeypatch):
    return FakeOllama(chat=lambda body, prompt: (400, {"error": "the input length exceeds the context length"}))


def invalid(monkeypatch):
    real = runner.METHODS["dump-all"]

    def broken(snapshot, inc, **kw):
        pred, transcript = real(snapshot, inc, **kw)
        return {"prediction_version": 1, "incident_id": inc}, transcript  # not a decision-013 prediction

    monkeypatch.setitem(runner.METHODS, "dump-all", broken)
    return FakeOllama(chat=answering)


@pytest.mark.parametrize("setup, error, says, outcome", [
    (overflowing, ollama.CallError, "context_overflow", "error"),
    (invalid, ValueError, "invalid prediction", "invalid_prediction"),
], ids=["non-retryable-call-error", "invalid-prediction"])
def test_power_after_a_held_out_attempt_that_ends_in_an_error_is_recorded_and_the_error_stands(
        tmp_path, monkeypatch, setup, error, says, outcome):
    # decision 029 「電力條件的實作」: an attempt that ends in a non-retryable error or an invalid prediction still gets its
    # power.jsonl line; the original error stops the run (not the power message) and closes the incident (023 §5)
    from test_eval_heldout import heldout_set, ledger

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    fake = setup(monkeypatch)
    local(monkeypatch, tmp_path, fake)
    power(monkeypatch, FORMAL, FORMAL, BATTERY)  # start, before INC-050's attempt, after it
    with pytest.raises(error, match=says) as e:
        run_method(layout, "dump-all", "heldout", out, project_dir=project)
    assert "power state" not in str(e.value)
    assert [(e["incident_id"], e["attempt"], e["event"], e.get("outcome")) for e in ledger(out, "dump-all")] == [
        ("INC-050", 1, "start", None), ("INC-050", 1, "end", outcome)]
    (line,) = power_lines(out, "heldout", "dump-all")
    assert (line["incident_id"], line["attempt"], line["formal"]) == ("INC-050", 1, False)
    assert line["after"]["power"] == BATTERY and "Battery Power" in line["problems"][0]
    monkeypatch.setitem(runner.METHODS, "dump-all", runner._llm("dump-all"))
    local(monkeypatch, tmp_path, FakeOllama(chat=answering))  # the power state is back, the model answers
    assert run_method(layout, "dump-all", "heldout", out, project_dir=project) == ["INC-050"]  # closed: never again
    assert [(e["incident_id"], e["attempt"]) for e in power_lines(out, "heldout", "dump-all")] == [
        ("INC-050", 1), ("INC-051", 1)]


def test_a_pilot_run_stopped_midway_leaves_earlier_predictions_that_the_freeze_check_refuses(tmp_path, monkeypatch):
    # review 2026-10-10 (decision 026 #32): a run with the settings being frozen that stops midway leaves the earlier
    # run's predictions of the incidents it did not reach under its own run_config.json; each power.jsonl line names the
    # run_config.json its prediction was written under, so the freeze check finds them even if they were scored
    from env.lock import sha256_path

    layout = stored(tmp_path / "data")
    stored(tmp_path / "data", inc="INC-002", rg="RG-002")
    out = tmp_path / "results"
    old, new = approved_config(), approved_config(num_ctx=262_144)
    local(monkeypatch, tmp_path, FakeOllama(chat=answering), config=old)
    run_method(layout, "agent", "pilot", out)  # a complete run with other settings
    earlier = (out / "pilot/agent/INC-002.json").read_text()
    local(monkeypatch, tmp_path, FakeOllama(chat=answering), config=new)
    power(monkeypatch, FORMAL, FORMAL, FORMAL, BATTERY)  # start, before INC-001, after INC-001, before INC-002
    with pytest.raises(ValueError, match="before INC-002"):
        run_method(layout, "agent", "pilot", out)
    assert (out / "pilot/agent/INC-002.json").read_text() == earlier  # produced with the other settings
    audit_set(layout, "pilot", out)
    score_method(layout, "agent", "pilot", out)  # scored against NEXT 8.2 (a stopped run is not scored)
    problems, shas = pilot_llm_problems(out, new, ["agent"])
    assert len(problems) == 1 and "INC-002" in problems[0] and "INC-001" not in problems[0] and shas == {}
    assert "026 #32" in problems[0] and "to the end" in problems[0]
    power(monkeypatch, FORMAL)
    run_method(layout, "agent", "pilot", out)  # run again to the end (exit 0), then score
    score_method(layout, "agent", "pilot", out)
    assert pilot_llm_problems(out, new, ["agent"])[0] == []
    sha = sha256_path(out / "pilot/agent/run_config.json")
    assert [(e["incident_id"], e["run_config_sha256"] == sha) for e in power_lines(out, "pilot", "agent")] == [
        ("INC-001", False), ("INC-002", False), ("INC-001", True), ("INC-001", True), ("INC-002", True)]


def test_a_rerun_after_021s_pilot_revision_that_stopped_midway_is_found_only_by_the_method_version(tmp_path, monkeypatch):
    # review 2026-10-11 (decision 021's Pilot revision): the rerun of dump-all / retrieval uses the same model, budgets and
    # runtime, so its run_config.json is byte-for-byte the original run's and the freeze check (026 #32: run_config,
    # power.jsonl's run_config_sha256) cannot tell the two runs apart; only the predictions' method.version can
    from eval.runner import method_version_problems

    layout = stored(tmp_path / "data")
    stored(tmp_path / "data", inc="INC-002", rg="RG-002")
    out = tmp_path / "results"
    local(monkeypatch, tmp_path, FakeOllama(chat=answering))
    monkeypatch.setitem(runner.LLM_METHOD_VERSIONS, "dump-all", "1")
    run_method(layout, "dump-all", "pilot", out)  # the original Pilot run, before the revision
    original = (out / "pilot/dump-all/run_config.json").read_text()
    earlier = (out / "pilot/dump-all/INC-002.json").read_text()
    monkeypatch.setitem(runner.LLM_METHOD_VERSIONS, "dump-all", "2")
    power(monkeypatch, FORMAL, FORMAL, FORMAL, BATTERY)  # start, before INC-001, after INC-001, before INC-002
    with pytest.raises(ValueError, match="before INC-002"):
        run_method(layout, "dump-all", "pilot", out)  # the rerun stops midway
    assert (out / "pilot/dump-all/run_config.json").read_text() == original
    assert (out / "pilot/dump-all/INC-002.json").read_text() == earlier
    audit_set(layout, "pilot", out)
    score_method(layout, "dump-all", "pilot", out)  # scored against NEXT (a stopped run is not scored)
    assert pilot_llm_problems(out, approved_config(), ["dump-all"])[0] == []  # the freeze check does not see it
    problems = method_version_problems(out, "pilot", ["dump-all", "stat-anomaly"])
    assert len(problems) == 1 and "dump-all" in problems[0] and "INC-002" in problems[0] and "INC-001" not in problems[0]
    assert "'1'" in problems[0] and "'2'" in problems[0] and "021" in problems[0] and "to the end" in problems[0]
    power(monkeypatch, FORMAL)
    run_method(layout, "dump-all", "pilot", out)  # run again to the end (exit 0)
    assert method_version_problems(out, "pilot", ["dump-all"]) == []
    (out / "pilot/dump-all/INC-002.json").write_text("{")
    assert "INC-002" in method_version_problems(out, "pilot", ["dump-all"])[0]  # unreadable: reported, never skipped
    assert "no predictions" in method_version_problems(out, "pilot", ["retrieval"])[0]  # never run: reported
