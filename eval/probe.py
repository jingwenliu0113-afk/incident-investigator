"""`python -m eval local-probe` (decision 029): one local Ollama model on the SYNTHETIC sample only, before the user picks
the model for the LLM methods. NOT results.

It runs dump-all, retrieval and the Agent (the real method code, the budgets of eval/llm_methods.json, price 0)
on the synthetic incident and reports per method: tool calls parsed, unparsed or written as text, a valid prediction
submitted or corrections / abstention, tokens, latency and the real-to-proxy token ratio of every call. It also runs the
truncation guard's self-test on generated filler with a tiny context (one long message, and a conversation of several
messages: the server itself must refuse both with a context error, "server"; caught only by the adapter's reply checks
is a GUARD FAILED, the CLI then exits 3), sends one prompt twice (does temperature 0 repeat, and is prompt_eval_count the
whole prompt even when it is cached?) and, when asked, measures prefill / decode speed at given sizes of generated filler
(no incident data). It records the model digest, the Ollama version and the power state it saw, unloads the model at
the end, needs the Mac heavy lock (a local model run is a heavy workload) and writes nothing under data/: the report goes
to stdout or --out.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path

from agent.harness import CallError
from collect.layout import DataLayout
from collect.sample import INCIDENT, SAMPLE_DIR
from env.lock import PROJECT_DIR

BANNER = ("LOCAL MODEL PROBE on the SYNTHETIC sample (decision 029): generated data and one local model. These numbers are "
          "NOT results; they only show whether tool calls parse, whether the context guard holds and how fast the model is.")
FOOTER = ("NOT results: the synthetic incident is small and its fault obvious. Method results come only from the Pilot and "
          "held-out sets, after the user approves a model (decision 029).")
DEFAULT_NUM_CTX_CAP = 65_536  # the synthetic dump-all prompt is ~40k proxy tokens
GUARD_NUM_CTX, GUARD_PROMPT, GUARD_PREDICT = 2_048, 6_000, 16
GUARD_TURNS = 4  # the conversation case: GUARD_TURNS messages of filler, each alone below GUARD_NUM_CTX
REPEAT_PROMPT, REPEAT_PREDICT, REPEAT_FILLER = "Name one animal and one colour in one short sentence.", 64, 2_000
SPEED_PREDICT = 128
CORRECTION_MARKS = ("error: the diagnosis has problems", "Call submit_diagnosis with your answer.")
WORDS = ("amber", "basil", "cedar", "delta", "ember", "fjord", "garnet", "harbor", "indigo", "juniper", "kestrel", "lagoon",
         "maple", "nectar", "orchid", "pebble", "quartz", "raven", "saffron", "tundra", "umber", "violet", "willow", "yarrow",
         "zephyr", "acorn", "birch", "canyon", "dune", "fern", "glacier", "heron")


def filler(size: int, salt: str) -> str:
    """About `size` proxy tokens of neutral words (deterministic per salt, so every size has its own prefix)."""
    head = f"Filler text ({salt}) for a speed measurement. Ignore the words and reply with one short sentence.\n"
    words, used, i = [], len(head.encode()), 0
    while used < size * 4:
        word = WORDS[int.from_bytes(hashlib.blake2b(f"{salt}:{i}".encode(), digest_size=2).digest()) % len(WORDS)]
        words.append(word)
        used, i = used + len(word) + 1, i + 1
    return head + " ".join(words)


def _texts(message: dict) -> list[str]:
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    out = []
    for b in content or []:
        if b.get("type") == "text":
            out.append(b["text"])
        elif b.get("type") == "tool_result":
            out.append(b["content"] if isinstance(b.get("content"), str) else json.dumps(b.get("content")))
        elif b.get("type") == "tool_use":
            out.append(json.dumps(b.get("input")))
        elif b.get("type") == "thinking":
            out.append(b["thinking"])
    return out


def prompt_proxy_tokens(system: str, messages: list[dict], tools: list[dict]) -> int:
    """Proxy tokens of what a call puts in the prompt, as the adapter's guard counts them (agent.ollama.sent_proxy_tokens)."""
    from agent.ollama import sent_proxy_tokens, to_ollama_messages, to_ollama_tools

    return sent_proxy_tokens(to_ollama_messages(system, messages), to_ollama_tools(tools))


def _seconds(ns) -> float | None:
    return None if not isinstance(ns, (int, float)) else round(ns / 1e9, 3)


