"""python -m eval.explore — decision 032's exploratory run: the three frozen LLM methods with Gemini on Vertex AI, on the
held-out incidents (and the Pilot, to check the adapter). EXPLORATORY, NOT a Gate decision: 100 and 031 stand.

    python -m eval.explore check                                  # free: the key works, the model is known (033)
    python -m eval.explore probe [--out PATH]                     # the SYNTHETIC sample only (032 §6 step 4)
    python -m eval.explore run --method <m> --set pilot|heldout [--limit N]
    python -m eval.explore score --method <m> --set pilot|heldout
    python -m eval.explore compare --method <m> --against <formal method> --set pilot|heldout
    python -m eval.explore gate --set pilot|heldout                # the three conditions, described, never decided
    python -m eval.explore gold-todo --set pilot|heldout           # blind worksheets of the new citations only
    python -m eval.explore gold-add --incident INC-001 --file <worksheet> --annotator human:<name>
    python -m eval.explore cost                                    # USD spent so far, from every reply recorded
    python -m eval.explore archive-pilot                           # an adapter fix: the Pilot runs again (032 §6 step 6)

What stays frozen (decision 032 §2, §4): this module only adds; it never writes data/external/results/<set>/ (the formal
results), evidence_gold.json or evidence_gold_todo.json, and it does not use the freeze check of decision 023 §6 (which
refuses any added code). Instead every held-out path checks that docs/heldout/freeze.json and heldout_incidents.json are
byte for byte the ones decision 032 registered, and the incident list comes from that file.

- Results: data/external/results/explore-032/<set>/<method>/ (predictions, transcripts, attempts.jsonl with the retry
  rule of decision 023 §5, calls.jsonl with every reply's tokens and cost, run_config.json, scores.json, table.md).
- Model: eval/llm_methods.explore-032.json (status draft: only the free check; probe: also the synthetic probe;
  approved: all). Endpoint (decision 033): the Gemini API with the user's key, or Vertex AI. The budgets must equal those
  of eval/llm_methods.json. Prices are per 1M tokens (input, cached input, output); price_changes date the later ones.
- Cost: cost_usd of a prediction is computed from its replies (cached input and thinking apart); a run stops before an
  attempt once everything recorded under explore-032/ reaches cost_ceiling_usd, and after the attempt that reaches it.
- Pin: the model version of the first reply is written once to explore-032/model_version.json; any other version later
  stops the run (agent.gemini PIN_MISMATCH).
- Scoring is the frozen eval.runner.score_method, run with two inputs swapped (the guard above, and gold = the formal
  judgments plus evidence_gold.explore-032.json); compare and gate read the formal stat-anomaly (and qwen) scores
  read-only and write next to the exploratory scores.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

import eval.runner as runner
from agent.harness import CallError
from collect.layout import DataLayout
from collect.snapshot import open_snapshot
from env.lock import PROJECT_DIR, sha256_path
from eval.runner import (HELDOUT_MAX_ATTEMPTS, LEDGER_USAGE, LLM_METHODS, MAIN_METRICS, RETRYABLE, SCOPES,
                         STATISTICAL_BASELINES, _append, _closed, _json_with_sha, _ledger, _now, incidents_in,
                         method_budgets)
from eval.score import check_prediction

DECISION = "032"
EXPLORE_DIR = "explore-032"
CONFIG = Path(__file__).resolve().parent / "llm_methods.explore-032.json"
FREEZE_SHA256 = "sha256:7d68302545d958c4ba4d787e2d4f6fa558c954ccb27b7369f217b4b14d20cb39"  # 032 §2, as published
LIST_SHA256 = "sha256:e606baae8b8944f1267e6296e7d9784620b952149b12f37e46dc99821a6140b5"
GOLD_FILE = "evidence_gold.explore-032.json"
TODO_FILE = "evidence_gold_todo.explore-032.json"
CALLS_LOG = "calls.jsonl"
PIN_FILE = "model_version.json"
SPLITS = ("pilot", "heldout")
STATUSES = {"draft": ("check",), "probe": ("check", "probe"), "approved": ("check", "probe", "run")}
PRICE_KEYS = ("input", "cached_input", "output")
EXPLORATORY = ("EXPLORATORY (decision 032), NOT a Gate decision: the frozen methods with another model (Gemini), on "
               "incidents whose results were already published. The Gate decision stays the one of decisions 100 and 031 "
               "(NOT PASSED).")


# ---------------------------------------------------------------- configuration

def _price_problem(price, where: str) -> str | None:
    price = price if isinstance(price, dict) else {}
    if any(isinstance(price.get(k), bool) or not isinstance(price.get(k), (int, float)) or price[k] < 0 for k in PRICE_KEYS):
        return f"{where} needs {', '.join(PRICE_KEYS)} in USD per 1M tokens, as the price list shows them"
    return None


def config_problems(config: dict, action: str) -> list[str]:
    """Why `config` cannot be used for `action`: "check" (models.get only, free), "probe" or "run"."""
    import re

    from agent.gemini import ENDPOINTS, PROVIDER, THINKING_LEVELS

    problems = []
    status = config.get("status")
    if action not in STATUSES.get(status, ()):
        problems.append(f"status {status!r} does not allow the {action} (draft: only the free check; probe: also the "
                        "synthetic probe; approved: everything): the user approves each paid step first (decision 032 §6)")
    if config.get("decision") != DECISION:
        problems.append(f"decision must be {DECISION!r}")
    if config.get("provider") != PROVIDER:
        problems.append(f"provider must be {PROVIDER!r}, got {config.get('provider')!r}")
    if config.get("endpoint") not in ENDPOINTS:
        problems.append(f"endpoint must be one of {ENDPOINTS} (decision 033), got {config.get('endpoint')!r}")
    if not isinstance(config.get("model"), str) or not config["model"]:
        problems.append("model must be the model id of the endpoint (e.g. gemini-4-argon)")
    if config.get("endpoint") == "vertex":
        v = config.get("vertex") or {}
        for k in ("project", "location"):
            if not isinstance(v.get(k), str) or not v[k]:
                problems.append(f"vertex.{k} must be set for the Vertex AI endpoint (given by the user; not a credential)")
    t = config.get("timeout_s")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
        problems.append(f"timeout_s must be a positive number, got {t!r}")
    s = config.get("settings") or {}
    if s.get("thinking_level") is not None and s.get("thinking_level") not in THINKING_LEVELS:
        problems.append(f"settings.thinking_level must be one of {THINKING_LEVELS} or null, got {s.get('thinking_level')!r}")
    temperature, seed, out = s.get("temperature"), s.get("seed"), s.get("max_output_tokens")
    if temperature is not None and (isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or temperature < 0):
        problems.append(f"settings.temperature must be a number >= 0 or null, got {temperature!r}")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed <= 0):
        problems.append(f"settings.seed must be a positive integer or null, got {seed!r}")
    if isinstance(out, bool) or not isinstance(out, int) or out <= 0:
        problems.append(f"settings.max_output_tokens must be a positive integer, got {out!r}")
    if action != "check" and (problem := _price_problem(config.get("price_per_mtok"), "price_per_mtok")):
        problems.append(problem)
    changes = config.get("price_changes") or []
    if not isinstance(changes, list) or any(
            not isinstance(c, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(c.get("from")))
            or _price_problem(c.get("price_per_mtok"), "") for c in changes) or [c["from"] for c in changes] != sorted(
            c["from"] for c in changes):
        problems.append("price_changes must list {from: <UTC time>, price_per_mtok: {...}} in time order (decision 033)")
    ceiling = config.get("cost_ceiling_usd")
    if action == "run" and (isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)) or ceiling <= 0):
        problems.append("cost_ceiling_usd must be the total the user approved after the first Pilot incident (032 §6 step 5)")
    frozen = runner.load_llm_config(need_client=False)["budgets"]
    if config.get("budgets") != frozen:
        problems.append("budgets must be exactly those of eval/llm_methods.json (decision 032 §2)")
    return problems


def load_config(action: str, path: Path | None = None) -> dict:
    path = Path(path or CONFIG)
    config = json.loads(path.read_text())
    if problems := config_problems(config, action):
        raise ValueError(f"{path.name} cannot be used for the {action}: " + "; ".join(problems))
    return config


def price_at(config: dict, at: str) -> dict:
    """The prices in force at `at` (a UTC time like the calls' "at"): the last price change at or before it (033)."""
    price = config["price_per_mtok"]
    for change in config.get("price_changes") or []:
        if change["from"] <= at:
            price = change["price_per_mtok"]
    return price


def _connection(config: dict) -> dict:
    v = config.get("vertex") or {}
    return {"project": v.get("project"), "location": v.get("location")} if config["endpoint"] == "vertex" else {}


def runtime(config: dict) -> dict:
    """The settings that define the run (run_config.json): a resumed run must have the same ones. The ceiling is not
    among them (the user may approve more), nor the status."""
    return {"provider": config["provider"], "endpoint": config["endpoint"], "model": config["model"], **_connection(config),
            **config["settings"], "price_per_mtok": config["price_per_mtok"],
            "price_changes": config.get("price_changes") or []}


def cloud_model(config: dict, *, expected_version: str | None):
    from agent.gemini import GeminiModel, sdk_call

    s = config["settings"]
    return GeminiModel(config["model"], call=sdk_call(config["endpoint"], config["timeout_s"], **_connection(config)),
                       thinking_level=s["thinking_level"], temperature=s["temperature"], seed=s["seed"],
                       max_output_tokens=s["max_output_tokens"], expected_version=expected_version)


def cloud_facts(config: dict) -> dict:
    from agent.gemini import sdk_model_facts

    return sdk_model_facts(config["endpoint"], config["model"], **_connection(config))


def check(*, config_path: Path | None = None, facts=None) -> dict:
    """The free check (decision 033): the key or credentials work and the endpoint knows the model (models.get only:
    nothing is generated, nothing is billed)."""
    config = load_config("check", config_path)
    return {"endpoint": config["endpoint"], "model": config["model"], "facts": (facts or cloud_facts)(config),
            "billed": False}


# ---------------------------------------------------------------- the incidents (032 §4)

def explore_guard(layout: DataLayout, project_dir: Path | None, *, need_list: bool = True) -> tuple[dict, dict | None]:
    """In place of eval.runner.heldout_guard (same return shape): the freeze record and the incident list must be the
    published ones, byte for byte; the list is then verified against the files it pins (collect.heldout). Raises
    PermissionError before anything is written."""
    from collect.heldout import FREEZE_FILE, load_heldout_incidents

    if project_dir is None:
        raise PermissionError("the exploratory held-out run needs the project directory to check the freeze record")
    path = Path(project_dir) / FREEZE_FILE
    if not path.exists() or sha256_path(path) != FREEZE_SHA256:
        raise PermissionError(f"{FREEZE_FILE} is not the published freeze record {FREEZE_SHA256} (decision 032 §2)")
    info = {"record": json.loads(path.read_text()), "sha256": FREEZE_SHA256}
    if not need_list:
        return info, None
    listing = layout.heldout_incidents_path
    if not listing.exists() or sha256_path(listing) != LIST_SHA256:
        raise PermissionError(f"heldout_incidents.json is not the published list {LIST_SHA256} (decision 032 §2)")
    return info, {"doc": load_heldout_incidents(layout, freeze_sha=FREEZE_SHA256), "sha256": LIST_SHA256}


def _pairs(layout: DataLayout, split: str, project_dir: Path | None) -> tuple[list[tuple[str, str]], tuple | None]:
    if split not in SPLITS:
        raise ValueError(f"--set must be one of {SPLITS}")
    if split == "heldout":
        freeze, listing = explore_guard(layout, project_dir)
        return [(i["incident_id"], i["run_group_id"]) for i in listing["doc"]["incidents"]], (freeze, listing)
    return incidents_in(layout, "pilot"), None


def explore_root(results_root: Path) -> Path:
    return Path(results_root) / EXPLORE_DIR


# ---------------------------------------------------------------- cost and pin

def _calls(root: Path) -> list[dict]:
    return [json.loads(line) for path in sorted(Path(root).rglob(CALLS_LOG)) for line in path.read_text().splitlines()
            if line.strip()]


def cost_so_far(results_root: Path) -> float:
    """USD of every reply recorded under explore-032/ (archived Pilot runs included)."""
    return round(sum(c["cost_usd"] for c in _calls(explore_root(results_root))), 6)


def cost_by_run(results_root: Path) -> dict:
    """USD and replies of each run directory under explore-032/ (e.g. "pilot/agent", "archive/pilot-…/agent")."""
    root = explore_root(results_root)
    out = {}
    for path in sorted(root.rglob(CALLS_LOG)):
        calls = _calls(path.parent) if path.parent != root else []
        out[path.parent.relative_to(root).as_posix()] = {"cost_usd": round(sum(c["cost_usd"] for c in calls), 6),
                                                         "replies": len(calls)}
    return out


def _record_calls(out_dir: Path, inc: str, attempt: int, model, config: dict) -> float:
    from agent.gemini import call_cost

    total = 0.0
    for call in model.drain():
        cost = call_cost(call, price_at(config, call["at"]))
        total += cost
        _append(out_dir, {"incident_id": inc, "attempt": attempt, **call, "cost_usd": round(cost, 6)}, name=CALLS_LOG)
    return round(total, 6)


def pinned_version(results_root: Path) -> str | None:
    path = explore_root(results_root) / PIN_FILE
    return json.loads(path.read_text())["model_version"] if path.exists() else None


def _pin(results_root: Path, model, config: dict, where: str) -> None:
    from collect.heldout import write_once

    if model.model_version is not None and pinned_version(results_root) is None:
        write_once(explore_root(results_root) / PIN_FILE, {"decision": DECISION, "model": config["model"],
                                                           "model_version": model.model_version, "first": where,
                                                           "at": _now()})


# ---------------------------------------------------------------- run

def run_explore(layout: DataLayout, method: str, split: str, results_root: Path, *, project_dir: Path | None = None,
                limit: int | None = None, config_path: Path | None = None, make_model=None, facts=None) -> list[str]:
    """Each incident of `split` once per method, with the retry rule of decision 023 §5 (an API or transport error: at
    most HELDOUT_MAX_ATTEMPTS attempts in all) on both sets; a blocked prompt or reply closes the incident as a model
    failure (an abstention when scored) and the run goes on. `limit`: at most that many incidents are attempted now.
    Returns the incidents of the set still without a prediction."""
    import os
    import secrets

    from agent.gemini import BLOCKED
    from collect.faults import write_atomic
    from collect.heldout import write_once
    from eval.runner import run_llm

    if method not in LLM_METHODS:
        raise ValueError(f"only the LLM methods run in decision 032 ({', '.join(LLM_METHODS)}); stat-anomaly is read from "
                         "the formal results")
    config = load_config("run", config_path)
    pairs, held = _pairs(layout, split, project_dir)
    make_model, facts = make_model or cloud_model, facts or cloud_facts
    facts(config)  # the model can be read before anything is written (ValueError)
    out_dir = explore_root(results_root) / split / method
    out_dir.mkdir(parents=True, exist_ok=True)
    lock = out_dir / "run.lock"
    token = secrets.token_hex(8)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise FileExistsError(f"{lock} exists: another exploratory run of {method} is going or was killed; a person checks "
                              "it and removes the lock") from None
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"pid": os.getpid(), "token": token, "started_at": _now()}) + "\n")
    try:
        run_config = {"decision": DECISION, "method": method, "split": split, "model": config["model"],
                      "budgets": method_budgets(method, config), "scope": SCOPES[method],
                      **({"freeze_sha256": held[0]["sha256"], "heldout_incidents_sha256": held[1]["sha256"]} if held else {}),
                      "gemini": runtime(config)}
        path = out_dir / "run_config.json"
        if path.exists():
            if json.loads(path.read_text()) != run_config:
                raise ValueError(f"{path} differs from this run's configuration: a resumed run is the same run "
                                 "(decision 032 §1: the settings are registered before the run)")
        else:
            write_once(path, run_config)
        ceiling, method_config = config["cost_ceiling_usd"], {**config, "price_per_mtok": None}
        ledger, attempted = _ledger(out_dir), 0
        for inc, _ in pairs:
            pred_path, transcript_path = out_dir / f"{inc}.json", out_dir / f"{inc}.transcript.json"
            events = ledger.get(inc, [])
            if pred_path.exists() or _closed(events):
                continue
            if limit is not None and attempted >= limit:
                break
            attempted += 1
            snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
            attempt = len({e["attempt"] for e in events if e["event"] == "start"})
            while attempt < HELDOUT_MAX_ATTEMPTS:
                facts(config)  # before the attempt starts: unreadable model or credentials stop the run, no attempt used
                if (spent := cost_so_far(results_root)) >= ceiling:
                    raise ValueError(f"USD {spent:.2f} recorded under {EXPLORE_DIR}/ reaches the approved ceiling "
                                     f"{ceiling:.2f}: the run stops before {inc}'s attempt (decision 032 §6 step 5); "
                                     "more needs the user's approval")
                model = make_model(config, expected_version=pinned_version(results_root))
                attempt += 1
                _append(out_dir, {"incident_id": inc, "attempt": attempt, "event": "start", "at": _now()})

                def end(outcome: str, detail: str = "", usage: dict | None = None) -> None:
                    _append(out_dir, {"incident_id": inc, "attempt": attempt, "event": "end", "outcome": outcome,
                                      "detail": detail[:300], "usage": usage, "at": _now()})

                try:
                    out = run_llm(method, snapshot, inc, model, method_config,
                                  cache_root=Path(snapshot.path).parents[2] / "cache")
                except CallError as e:
                    usage = {**{k: (e.usage or {}).get(k) for k in LEDGER_USAGE},
                             "cost_usd": _record_calls(out_dir, inc, attempt, model, config)}
                    _pin(results_root, model, config, f"{split}/{method}/{inc}")
                    if e.reason in RETRYABLE:
                        end(e.reason, e.detail, usage)
                        continue
                    if e.reason == BLOCKED:  # 032 §3: a model failure (no_answer), never retried; the run goes on
                        end(BLOCKED, e.detail, usage)
                        break
                    end("error", f"CallError {e.reason}: {e.detail}", usage)
                    raise
                except Exception as e:
                    end("error", f"{type(e).__name__}: {e}", {"cost_usd": _record_calls(out_dir, inc, attempt, model, config)})
                    raise
                pred, transcript = out
                pred["usage"]["cost_usd"] = _record_calls(out_dir, inc, attempt, model, config)
                transcript["usage"] = pred["usage"]
                _pin(results_root, model, config, f"{split}/{method}/{inc}")
                usage = {k: pred["usage"].get(k) for k in LEDGER_USAGE}
                if problems := check_prediction(pred):
                    end("invalid_prediction", "; ".join(problems[:5]), usage)
                    raise ValueError(f"{method} wrote an invalid prediction for {inc}: {problems[:5]}")
                for target in (transcript_path, pred_path):
                    if target.exists():
                        raise FileExistsError(f"{target} exists: a prediction is never overwritten")
                write_atomic(transcript_path, transcript)
                write_atomic(pred_path, pred)  # last: the prediction file alone marks a complete attempt
                end("ok", usage=usage)
                break
            if (spent := cost_so_far(results_root)) >= ceiling:
                raise ValueError(f"USD {spent:.2f} recorded under {EXPLORE_DIR}/ reached the approved ceiling {ceiling:.2f} "
                                 f"after {inc}: what was written stands and the run stops (decision 032 §6 step 5)")
        return [inc for inc, _ in pairs if not (out_dir / f"{inc}.json").exists()]
    finally:
        try:
            if json.loads(lock.read_text()).get("token") == token:
                lock.unlink()
        except (OSError, ValueError):
            pass


