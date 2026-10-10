"""The local Ollama adapter for the model interface of decision 020 §6 (decision 029): complete(system, messages, tools)
-> {content, usage} with Anthropic Messages API shapes, over Ollama's /api/chat on this Mac only.

- Loopback only: the transport refuses any host but 127.0.0.1, localhost (resolving to loopback only) and ::1, uses
  http.client directly (no proxy settings) and the pin check refuses Ollama's cloud (remote) models, so this adapter can
  never reach a remote or paid service.
- Never a silently truncated call: the request sets truncate and shift to false (Ollama is expected to error instead of
  dropping old messages or shifting the context; the probe's self-test confirms it on this Ollama), and every reply is
  checked without trusting that: a prompt_eval_count is present, the proxy tokens sent are not above num_ctx, the count is
  not below half of them, prompt + output stay below num_ctx, a "length" stop comes only at num_predict, and /api/ps shows
  the model loaded with exactly num_ctx and the pinned digest. A failed check is a CallError whose reason is not retryable
  (decision 023 §5 / 026 #17 retry only API and transport errors); its `guard` names the check (the probe needs "server").
- Pinning: the model digest (/api/tags, the manifest digest that names the weights, template and parameters by sha256)
  and the Ollama version are checked against eval/llm_methods.json at the start of a run and before every incident's
  attempt (eval.runner), never inside an attempt.
- unload(): the model leaves memory (keep_alive 0, confirmed by /api/ps) before a run or probe ends, inside its heavy lock.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from agent.harness import CallError
from collect.snapshot import proxy_tokens

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_S = 3600.0
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")
CONTEXT_OVERFLOW = "context_overflow"  # the request or its reply does not fit num_ctx
CONTEXT_UNVERIFIED = "context_unverified"  # the reply cannot be shown to be untruncated
PIN_MISMATCH = "pin_mismatch"  # another model is loaded under the tag
REMOTE_MODEL = "remote_model"  # Ollama forwarded the call to a remote (cloud) model
CONTEXT_ERROR = re.compile(r"context (length|window|size)|exceeds? .*context", re.IGNORECASE)
COUNT_FLOOR = 0.5  # a full prompt is never evaluated as fewer real tokens than half its proxy tokens (decision 029 §2)
UNLOAD_WAIT_S = 10.0
TIMINGS = ("done_reason", "total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count",
           "eval_duration")

Transport = Callable[..., tuple[int, dict]]  # (method, path, body=None) -> (HTTP status, JSON body)


def _loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


class HttpTransport:
    """JSON over HTTP to a local Ollama. Transport failures raise OSError / http.client.HTTPException."""

    def __init__(self, url: str | None = DEFAULT_URL, timeout: float = DEFAULT_TIMEOUT_S, *, resolve=socket.getaddrinfo):
        parts = urlsplit(url) if isinstance(url, str) else None
        host = parts.hostname if parts else None
        if (parts is None or parts.scheme != "http" or host not in LOOPBACK_NAMES or parts.username or parts.password
                or parts.path not in ("", "/") or parts.query or parts.fragment):
            raise ValueError(f"the Ollama URL must be http:// on a loopback host ({', '.join(LOOPBACK_NAMES)}), got {url!r}: "
                             "the adapter never reaches a remote service (decision 029)")
        port = parts.port or 11434
        if host == "localhost":
            try:
                addresses = {info[4][0] for info in resolve(host, port, 0, socket.SOCK_STREAM)}
            except OSError as e:
                raise ValueError(f"localhost does not resolve ({e}), so it cannot be shown to be loopback") from e
            if not addresses or not all(_loopback(a) for a in addresses):
                raise ValueError(f"localhost resolves to {sorted(addresses)}, not only loopback addresses (decision 029)")
        self.url, self.host, self.port, self.timeout = url, host, port, timeout

    def __call__(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            payload = None if body is None else json.dumps(body).encode()
            conn.request(method, path, body=payload, headers={"Content-Type": "application/json"} if payload else {})
            response = conn.getresponse()
            raw = response.read()
        finally:
            conn.close()
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {"error": raw[:300].decode(errors="replace")}
        return response.status, data if isinstance(data, dict) else {"error": f"unexpected JSON {str(data)[:200]}"}


def default_transport(url: str | None = DEFAULT_URL, timeout: float = DEFAULT_TIMEOUT_S) -> Transport:
    return HttpTransport(url, timeout)


# ---------------------------------------------------------------- shapes: Anthropic Messages API <-> Ollama /api/chat

def _blocks(content) -> list[dict]:
    return [{"type": "text", "text": content}] if isinstance(content, str) else list(content)


def _result_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


def to_ollama_messages(system: str, messages: list[dict]) -> list[dict]:
    """Anthropic-shaped messages as Ollama chat messages: tool_use -> assistant tool_calls (with our ids), tool_result ->
    a "tool" message naming the tool, text -> user / assistant content, thinking -> the assistant's thinking field."""
    out = [{"role": "system", "content": system}] if system else []
    names: dict[str, str] = {}
    for message in messages:
        blocks = _blocks(message["content"])
        if message["role"] == "assistant":
            msg = {"role": "assistant", "content": "\n".join(b["text"] for b in blocks if b.get("type") == "text")}
            if thinking := "\n".join(b["thinking"] for b in blocks if b.get("type") == "thinking"):
                msg["thinking"] = thinking
            calls = []
            for b in blocks:
                if b.get("type") == "tool_use":
                    names[b["id"]] = b["name"]
                    calls.append({"id": b["id"], "function": {"name": b["name"], "arguments": b.get("input") or {}}})
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        if message["role"] != "user":
            raise ValueError(f"unsupported role {message['role']!r}")
        texts: list[str] = []
        for b in blocks:
            kind = b.get("type")
            if kind == "text":
                texts.append(b["text"])
            elif kind == "tool_result":
                if texts:
                    out.append({"role": "user", "content": "\n\n".join(texts)})
                    texts = []
                if b["tool_use_id"] not in names:
                    raise ValueError(f"tool_result for an unknown tool_use id {b['tool_use_id']!r}")
                text = _result_text(b.get("content"))
                if b.get("is_error") and not text.startswith("error"):
                    text = "error: " + text
                out.append({"role": "tool", "content": text, "tool_name": names[b["tool_use_id"]],
                            "tool_call_id": b["tool_use_id"]})
            else:
                raise ValueError(f"unsupported content block {kind!r}")
        if texts:
            out.append({"role": "user", "content": "\n\n".join(texts)})
    return out