class Recorder:
    """Wraps the model: what each call sent and got back (proxy vs real tokens, tool calls, timings)."""

    def __init__(self, model, tool_text: re.Pattern):
        self.model, self.tool_text, self.calls = model, tool_text, []

    def complete(self, system, messages, tools):
        sent = prompt_proxy_tokens(system, messages, tools)
        last = messages[-1] if len(messages) > 1 else {}
        correction = last.get("role") == "user" and any(m in t for t in _texts(last) for m in CORRECTION_MARKS)
        t0 = time.monotonic()
        try:
            response = self.model.complete(system, messages, tools)
        except CallError as e:
            self.calls.append({"prompt_proxy_tokens": sent, "correction": correction, "error": e.reason,
                               "guard": getattr(e, "guard", None), "detail": e.detail,
                               "latency_s": round(time.monotonic() - t0, 3)})
            raise
        uses = [b["name"] for b in response["content"] if b["type"] == "tool_use"]
        unparsed = sum("unparsed_arguments" in b for b in response["content"] if b["type"] == "tool_use")
        text = " ".join(b["text"] for b in response["content"] if b["type"] == "text")
        real, o = response["usage"]["input_tokens"], response.get("ollama") or {}
        self.calls.append({"prompt_proxy_tokens": sent, "prompt_eval_count": real,
                           "eval_count": response["usage"]["output_tokens"], "real_per_proxy": round(real / sent, 3),
                           "done_reason": o.get("done_reason"), "tool_uses": uses, "unparsed_tool_calls": unparsed,
                           "text_tool_call": not uses and bool(self.tool_text.search(text)), "correction": correction,
                           "load_s": _seconds(o.get("load_duration")), "prompt_eval_s": _seconds(o.get("prompt_eval_duration")),
                           "eval_s": _seconds(o.get("eval_duration")), "latency_s": round(time.monotonic() - t0, 3)})
        return response


def _tool_text() -> re.Pattern:
    from agent.harness import api_tools
    from baselines.retrieval import PROPOSE_SPEC

    names = [t["name"] for t in api_tools()] + [PROPOSE_SPEC["name"]]
    return re.compile(r"<tool_call>|\"(name|arguments)\"\s*:|\b(" + "|".join(map(re.escape, names)) + r")\b")


def _method(kind: str, snapshot, model, config: dict, cache_root: Path) -> dict:
    from eval.runner import run_llm
    from eval.score import check_prediction

    rec = Recorder(model, _tool_text())
    error, pred, transcript, usage = None, None, None, {}
    try:
        pred, transcript = run_llm(kind, snapshot, INCIDENT, rec, config, cache_root=cache_root)
        usage = pred["usage"]
    except CallError as e:
        error, usage = {"reason": e.reason, "detail": e.detail}, e.usage or {}
    except Exception as e:  # reported, never raised: the probe compares models, one failing method is a finding
        error = {"reason": "exception", "detail": f"{type(e).__name__}: {e}"[:300]}
    stop = transcript["stop_reason"] if transcript else None
    calls, ratios = rec.calls, [c["real_per_proxy"] for c in rec.calls if "real_per_proxy" in c]
    return {"error": error, "stop_reason": stop,
            "valid_prediction": pred is not None and stop in ("submitted", "submitted_after_limit")
            and not check_prediction(pred, services=snapshot.services),
            "abstained": None if pred is None else not pred["origin_candidates"] and pred["fault"]["fault_type"] is None,
            "corrections": sum(c["correction"] for c in calls), "calls": len(calls),
            "tool_calls_parsed": sum(len(c.get("tool_uses", [])) - c.get("unparsed_tool_calls", 0) for c in calls),
            "unparsed_tool_calls": sum(c.get("unparsed_tool_calls", 0) for c in calls),
            "tool_names": sorted({n for c in calls for n in c.get("tool_uses", [])}),
            "text_tool_calls": sum(c.get("text_tool_call", False) for c in calls),
            **{k: usage.get(k) for k in ("tokens_in", "tokens_out", "latency_s", "cost_usd", "proxy_tokens", "tool_calls",
                                         "retrievals")},
            "proxy_to_real": {"first_call": ratios[0] if ratios else None, "min": min(ratios, default=None),
                              "max": max(ratios, default=None)},
            "per_call": calls,
            "prediction": None if pred is None else {k: pred[k] for k in ("fault", "origin_candidates", "affected_services",
                                                                           "user_symptom")}}


def _ask(model, text: str) -> dict:
    return model.complete("", [{"role": "user", "content": [{"type": "text", "text": text}]}], [])


