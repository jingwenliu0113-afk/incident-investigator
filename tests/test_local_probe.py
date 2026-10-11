"""`python -m eval local-probe` (decision 029): the three LLM methods with one local model on the SYNTHETIC sample only,
the context guard self-test, a repeat check and prefill / decode speed on generated filler. Never results; writes
nothing under data/. The scripted transport stands in for Ollama. These tests run it on this Mac (--host local: the
heavy lock and pmset); the inference host gpu-server is tested in test_remote_inference.py (decision 029 revision 1)."""

import json
import shutil

import pytest

import agent.ollama as ollama
import env.soak as soak
from collect.sample import SAMPLE_DIR
from env.lock import PROJECT_DIR
from eval.runner import LLM_METHODS
from ollama_fixtures import DIGEST, MODEL, VERSION, FakeOllama, answering, call, reply


POWER = {"source": "AC Power", "settings": {"powermode": "2", "lowpowermode": "0"}}


@pytest.fixture(autouse=True)
def power(monkeypatch):
    """The power state is read only (pmset, decision 025); a fixed one here."""
    import collect.provenance as provenance

    monkeypatch.setattr(provenance, "power_facts", lambda *a, **k: POWER)


def tree(root):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*"))


def no_lock(project_dir):
    return {}


def test_the_probe_runs_the_three_methods_on_the_synthetic_sample_and_says_it_is_not_a_result():
    from eval.probe import BANNER, run_probe

    fake = FakeOllama(chat=answering)
    before = tree(PROJECT_DIR / "data")
    report = run_probe(MODEL, host="local", num_ctx=65_536, context_sizes=(1000, 4000, 100_000), transport=fake,
                       require_lock=no_lock)
    assert tree(PROJECT_DIR / "data") == before  # nothing written under data/
    assert report["banner"] == BANNER and "NOT results" in BANNER and report["synthetic"] is True
    assert report["sample"]["path"] == SAMPLE_DIR.as_posix()
    assert report["ollama"] == {"version": VERSION, "model": MODEL, "digest": DIGEST, "context_length": 262_144,
                                "capabilities": ["completion", "tools", "thinking"],
                                "details": {"family": "qwen3", "parameter_size": "1B", "quantization_level": "Q4_K_M"},
                                "parameters": "temperature 0.6\ntop_k 20"}
    assert report["settings"] == {"num_ctx": 65_536, "num_predict": 8192, "temperature": 0, "seed": 42, "think": False,
                                  "budgets": json.loads((PROJECT_DIR / "eval/llm_methods.json").read_text())["budgets"]}
    for method in LLM_METHODS:
        m = report["methods"][method]
        assert m["error"] is None and m["valid_prediction"] is True and m["stop_reason"] == "submitted", method
        assert m["tool_calls_parsed"] >= 1 and m["text_tool_calls"] == 0 and m["corrections"] == 0 and not m["abstained"]
        assert m["tokens_in"] > 0 and m["tokens_out"] > 0 and m["latency_s"] >= 0 and m["cost_usd"] == 0.0
        assert 1.0 < m["proxy_to_real"]["first_call"] < 3.0 and len(m["per_call"]) == m["calls"]
        assert m["prediction"]["origin_candidates"] == ["payment", "checkout"] and m["unparsed_tool_calls"] == 0
    assert report["methods"]["agent"]["calls"] == 2 and report["methods"]["retrieval"]["calls"] == 2
    guard = report["guard_selftest"]
    assert guard["passed"] is True and [c["case"] for c in guard["checks"]] == ["one long message", "several messages"]
    for check in guard["checks"]:  # refused by the server itself (truncate: false), not only caught by the adapter
        assert check["reason"] == "context_overflow" and check["guard"] == "server" and check["num_ctx"] == 2048
        assert check["prompt_proxy_tokens"] > 2048
    repeat = report["repeat_check"]
    assert repeat["identical"] is True and repeat["prompt_eval_counts"][0] == repeat["prompt_eval_counts"][1] > 1000
    assert report["power"] == POWER and report["unloaded"] is True and fake.loaded is None
    assert report["host"] == "local" and "gpu" not in report  # this Mac (decision 029 revision 1: --host local)
    assert not any("GUARD" in w for w in report["warnings"])
    measured, skipped = report["speed"][:2], report["speed"][2]
    assert [s["size_proxy_tokens"] for s in measured] == [1000, 4000]
    assert all(s["prefill_tok_s"] > 0 and s["decode_tok_s"] == 40.0 and s["prompt_eval_count"] > 0 for s in measured)
    assert skipped == {"size_proxy_tokens": 100_000, "skipped": "larger than num_ctx 65536"}
    assert report["fit"]["dump-all"]["fits"] is False and any("dump-all" in w for w in report["warnings"])
    assert report["config_if_approved"] == {
        "provider": "ollama", "model": MODEL, "model_version": DIGEST, "price_per_mtok": {"input": 0, "output": 0},
        "ollama": {"version": VERSION, "num_ctx": 65_536, "think": False}}
    for body in fake.chats():  # the filler and the repeat prompt carry no incident data
        if not body.get("tools"):
            assert "payment" not in json.dumps(body)