def archive_pilot(results_root: Path) -> Path:
    """decision 032 §6 step 6: after an adapter fix the whole Pilot runs again; the old one is moved aside, never deleted
    (its replies still count toward the ceiling)."""
    src = explore_root(results_root) / "pilot"
    if not src.exists():
        raise LookupError(f"{src} does not exist: nothing to archive")
    if any(src.rglob("run.lock")):
        raise FileExistsError(f"a run.lock under {src}: a Pilot run is going or was killed")
    dst = explore_root(results_root) / "archive" / f"pilot-{_now().replace(':', '')}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return dst


# ---------------------------------------------------------------- gold (032 §5)

def _formal_gold(layout: DataLayout, inc: str) -> dict | None:
    path = runner._gold_path(layout, inc)
    return json.loads(path.read_text()) if path.exists() else None


def _explore_gold_path(layout: DataLayout, inc: str) -> Path:
    return layout.label_path(inc).with_name(GOLD_FILE)


def explore_gold(layout: DataLayout, inc: str) -> dict | None:
    """The formal judgments plus decision 032's (never the same citation twice)."""
    from eval.relevance import key

    formal = _formal_gold(layout, inc)
    path = _explore_gold_path(layout, inc)
    if not path.exists():
        return formal
    extra = json.loads(path.read_text())
    if both := {key(e) for e in (formal or {}).get("items", [])} & {key(e) for e in extra["items"]}:
        raise ValueError(f"{inc}: {len(both)} citation(s) judged in both evidence_gold.json and {GOLD_FILE}")
    return {"gold_version": 1, "incident_id": inc, "items": [*(formal or {}).get("items", []), *extra["items"]]}