def _guard_case(model, case: str, messages: list[dict]) -> dict:
    out = {"case": case, "num_ctx": GUARD_NUM_CTX, "prompt_proxy_tokens": prompt_proxy_tokens("", messages, [])}
    try:
        response = model.complete("", messages, [])
    except CallError as e:
        return {**out, "raised": True, "reason": e.reason, "guard": getattr(e, "guard", None), "detail": e.detail}
    return {**out, "raised": False, "reason": None, "guard": None,
            "detail": f"a reply came back (prompt_eval_count {response['usage']['input_tokens']}): the guard did not hold"}


def _guard(make) -> dict:
    """The truncation guard on this Ollama (decision 029 §2): prompts far above a tiny num_ctx, as one long message and as
    a conversation of several shorter ones (where a server could drop old messages), must be refused by the server itself
    with a context error (guard "server"); caught only by the adapter's reply checks means truncate: false does not hold."""
    model = make(num_ctx=GUARD_NUM_CTX, num_predict=GUARD_PREDICT, think=False)
    turn = GUARD_PROMPT // GUARD_TURNS
    conversation = []
    for i in range(GUARD_TURNS):
        conversation += [{"role": "user", "content": [{"type": "text", "text": filler(turn, f"guard-{i}")}]},
                         {"role": "assistant", "content": [{"type": "text", "text": "Noted."}]}]
    conversation.append({"role": "user", "content": [{"type": "text", "text": "Reply with one word."}]})
    checks = [_guard_case(model, "one long message",
                          [{"role": "user", "content": [{"type": "text", "text": filler(GUARD_PROMPT, "guard")}]}]),
              _guard_case(model, "several messages", conversation)]
    from agent.ollama import CONTEXT_OVERFLOW

    return {"passed": all(c["reason"] == CONTEXT_OVERFLOW and c["guard"] == "server" for c in checks), "checks": checks}


def _repeat(make) -> dict:
    """The same prompt twice: identical replies at temperature 0, and the same prompt_eval_count although the second
    prompt is cached (the guard and tokens_in need the whole prompt counted, not only its uncached part)."""
    model = make(num_predict=REPEAT_PREDICT)
    prompt = filler(REPEAT_FILLER, "repeat") + "\n\n" + REPEAT_PROMPT
    try:
        replies = [_ask(model, prompt) for _ in range(2)]
    except CallError as e:
        return {"identical": None, "error": e.reason, "guard": getattr(e, "guard", None), "detail": e.detail}
    return {"identical": replies[0]["content"] == replies[1]["content"],
            "prompt_eval_counts": [r["usage"]["input_tokens"] for r in replies], "outputs": [r["content"] for r in replies]}


def _speed(make, sizes, num_ctx: int) -> list[dict]:
    model, out = make(num_predict=SPEED_PREDICT), []
    for size in sizes:
        if size + SPEED_PREDICT > num_ctx:
            out.append({"size_proxy_tokens": size, "skipped": f"larger than num_ctx {num_ctx}"})
            continue
        try:
            response = _ask(model, filler(size, f"speed-{size}"))
        except CallError as e:
            out.append({"size_proxy_tokens": size, "error": e.reason, "detail": e.detail})
            continue
        o = response["ollama"]
        prefill, decode = _seconds(o.get("prompt_eval_duration")), _seconds(o.get("eval_duration"))
        out.append({"size_proxy_tokens": size, "prompt_eval_count": o.get("prompt_eval_count"),
                    "eval_count": o.get("eval_count"), "load_s": _seconds(o.get("load_duration")), "prefill_s": prefill,
                    "decode_s": decode, "total_s": _seconds(o.get("total_duration")),
                    "prefill_tok_s": round(o["prompt_eval_count"] / prefill, 1) if prefill else None,
                    "decode_tok_s": round(o["eval_count"] / decode, 1) if decode and o.get("eval_count") else None})
    return out


def out_problem(path: Path) -> str | None:
    """--out never points under data/ (the probe writes nothing there)."""
    data = str((PROJECT_DIR / "data").resolve()).casefold()
    target = str(Path(path).resolve()).casefold()
    if target == data or target.startswith(data.rstrip("/") + "/"):
        return f"the probe writes nothing under data/ (decision 029): {path}"
    return None


