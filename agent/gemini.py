"""The Gemini adapter for the model interface of decision 020 §6 (decisions 032, 033; exploratory only):
complete(system, messages, tools) -> {content, usage} with Anthropic Messages API shapes, over the Google Gen AI SDK.

- Used only by eval.explore on the branch explore/032-argon; the frozen methods, prompts, tools and budgets are unchanged
  (decision 032 §2). Endpoint (decision 033): the Gemini API with the user's API key, which the user keeps in the macOS
  keychain and tools/with-gemini-key puts into one command's environment as GEMINI_API_KEY (the SDK reads it); or Vertex
  AI with the user's Application Default Credentials. This module never reads, asks for, prints or stores a credential (key_problem only sees whether the
  variable is set).
- Shapes: tool_use <-> function_call (our ids are deterministic, toolu_<turn>_<i>; Gemini's own call id is kept as
  `call_id`), tool_result -> function_response ({"output": text} or {"error": text}), thinking <-> a thought part. Every
  thought signature the model returns stays on its block and goes back unchanged, as Gemini requires for tool calls.
- Usage: input_tokens = the prompt tokens (cached ones included), output_tokens = answer + thinking tokens (both billed
  as output). Every reply is also kept in `calls` (cached and thinking tokens apart) for the cost of decision 032 §3.
- Failures (decision 023 §5 reasons): HTTP 408 / 429 / 5xx and dropped connections are retried inside the call
  (CALL_RETRIES, waiting BACKOFF_S) and then reported as api_error / transport_error; a timeout is not waited for again;
  HTTP 400 is "bad_request" and a blocked prompt or reply "blocked" (decision 032 §3: a model failure, never retried).
- Pinning: Vertex has no digest to pin, so every reply must name its model version and it must stay the one first seen
  (or `expected_version`, the version of the experiment): otherwise "pin_mismatch" (decision 032 §3).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from agent.harness import CallError

PROVIDER = "google-gemini"
ENDPOINTS = ("gemini-api", "vertex")  # decision 033: the Gemini API with the user's API key; Vertex AI with ADC
KEY_VARIABLES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")  # where the SDK looks for the Gemini API key
BLOCKED = "blocked"  # the provider's filters blocked the prompt or the reply
BAD_REQUEST = "bad_request"  # HTTP 400: the request itself is wrong, so sending it again cannot help
PIN_MISMATCH = "pin_mismatch"  # a reply from another model version, or one that names none
CALL_RETRIES = 4
BACKOFF_S = (10, 30, 90, 180)
RETRY_STATUS = (408, 429, 500, 502, 503, 504)
BLOCK_FINISH = ("SAFETY", "RECITATION", "LANGUAGE", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY",
                "IMAGE_PROHIBITED_CONTENT", "IMAGE_RECITATION")
THINKING_LEVELS = ("MINIMAL", "LOW", "MEDIUM", "HIGH")
DEFAULT_TIMEOUT_S = 3600.0

Call = Callable[[dict], dict]  # a generate_content request (dict) -> the response as JSON-mode dict


# ---------------------------------------------------------------- shapes: Anthropic Messages API <-> Gemini contents

def _blocks(content) -> list[dict]:
    return [{"type": "text", "text": content}] if isinstance(content, str) else list(content)


def _result_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


def _signature(block: dict) -> dict:
    return {"thought_signature": block["thought_signature"]} if block.get("thought_signature") else {}


def to_gemini_contents(messages: list[dict]) -> list[dict]:
    """Anthropic-shaped messages as Gemini contents (role user / model). A message without parts (an empty reply kept in
    the transcript) is left out, and consecutive messages of one role become one turn."""
    out: list[dict] = []
    names: dict[str, str] = {}
    call_ids: dict[str, str] = {}
    for message in messages:
        parts = []
        if message["role"] == "assistant":
            role = "model"
            for b in _blocks(message["content"]):
                kind = b.get("type")
                if kind == "text":
                    parts.append({"text": b["text"], **_signature(b)})
                elif kind == "thinking":
                    parts.append({"text": b["thinking"], "thought": True, **_signature(b)})
                elif kind == "tool_use":
                    names[b["id"]] = b["name"]
                    call = {"name": b["name"], "args": b.get("input") or {}}
                    if b.get("call_id"):
                        call_ids[b["id"]] = call["id"] = b["call_id"]
                    parts.append({"function_call": call, **_signature(b)})
                else:
                    raise ValueError(f"unsupported content block {kind!r}")
        elif message["role"] == "user":
            role = "user"
            for b in _blocks(message["content"]):
                kind = b.get("type")
                if kind == "text":
                    parts.append({"text": b["text"]})
                elif kind == "tool_result":
                    if b["tool_use_id"] not in names:
                        raise ValueError(f"tool_result for an unknown tool_use id {b['tool_use_id']!r}")
                    text = _result_text(b.get("content"))
                    result = {"name": names[b["tool_use_id"]], "response": {"error" if b.get("is_error") else "output": text}}
                    if b["tool_use_id"] in call_ids:
                        result["id"] = call_ids[b["tool_use_id"]]
                    parts.append({"function_response": result})
                else:
                    raise ValueError(f"unsupported content block {kind!r}")
        else:
            raise ValueError(f"unsupported role {message['role']!r}")
        if not parts:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["parts"].extend(parts)
        else:
            out.append({"role": role, "parts": parts})
    return out


def to_function_declarations(tools: list[dict]) -> list[dict]:
    """The tool schemas as given (JSON Schema, not Gemini's OpenAPI subset): nothing about a tool is changed."""
    return [{"name": t["name"], "description": t.get("description", ""), "parameters_json_schema": t["input_schema"]}
            for t in tools]


def to_content(response: dict, turn: int) -> list[dict]:
    """The first candidate's parts as content blocks. Arguments that are not a JSON object keep an empty `input` and their
    text in `unparsed_arguments`, which the harness rejects as malformed (decision 020 §3, 029 §1)."""
    candidates = response.get("candidates") or [{}]
    blocks, i = [], 0
    for part in (candidates[0].get("content") or {}).get("parts") or []:
        if part.get("function_call"):
            call = part["function_call"]
            args = call.get("args")
            block = {"type": "tool_use", "id": f"toolu_{turn:03d}_{i}", "name": call.get("name") or "",
                     "input": args if isinstance(args, dict) else {}, **_signature(part)}
            if args is not None and not isinstance(args, dict):
                block["unparsed_arguments"] = json.dumps(args)
            if call.get("id"):
                block["call_id"] = call["id"]
            blocks.append(block)
            i += 1
        elif part.get("thought"):
            blocks.append({"type": "thinking", "thinking": part.get("text") or "", **_signature(part)})
        elif "text" in part or part.get("thought_signature"):
            blocks.append({"type": "text", "text": part.get("text") or "", **_signature(part)})
    return blocks


def usage_of(response: dict) -> dict:
    u = response.get("usage_metadata") or {}
    return {k: u.get(f) or 0 for k, f in (("prompt", "prompt_token_count"), ("cached", "cached_content_token_count"),
                                          ("candidates", "candidates_token_count"), ("thoughts", "thoughts_token_count"))}


def call_cost(usage: dict, price_per_mtok: dict) -> float:
    """USD of one reply: uncached and cached prompt tokens at their prices, answer and thinking tokens as output."""
    uncached = usage["prompt"] - usage["cached"]
    return (uncached * price_per_mtok["input"] + usage["cached"] * price_per_mtok["cached_input"]
            + (usage["candidates"] + usage["thoughts"]) * price_per_mtok["output"]) / 1e6


# ---------------------------------------------------------------- failures

def _transport_errors() -> tuple[tuple, tuple]:
    """(timeouts, other transport failures) of the HTTP libraries the SDK may use."""
    timeouts, transport = [TimeoutError], [OSError]
    for name in ("httpx", "httpx2"):
        try:
            lib = __import__(name)
        except ImportError:
            continue
        timeouts.append(lib.TimeoutException)
        transport.append(lib.TransportError)
    return tuple(timeouts), tuple(transport)


def _failure(e: Exception) -> tuple[str | None, bool]:
    """(the stop reason of a failed call, whether to wait and send it again); reason None: not a call failure."""
    from google.genai import errors

    if isinstance(e, errors.APIError):
        if e.code == 400:
            return BAD_REQUEST, False
        return "api_error", e.code in RETRY_STATUS
    try:
        from google.auth import exceptions as auth
        if isinstance(e, auth.GoogleAuthError):
            return "api_error", False
    except ImportError:
        pass
    timeouts, transport = _transport_errors()
    if isinstance(e, timeouts):
        return "transport_error", False
    if isinstance(e, transport):
        return "transport_error", True
    return None, False


def _detail(e: Exception) -> str:
    from google.genai import errors

    if isinstance(e, errors.APIError):
        return f"HTTP {e.code} {e.status}: {e.message}"[:300]
    return f"{type(e).__name__}: {e}"[:300]


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class GeminiModel:
    """One Gemini model with fixed settings (decision 032 §3). `call` sends one request (sdk_call in a run, a
    script in the tests); `calls` lists every reply that came back, billed or not, until the runner drains it."""

    def __init__(self, model: str, *, call: Call, thinking_level: str | None, temperature: float | None, seed: int | None,
                 max_output_tokens: int, expected_version: str | None = None, sleep=time.sleep):
        if thinking_level is not None and thinking_level not in THINKING_LEVELS:
            raise ValueError(f"thinking_level must be one of {THINKING_LEVELS} or None, got {thinking_level!r}")
        self.model, self.call, self.thinking_level, self.temperature = model, call, thinking_level, temperature
        self.seed, self.max_output_tokens, self.sleep = seed, max_output_tokens, sleep
        self.model_version = expected_version
        self.calls: list[dict] = []

    def request(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        config: dict = {"system_instruction": system} if system else {}
        if self.temperature is not None:
            config["temperature"] = self.temperature
        if self.seed is not None:
            config["seed"] = self.seed
        config["max_output_tokens"] = self.max_output_tokens
        if self.thinking_level is not None:
            config["thinking_config"] = {"thinking_level": self.thinking_level}
        config["automatic_function_calling"] = {"disable": True}
        if tools:
            config["tools"] = [{"function_declarations": to_function_declarations(tools)}]
        return {"model": self.model, "contents": to_gemini_contents(messages), "config": config}

    def _send(self, request: dict) -> tuple[dict, int]:
        retries = 0
        while True:
            try:
                return self.call(request), retries
            except Exception as e:
                reason, wait = _failure(e)
                if reason is None:
                    raise
                if wait and retries < CALL_RETRIES:
                    self.sleep(BACKOFF_S[retries])
                    retries += 1
                    continue
                raise CallError(reason, _detail(e)) from e

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        turn = sum(1 for m in messages if m.get("role") == "assistant")
        start = time.monotonic()
        response, retries = self._send(self.request(system, messages, tools))
        candidates = response.get("candidates") or [{}]
        finish = candidates[0].get("finish_reason")
        detail = {"model_version": response.get("model_version"), "finish_reason": finish, **usage_of(response)}
        self.calls.append({"at": _now(), **detail, "latency_s": round(time.monotonic() - start, 3), "retries": retries})
        if block := (response.get("prompt_feedback") or {}).get("block_reason"):
            raise CallError(BLOCKED, f"the prompt was blocked: {block}")
        if finish in BLOCK_FINISH:
            raise CallError(BLOCKED, f"the reply was blocked: finish_reason {finish}")
        version = detail["model_version"]
        if not version:
            raise CallError(PIN_MISMATCH, "the reply names no model version, so it cannot be shown to be the pinned one")
        if self.model_version is not None and version != self.model_version:
            raise CallError(PIN_MISMATCH, f"the reply comes from {version}, not the pinned {self.model_version}")
        self.model_version = version
        content = to_content(response, turn)
        stop = ("max_tokens" if finish == "MAX_TOKENS"
                else "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn")
        return {"content": content, "stop_reason": stop,
                "usage": {"input_tokens": detail["prompt"], "output_tokens": detail["candidates"] + detail["thoughts"]},
                "gemini": detail}

    def drain(self) -> list[dict]:
        calls, self.calls = self.calls, []
        return calls


# ---------------------------------------------------------------- the SDK (a run only; never in the tests)

def key_problem(environ=None) -> str | None:
    """Why the Gemini API cannot authenticate (None when it can). Only whether a key variable is set is looked at; its
    value is never read here, printed or stored (the SDK reads it)."""
    import os

    environ = os.environ if environ is None else environ
    if not any(environ.get(name) for name in KEY_VARIABLES):
        return (f"no API key in the environment ({' or '.join(KEY_VARIABLES)}): run the command under "
                "tools/with-gemini-key, which takes the key the user stored in the macOS keychain (decision 033); it is "
                "never pasted into the conversation")
    return None


def _client(endpoint: str, timeout_s: float, *, project: str | None = None, location: str | None = None):
    from google import genai
    from google.genai import types

    if endpoint not in ENDPOINTS:
        raise ValueError(f"endpoint must be one of {ENDPOINTS}, got {endpoint!r}")
    options = types.HttpOptions(timeout=int(timeout_s * 1000), retry_options=types.HttpRetryOptions(attempts=1))
    if endpoint == "vertex":
        return genai.Client(vertexai=True, project=project, location=location, http_options=options)
    if problem := key_problem():
        raise ValueError(problem)
    return genai.Client(http_options=options)  # the Gemini API; the SDK takes the key from the environment


def sdk_call(endpoint: str, timeout_s: float = DEFAULT_TIMEOUT_S, *, project: str | None = None,
             location: str | None = None) -> Call:
    """generate_content with the SDK's own retries off (GeminiModel retries, and records each retry)."""
    from google.genai import types

    client = _client(endpoint, timeout_s, project=project, location=location)

    def call(request: dict) -> dict:
        response = client.models.generate_content(
            model=request["model"], contents=[types.Content.model_validate(c) for c in request["contents"]],
            config=types.GenerateContentConfig.model_validate(request["config"]))
        return response.model_dump(mode="json", exclude_none=True,
                                   exclude={"sdk_http_response", "automatic_function_calling_history"})
    return call


def sdk_model_facts(endpoint: str, model: str, timeout_s: float = 60.0, *, project: str | None = None,
                    location: str | None = None) -> dict:
    """What the endpoint says about `model` (models.get: free, no generation). ValueError when it cannot be read, so a
    run stops before an attempt starts (decision 032 §4, like the pin check of decision 029)."""
    client = _client(endpoint, timeout_s, project=project, location=location)  # a missing key: its own ValueError
    try:
        m = client.models.get(model=model)
    except Exception as e:
        raise ValueError(f"cannot read {model} on {endpoint}: {_detail(e)}") from e
    return {"name": m.name, "version": m.version, "display_name": m.display_name,
            "input_token_limit": m.input_token_limit, "output_token_limit": m.output_token_limit}