def gold_todo(layout: DataLayout, split: str, results_root: Path, *, project_dir: Path | None = None) -> dict:
    """Blind worksheets (decision 017 §3) of the exploratory predictions' sampled citations that nobody judged yet, in
    TODO_FILE beside the label; the formal worksheet is never touched."""
    from collect.review import effective_label
    from collect.snapshot import _rel
    from eval.relevance import _ns, gold_sample, key, resolved_unique

    pairs, _ = _pairs(layout, split, project_dir)
    rows = []
    for inc, _ in pairs:
        snapshot = open_snapshot(layout.incident_dir(inc) / "normalized", layout)
        cited = {}
        for path in sorted((explore_root(results_root) / split).glob(f"*/{inc}.json")):
            pred = json.loads(path.read_text())
            cited[pred["method"]["name"]] = [{"id": k[0], "t0": k[1], "t1": k[2]}
                                             for k, _ in resolved_unique(pred["evidence"], snapshot)]
        gold = explore_gold(layout, inc)
        todo = gold_sample(inc, cited, annotated={key(e) for e in (gold or {}).get("items", [])})
        label = effective_label(layout, inc)[0]
        start, offset = snapshot.window["start_ns"], runner._clock_offset(layout, inc)
        sheet = {"incident_id": inc,
                 "how_to": "set relevant to true or false for each item (decision 017 §3), leave null to judge later, "
                           "then: python -m eval.explore gold-add --incident <INC> --file <this file> --annotator human:<name>",
                 "context": {"fault_type": label["injected_fault"]["fault_type"], "origin_service": label["origin_service"],
                             "affected_services": label["affected_services"],
                             "fault": [_rel(_ns(label["fault_start"], offset), start), _rel(_ns(label["fault_end"], offset), start)]},
                 "items": [{**e, "record": runner._render(snapshot, e), "relevant": None} for e in todo]}
        todo_path = layout.label_path(inc).with_name(TODO_FILE)
        if todo_path.exists():  # judgments typed into the old sheet but not added yet are never wiped
            done = {key(e) for e in (gold or {}).get("items", [])}
            pending = [e for e in json.loads(todo_path.read_text()).get("items", [])
                       if e.get("relevant") is not None and key(e) not in done]
            if pending:
                raise ValueError(f"{todo_path} has {len(pending)} judgments not merged yet: run "
                                 f"`python -m eval.explore gold-add --incident {inc} ...` first")
        todo_path.write_text(json.dumps(sheet, indent=2) + "\n")
        rows.append({"incident_id": inc, "to_judge": len(todo)})
    return {"split": split, "incidents": rows}


