"""Agent harness v1 (decision 020): the tool-use loop over decision 019's tools, a checked structured submission,
usage accounting and a transcript. The model is any object with complete(system, messages, tools) -> {content, usage}
(Anthropic Messages API shapes); the real API client is a separate adapter added only after the cost is approved.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from agent.prompt import SYMPTOM_KINDS, SYSTEM, task_prompt
from agent.tools import MAX_SECONDS, TOOL_SPECS, ToolSession
from collect.labels import FAULT_TYPES
from eval.score import check_prediction

MAX_CORRECTIONS = 2


class CallError(Exception):
    """A model.complete call that failed (decision 023 §5). The adapter raises it for API and transport errors only, with
    `reason` taken from the stop reason it saw (HTTP status or error type, never the output content); the method entry
    points set `usage` to what was used before the failure (tokens_in, tokens_out, cost_usd, latency_s) and re-raise.
    It can only come before a prediction is accepted: every method stops calling once one is."""

    def __init__(self, reason: str, detail: str = "", usage: dict | None = None):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail, self.usage = reason, detail, usage


def usage_so_far(tokens: dict, t_start: float, price_per_mtok: dict | None) -> dict:
    cost = None if price_per_mtok is None else (tokens["input"] * price_per_mtok["input"]
                                               + tokens["output"] * price_per_mtok["output"]) / 1e6
    return {"tokens_in": tokens["input"], "tokens_out": tokens["output"], "cost_usd": cost,
            "latency_s": round(time.monotonic() - t_start, 3)}
SUBMIT_NOW = ("You have reached the limit of this investigation. Call submit_diagnosis now with your best answer; "
              "no more tool calls will be answered.")

SUBMIT_SPEC = {
    "name": "submit_diagnosis",
    "description": "Submit the diagnosis (once). It is checked; if it has problems you are told what to fix.",
    "parameters": {
        "type": "object", "additionalProperties": False,
        "required": ["fault", "origin_candidates", "affected_services", "user_symptom", "evidence"],
        "properties": {
            "fault": {"type": "object", "required": ["fault_type", "fault_family"], "properties": {
                "fault_type": {"enum": [*sorted(FAULT_TYPES), None]},
                "fault_family": {"enum": [*sorted(set(FAULT_TYPES.values())), None]}}},
            "origin_candidates": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
            "affected_services": {"type": "array", "items": {"type": "string"}},
            "user_symptom": {"type": "object", "required": ["kinds"],
                             "properties": {"kinds": {"type": "array", "items": {"enum": list(SYMPTOM_KINDS)}}}},
            "evidence": {"type": "array", "items": {"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string"}, "t0": {"type": "number"}, "t1": {"type": "number"}}}},
        },
    },
}


def api_tools() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in (*TOOL_SPECS, SUBMIT_SPEC)]


def _abstain(incident_id: str, method: dict) -> dict:
    return {"prediction_version": 1, "incident_id": incident_id, "method": dict(method),
            "fault": {"fault_type": None, "fault_family": None}, "origin_candidates": [], "affected_services": [],
            "user_symptom": {"kinds": []}, "evidence": []}


def _prediction(answer: dict, incident_id: str, method: dict, start_ns: int, services) -> tuple[dict | None, list[str]]:
    """The submitted answer as a decision-013 prediction (evidence times converted to the data clock), and its problems."""
    try:
        evidence = []
        for e in answer.get("evidence") or []:
            item = {"id": e["id"]}
            for k in ("t0", "t1"):
                if e.get(k) is not None:
                    seconds = float(e[k])
                    if not math.isfinite(seconds) or abs(seconds) > MAX_SECONDS:
                        return None, [f"evidence {e['id']}: {k} must be seconds since the start of the window"]
                    # the model sees milliseconds (the renderer floors to ms): t0 / t1 cover the whole millisecond shown
                    ms_ns = start_ns + round(seconds * 1000) * 1_000_000
                    item[k] = ms_ns if k == "t0" else ms_ns + 999_999
            evidence.append(item)
        pred = {**_abstain(incident_id, method), **{k: answer[k] for k in
                ("fault", "origin_candidates", "affected_services", "user_symptom") if k in answer}, "evidence": evidence}
    except (TypeError, KeyError, ValueError, AttributeError, OverflowError) as e:
        return None, [f"the answer is malformed: {e}"]
    problems = check_prediction({**pred, "usage": {}}, services=services)
    return (None, problems) if problems else (pred, [])


def investigate(snapshot, incident_id: str, model, *, cache_root: Path, method: dict, max_turns: int = 30,
                max_tool_calls: int | None = None, max_proxy_tokens: int | None = None,
                price_per_mtok: dict | None = None) -> tuple[dict, dict]:
    t_start = time.monotonic()
    session = ToolSession(snapshot, cache_root=cache_root, max_calls=max_tool_calls, max_proxy_tokens=max_proxy_tokens)
    tools = api_tools()
    messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": task_prompt(snapshot)}]}]
    tokens = {"input": 0, "output": 0}
    turns, corrections, final_chance, limit_reason, stop, pred = 0, 0, False, None, None, None
    while stop is None:
        try:
            response = model.complete(SYSTEM, messages, tools)
        except CallError as e:
            e.usage = usage_so_far(tokens, t_start, price_per_mtok)
            raise
        turns += 1
        tokens["input"] += response.get("usage", {}).get("input_tokens", 0)
        tokens["output"] += response.get("usage", {}).get("output_tokens", 0)
        content = response["content"]
        messages.append({"role": "assistant", "content": content})
        results: list[dict] = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            if block["name"] == "submit_diagnosis":
                candidate, problems = _prediction(block.get("input") or {}, incident_id, method,
                                                  snapshot.window["start_ns"], snapshot.services)
                if candidate is not None and pred is None:
                    pred = candidate
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "content": "accepted"})
                elif candidate is not None:
                    results.append({"type": "tool_result", "tool_use_id": block["id"],
                                    "content": "ignored: a diagnosis was already accepted"})
                else:
                    corrections += 1
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "is_error": True,
                                    "content": "error: the diagnosis has problems, fix them and submit again: " + "; ".join(problems)})
            elif final_chance:
                results.append({"type": "tool_result", "tool_use_id": block["id"], "is_error": True,
                                "content": "error: no more tool calls; call submit_diagnosis"})
            else:
                results.append({"type": "tool_result", "tool_use_id": block["id"],
                                "content": session.call(block["name"], block.get("input") or {})})
        if pred is not None:
            stop = "submitted_after_limit" if final_chance else "submitted"
        elif corrections > MAX_CORRECTIONS:
            stop = "invalid_submission"
        elif final_chance:
            stop = limit_reason
        else:
            if not results:
                results = [{"type": "text", "text": "Continue: use the tools, or call submit_diagnosis."}]
            messages.append({"role": "user", "content": results})
            if turns >= max_turns or session.exhausted:
                limit_reason = "turn_limit" if turns >= max_turns else "tool_budget"
                messages[-1]["content"].append({"type": "text", "text": SUBMIT_NOW})
                final_chance = True
    if stop in ("submitted", "submitted_after_limit") and messages[-1]["role"] == "assistant":
        messages.append({"role": "user", "content": results})  # the "accepted" result closes the transcript
    pred = pred or _abstain(incident_id, method)
    cost = None if price_per_mtok is None else (tokens["input"] * price_per_mtok["input"]
                                               + tokens["output"] * price_per_mtok["output"]) / 1e6
    pred["usage"] = {"tokens_in": tokens["input"], "tokens_out": tokens["output"],
                     "proxy_tokens": session.usage["proxy_tokens"], "tool_calls": session.usage["tool_calls"],
                     "retrievals": 0, "latency_s": round(time.monotonic() - t_start, 3), "cost_usd": cost}
    transcript = {"incident_id": incident_id, "method": dict(method), "stop_reason": stop, "turns": turns,
                  "corrections": corrections, "messages": messages, "exposure": list(session.exposure), "usage": pred["usage"]}
    return pred, transcript


def submit_round(model, system: str, messages: list[dict], snapshot, incident_id: str, method: dict,
                 tokens: dict) -> tuple[dict | None, str]:
    """One answering step with only submit_diagnosis available (dump-all, retrieval): the model's call is checked;
    problems or a reply without a submission are sent back, at most MAX_CORRECTIONS times (decision 020 §3)."""
    tools = [t for t in api_tools() if t["name"] == "submit_diagnosis"]
    corrections = 0
    while True:
        response = model.complete(system, messages, tools)
        tokens["input"] += response.get("usage", {}).get("input_tokens", 0)
        tokens["output"] += response.get("usage", {}).get("output_tokens", 0)
        messages.append({"role": "assistant", "content": response["content"]})
        pred, reply, problems = None, [], []
        for b in response["content"]:  # every tool_use gets a tool_result (the API rejects the next turn otherwise)
            if b.get("type") != "tool_use":
                continue
            if b.get("name") != "submit_diagnosis":
                content, error = "error: only submit_diagnosis is available now", True
            elif pred is not None:
                content, error = "ignored: a diagnosis was already accepted", False
            else:
                candidate, issues = _prediction(b.get("input") or {}, incident_id, method, snapshot.window["start_ns"],
                                                snapshot.services)
                pred, problems = candidate, problems + issues
                content = "accepted" if candidate else ("error: the diagnosis has problems, fix them and submit again: "
                                                        + "; ".join(issues))
                error = candidate is None
            reply.append({"type": "tool_result", "tool_use_id": b["id"], "content": content, **({"is_error": True} if error else {})})
        if pred is not None:
            messages.append({"role": "user", "content": reply})
            return pred, "submitted"
        reason = "invalid_submission" if reply else "no_submission"
        if not reply:
            reply = [{"type": "text", "text": "Call submit_diagnosis with your answer."}]
        messages.append({"role": "user", "content": reply})
        corrections += 1
        if corrections > MAX_CORRECTIONS:
            return None, reason


def finish(pred: dict | None, incident_id: str, method: dict, tokens: dict, *, proxy: int, tool_calls: int,
           retrievals: int, t_start: float, price_per_mtok: dict | None) -> dict:
    pred = pred or _abstain(incident_id, method)
    cost = None if price_per_mtok is None else (tokens["input"] * price_per_mtok["input"]
                                               + tokens["output"] * price_per_mtok["output"]) / 1e6
    pred["usage"] = {"tokens_in": tokens["input"], "tokens_out": tokens["output"], "proxy_tokens": proxy,
                     "tool_calls": tool_calls, "retrievals": retrievals, "latency_s": round(time.monotonic() - t_start, 3),
                     "cost_usd": cost}
    return pred
