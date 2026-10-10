"""A scripted local Ollama API for the decision-029 tests: the adapter's transport is replaced, the real Ollama is never
reached. /api/version, /api/tags, /api/show, /api/ps and /api/chat answer like Ollama 0.35 does in shape."""

import json
import math

from collect.snapshot import proxy_tokens

MODEL = "qwen-test:1b-q4"
DIGEST_HEX = "ab" * 32
DIGEST = "sha256:" + DIGEST_HEX
VERSION = "0.35.0"
ANSWER = {"fault": {"fault_type": "error_response", "fault_family": "error"}, "origin_candidates": ["payment", "checkout"],
          "affected_services": ["payment", "checkout"], "user_symptom": {"kinds": ["errors"]}, "evidence": []}


def call(name, args):
    return {"function": {"name": name, "arguments": args}}


def reply(*calls, content="", thinking=None):
    message = {"role": "assistant", "content": content}
    if thinking is not None:
        message["thinking"] = thinking
    if calls:
        message["tool_calls"] = list(calls)
    return message


def answering(body, prompt):
    """A model that does what each method asks: queries, one tool call then a submission, or a short sentence."""
    names = [t["function"]["name"] for t in body.get("tools") or []]
    if "propose_queries" in names:
        return reply(call("propose_queries", {"queries": [{"text": "error"}, {"text": "payment"}]}))
    if names == ["submit_diagnosis"]:
        return reply(call("submit_diagnosis", ANSWER))
    if names:
        if any(m["role"] == "tool" for m in body["messages"]):
            return reply(call("submit_diagnosis", ANSWER), content="payment fails")
        return reply(call("search_spans", {"status": "error", "limit": 5}))
    return reply(content="Amber cedar harbor.")


class FakeOllama:
    """The transport (method, path, body) -> (status, json) of a local Ollama with one installed model.

    truncating: ignores truncate: false like a server that silently drops old messages (and cuts a single prompt) to fit
    num_ctx. sticky: an unload request (empty messages, keep_alive 0) leaves the model loaded. down_after: every request
    after that many fails like a server that is not running (ConnectionRefusedError); `down` does so at once."""

    def __init__(self, *replies, model=MODEL, digest=DIGEST_HEX, version=VERSION, context_length=262_144,
                 capabilities=("completion", "tools", "thinking"), ratio=1.25, loaded_ctx=None, chat=None, extra=None,
                 truncating=False, sticky=False, down_after=None):
        self.replies, self.requests, self.loaded = list(replies), [], None
        self.model, self.digest, self.version, self.context_length = model, digest, version, context_length
        self.capabilities, self.ratio, self.loaded_ctx, self.chat, self.extra = capabilities, ratio, loaded_ctx, chat, extra
        self.truncating, self.sticky, self.down_after, self.down = truncating, sticky, down_after, False

    def prompt_tokens(self, body) -> int:
        return math.ceil(proxy_tokens(json.dumps(body["messages"]) + json.dumps(body.get("tools") or [])) * self.ratio)

    def _truncated(self, body) -> int:
        """What a truncating server evaluates: old non-system messages dropped, then the last one cut, to fit num_ctx."""
        num_ctx, messages = body["options"]["num_ctx"], list(body["messages"])
        while self.prompt_tokens({**body, "messages": messages}) > num_ctx and sum(m["role"] != "system" for m in messages) > 1:
            messages.pop(next(i for i, m in enumerate(messages) if m["role"] != "system"))
        return min(self.prompt_tokens({**body, "messages": messages}), num_ctx - 1)

    def __call__(self, method, path, body=None):
        self.requests.append((method, path, body))
        if self.down or (self.down_after is not None and len(self.requests) > self.down_after):
            raise ConnectionRefusedError(61, "Connection refused")
        if path == "/api/chat" and body.get("keep_alive") == 0 and not body.get("messages"):  # Ollama's unload request
            if not self.sticky:
                self.loaded = None
            return 200, {"model": body["model"], "message": {"role": "assistant", "content": ""}, "done": True,
                         "done_reason": "unload"}
        if path == "/api/version":
            return 200, {"version": self.version}
        if path == "/api/tags":
            return 200, {"models": [{"name": self.model, "model": self.model, "digest": self.digest, "size": 5_000_000_000,
                                     "details": {"family": "qwen3", "parameter_size": "1B", "quantization_level": "Q4_K_M"}}]}
        if path == "/api/show":
            if body["model"] != self.model:
                return 404, {"error": f"model '{body['model']}' not found"}
            return 200, {"capabilities": list(self.capabilities), "parameters": "temperature 0.6\ntop_k 20",
                         "details": {"family": "qwen3", "parameter_size": "1B", "quantization_level": "Q4_K_M"},
                         "model_info": {"general.architecture": "qwen3", "qwen3.context_length": self.context_length},
                         **(self.extra or {})}
        if path == "/api/ps":
            models = [] if self.loaded is None else [{"name": self.model, "model": self.model, "digest": self.digest,
                                                     "context_length": self.loaded_ctx or self.loaded}]
            return 200, {"models": models}
        if path == "/api/chat":
            prompt = self.prompt_tokens(body)
            if prompt > body["options"]["num_ctx"]:
                if body.get("truncate") is False and not self.truncating:
                    return 400, {"error": "the input length exceeds the context length"}
                prompt = self._truncated(body)
            self.loaded = body["options"]["num_ctx"]
            if self.chat is not None:
                message = self.chat(body, prompt)
            else:
                message = self.replies.pop(0) if self.replies else reply(content="thinking")
            if isinstance(message, tuple):  # (status, data): a raw answer
                return message
            return 200, {"model": self.model, "message": message, "done": True, "done_reason": "stop",
                         "prompt_eval_count": prompt, "eval_count": 20, "total_duration": 3_000_000_000,
                         "load_duration": 500_000_000, "prompt_eval_duration": 2_000_000_000, "eval_duration": 500_000_000}
        return 404, {"error": f"unknown path {path}"}

    def chats(self):
        return [b for m, p, b in self.requests if p == "/api/chat" and b.get("messages")]

    def unloads(self):
        return [b for m, p, b in self.requests if p == "/api/chat" and not b.get("messages")]


def approved_config(**ollama):
    """eval/llm_methods.json as the user would approve a local model (decision 029); budgets as committed."""
    return {"status": "approved", "note": "test", "provider": "ollama", "model": MODEL, "model_version": DIGEST,
            "temperature": 0, "price_per_mtok": {"input": 0, "output": 0},
            "ollama": {"url": "http://127.0.0.1:11434", "version": VERSION, "num_ctx": 196_608, "num_predict": 8192,
                       "seed": 42, "think": False, "timeout_s": 3600, **ollama},
            "budgets": {"dump_all_proxy_tokens": 120_000, "retrieval_queries": 8, "retrieval_k": 25,
                        "agent_max_tool_calls": 40, "agent_max_proxy_tokens": 120_000, "agent_max_turns": 30}}