def test_a_method_that_fails_or_writes_tool_calls_as_text_is_reported_not_raised():
    from eval.probe import run_probe

    def texty(body, prompt):
        names = [t["function"]["name"] for t in body.get("tools") or []]
        if names == ["submit_diagnosis"]:
            return reply(content='<tool_call>{"name": "submit_diagnosis", "arguments": {}}</tool_call>')
        if "propose_queries" in names:
            return 500, {"error": "model runner has unexpectedly stopped"}
        return answering(body, prompt)

    report = run_probe(MODEL, host="local", num_ctx=65_536, transport=FakeOllama(chat=texty), require_lock=no_lock)
    dump = report["methods"]["dump-all"]
    assert dump["error"] is None and dump["valid_prediction"] is False and dump["abstained"] is True
    assert dump["text_tool_calls"] == 3 and dump["tool_calls_parsed"] == 0 and dump["corrections"] == 2
    assert dump["stop_reason"] == "no_submission"
    failed = report["methods"]["retrieval"]
    assert failed["error"]["reason"] == "api_error" and failed["valid_prediction"] is False
    assert report["methods"]["agent"]["valid_prediction"] is True and report["speed"] == []


def test_a_server_that_does_not_refuse_an_overlong_prompt_fails_the_guard(tmp_path, monkeypatch, capsys):
    from eval.__main__ import main
    from eval.probe import run_probe

    report = run_probe(MODEL, host="local", num_ctx=65_536, transport=FakeOllama(chat=answering, truncating=True),
                       require_lock=no_lock)
    guard = report["guard_selftest"]
    assert guard["passed"] is False and all(c["guard"] == "sent_proxy" for c in guard["checks"])
    assert any(w.startswith("GUARD FAILED") for w in report["warnings"])

    class DropsOldMessages(FakeOllama):  # refuses one long message but drops old ones from a conversation
        def __call__(self, method, path, body=None):
            self.truncating = path == "/api/chat" and sum(m["role"] != "system" for m in body.get("messages") or []) > 1
            return super().__call__(method, path, body)

    checks = run_probe(MODEL, host="local", num_ctx=65_536, transport=DropsOldMessages(chat=answering),
                       require_lock=no_lock)["guard_selftest"]["checks"]
    assert [c["guard"] for c in checks] == ["server", "sent_proxy"]
    monkeypatch.setattr(ollama, "default_transport", lambda url, timeout: FakeOllama(chat=answering, truncating=True))
    monkeypatch.setattr(soak, "require_heavy_lock", no_lock)
    out = tmp_path / "probe.json"
    # GUARD FAILED: needs a person
    assert main(["local-probe", "--model", MODEL, "--host", "local", "--num-ctx", "65536", "--out", str(out)]) == 3
    assert json.loads(out.read_text())["guard_selftest"]["passed"] is False  # the report is still written
    assert "GUARD FAILED" in capsys.readouterr().err


def test_unparsed_tool_calls_and_counts_of_cached_prompts_are_reported(tmp_path):
    from eval.probe import run_probe

    repeats = []

    def chat(body, prompt):
        names = [t["function"]["name"] for t in body.get("tools") or []]
        if names == ["submit_diagnosis"]:
            return reply(call("submit_diagnosis", "{not json"))
        if not names and "Name one animal" in body["messages"][-1]["content"]:
            repeats.append(prompt)
            if len(repeats) == 2:  # a server that counts only the uncached part of a repeated prompt
                return 200, {"message": reply(content="Amber cedar."), "done": True, "done_reason": "stop",
                             "prompt_eval_count": 3, "eval_count": 4}
        return answering(body, prompt)

    report = run_probe(MODEL, host="local", num_ctx=65_536, transport=FakeOllama(chat=chat), require_lock=no_lock)
    dump = report["methods"]["dump-all"]
    assert dump["unparsed_tool_calls"] == 3 and dump["corrections"] == 2 and dump["valid_prediction"] is False
    assert dump["stop_reason"] == "invalid_submission"
    repeat = report["repeat_check"]
    assert repeat["identical"] is None and repeat["error"] == "context_unverified" and repeat["guard"] == "count_floor"
    assert any("uncached" in w for w in report["warnings"])