def run_probe(model_tag: str, *, num_ctx: int | None = None, think: bool = False, context_sizes=(), transport=None,
              require_lock=None, sample_root: Path | None = None, config_path: Path | None = None) -> dict:
    import agent.ollama as ollama
    import collect.provenance as provenance
    from collect.snapshot import open_snapshot
    from env.soak import require_heavy_lock
    from eval.demo import check_sample
    from eval.runner import LLM_CONFIG, LLM_METHODS, fit_problems, llm_fit

    (require_lock or require_heavy_lock)(PROJECT_DIR)
    root = Path(sample_root) if sample_root is not None else PROJECT_DIR / SAMPLE_DIR
    manifest = check_sample(root)  # synthetic: true and every file exactly as listed, or ValueError
    if manifest.get("incident_id") != INCIDENT:
        raise ValueError(f"{root} is not the synthetic sample ({INCIDENT}): the probe runs on nothing else (decision 029)")
    config = json.loads(Path(config_path or LLM_CONFIG).read_text())  # its budgets and settings, approved or not: never needs approval
    o, budgets = config.get("ollama") or {}, config["budgets"]
    num_predict, seed = o.get("num_predict") or 8192, o.get("seed") or 42
    temperature = config.get("temperature") if config.get("temperature") is not None else 0
    transport = transport or ollama.default_transport(o.get("url") or ollama.DEFAULT_URL,
                                                      o.get("timeout_s") or ollama.DEFAULT_TIMEOUT_S)
    facts = ollama.server_facts(transport, model_tag)
    if num_ctx is None:
        num_ctx = min(facts["context_length"] or DEFAULT_NUM_CTX_CAP, DEFAULT_NUM_CTX_CAP)
    if problems := ollama.pin_problems(facts, num_ctx=num_ctx):
        raise ValueError("the probe refuses this model (decision 029): " + "; ".join(problems))
    warnings = ollama.capability_problems(facts, think=think) + fit_problems(
        {"ollama": {"num_ctx": num_ctx, "num_predict": num_predict}, "budgets": budgets})

    def make(**kw):
        settings = {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": temperature, "seed": seed,
                    "think": think, **kw}
        return ollama.OllamaModel(model_tag, transport=transport, digest=facts["digest"], **settings)

    try:
        guard = _guard(make)
        for check in guard["checks"]:
            if not (check["reason"] == ollama.CONTEXT_OVERFLOW and check["guard"] == "server"):
                warnings.append(f"GUARD FAILED ({check['case']}): the server did not refuse a prompt above num_ctx "
                                f"(reason {check['reason']}, caught by {check['guard']}: {check['detail']}); "
                                "do not run the LLM methods on this Ollama version")
        layout = DataLayout(root)
        snapshot = open_snapshot(layout.incident_dir(INCIDENT) / "normalized", layout)
        method_config = {"budgets": budgets, "price_per_mtok": {"input": 0, "output": 0}}
        model = make()
        with tempfile.TemporaryDirectory(prefix="ii-local-probe-") as cache:
            methods = {kind: _method(kind, snapshot, model, method_config, Path(cache)) for kind in LLM_METHODS}
        repeat = _repeat(make)
        if repeat["identical"] is False:
            warnings.append("the same prompt gave two different replies at temperature 0 (see repeat_check)")
        counts = repeat.get("prompt_eval_counts") or []
        if repeat.get("guard") in ("count_floor", "count_missing") or (len(counts) == 2 and counts[0] != counts[1]):
            warnings.append("prompt_eval_count of a repeated (cached) prompt is not the whole prompt: Ollama may count only "
                            "uncached tokens, so the context guard and tokens_in cannot rely on it (see repeat_check)")
        speed = _speed(make, context_sizes, num_ctx)
    finally:
        unloaded = ollama.unload(transport, model_tag)
    if unloaded is not None:
        warnings.append(unloaded)
    return {"banner": BANNER, "synthetic": True,
            "sample": {"path": SAMPLE_DIR.as_posix() if root == PROJECT_DIR / SAMPLE_DIR else str(root),
                       "incident_id": INCIDENT, "generator": manifest.get("generator")},
            "ollama": {"version": facts["ollama_version"], "model": model_tag, "digest": facts["digest"],
                       "context_length": facts["context_length"], "capabilities": facts["capabilities"],
                       "details": facts["details"], "parameters": facts["parameters"]},
            "settings": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": temperature, "seed": seed,
                         "think": think, "budgets": budgets},
            "power": provenance.power_facts(),  # read only (pmset, decision 025): speed depends on it
            "warnings": warnings, "fit": llm_fit(budgets, num_ctx, num_predict), "guard_selftest": guard,
            "methods": methods, "repeat_check": repeat, "speed": speed, "unloaded": unloaded is None,
            "config_if_approved": {"provider": "ollama", "model": model_tag, "model_version": facts["digest"],
                                   "price_per_mtok": {"input": 0, "output": 0},
                                   "ollama": {"version": facts["ollama_version"], "num_ctx": num_ctx, "think": think}},
            "footer": FOOTER}
