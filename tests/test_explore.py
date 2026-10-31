"""decision 032's exploratory run (eval.explore): the frozen methods with the Gemini adapter on the held-out incidents,
written apart from every formal result and gold judgment, priced per reply and capped. A scripted Gemini stands in for
Vertex AI; nothing reaches the network or spends anything."""

import json
import subprocess

import pytest

import eval.explore as explore
from agent.harness import CallError
from collect.freeze import freeze_sha256
from collect.heldout import FREEZE_FILE
from env.lock import PROJECT_DIR, sha256_path
from eval.runner import load_llm_config
from ollama_fixtures import ANSWER
from test_eval_heldout import heldout_set
from test_gemini import SIG, VERSION, Scripted, api_error, part_call, response

PRICE = {"input": 2.0, "cached_input": 0.1, "output": 10.0}


def config_doc(**over) -> dict:
    doc = {"status": "approved", "decision": "032", "provider": "google-gemini", "endpoint": "gemini-api",
           "model": "gemini-test", "timeout_s": 3600,
           "settings": {"thinking_level": "LOW", "temperature": 0, "seed": 42, "max_output_tokens": 32_768},
           "price_per_mtok": dict(PRICE), "price_changes": [], "cost_ceiling_usd": 100,
           "budgets": load_llm_config(need_client=False)["budgets"]}
    return {**doc, **over}


def answering(request):
    """Does what each method asks: queries, one tool call then a submission, or a submission."""
    names = [d["name"] for t in request["config"].get("tools", []) for d in t["function_declarations"]]
    if "propose_queries" in names:
        return response(part_call("propose_queries", {"queries": [{"text": "error"}, {"text": "payment"}]}, sig=SIG))
    if names == ["submit_diagnosis"]:
        return response(part_call("submit_diagnosis", ANSWER, sig=SIG))
    if any("function_response" in p for c in request["contents"] for p in c["parts"]):
        return response(part_call("submit_diagnosis", ANSWER, sig=SIG))
    return response(part_call("search_spans", {"status": "error", "limit": 5}, sig=SIG))


class Maker:
    """make_model for run_explore: a GeminiModel over `call` (default: answering every request)."""

    def __init__(self, call=None):
        self.call, self.models = call or answering, []

    def __call__(self, config, *, expected_version):
        from agent.gemini import GeminiModel

        s = config["settings"]
        m = GeminiModel(config["model"], call=self.call, thinking_level=s["thinking_level"], temperature=s["temperature"],
                        seed=s["seed"], max_output_tokens=s["max_output_tokens"], expected_version=expected_version,
                        sleep=lambda x: None)
        self.models.append(m)
        return m


def facts(config):
    return {"name": "publishers/google/models/" + config["model"], "version": "001", "display_name": "Test"}


def setting(tmp_path, monkeypatch, **over):
    """The held-out fixture set, registered as the published files, and an approved exploratory config."""
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    monkeypatch.setattr(explore, "FREEZE_SHA256", freeze_sha256(project))
    monkeypatch.setattr(explore, "LIST_SHA256", sha256_path(layout.heldout_incidents_path))
    path = tmp_path / "explore.json"
    path.write_text(json.dumps(config_doc(**over)))
    return project, layout, out, path


def run(layout, out, project, path, method="agent", split="heldout", maker=None, **kw):
    return explore.run_explore(layout, method, split, out, project_dir=project, config_path=path,
                               make_model=maker or Maker(), facts=kw.pop("facts", facts), **kw)


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else []


# ---------------------------------------------------------------- configuration

def test_the_committed_config_is_a_draft_with_the_frozen_budgets():
    config = json.loads(explore.CONFIG.read_text())
    assert config["status"] == "draft" and config["decision"] == "032"
    assert (config["endpoint"], config["model"]) == ("gemini-api", "gemini-4-argon")  # decision 033
    assert explore.config_problems(config, "check") == []  # the free check runs while the config is a draft
    assert config["budgets"] == load_llm_config(need_client=False)["budgets"]
    assert config["settings"]["thinking_level"] == "LOW"  # 032 §3, confirmed after the probe
    assert any("does not allow the probe" in p for p in explore.config_problems(config, "probe"))