def test_the_probe_refuses_anything_but_the_synthetic_sample(tmp_path):
    from eval.probe import run_probe

    fake = FakeOllama(chat=answering)
    copy = tmp_path / "copy"
    shutil.copytree(PROJECT_DIR / SAMPLE_DIR, copy)
    manifest = json.loads((copy / "sample.json").read_text())
    (copy / "sample.json").write_text(json.dumps({**manifest, "synthetic": False}))
    with pytest.raises(ValueError, match="synthetic"):
        run_probe(MODEL, host="local", transport=fake, require_lock=no_lock, sample_root=copy)
    (copy / "sample.json").write_text(json.dumps(manifest))
    label = next(copy.rglob("label.json"))
    label.write_text(label.read_text() + " ")
    with pytest.raises(ValueError, match="sha256"):
        run_probe(MODEL, host="local", transport=fake, require_lock=no_lock, sample_root=copy)
    assert fake.requests == []


@pytest.mark.parametrize("fake, kw, says", [
    (FakeOllama(model="gpt-oss:120b-cloud"), {"model": "gpt-oss:120b-cloud"}, "remote"),
    (FakeOllama(extra={"remote_host": "https://ollama.com"}), {}, "remote"),
    (FakeOllama(), {"model": "missing:1b"}, "not installed"),
    (FakeOllama(context_length=40_960), {"num_ctx": 65_536}, "context length"),
])
def test_the_probe_refuses_a_remote_missing_or_too_small_model_before_any_call(fake, kw, says):
    from eval.probe import run_probe

    with pytest.raises(ValueError, match=says):
        run_probe(kw.pop("model", MODEL), host="local", transport=fake, require_lock=no_lock, **kw)
    assert fake.chats() == []


def test_the_default_context_is_the_models_capped_and_the_lock_is_required():
    from eval.probe import DEFAULT_NUM_CTX_CAP, run_probe

    small = FakeOllama(chat=answering, context_length=40_960)
    assert run_probe(MODEL, host="local", transport=small, require_lock=no_lock)["settings"]["num_ctx"] == 40_960
    large = FakeOllama(chat=answering)
    assert run_probe(MODEL, host="local", transport=large, require_lock=no_lock)["settings"]["num_ctx"] == DEFAULT_NUM_CTX_CAP

    def busy(project_dir):
        raise soak.LockNotHeld("Mac heavy lock not held; run via ./tools/with-mac-lock (MACHINE_POLICY.md)")

    untouched = FakeOllama(chat=answering)
    with pytest.raises(soak.LockNotHeld):
        run_probe(MODEL, host="local", transport=untouched, require_lock=busy)
    assert untouched.requests == []


def test_the_cli_writes_json_and_never_under_data(tmp_path, monkeypatch, capsys):
    from eval.__main__ import main

    fake = FakeOllama(chat=answering)
    monkeypatch.setattr(ollama, "default_transport", lambda url, timeout: fake)
    monkeypatch.setattr(soak, "require_heavy_lock", no_lock)
    out = tmp_path / "probe.json"
    assert main(["local-probe", "--model", MODEL, "--host", "local", "--num-ctx", "65536", "--think", "--context-sizes",
                 "1000,2000",
                 "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["settings"]["think"] is True and [s["size_proxy_tokens"] for s in report["speed"]] == [1000, 2000]
    assert "NOT results" in capsys.readouterr().err
    assert main(["local-probe", "--model", MODEL, "--host", "local", "--num-ctx", "65536"]) == 0
    assert json.loads(capsys.readouterr().out)["methods"]["agent"]["valid_prediction"] is True
    for bad in (PROJECT_DIR / "data" / "probe.json", PROJECT_DIR / "data" / "external" / "x" / "probe.json"):
        assert main(["local-probe", "--model", MODEL, "--host", "local", "--out", str(bad)]) == 2
        assert not bad.exists()
    assert "under data/" in capsys.readouterr().err
    assert main(["local-probe", "--model", MODEL, "--host", "local", "--context-sizes", "8k"]) == 2
    with pytest.raises(SystemExit):
        main(["local-probe"])  # --model is required


def test_the_guard_self_test_passes_only_when_the_server_itself_refused():
    from agent.ollama import CONTEXT_OVERFLOW, _guarded
    from eval.probe import _guard

    class Caught:  # an overflow caught by the adapter's reply checks after a reply, not refused by the server
        def __init__(self, guard):
            self.guard = guard

        def complete(self, system, messages, tools):
            raise _guarded(CONTEXT_OVERFLOW, self.guard, "x")

    assert _guard(lambda **kw: Caught("server"))["passed"] is True
    for guard in ("count_at_num_ctx", "length_stop"):
        result = _guard(lambda **kw: Caught(guard))
        assert result["passed"] is False and {c["guard"] for c in result["checks"]} == {guard}