def to_ollama_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t["input_schema"]}} for t in tools]


def _arguments(value) -> tuple[dict, str | None]:
    """A tool call's arguments as an object, and the raw text when they are not one. None (no arguments: Ollama writes
    an empty map as null) is an empty object; a string is parsed; anything that is not an object is kept raw."""
    if value is None:
        return {}, None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}, value
    if isinstance(parsed, dict):
        return parsed, None
    return {}, value if isinstance(value, str) else json.dumps(value)


def to_content(message: dict, turn: int) -> list[dict]:
    """An Ollama reply as content blocks. Tool-call ids are ours and deterministic (toolu_<turn>_<i>, unique in a
    conversation). Arguments that are not a JSON object keep an empty `input` (the Anthropic shape) and their raw text in
    `unparsed_arguments`, which the harness rejects as a malformed answer or argument (decision 020 §3, 029 §1)."""
    blocks: list[dict] = []
    if thinking := message.get("thinking"):
        blocks.append({"type": "thinking", "thinking": thinking})
    if text := message.get("content"):
        blocks.append({"type": "text", "text": text})
    for i, tool_call in enumerate(message.get("tool_calls") or []):
        fn = tool_call.get("function") or {}
        args, raw = _arguments(fn.get("arguments"))
        block = {"type": "tool_use", "id": f"toolu_{turn:03d}_{i}", "name": fn.get("name") or "", "input": args}
        if raw is not None:
            block["unparsed_arguments"] = raw
        blocks.append(block)
    return blocks


def sent_proxy_tokens(messages: list[dict], tools: list[dict]) -> int:
    """Proxy tokens of what an Ollama chat request puts in the prompt: message text, tool calls and results, tool schemas.
    Earlier thinking is left out (a chat template may drop it), so this is a floor of what the prompt holds."""
    texts = [json.dumps(tools)] if tools else []
    for m in messages:
        texts.append(m.get("content") or "")
        texts += [json.dumps((c.get("function") or {}).get("arguments")) for c in m.get("tool_calls") or []]
    return proxy_tokens("\n".join(texts))


