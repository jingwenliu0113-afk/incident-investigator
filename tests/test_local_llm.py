"""The LLM methods on a local Ollama model (decision 029): the approval guard, the pinned fields, the context fit check,
the heavy lock and the runtime record in run_config.json. The scripted transport stands in for Ollama."""

import json

import pytest

import agent.ollama as ollama
import env.soak as soak
import eval.runner as runner
from eval.runner import LLM_CONFIG, LLM_METHODS, audit_set, llm_fit, load_llm_config, run_method, score_method
from ollama_fixtures import DIGEST, MODEL, VERSION, FakeOllama, answering, approved_config
from test_eval_runner import stored

COMMITTED_BUDGETS = {"dump_all_proxy_tokens": 120_000, "retrieval_queries": 8, "retrieval_k": 25,
                     "agent_max_tool_calls": 40, "agent_max_proxy_tokens": 120_000, "agent_max_turns": 30}
RECORD = {"provider": "ollama", "model": MODEL, "model_version": DIGEST, "ollama_version": VERSION, "num_ctx": 196_608,
          "num_predict": 8192, "temperature": 0, "seed": 42, "think": False}


def write(tmp_path, config, name="llm.json"):
    path = tmp_path / name
    path.write_text(json.dumps(config))
    return path


def local(monkeypatch, tmp_path, fake, config=None, locks=None):
    """An approved local config, the scripted Ollama behind the default transport and a held heavy lock."""
    monkeypatch.setattr(runner, "LLM_CONFIG", write(tmp_path, config or approved_config()))
    monkeypatch.setattr(ollama, "default_transport", lambda url, timeout: fake)
    held = [] if locks is None else locks
    monkeypatch.setattr(soak, "require_heavy_lock", lambda project_dir: held.append(project_dir) or {})
    return held


def test_the_committed_config_stays_proposed_with_the_new_fields_and_unchanged_budgets():
    config = json.loads(LLM_CONFIG.read_text())
    assert config["status"] == "proposed" and config["model"] is None and config["provider"] is None
    assert config["model_version"] is None and config["price_per_mtok"] is None and config["temperature"] == 0
    assert config["ollama"] == {"url": "http://127.0.0.1:11434", "version": None, "num_ctx": None, "num_predict": 8192,
                                "seed": 42, "think": None, "timeout_s": 3600}
    assert config["budgets"] == COMMITTED_BUDGETS and "029" in config["note"]
    with pytest.raises(ValueError, match="not approved"):
        load_llm_config()


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
        assert pred["method"] == {"name": method, "version": "1"} and pred["origin_candidates"] == ["payment", "checkout"]
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
    score_method(layout, "agent", "pilot", out)
    table = (out / "pilot" / "agent" / "table.md").read_text()
    assert f"ollama {VERSION}" in table and DIGEST in table and "num_ctx 196608" in table and "local" in table


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