def test_each_paid_step_needs_its_status_and_the_run_needs_a_ceiling():
    assert explore.config_problems(config_doc(status="probe", cost_ceiling_usd=None), "probe") == []
    assert any("does not allow the run" in p for p in explore.config_problems(config_doc(status="probe"), "run"))
    assert any("cost_ceiling_usd" in p for p in explore.config_problems(config_doc(cost_ceiling_usd=None), "run"))
    assert explore.config_problems(config_doc(), "run") == []
    budgets = {**config_doc()["budgets"], "agent_max_turns": 31}
    assert any("budgets" in p for p in explore.config_problems(config_doc(budgets=budgets), "run"))
    assert any("price_per_mtok" in p for p in explore.config_problems(config_doc(price_per_mtok={"input": 1}), "probe"))
    bad = config_doc(settings={"thinking_level": "SOME", "temperature": -1, "seed": 0, "max_output_tokens": 0})
    assert len([p for p in explore.config_problems(bad, "run") if p.startswith("settings.")]) == 4
    unset = config_doc(settings={"thinking_level": None, "temperature": None, "seed": None, "max_output_tokens": 32_768})
    assert explore.config_problems(unset, "run") == []  # null: the model's default (032 §3, after the probe)


def test_the_vertex_endpoint_needs_a_project_and_a_location_and_prices_change_by_date():
    assert any("vertex.project" in p for p in explore.config_problems(config_doc(endpoint="vertex"), "run"))
    assert explore.config_problems(config_doc(endpoint="vertex", vertex={"project": "p", "location": "global"}), "run") == []
    assert any("endpoint" in p for p in explore.config_problems(config_doc(endpoint="openai"), "run"))
    later = {"input": 4.0, "cached_input": 0.2, "output": 20.0}
    config = config_doc(price_changes=[{"from": "2026-12-01T00:00:00Z", "price_per_mtok": later}])
    assert explore.config_problems(config, "run") == []
    assert explore.price_at(config, "2026-11-30T23:59:59Z") == PRICE and explore.price_at(config, "2026-12-01T00:00:00Z") == later
    unordered = config_doc(price_changes=[{"from": "2026-12-01T00:00:00Z", "price_per_mtok": later},
                                          {"from": "2026-11-01T00:00:00Z", "price_per_mtok": later}])
    assert any("price_changes" in p for p in explore.config_problems(unordered, "run"))


def test_the_free_check_reads_the_model_and_bills_nothing(tmp_path):
    path = tmp_path / "explore.json"
    path.write_text(json.dumps(config_doc(status="draft", price_per_mtok=None)))
    assert explore.check(config_path=path, facts=facts) == {
        "endpoint": "gemini-api", "model": "gemini-test", "facts": facts(config_doc()), "billed": False}


# ---------------------------------------------------------------- the guard (032 §4)

def test_the_guard_needs_the_published_files_not_the_freeze_check(tmp_path, monkeypatch):
    import collect.freeze as freeze

    project, layout, out, path = setting(tmp_path, monkeypatch)
    monkeypatch.setattr(freeze, "check_freeze", lambda project_dir, run=None: (None, ["code was added after the freeze"]))
    run(layout, out, project, path)  # the branch's added code does not stop it
    assert sorted(p.name for p in (out / "explore-032/heldout/agent").glob("INC-*.json")) == [
        "INC-050.json", "INC-050.transcript.json", "INC-051.json", "INC-051.transcript.json"]
    before = tree(out)
    monkeypatch.setattr(explore, "LIST_SHA256", "sha256:" + "0" * 64)
    with pytest.raises(PermissionError, match="published list"):
        run(layout, out, project, path, method="retrieval")
    monkeypatch.setattr(explore, "FREEZE_SHA256", "sha256:" + "0" * 64)
    with pytest.raises(PermissionError, match="published freeze record"):
        run(layout, out, project, path, method="retrieval")
    assert tree(out) == before


# ---------------------------------------------------------------- run