def _guarded(reason: str, guard: str, detail: str) -> CallError:
    """A CallError of the truncation guard; `guard` names the check that caught it ("server": Ollama refused itself)."""
    error = CallError(reason, detail)
    error.guard = guard
    return error


def _count(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _digest(value) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value if value.startswith("sha256:") else "sha256:" + value


class OllamaModel:
    """One local model with fixed options; complete() never returns a truncated call (module docstring)."""

    def __init__(self, model: str, *, num_ctx: int, num_predict: int, temperature: float, seed: int, think: bool,
                 transport: Transport, digest: str | None = None):
        if not _count(num_ctx) or num_ctx <= 0:
            raise ValueError(f"num_ctx must be a positive integer, got {num_ctx!r}: Ollama's default context is never used")
        if not _count(num_predict) or not 0 < num_predict < num_ctx:
            raise ValueError(f"num_predict must be a positive integer below num_ctx, got {num_predict!r}")
        self.model, self.num_ctx, self.num_predict, self.temperature = model, num_ctx, num_predict, temperature
        self.seed, self.think, self.transport, self.digest = seed, bool(think), transport, digest

    def request(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        body = {"model": self.model, "messages": to_ollama_messages(system, messages), "stream": False,
                "think": self.think, "truncate": False, "shift": False,
                "options": {"temperature": self.temperature, "seed": self.seed, "num_ctx": self.num_ctx,
                            "num_predict": self.num_predict}}
        if tools:
            body["tools"] = to_ollama_tools(tools)
        return body

    def _call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        try:
            return self.transport(method, path, body)
        except (OSError, http.client.HTTPException) as e:  # refused, reset, timed out: the stop reason is the transport
            raise CallError("transport_error", f"{type(e).__name__}: {e}"[:300]) from e

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        turn = sum(1 for m in messages if m.get("role") == "assistant")
        body = self.request(system, messages, tools)
        sent = sent_proxy_tokens(body["messages"], body.get("tools") or [])
        status, data = self._call("POST", "/api/chat", body)
        if status != 200 or data.get("error"):
            message = str(data.get("error") or "")
            if CONTEXT_ERROR.search(message):
                raise _guarded(CONTEXT_OVERFLOW, "server", f"HTTP {status}: {message}"[:300])
            raise CallError("api_error", f"HTTP {status}: {message}"[:300])
        if data.get("remote_model") or data.get("remote_host"):
            raise CallError(REMOTE_MODEL, f"Ollama answered from a remote model {data.get('remote_model')!r}: local only")
        prompt, out = data.get("prompt_eval_count"), data.get("eval_count", 0)  # Ollama omits a count of 0
        if not _count(prompt) or prompt == 0 or not _count(out):
            raise _guarded(CONTEXT_UNVERIFIED, "count_missing",
                           f"the reply has no usable prompt_eval_count / eval_count ({prompt!r}, {out!r})")
        if sent > self.num_ctx:  # proxy tokens undercount telemetry: a reply to this was cut, or cannot be shown not to be
            raise _guarded(CONTEXT_UNVERIFIED, "sent_proxy", f"{sent} proxy tokens were sent, above num_ctx {self.num_ctx}, "
                                                             f"yet a reply came back (prompt_eval_count {prompt})")
        if prompt < COUNT_FLOOR * sent:
            raise _guarded(CONTEXT_UNVERIFIED, "count_floor", f"prompt_eval_count {prompt} is below half of the {sent} proxy "
                                                              "tokens sent: part of the prompt was dropped or not counted")
        if prompt + out >= self.num_ctx:
            raise _guarded(CONTEXT_OVERFLOW, "count_at_num_ctx",
                           f"prompt {prompt} + output {out} tokens reached num_ctx {self.num_ctx}")
        if data.get("done_reason") == "length" and out < self.num_predict:
            raise _guarded(CONTEXT_OVERFLOW, "length_stop", f"generation stopped by length after {out} tokens, before "
                                                            f"num_predict {self.num_predict}: the context ran out")
        self._check_loaded()
        content = to_content(data.get("message") or {}, turn)
        stop = ("max_tokens" if data.get("done_reason") == "length"
                else "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn")
        return {"content": content, "stop_reason": stop, "usage": {"input_tokens": prompt, "output_tokens": out},
                "ollama": {k: data.get(k) for k in TIMINGS}}

    def _check_loaded(self) -> None:
        """/api/ps: the model that answered is loaded with exactly num_ctx (no clamping) and the pinned digest."""
        status, data = self._call("GET", "/api/ps")
        entry = next((m for m in (data.get("models") or []) if self.model in (m.get("name"), m.get("model"))), None)
        if status != 200 or entry is None:
            raise _guarded(CONTEXT_UNVERIFIED, "loaded_context", f"/api/ps does not list {self.model} as loaded (HTTP {status})")
        if entry.get("context_length") != self.num_ctx:
            raise _guarded(CONTEXT_UNVERIFIED, "loaded_context", f"{self.model} is loaded with a context of "
                                                                 f"{entry.get('context_length')}, not num_ctx {self.num_ctx}")
        if self.digest is not None and _digest(entry.get("digest")) != self.digest:
            raise CallError(PIN_MISMATCH, f"the loaded {self.model} has digest {entry.get('digest')}, not {self.digest}")


def unload(transport: Transport, model: str, *, wait_s: float | None = None, sleep=time.sleep) -> str | None:
    """Unload `model` (an empty chat with keep_alive 0) and confirm with /api/ps that it left memory, so nothing of a run
    or probe outlives its heavy lock (decision 029). Returns None when confirmed, otherwise why not; it never raises
    (it runs in a finally, after the result or the error that matters)."""
    wait_s = UNLOAD_WAIT_S if wait_s is None else wait_s
    tries = int(wait_s / 0.5) + 1
    try:
        transport("POST", "/api/chat", {"model": model, "messages": [], "keep_alive": 0, "stream": False})
        for attempt in range(tries):
            _, data = transport("GET", "/api/ps")
            if not any(model in (m.get("name"), m.get("model")) for m in data.get("models") or []):
                return None
            if attempt + 1 < tries:
                sleep(0.5)
        return (f"{model} is still loaded after an unload request ({wait_s:g} s): stop the server "
                "(tools/with-local-ollama does) before the heavy lock is released")
    except (OSError, http.client.HTTPException) as e:
        return f"cannot reach the local Ollama server to unload {model}: {type(e).__name__}: {e}"


# ---------------------------------------------------------------- pinning (decision 029)

def server_facts(transport: Transport, model: str) -> dict:
    """What the local Ollama says about itself and `model` (read only: /api/version, /api/tags, /api/show)."""
    try:
        _, version = transport("GET", "/api/version")
        _, tags = transport("GET", "/api/tags")
        status, show = transport("POST", "/api/show", {"model": model})
    except (OSError, http.client.HTTPException) as e:
        raise ValueError(f"cannot reach the local Ollama server: {type(e).__name__}: {e} (start it: ollama serve)") from e
    entry = next((m for m in tags.get("models") or [] if model in (m.get("name"), m.get("model"))), None)
    show = show if status == 200 else {}
    info = show.get("model_info") or {}
    context = next((v for k, v in info.items() if k.endswith(".context_length") and _count(v)), None)
    remote = model.endswith("cloud") or any((entry or {}).get(k) or show.get(k) for k in ("remote_model", "remote_host"))
    return {"ollama_version": version.get("version"), "model": model, "digest": _digest((entry or {}).get("digest")),
            "remote": bool(remote), "context_length": context, "capabilities": show.get("capabilities"),
            "parameters": show.get("parameters"), "details": show.get("details") or (entry or {}).get("details")}


def pin_problems(facts: dict, *, digest: str | None = None, version: str | None = None, num_ctx: int) -> list[str]:
    """Why this server and model are not the pinned local one (digest / version None: not compared, e.g. the probe)."""
    model, problems = facts["model"], []
    if facts["digest"] is None:
        problems.append(f"{model} is not installed (not listed by /api/tags)")
    if facts["remote"]:
        problems.append(f"{model} is a remote (cloud) model: only models that run on this Mac are allowed (decision 029)")
    if digest is not None and facts["digest"] != digest:
        problems.append(f"{model} has digest {facts['digest']}, not the pinned {digest}")
    if version is not None and facts["ollama_version"] != version:
        problems.append(f"Ollama is version {facts['ollama_version']}, not the pinned {version}")
    if facts["context_length"] is None:
        problems.append(f"/api/show gives no context length for {model}")
    elif num_ctx > facts["context_length"]:
        problems.append(f"num_ctx {num_ctx} is above {model}'s context length {facts['context_length']}")
    return problems


def capability_problems(facts: dict, *, think: bool) -> list[str]:
    caps = facts["capabilities"] or []
    problems = [] if "tools" in caps else [f"{facts['model']} does not report the tools capability (/api/show)"]
    if think and "thinking" not in caps:
        problems.append(f"{facts['model']} does not report the thinking capability, but think is on")
    return problems


def config_problems(config: dict) -> list[str]:
    """The fields an approved local config must pin (decision 029); the context fit is checked by eval.runner."""
    problems = []
    model, o = config.get("model"), config.get("ollama") or {}
    if not isinstance(model, str) or not model or model.endswith("cloud"):
        problems.append(f"model must be the tag of a local Ollama model, got {model!r}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(config.get("model_version"))):
        problems.append("model_version must be the model digest sha256:<64 hex> (/api/tags)")
    t = config.get("temperature")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
        problems.append(f"temperature must be a number >= 0, got {t!r}")
    if config.get("price_per_mtok") != {"input": 0, "output": 0}:
        problems.append("price_per_mtok must be {input: 0, output: 0}: a local model has no external cost, so cost_usd "
                        "is 0, not unknown (decision 029)")
    try:
        HttpTransport(o.get("url"))
    except ValueError as e:
        problems.append(str(e))
    if not isinstance(o.get("version"), str) or not o.get("version"):
        problems.append("ollama.version must pin the Ollama version (/api/version)")
    num_ctx, num_predict = o.get("num_ctx"), o.get("num_predict")
    if not _count(num_ctx) or num_ctx == 0:
        problems.append(f"ollama.num_ctx must be a positive integer, got {num_ctx!r}")
    if not _count(num_predict) or num_predict == 0 or (_count(num_ctx) and num_predict >= num_ctx):
        problems.append(f"ollama.num_predict must be a positive integer below num_ctx, got {num_predict!r}")
    if not _count(o.get("seed")) or o.get("seed") == 0:
        problems.append("ollama.seed must be a positive integer (a 0 can be dropped as unset on the way to the runner)")
    if not isinstance(o.get("think"), bool):
        problems.append(f"ollama.think must be true or false, got {o.get('think')!r}")
    timeout = o.get("timeout_s")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        problems.append(f"ollama.timeout_s must be a positive number, got {timeout!r}")
    return problems


def model_from_config(config: dict, *, transport: Transport | None = None) -> tuple[OllamaModel, dict]:
    """The adapter of an approved local config, after the pin check against the running server (ValueError otherwise)."""
    o = config["ollama"]
    transport = transport or default_transport(o["url"], o.get("timeout_s", DEFAULT_TIMEOUT_S))
    facts = server_facts(transport, config["model"])
    problems = (pin_problems(facts, digest=config["model_version"], version=o["version"], num_ctx=o["num_ctx"])
                + capability_problems(facts, think=o["think"]))
    if problems:
        raise ValueError("the local model is not the one eval/llm_methods.json pins (decision 029): " + "; ".join(problems))
    model = OllamaModel(config["model"], num_ctx=o["num_ctx"], num_predict=o["num_predict"],
                        temperature=config["temperature"], seed=o["seed"], think=o["think"], transport=transport,
                        digest=facts["digest"])
    return model, facts


def run_record(config: dict, facts: dict) -> dict:
    """The local runtime in run_config.json (decision 024 / 029): every value is pinned, so a resumed run matches."""
    o = config["ollama"]
    return {"provider": "ollama", "model": config["model"], "model_version": facts["digest"],
            "ollama_version": facts["ollama_version"], "num_ctx": o["num_ctx"], "num_predict": o["num_predict"],
            "temperature": config["temperature"], "seed": o["seed"], "think": o["think"]}