def gold_add(layout: DataLayout, incident_id: str, sheet_path: Path, *, annotator: str, now: str,
             project_dir: Path | None = None) -> dict:
    """Merge a filled worksheet into GOLD_FILE (append-only; a person's judgments only)."""
    from eval.relevance import check_gold, key, merge_gold

    split = "heldout" if runner._is_heldout_incident(layout, incident_id) else "pilot"
    if incident_id not in {inc for inc, _ in _pairs(layout, split, project_dir)[0]}:
        raise PermissionError(f"{incident_id} is not an incident of the exploratory {split} set: no gold judgment")
    sheet = json.loads(Path(sheet_path).read_text())
    if sheet.get("incident_id") != incident_id:
        raise ValueError(f"the worksheet belongs to {sheet.get('incident_id')}, not {incident_id}")
    judged = [e for e in sheet["items"] if e.get("relevant") is not None]
    formal = {key(e) for e in (_formal_gold(layout, incident_id) or {}).get("items", [])}
    if again := [e["id"] for e in judged if key(e) in formal]:
        raise ValueError(f"already judged in evidence_gold.json, never judged twice: {again[:5]}")
    path = _explore_gold_path(layout, incident_id)
    before = json.loads(path.read_text()) if path.exists() else None
    doc = merge_gold(before, incident_id, judged, annotator=annotator, now=now)
    if problems := check_gold(doc):
        raise ValueError(f"{GOLD_FILE} would be invalid: {problems[:5]}")
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return {"added": len(doc["items"]) - len((before or {}).get("items", [])), "unjudged": len(sheet["items"]) - len(judged)}