def test_a_heldout_run_writes_only_under_explore_and_prices_every_reply(tmp_path, monkeypatch):
    project, layout, out, path = setting(tmp_path, monkeypatch)
    for method in ("retrieval", "agent", "dump-all"):
        assert run(layout, out, project, path, method=method) == []
    assert not (out / "heldout").exists()  # the formal results are never written
    root = out / "explore-032"
    for method in ("retrieval", "agent", "dump-all"):
        d = root / "heldout" / method
        config = json.loads((d / "run_config.json").read_text())
        assert config["decision"] == "032" and config["freeze_sha256"] == explore.FREEZE_SHA256
        assert config["gemini"]["thinking_level"] == "LOW" and "cost_ceiling_usd" not in config["gemini"]
        calls = lines(d / "calls.jsonl")
        for inc in ("INC-050", "INC-051"):
            pred = json.loads((d / f"{inc}.json").read_text())
            mine = [c for c in calls if c["incident_id"] == inc]
            assert mine and pred["usage"]["cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in mine))
            assert json.loads((d / f"{inc}.transcript.json").read_text())["usage"]["cost_usd"] == pred["usage"]["cost_usd"]
        assert [e["outcome"] for e in lines(d / "attempts.jsonl") if e["event"] == "end"] == ["ok", "ok"]
    agent_call = lines(root / "heldout/agent/calls.jsonl")[0]
    assert agent_call["cost_usd"] == pytest.approx((1000 * 2.0 + 70 * 10.0) / 1e6)  # answer + thinking as output
    assert json.loads((root / "model_version.json").read_text())["model_version"] == VERSION
    spent = explore.cost_so_far(out)
    maker = Maker()
    run(layout, out, project, path, maker=maker)  # each incident once: nothing left to attempt
    assert maker.models == [] and explore.cost_so_far(out) == spent
    assert set(explore.cost_by_run(out)) == {"heldout/agent", "heldout/dump-all", "heldout/retrieval"}


def test_each_reply_is_priced_at_the_price_of_its_time(tmp_path, monkeypatch):
    later = {"input": 4.0, "cached_input": 0.2, "output": 20.0}
    project, layout, out, path = setting(tmp_path, monkeypatch,
                                         price_changes=[{"from": "2000-01-01T00:00:00Z", "price_per_mtok": later}])
    run(layout, out, project, path, limit=1)
    first = lines(out / "explore-032/heldout/agent/calls.jsonl")[0]
    assert first["cost_usd"] == pytest.approx((1000 * 4.0 + 70 * 20.0) / 1e6)


def test_limit_attempts_only_that_many_incidents_and_a_resumed_run_needs_the_same_settings(tmp_path, monkeypatch):
    project, layout, out, path = setting(tmp_path, monkeypatch)
    assert run(layout, out, project, path, limit=1) == ["INC-051"]
    path.write_text(json.dumps(config_doc(settings={**config_doc()["settings"], "thinking_level": "HIGH"})))
    with pytest.raises(ValueError, match="differs from this run's configuration"):
        run(layout, out, project, path)
    path.write_text(json.dumps(config_doc(cost_ceiling_usd=500)))  # more approved: not a setting of the run
    assert run(layout, out, project, path) == []


def test_api_errors_are_retried_once_and_a_blocked_reply_closes_the_incident_as_a_model_failure(tmp_path, monkeypatch):
    from agent.gemini import CALL_RETRIES

    project, layout, out, path = setting(tmp_path, monkeypatch)
    failing = [api_error(503)] * (CALL_RETRIES + 1)
    script = Scripted(*failing, *failing, response(finish="SAFETY"))
    assert run(layout, out, project, path, maker=Maker(script)) == ["INC-050", "INC-051"]
    events = lines(out / "explore-032/heldout/agent/attempts.jsonl")
    ends = {(e["incident_id"], e["attempt"]): e["outcome"] for e in events if e["event"] == "end"}
    assert ends == {("INC-050", 1): "api_error", ("INC-050", 2): "api_error", ("INC-051", 1): "blocked"}
    blocked = [c for c in lines(out / "explore-032/heldout/agent/calls.jsonl") if c["incident_id"] == "INC-051"]
    assert len(blocked) == 1 and blocked[0]["cost_usd"] > 0  # a blocked reply is still billed and recorded


def test_another_model_version_stops_the_run(tmp_path, monkeypatch):
    from agent.gemini import PIN_MISMATCH

    project, layout, out, path = setting(tmp_path, monkeypatch)
    run(layout, out, project, path, limit=1)

    def other(request):
        return {**answering(request), "model_version": "gemini-test-999"}

    with pytest.raises(CallError) as e:
        run(layout, out, project, path, maker=Maker(other))
    assert e.value.reason == PIN_MISMATCH
    ends = [e for e in lines(out / "explore-032/heldout/agent/attempts.jsonl") if e["event"] == "end"]
    assert ends[-1]["outcome"] == "error" and PIN_MISMATCH in ends[-1]["detail"]


def test_the_cost_ceiling_stops_before_an_attempt_and_after_the_one_that_reaches_it(tmp_path, monkeypatch):
    project, layout, out, path = setting(tmp_path, monkeypatch, cost_ceiling_usd=0.000001)
    with pytest.raises(ValueError, match="reached the approved ceiling"):
        run(layout, out, project, path)
    assert (out / "explore-032/heldout/agent/INC-050.json").exists()  # what was written stands
    assert not (out / "explore-032/heldout/agent/INC-051.json").exists()
    with pytest.raises(ValueError, match="reaches the approved ceiling"):
        run(layout, out, project, path, method="retrieval")
    assert lines(out / "explore-032/heldout/retrieval/attempts.jsonl") == []  # no attempt started


def test_an_unreadable_model_stops_the_run_before_an_attempt(tmp_path, monkeypatch):
    project, layout, out, path = setting(tmp_path, monkeypatch)
    seen = []

    def flaky(config):
        seen.append(1)
        if len(seen) > 1:
            raise ValueError("cannot read gemini-test on Vertex AI: HTTP 401")
        return facts(config)

    with pytest.raises(ValueError, match="401"):
        run(layout, out, project, path, facts=flaky)
    assert lines(out / "explore-032/heldout/agent/attempts.jsonl") == []


def test_a_draft_config_runs_nothing(tmp_path, monkeypatch):
    project, layout, out, path = setting(tmp_path, monkeypatch, status="draft")
    with pytest.raises(ValueError, match="does not allow the run"):
        run(layout, out, project, path)
    assert not out.exists()


def test_the_pilot_runs_with_the_same_rules_and_can_be_moved_aside_for_a_rerun(tmp_path, monkeypatch):
    project, layout, out, path = setting(tmp_path, monkeypatch)
    pairs = [("INC-050", "RG-050"), ("INC-051", "RG-051")]
    monkeypatch.setattr(explore, "incidents_in", lambda layout, split: pairs)
    assert run(layout, out, project, path, split="pilot") == []
    spent = explore.cost_so_far(out)
    moved = explore.archive_pilot(out)
    assert not (out / "explore-032/pilot").exists() and (moved / "agent/INC-050.json").exists()
    assert explore.cost_so_far(out) == spent  # archived replies still count toward the ceiling


# ---------------------------------------------------------------- gold, scoring, compare, gate

def test_gold_worksheets_and_judgments_stay_apart_from_the_formal_ones(tmp_path, monkeypatch):
    project, layout, out, path = setting(tmp_path, monkeypatch)
    run(layout, out, project, path)
    assert [r["incident_id"] for r in explore.gold_todo(layout, "heldout", out, project_dir=project)["incidents"]] == [
        "INC-050", "INC-051"]
    label_dir = layout.label_path("INC-050").parent
    assert (label_dir / explore.TODO_FILE).exists() and not (label_dir / "evidence_gold_todo.json").exists()
    formal = {"gold_version": 1, "incident_id": "INC-050", "items": [
        {"id": "s-" + "a" * 16, "t0": None, "t1": None, "relevant": True, "annotator": "human:t",
         "annotated_at": "2026-10-27T00:00:00Z"}]}
    (label_dir / "evidence_gold.json").write_text(json.dumps(formal))
    sheet = tmp_path / "sheet.json"
    item = {"id": "s-" + "b" * 16, "t0": None, "t1": None, "relevant": False}
    sheet.write_text(json.dumps({"incident_id": "INC-050", "items": [item, {**item, "id": "s-" + "c" * 16, "relevant": None}]}))
    with pytest.raises(ValueError, match="human"):
        explore.gold_add(layout, "INC-050", sheet, annotator="agent:x", now="2026-11-01T00:00:00Z", project_dir=project)
    assert explore.gold_add(layout, "INC-050", sheet, annotator="human:t", now="2026-11-01T00:00:00Z",
                            project_dir=project) == {"added": 1, "unjudged": 1}
    assert json.loads((label_dir / "evidence_gold.json").read_text()) == formal  # untouched
    merged = explore.explore_gold(layout, "INC-050")
    assert [(e["id"], e["relevant"]) for e in merged["items"]] == [("s-" + "a" * 16, True), ("s-" + "b" * 16, False)]
    sheet.write_text(json.dumps({"incident_id": "INC-050", "items": [{**item, "id": "s-" + "a" * 16}]}))
    with pytest.raises(ValueError, match="never judged twice"):
        explore.gold_add(layout, "INC-050", sheet, annotator="human:t", now="2026-11-01T00:00:00Z", project_dir=project)


def test_scoring_runs_the_frozen_scorer_with_the_merged_gold_and_restores_it(tmp_path, monkeypatch):
    import eval.runner as runner

    project, layout, out, path = setting(tmp_path, monkeypatch)
    run(layout, out, project, path)
    asked = []
    real = explore.explore_gold
    monkeypatch.setattr(explore, "explore_gold", lambda layout, inc: asked.append(inc) or real(layout, inc))
    guard, gold = runner.heldout_guard, runner._gold
    result = explore.score(layout, "agent", "heldout", out, project_dir=project)
    assert (runner.heldout_guard, runner._gold) == (guard, gold)  # the frozen module is left as it was
    assert asked == ["INC-050", "INC-051"]
    assert result["aggregate"]["n_incidents"] == 2 and result["heldout"]["freeze_sha256"] == explore.FREEZE_SHA256
    assert result["explore"]["statement"] == explore.EXPLORATORY and result["explore"]["model_versions"] == [VERSION]
    assert result["explore"]["cost_usd"] == pytest.approx(explore.cost_so_far(out))
    table = (out / "explore-032/heldout/agent/table.md").read_text()
    assert table.startswith("> **EXPLORATORY (decision 032), NOT a Gate decision")
    assert "## Model and cost (decision 032" in table and "of which thinking" in table
    assert not (out / "heldout").exists()


def test_compare_and_gate_read_the_formal_baseline_and_never_decide(tmp_path, monkeypatch):
    from eval.runner import run_method, score_method

    project, layout, out, path = setting(tmp_path, monkeypatch)
    run_method(layout, "stat-anomaly", "heldout", out, project_dir=project)  # the formal baseline (fixture freeze passes)
    score_method(layout, "stat-anomaly", "heldout", out, project_dir=project)
    formal = (out / "heldout/stat-anomaly/scores.json").read_bytes()
    run(layout, out, project, path)
    explore.score(layout, "agent", "heldout", out, project_dir=project)
    with pytest.raises(LookupError, match="compare"):
        explore.gate("heldout", out, layout=layout, project_dir=project)
    result = explore.compare("heldout", "agent", "stat-anomaly", out, layout=layout, project_dir=project, resamples=200)
    assert result["b"] == "formal stat-anomaly" and result["paired"]["origin_top1"]["n"] == 2
    gate = explore.gate("heldout", out, layout=layout, project_dir=project)
    assert gate["decision"] is None and gate["kind"] == "exploratory"
    text = (out / "explore-032/heldout/agent/gate.md").read_text()
    assert text.startswith("# The Gate conditions, described: the exploratory agent")
    assert "EXPLORATORY (decision 032)" in text and "on the Pilot" not in text
    assert "Gate decision: PASS" not in text and "Gate decision: NOT PASSED" not in text
    assert (out / "heldout/stat-anomaly/scores.json").read_bytes() == formal  # read only
    assert not (out / "heldout/agent").exists()


# ---------------------------------------------------------------- the synthetic probe

def test_the_probe_runs_the_three_methods_on_the_synthetic_sample_and_writes_nothing(tmp_path):
    path = tmp_path / "explore.json"
    path.write_text(json.dumps(config_doc(status="probe", cost_ceiling_usd=None)))
    before = tree(PROJECT_DIR / "data")
    report = explore.probe(config_path=path, make_model=Maker(), facts=facts)
    assert tree(PROJECT_DIR / "data") == before
    assert set(report["methods"]) == {"dump-all", "retrieval", "agent"}
    assert all(m["valid_prediction"] and m["error"] is None for m in report["methods"].values())
    assert report["model_versions"] == [VERSION] and report["cost_usd_total"] > 0
    assert report["cost_usd_total"] == pytest.approx(sum(m["cost_usd"] for m in report["methods"].values()))
    path.write_text(json.dumps(config_doc(status="draft")))
    with pytest.raises(ValueError, match="does not allow the probe"):
        explore.probe(config_path=path, make_model=Maker(), facts=facts)


def test_the_cli_refuses_every_paid_step_while_the_committed_config_is_a_draft(capsys):
    before = tree(PROJECT_DIR / "data")
    assert explore.main(["run", "--method", "agent", "--set", "heldout"]) == 2
    assert "does not allow the run" in capsys.readouterr().err
    assert explore.main(["probe"]) == 2
    assert "does not allow the probe" in capsys.readouterr().err
    assert tree(PROJECT_DIR / "data") == before
    with pytest.raises(SystemExit):
        explore.main(["run", "--method", "agent"])  # --set is required
    assert "--set" in capsys.readouterr().err


# ---------------------------------------------------------------- the frozen code (032 §4)

def test_the_branch_only_adds_code_files_to_the_published_state():
    """decision 032 §4: on explore/032-argon the code of the published commit (tag heldout-final) is never changed; the
    exploratory run only adds files."""
    from collect.freeze import CODE_DIRS

    tag = subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/tags/heldout-final"], cwd=PROJECT_DIR,
                         capture_output=True, text=True)
    if tag.returncode != 0:
        pytest.skip("the tag heldout-final is not in this clone")
    diff = subprocess.run(["git", "diff", "--name-status", "heldout-final", "--", *CODE_DIRS, "tests"], cwd=PROJECT_DIR,
                          capture_output=True, text=True, check=True).stdout.splitlines()
    changed = [line for line in diff if not line.startswith("A\t")]
    assert changed == [], changed
