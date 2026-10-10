"""The local Ollama adapter (decision 029): the model interface of decision 020 §6 over /api/chat, the truncation guard,
the pin check and loopback only. A scripted transport or a stub server on 127.0.0.1 stands in for Ollama."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent.harness import CallError
from eval.runner import RETRYABLE
from ollama_fixtures import ANSWER, DIGEST, MODEL, VERSION, FakeOllama, call, reply
from test_agent_tools import Snap


def model(fake, **kw):
    from agent.ollama import OllamaModel

    settings = {"num_ctx": 32_768, "num_predict": 1024, "temperature": 0, "seed": 42, "think": False, "digest": DIGEST}
    return OllamaModel(MODEL, transport=fake, **{**settings, **kw})


TOOL = {"name": "search_spans", "description": "find spans", "input_schema": {"type": "object", "properties": {}}}


def test_messages_and_tools_are_converted_to_the_ollama_chat_shape():
    from agent.ollama import to_ollama_messages, to_ollama_tools

    messages = [
        {"role": "user", "content": [{"type": "text", "text": "task"}]},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "look"},
                                          {"type": "tool_use", "id": "toolu_000_0", "name": "search_spans", "input": {"status": "error"}},
                                          {"type": "tool_use", "id": "toolu_000_1", "name": "list_services", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_000_0", "content": "3 spans"},
                                     {"type": "tool_result", "tool_use_id": "toolu_000_1", "is_error": True,
                                      "content": "error: no more tool calls; call submit_diagnosis"},
                                     {"type": "text", "text": "submit now"}]},
        {"role": "user", "content": "plain string"},
    ]
    assert to_ollama_messages("system text", messages) == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "look", "thinking": "hmm",
         "tool_calls": [{"id": "toolu_000_0", "function": {"name": "search_spans", "arguments": {"status": "error"}}},
                        {"id": "toolu_000_1", "function": {"name": "list_services", "arguments": {}}}]},
        {"role": "tool", "content": "3 spans", "tool_name": "search_spans", "tool_call_id": "toolu_000_0"},
        {"role": "tool", "content": "error: no more tool calls; call submit_diagnosis", "tool_name": "list_services",
         "tool_call_id": "toolu_000_1"},
        {"role": "user", "content": "submit now"},
        {"role": "user", "content": "plain string"},
    ]
    assert to_ollama_tools([TOOL]) == [{"type": "function", "function": {
        "name": "search_spans", "description": "find spans", "parameters": {"type": "object", "properties": {}}}}]
    with pytest.raises(ValueError, match="unknown tool_use id"):
        to_ollama_messages("", [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": ""}]}])


def test_a_reply_becomes_content_blocks_with_deterministic_tool_ids_and_usage():
    fake = FakeOllama(reply(call("search_spans", {"status": "error"}), call("submit_diagnosis", json.dumps(ANSWER)),
                            content="looking", thinking="first errors"))
    history = [{"role": "user", "content": [{"type": "text", "text": "task"}]},
               {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
               {"role": "user", "content": [{"type": "text", "text": "go on"}]}]
    out = model(fake).complete("sys", history, [TOOL])
    assert out["content"] == [
        {"type": "thinking", "thinking": "first errors"}, {"type": "text", "text": "looking"},
        {"type": "tool_use", "id": "toolu_001_0", "name": "search_spans", "input": {"status": "error"}},
        {"type": "tool_use", "id": "toolu_001_1", "name": "submit_diagnosis", "input": ANSWER},  # string arguments parsed
    ]
    chat = fake.chats()[0]
    assert out["usage"] == {"input_tokens": fake.prompt_tokens(chat), "output_tokens": 20}
    assert out["stop_reason"] == "tool_use" and out["ollama"]["prompt_eval_duration"] == 2_000_000_000
    same = FakeOllama(reply(call("search_spans", {"status": "error"})))
    assert model(same).complete("sys", history, [TOOL])["content"][0]["id"] == "toolu_001_0"  # ids never depend on Ollama's
    broken = model(FakeOllama(reply(call("submit_diagnosis", "{not json")))).complete("sys", history, [TOOL])["content"]
    assert broken == [{"type": "tool_use", "id": "toolu_001_0", "name": "submit_diagnosis", "input": {},
                       "unparsed_arguments": "{not json"}]
    assert model(FakeOllama(reply(content=""))).complete("sys", history, [])["content"] == []


def test_the_request_fixes_the_context_temperature_seed_and_never_lets_ollama_truncate():
    fake = FakeOllama(reply(content="ok"))
    model(fake, think=True, num_predict=2048).complete("sys", [{"role": "user", "content": "hi"}], [TOOL])
    body = fake.chats()[0]
    assert body["model"] == MODEL and body["stream"] is False and body["think"] is True
    assert body["truncate"] is False and body["shift"] is False  # Ollama errors instead of dropping or shifting context
    assert body["options"] == {"temperature": 0, "seed": 42, "num_ctx": 32_768, "num_predict": 2048}
    assert [m["role"] for m in body["messages"]] == ["system", "user"] and len(body["tools"]) == 1
    model(fake).complete("", [{"role": "user", "content": "hi"}], [])
    assert "tools" not in fake.chats()[1] and fake.chats()[1]["messages"] == [{"role": "user", "content": "hi"}]
    with pytest.raises(ValueError, match="num_ctx"):
        model(fake, num_ctx=None)
    with pytest.raises(ValueError, match="num_predict"):
        model(fake, num_predict=40_000)


def overflowing(prompt_eval_count, eval_count, done_reason="stop"):
    def chat(body, prompt):
        return 200, {"message": reply(content="x"), "done": True, "done_reason": done_reason,
                     "prompt_eval_count": prompt_eval_count, "eval_count": eval_count}
    return chat


@pytest.mark.parametrize("fake, reason, says", [
    (FakeOllama(ratio=1000), "context_overflow", "exceeds the context length"),  # Ollama refuses (truncate: false)
    (FakeOllama(chat=overflowing(32_000, 768)), "context_overflow", "reached num_ctx"),
    (FakeOllama(chat=overflowing(1000, 50, "length")), "context_overflow", "before num_predict"),
    (FakeOllama(chat=overflowing(None, 50)), "context_unverified", "prompt_eval_count"),
    (FakeOllama(loaded_ctx=4096), "context_unverified", "loaded with a context of 4096"),
    (FakeOllama(digest="cd" * 32), "pin_mismatch", "digest"),  # another model under the same tag
])
def test_a_context_overflow_is_a_call_error_never_a_silently_truncated_reply(fake, reason, says):
    with pytest.raises(CallError) as e:
        model(fake).complete("sys", [{"role": "user", "content": "x" * 400}], [TOOL])
    assert e.value.reason == reason and says in e.value.detail
    assert reason not in RETRYABLE  # deterministic: retrying the same request overflows again (decision 029)


def test_an_output_capped_by_num_predict_is_returned_like_a_max_tokens_stop():
    out = model(FakeOllama(chat=overflowing(1000, 1024, "length"))).complete("sys", [{"role": "user", "content": "x"}], [])
    assert out["stop_reason"] == "max_tokens" and out["content"] == [{"type": "text", "text": "x"}]


def test_api_and_transport_errors_keep_their_retryable_reasons():
    def raising(exc):
        def transport(method, path, body=None):
            raise exc
        return transport

    for transport, reason in ((FakeOllama(chat=lambda b, p: (500, {"error": "model runner has unexpectedly stopped"})),
                               "api_error"),
                              (FakeOllama(chat=lambda b, p: (200, {"error": "out of memory"})), "api_error"),
                              (raising(ConnectionRefusedError(61, "refused")), "transport_error"),
                              (raising(TimeoutError("timed out")), "transport_error")):
        with pytest.raises(CallError) as e:
            model(transport).complete("sys", [{"role": "user", "content": "x"}], [])
        assert e.value.reason == reason and reason in RETRYABLE
    remote = FakeOllama(chat=lambda b, p: (200, {"message": reply(content="x"), "done": True, "prompt_eval_count": 9,
                                                  "eval_count": 1, "remote_model": "big", "remote_host": "https://x"}))
    with pytest.raises(CallError) as e:
        model(remote).complete("sys", [{"role": "user", "content": "x"}], [])
    assert e.value.reason == "remote_model" and "remote_model" not in RETRYABLE


@pytest.mark.parametrize("url", ["http://example.com:11434", "http://10.0.0.5:11434", "https://127.0.0.1:11434",
                                 "http://127.0.0.1.example.com:11434", "http://user@evil.com:11434", "127.0.0.1:11434",
                                 "http://[2001:db8::1]:11434", "http://0.0.0.0:11434", None])
def test_only_a_loopback_url_is_accepted(url):
    from agent.ollama import HttpTransport

    with pytest.raises(ValueError, match="loopback"):
        HttpTransport(url)


def test_localhost_must_resolve_to_loopback_only():
    from agent.ollama import HttpTransport

    assert HttpTransport("http://localhost:11434", resolve=lambda *a: [(2, 1, 6, "", ("127.0.0.1", 11434))]).port == 11434
    assert HttpTransport("http://[::1]:11434").host == "::1"
    with pytest.raises(ValueError, match="loopback"):
        HttpTransport("http://localhost:11434", resolve=lambda *a: [(2, 1, 6, "", ("192.168.1.9", 11434))])


def test_the_pin_check_refuses_another_digest_version_context_or_a_remote_model():
    from agent.ollama import capability_problems, pin_problems, server_facts

    facts = server_facts(FakeOllama(), MODEL)
    assert facts == {"ollama_version": VERSION, "model": MODEL, "digest": DIGEST, "remote": False, "context_length": 262_144,
                     "capabilities": ["completion", "tools", "thinking"], "parameters": "temperature 0.6\ntop_k 20",
                     "details": {"family": "qwen3", "parameter_size": "1B", "quantization_level": "Q4_K_M"}}
    assert pin_problems(facts, digest=DIGEST, version=VERSION, num_ctx=196_608) == []
    assert "digest" in " ".join(pin_problems(facts, digest="sha256:" + "cd" * 32, version=VERSION, num_ctx=1))
    assert "0.36.0" in " ".join(pin_problems(facts, digest=DIGEST, version="0.36.0", num_ctx=1))
    assert "context length" in " ".join(pin_problems(facts, digest=DIGEST, version=VERSION, num_ctx=300_000))
    missing = server_facts(FakeOllama(model="other:1b"), MODEL)
    assert missing["digest"] is None and "not installed" in " ".join(pin_problems(missing, num_ctx=1))
    for fake in (FakeOllama(extra={"remote_model": "big", "remote_host": "https://ollama.com"}),
                 FakeOllama(model="gpt-oss:120b-cloud")):
        facts = server_facts(fake, fake.model)
        assert facts["remote"] and "remote" in " ".join(pin_problems(facts, num_ctx=1))
    plain = server_facts(FakeOllama(capabilities=("completion",)), MODEL)
    assert capability_problems(plain, think=False) == [f"{MODEL} does not report the tools capability (/api/show)"]
    assert len(capability_problems(plain, think=True)) == 2


def test_a_model_from_an_approved_config_is_pinned_or_refused():
    from agent.ollama import model_from_config
    from ollama_fixtures import approved_config

    model, facts = model_from_config(approved_config(), transport=FakeOllama())
    assert (model.num_ctx, model.num_predict, model.seed, model.think, model.digest) == (196_608, 8192, 42, False, DIGEST)
    assert facts["ollama_version"] == VERSION
    for fake, says in ((FakeOllama(digest="cd" * 32), "digest"), (FakeOllama(version="0.36.0"), "version"),
                       (FakeOllama(context_length=40_960), "context length"), (FakeOllama(capabilities=()), "tools")):
        with pytest.raises(ValueError, match=says):
            model_from_config(approved_config(), transport=fake)
    with pytest.raises(ValueError, match="cannot reach"):
        model_from_config(approved_config(url="http://127.0.0.1:1"))


class Stub(BaseHTTPRequestHandler):
    fake = None

    def _answer(self, body):
        status, data = Stub.fake(self.command, self.path, body)
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._answer(None)

    def do_POST(self):
        self._answer(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))

    def log_message(self, *args):
        pass


def test_the_real_http_transport_talks_to_a_loopback_stub_server():
    from agent.ollama import HttpTransport, model_from_config
    from ollama_fixtures import approved_config

    Stub.fake = FakeOllama(reply(call("submit_diagnosis", ANSWER)))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        assert HttpTransport(url)("GET", "/api/version") == (200, {"version": VERSION})
        assert HttpTransport(url)("GET", "/api/nothing")[0] == 404
        model, facts = model_from_config(approved_config(url=url))
        assert facts["digest"] == DIGEST
        out = model.complete("sys", [{"role": "user", "content": "task"}], [TOOL])
        assert out["content"][0]["name"] == "submit_diagnosis" and out["usage"]["output_tokens"] == 20
        assert [p for _, p, _ in Stub.fake.requests][2:] == ["/api/version", "/api/tags", "/api/show", "/api/chat", "/api/ps"]
    finally:
        server.shutdown()
        server.server_close()
    with pytest.raises(CallError) as e:  # nothing listens there any more
        model.complete("sys", [{"role": "user", "content": "task"}], [TOOL])
    assert e.value.reason == "transport_error"


def test_the_harness_runs_on_the_adapter_and_a_local_model_costs_zero(tmp_path):
    from agent.harness import investigate

    fake = FakeOllama(reply(call("search_spans", {"status": "error"})), reply(call("submit_diagnosis", ANSWER)))
    pred, transcript = investigate(Snap(), "INC-001", model(fake), cache_root=tmp_path / "cache",
                                   method={"name": "agent", "version": "1"}, price_per_mtok={"input": 0, "output": 0})
    assert transcript["stop_reason"] == "submitted" and pred["origin_candidates"] == ["payment", "checkout"]
    assert pred["usage"]["cost_usd"] == 0.0 and pred["usage"]["tokens_in"] > 0 and pred["usage"]["tool_calls"] == 1
    second = fake.chats()[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"] and second[3]["tool_name"] == "search_spans"