# ---------------------------------------------------------------- scoring, compare, gate

@contextmanager
def _frozen_scoring():
    """The frozen scorer with the two inputs that name the formal set swapped: the guard and the gold judgments."""
    saved = runner.heldout_guard, runner._gold
    runner.heldout_guard, runner._gold = explore_guard, explore_gold
    try:
        yield
    finally:
        runner.heldout_guard, runner._gold = saved


def score(layout: DataLayout, method: str, split: str, results_root: Path, *, project_dir: Path | None = None) -> dict:
    root = explore_root(results_root)
    out_dir = root / split / method
    if split == "pilot" and (missing := [inc for inc, _ in incidents_in(layout, "pilot")
                                         if not (out_dir / f"{inc}.json").exists()]):
        raise LookupError(f"Pilot incidents without a prediction: {missing} (the Pilot checks the adapter; run them, or "
                          "report why they cannot be)")
    with _frozen_scoring():
        result = runner.score_method(layout, method, split, root, project_dir=project_dir)
    calls = _calls(out_dir)
    totals = {k: sum(c[k] for c in calls) for k in ("prompt", "cached", "candidates", "thoughts")}
    result["explore"] = {"decision": DECISION, "statement": EXPLORATORY, "model_versions": sorted({c["model_version"] for c in calls
                                                                                                  if c.get("model_version")}),
                         "calls": len(calls), "tokens": totals, "cost_usd": round(sum(c["cost_usd"] for c in calls), 6)}
    (out_dir / "scores.json").write_text(json.dumps(result, indent=2) + "\n")
    table = (out_dir / "table.md").read_text()
    (out_dir / "table.md").write_text(_banner(result["run_config"]) + table + _explore_lines(result))
    return result


