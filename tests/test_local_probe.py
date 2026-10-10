"""`python -m eval local-probe` (decision 029): the three LLM methods with one local model on the SYNTHETIC sample only,
the context guard self-test, a repeat check and prefill / decode speed on generated filler. Never results; writes
nothing under data/. The scripted transport stands in for Ollama."""

import json
import shutil

import pytest

import agent.ollama as ollama
import env.soak as soak
from collect.sample import SAMPLE_DIR
from env.lock import PROJECT_DIR
from eval.runner import LLM_METHODS
from ollama_fixtures import DIGEST, MODEL, VERSION, FakeOllama, answering, reply


def tree(root):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*"))


def no_lock(project_dir):
    return {}


def test_the_probe_runs_the_three_methods_on_the_synthetic_sample_and_says_it_is_not_a_result():
    from eval.probe import BANNER, run_probe

    fake = FakeOllama(chat=answering)
    before = tree(PROJECT_DIR / "data")
    report = run_probe(MODEL, num_ctx=65_536, context_sizes=(1000, 4000, 100_000), transport=fake, require_lock=no_lock)
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
        assert m["prediction"]["origin_candidates"] == ["payment", "checkout"]
    assert report["methods"]["agent"]["calls"] == 2 and report["methods"]["retrieval"]["calls"] == 2
    guard = report["guard_selftest"]
    assert guard["raised"] is True and guard["reason"] == "context_overflow" and guard["num_ctx"] == 2048
    assert report["repeat_check"]["identical"] is True
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

    report = run_probe(MODEL, num_ctx=65_536, transport=FakeOllama(chat=texty), require_lock=no_lock)
    dump = report["methods"]["dump-all"]
    assert dump["error"] is None and dump["valid_prediction"] is False and dump["abstained"] is True
    assert dump["text_tool_calls"] == 3 and dump["tool_calls_parsed"] == 0 and dump["corrections"] == 2
    assert dump["stop_reason"] == "no_submission"
    failed = report["methods"]["retrieval"]
    assert failed["error"]["reason"] == "api_error" and failed["valid_prediction"] is False
    assert report["methods"]["agent"]["valid_prediction"] is True and report["speed"] == []


def test_the_probe_refuses_anything_but_the_synthetic_sample(tmp_path):
    from eval.probe import run_probe

    fake = FakeOllama(chat=answering)
    copy = tmp_path / "copy"
    shutil.copytree(PROJECT_DIR / SAMPLE_DIR, copy)
    manifest = json.loads((copy / "sample.json").read_text())
    (copy / "sample.json").write_text(json.dumps({**manifest, "synthetic": False}))
    with pytest.raises(ValueError, match="synthetic"):
        run_probe(MODEL, transport=fake, require_lock=no_lock, sample_root=copy)
    (copy / "sample.json").write_text(json.dumps(manifest))
    label = next(copy.rglob("label.json"))
    label.write_text(label.read_text() + " ")
    with pytest.raises(ValueError, match="sha256"):
        run_probe(MODEL, transport=fake, require_lock=no_lock, sample_root=copy)
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
        run_probe(kw.pop("model", MODEL), transport=fake, require_lock=no_lock, **kw)
    assert fake.chats() == []


def test_the_default_context_is_the_models_capped_and_the_lock_is_required():
    from eval.probe import DEFAULT_NUM_CTX_CAP, run_probe

    small = FakeOllama(chat=answering, context_length=40_960)
    assert run_probe(MODEL, transport=small, require_lock=no_lock)["settings"]["num_ctx"] == 40_960
    large = FakeOllama(chat=answering)
    assert run_probe(MODEL, transport=large, require_lock=no_lock)["settings"]["num_ctx"] == DEFAULT_NUM_CTX_CAP

    def busy(project_dir):
        raise soak.LockNotHeld("Mac heavy lock not held; run via ./tools/with-mac-lock (MACHINE_POLICY.md)")

    untouched = FakeOllama(chat=answering)
    with pytest.raises(soak.LockNotHeld):
        run_probe(MODEL, transport=untouched, require_lock=busy)
    assert untouched.requests == []


def test_the_cli_writes_json_and_never_under_data(tmp_path, monkeypatch, capsys):
    from eval.__main__ import main

    fake = FakeOllama(chat=answering)
    monkeypatch.setattr(ollama, "default_transport", lambda url, timeout: fake)
    monkeypatch.setattr(soak, "require_heavy_lock", no_lock)
    out = tmp_path / "probe.json"
    assert main(["local-probe", "--model", MODEL, "--num-ctx", "65536", "--think", "--context-sizes", "1000,2000",
                 "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["settings"]["think"] is True and [s["size_proxy_tokens"] for s in report["speed"]] == [1000, 2000]
    assert "NOT results" in capsys.readouterr().err
    assert main(["local-probe", "--model", MODEL, "--num-ctx", "65536"]) == 0
    assert json.loads(capsys.readouterr().out)["methods"]["agent"]["valid_prediction"] is True
    for bad in (PROJECT_DIR / "data" / "probe.json", PROJECT_DIR / "data" / "external" / "x" / "probe.json"):
        assert main(["local-probe", "--model", MODEL, "--out", str(bad)]) == 2
        assert not bad.exists()
    assert "under data/" in capsys.readouterr().err
    assert main(["local-probe", "--model", MODEL, "--context-sizes", "8k"]) == 2
    with pytest.raises(SystemExit):
        main(["local-probe"])  # --model is required