def _banner(run_config: dict) -> str:
    g = run_config["gemini"]
    return (f"> **{EXPLORATORY}**\n>\n> Model: {g['provider']} {g['model']}, thinking {g['thinking_level']}, temperature "
            f"{g['temperature']}, seed {g['seed']}, max_output_tokens {g['max_output_tokens']} (decision 032 §3).\n\n")


def _explore_lines(result: dict) -> str:
    e, g = result["explore"], result["run_config"]["gemini"]
    p, t = g["price_per_mtok"], e["tokens"]
    changes = "".join(f"; from {c['from']}: input {c['price_per_mtok']['input']}, cached input "
                      f"{c['price_per_mtok']['cached_input']}, output {c['price_per_mtok']['output']}"
                      for c in g.get("price_changes") or [])
    return "\n".join([
        "", "## Model and cost (decision 032; reported, never scored)", "",
        f"Model: {g['provider']} {g['model']} through {g['endpoint']}; versions seen: {', '.join(e['model_versions']) or '-'}.",
        f"Settings: thinking {g['thinking_level']}, temperature {g['temperature']}, seed {g['seed']}, max_output_tokens "
        f"{g['max_output_tokens']}.",
        f"Prices (USD per 1M tokens, each reply at the price of its time): input {p['input']}, cached input "
        f"{p['cached_input']}, output {p['output']}{changes}.",
        f"Replies: {e['calls']} (failed attempts included); prompt tokens {t['prompt']:,} of which cached {t['cached']:,}; "
        f"output tokens {t['candidates'] + t['thoughts']:,} of which thinking {t['thoughts']:,}; cost USD {e['cost_usd']:.2f}.",
        "Tokens and latency are not comparable with the formal run (another tokenizer; network and cloud instead of the "
        "local GPU); proxy tokens are.", ""])


def _formal_scores(results_root: Path, split: str, method: str) -> tuple[dict, str]:
    found = _json_with_sha(Path(results_root) / split / method / "scores.json")
    if found is None:
        raise LookupError(f"the formal {method} has no scores on the {split} set")
    return found


def _check_held(doc: dict, name: str, split: str) -> None:
    if split != "heldout":
        return
    held = doc.get("heldout") or {}
    if (held.get("freeze_sha256"), held.get("heldout_incidents_sha256")) != (FREEZE_SHA256, LIST_SHA256):
        raise PermissionError(f"{name}'s held-out scores are not of the published freeze record and incident list")


def compare(split: str, method: str, against: str, results_root: Path, *, layout: DataLayout,
            project_dir: Path | None = None, resamples: int = 10_000) -> dict:
    """Paired differences exploratory `method` - formal `against` (decision 023 §7's bootstrap), written to
    explore-032/<set>/compare-<method>-vs-formal-<against>.json / .md."""
    from eval.compare import lofo, paired

    if split == "heldout":
        explore_guard(layout, project_dir)
    root = explore_root(results_root)
    found = _json_with_sha(root / split / method / "scores.json")
    if found is None:
        raise LookupError(f"the exploratory {method} has no scores on the {split} set: `python -m eval.explore score`")
    (a_doc, a_sha), (b_doc, b_sha) = found, _formal_scores(results_root, split, against)
    _check_held(a_doc, f"exploratory {method}", split)
    _check_held(b_doc, f"formal {against}", split)
    a, b = a_doc["incidents"], b_doc["incidents"]
    result = {"decision": DECISION, "statement": EXPLORATORY, "split": split, "a": method, "b": f"formal {against}",
              "scores_sha256": {method: a_sha, f"formal {against}": b_sha},
              "paired": {m: paired(a, b, m, resamples=resamples) for m in MAIN_METRICS},
              "lofo": {m: lofo(a, b, m, resamples=resamples) for m in MAIN_METRICS}}
    base = root / split / f"compare-{method}-vs-formal-{against}"
    base.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [f"# {method} (Gemini, decision 032) - formal {against} on the {split} set", "", f"**{EXPLORATORY}**", "",
             "| metric | n | mean difference | 95% interval |", "|---|---:|---:|---|"]
    lines += [f"| {m} | {r['n']} | {r['mean_diff']:.3f} | [{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}] |"
              for m, r in result["paired"].items()]
    base.with_suffix(".md").write_text("\n".join(lines) + "\n")
    return result


def gate(split: str, results_root: Path, *, layout: DataLayout, project_dir: Path | None = None) -> dict:
    """The three conditions of decision 023 §7 computed as eval.runner.gate_methods does, for the exploratory agent
    against the formal statistical baselines; `decision` is always null (032 §1). Writes explore-032/<set>/agent/gate.*"""
    from collect.faults import write_atomic
    from eval.gate import (GATE_METRIC, PILOT_MIN_K, condition_1, condition_2, condition_3, coverage, fault_directions)

    method, listing = runner.GATE_METHOD, None
    if split == "heldout":
        listing = explore_guard(layout, project_dir)[1]
    root = explore_root(results_root)
    found = _json_with_sha(root / split / method / "scores.json")
    if found is None:
        raise LookupError(f"the exploratory {method} has no scores on the {split} set")
    _check_held(found[0], f"exploratory {method}", split)
    docs = {method: found}
    for b in STATISTICAL_BASELINES:
        docs[b] = _formal_scores(results_root, split, b)
        _check_held(docs[b][0], f"formal {b}", split)
    compares = {}
    for b in STATISTICAL_BASELINES:
        doc = _json_with_sha(root / split / f"compare-{method}-vs-formal-{b}.json")
        if doc is None or doc[0].get("scores_sha256") != {method: docs[method][1], f"formal {b}": docs[b][1]}:
            raise LookupError(f"run `python -m eval.explore compare --method {method} --against {b} --set {split}` first "
                              "(from the current scores)")
        compares[b] = doc[0]
    rows = docs[method][0]["incidents"]
    tables = {m: runner.fault_table(split, d["incidents"], listing["doc"] if listing else None) for m, (d, _) in docs.items()}
    k_of = {f: v["k"] for f, v in tables[method]["faults"].items() if v["n"]}
    design_k = {m: {f: v["k"] for f, v in t["faults"].items()} for m, t in tables.items()}
    c1, c2, c3 = condition_1(compares), condition_2(rows, k_of, min_k=1 if listing else PILOT_MIN_K), condition_3(rows)
    result = {"gate_version": 1, "split": split, "method": method, "baselines": list(STATISTICAL_BASELINES),
              "kind": "exploratory", "statement": EXPLORATORY, "all_met": bool(c1["met"] and c2["met"] and c3["met"]),
              "decision": None, "conditions": {"1": c1, "2": c2, "3": c3},
              "descriptive": {
                  "coverage": coverage(rows),
                  "paired_other_metrics": {b: {m: v for m, v in compares[b]["paired"].items() if m != GATE_METRIC}
                                           for b in STATISTICAL_BASELINES},
                  "lofo": {b: (compares[b].get("lofo") or {}).get(GATE_METRIC) for b in STATISTICAL_BASELINES},
                  "fault_directions": {b: fault_directions(rows, docs[b][0]["incidents"], design_k[method], design_k[b])
                                       for b in STATISTICAL_BASELINES},
                  "per_fault": tables},
              "inputs": {"scores_sha256": {(m if m == method else f"formal {m}"): sha for m, (_, sha) in docs.items()}}}
    title = f"# Gate: {method} on the {split} set (SPEC Gate, decision 023 §7)"
    text = runner._gate_md(result).replace(runner._outcome(result), _outcome(result)).replace(
        title, f"# The Gate conditions, described: the exploratory {method} on the {split} set (decision 032; the "
               "conditions of decision 023 §7)", 1)
    write_atomic(root / split / method / "gate.md", text.encode())
    write_atomic(root / split / method / "gate.json", (json.dumps(result, indent=2) + "\n").encode())
    return result


def _outcome(result: dict) -> str:
    return (f"All three conditions met: {'yes' if result['all_met'] else 'no'} (EXPLORATORY, decision 032; NOT a Gate "
            "decision).")


# ---------------------------------------------------------------- the synthetic probe (032 §6 step 4)

def probe(*, config_path: Path | None = None, sample_root: Path | None = None, make_model=None, facts=None) -> dict:
    """The three methods once each on the SYNTHETIC sample: does the adapter work, are the settings accepted, what do
    the replies cost. Writes nothing under data/ (the caller prints it or writes --out elsewhere)."""
    import tempfile

    from agent.gemini import call_cost
    from collect.sample import INCIDENT, SAMPLE_DIR
    from eval.demo import check_sample
    from eval.probe import _method

    config = load_config("probe", config_path)
    root = Path(sample_root) if sample_root is not None else PROJECT_DIR / SAMPLE_DIR
    if check_sample(root).get("incident_id") != INCIDENT:
        raise ValueError(f"{root} is not the synthetic sample ({INCIDENT}): the probe runs on nothing else")
    make_model, facts = make_model or cloud_model, facts or cloud_facts
    seen = facts(config)
    layout = DataLayout(root)
    snapshot = open_snapshot(layout.incident_dir(INCIDENT) / "normalized", layout)
    model = make_model(config, expected_version=None)
    methods = {}
    with tempfile.TemporaryDirectory(prefix="ii-explore-probe-") as cache:
        for kind in LLM_METHODS:
            methods[kind] = _method(kind, snapshot, model, {"budgets": config["budgets"], "price_per_mtok": None}, Path(cache))
            calls = model.drain()
            methods[kind]["gemini_calls"] = calls
            methods[kind]["cost_usd"] = round(sum(call_cost(c, price_at(config, c["at"])) for c in calls), 6)
    versions = sorted({c["model_version"] for m in methods.values() for c in m["gemini_calls"] if c.get("model_version")})
    return {"decision": DECISION, "synthetic": True, "statement": "a probe on the synthetic sample, not a result",
            "model": config["model"], "model_facts": seen, "model_versions": versions, "settings": config["settings"],
            "price_per_mtok": config["price_per_mtok"], "price_changes": config.get("price_changes") or [],
            "methods": methods,
            "cost_usd_total": round(sum(m["cost_usd"] for m in methods.values()), 6)}


# ---------------------------------------------------------------- CLI

def main(argv: Sequence[str] | None = None) -> int:
    from datetime import UTC, datetime

    parser = argparse.ArgumentParser(prog="python -m eval.explore", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check", "probe", "run", "score", "compare", "gate", "gold-todo", "gold-add", "cost",
                                            "archive-pilot"])
    parser.add_argument("--method", choices=LLM_METHODS)
    parser.add_argument("--against", choices=sorted(runner.METHODS), help="compare: a formal method (read only)")
    parser.add_argument("--set", dest="split", choices=SPLITS)
    parser.add_argument("--limit", type=int, help="run: attempt at most this many incidents now")
    parser.add_argument("--incident")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--annotator")
    parser.add_argument("--out", type=Path, help="probe: write the JSON report here (never under data/)")
    ns = parser.parse_args(argv)
    needs = {"run": ("method", "split"), "score": ("method", "split"), "compare": ("method", "against", "split"),
             "gate": ("split",), "gold-todo": ("split",), "gold-add": ("incident", "file", "annotator")}
    if missing := [k for k in needs.get(ns.command, ()) if getattr(ns, k) is None]:
        parser.error(f"{ns.command} needs " + ", ".join(f"--{k.replace('split', 'set')}" for k in missing))
    layout = DataLayout(PROJECT_DIR / "data/external")
    results = PROJECT_DIR / "data/external/results"
    try:
        if ns.command == "check":
            print(json.dumps(check(), indent=2))
        elif ns.command == "probe":
            from eval.probe import out_problem

            if ns.out is not None and (problem := out_problem(ns.out)):
                raise ValueError(problem)
            text = json.dumps(probe(), indent=2)
            if ns.out is None:
                print(text)
            else:
                ns.out.write_text(text + "\n")
                print(f"written: {ns.out}")
        elif ns.command == "run":
            left = run_explore(layout, ns.method, ns.split, results, project_dir=PROJECT_DIR, limit=ns.limit)
            print(json.dumps({"without_prediction": left, "cost_usd_so_far": cost_so_far(results)}, indent=2))
        elif ns.command == "score":
            result = score(layout, ns.method, ns.split, results, project_dir=PROJECT_DIR)
            print(json.dumps({"aggregate": result["aggregate"], "evidence": result["evidence"],
                              "explore": result["explore"]}, indent=2))
        elif ns.command == "compare":
            print(json.dumps(compare(ns.split, ns.method, ns.against, results, layout=layout,
                                     project_dir=PROJECT_DIR)["paired"], indent=2))
        elif ns.command == "gate":
            result = gate(ns.split, results, layout=layout, project_dir=PROJECT_DIR)
            print(result["statement"] + "\n" + _outcome(result))
        elif ns.command == "gold-todo":
            print(json.dumps(gold_todo(layout, ns.split, results, project_dir=PROJECT_DIR), indent=2))
        elif ns.command == "gold-add":
            print(json.dumps(gold_add(layout, ns.incident, ns.file, annotator=ns.annotator,
                                      now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), project_dir=PROJECT_DIR)))
        elif ns.command == "cost":
            print(json.dumps({"cost_usd": cost_so_far(results), "by_run": cost_by_run(results),
                              "pinned_version": pinned_version(results)}, indent=2))
        elif ns.command == "archive-pilot":
            print(f"moved to {archive_pilot(results)}")
    except (ValueError, OSError, LookupError, RuntimeError, CallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
