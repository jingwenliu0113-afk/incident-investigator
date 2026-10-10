"""Running a method over one set and scoring it (SPEC Core §7–§10; decisions 013, 014)."""

import json

import pytest

from collect.layout import DataLayout
from collect.normalize import NormalizeInputs, normalize
from collect.policy import load_policy
from collect.rawfile import scan_raw_file
from eval.runner import METHODS, audit_set, incidents_in, run_method, score_method
from normalize_fixtures import HOST_END, HOST_START, write_raw
from test_records import injection

LABEL = {"label_version": 1, "incident_id": "INC-001", "run_group_id": "RG-001", "fault_family": "error",
         "injected_fault": {"fault_type": "error_response", "flag": "paymentFailure", "variant": "100%"},
         "origin_service": "payment", "affected_services": ["payment", "checkout"],
         "user_symptom": {"kinds": ["errors"]}, "fault_start": "2026-10-08T11:50:00Z", "fault_end": "2026-10-08T11:55:00Z",
         "traffic_profile": "locust-upstream-3.1.0", "seed": 42,
         "labeling": {"method": "catalog", "labeled_at": "2026-10-08T13:00:00Z", "labeler": "agent:test"}}


def stored(root, split="pilot", inc="INC-001", rg="RG-001"):
    layout = DataLayout(root)
    files = write_raw(layout.raw_dir(rg))
    scans = {sig: scan_raw_file(p, sig) for sig, p in files.items()}
    inputs = NormalizeInputs(raw_dir=layout.raw_dir(rg), raw_sha256={k: v["sha256"] for k, v in scans.items()},
                             raw_duplicates={k: v["duplicates"] for k, v in scans.items()},
                             window_host=(HOST_START, HOST_END), clock_offsets=[0.0, 0.0])
    normalize(inputs, load_policy(), incident_dir=layout.incident_dir(inc), report_path=layout.normalize_report_path(inc),
              staging_dir=layout.root / "staging" / inc)
    truth = layout.run_group_truth_dir(rg)
    truth.mkdir(parents=True, exist_ok=True)
    layout.injection_path(rg).write_text(json.dumps(injection(run_group_id=rg, incident_ids=[inc], split=split)))
    layout.label_path(inc).write_text(json.dumps({**LABEL, "incident_id": inc, "run_group_id": rg}))
    return layout


def test_incidents_are_chosen_by_the_set_fixed_at_collection(tmp_path):
    layout = stored(tmp_path / "data")
    assert incidents_in(layout, "pilot") == [("INC-001", "RG-001")]
    assert incidents_in(layout, "heldout") == []


def test_a_method_reads_only_the_snapshot_and_its_predictions_are_checked_and_scored(tmp_path, monkeypatch):
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    paths = run_method(layout, "stat-anomaly", "pilot", out)
    audit_set(layout, "pilot", out)
    pred = json.loads(paths[0].read_text())
    assert pred["incident_id"] == "INC-001" and pred["method"]["name"] == "stat-anomaly"
    result = score_method(layout, "stat-anomaly", "pilot", out)
    assert result["aggregate"]["n_incidents"] == 1 and "origin_top1" in result["aggregate"]["metrics"]
    assert result["incidents"][0]["run_group_id"] == "RG-001" and "evidence_existence" in result["incidents"][0]
    table = (out / "pilot" / "stat-anomaly" / "table.md").read_text()
    assert "origin_top1" in table and "fault_type" in table and "n = 1" in table

    def bad(snapshot, incident_id):
        return {"prediction_version": 1, "incident_id": incident_id, "root_cause": "payment"}

    monkeypatch.setitem(METHODS, "broken", bad)
    with pytest.raises(ValueError, match="prediction"):
        run_method(layout, "broken", "pilot", tmp_path / "r2")


def test_an_empty_set_scores_to_an_empty_table(tmp_path):
    result = score_method(DataLayout(tmp_path / "data"), "stat-anomaly", "pilot", tmp_path / "results")
    assert result["aggregate"]["n_incidents"] == 0
    assert "n = 0" in (tmp_path / "results" / "pilot" / "stat-anomaly" / "table.md").read_text()


def test_leakage_audit_of_a_set_lands_on_the_ground_truth_side(tmp_path):
    from eval.runner import audit_set

    layout = stored(tmp_path / "data")
    out = audit_set(layout, "pilot", tmp_path / "results")
    path = layout.ground_truth_root / "incidents" / "INC-001" / "leakage_audit.json"
    assert layout.is_ground_truth(path) and json.loads(path.read_text())["difficulty"] in ("easy", "medium", "hard")
    assert out["incidents"][0]["incident_id"] == "INC-001" and out["incidents"][0]["lexicon_hits"] == 0
    assert "difficulty" in (tmp_path / "results" / "pilot" / "leakage.md").read_text()


def test_evidence_relevance_weak_labels_a_blind_gold_worksheet_and_gold_precision(tmp_path, monkeypatch):
    from baselines.statistical import predict
    from collect.snapshot import open_snapshot
    from eval.runner import gold_add, gold_todo_set

    layout = stored(tmp_path / "data")
    snap = open_snapshot(layout.incident_dir("INC-001") / "normalized", layout)
    spans = [s["id"] for s in snap.spans()][:3]

    def cites(snapshot, incident_id):
        return {**predict(snapshot, incident_id), "evidence": [{"id": i} for i in spans] + [{"id": "s-" + "f" * 16}]}

    monkeypatch.setitem(METHODS, "cites", cites)
    out = tmp_path / "results"
    run_method(layout, "cites", "pilot", out)
    audit_set(layout, "pilot", out)
    todo = gold_todo_set(layout, "pilot", out)
    path = layout.label_path("INC-001").with_name("evidence_gold_todo.json")
    assert todo["incidents"] == [{"incident_id": "INC-001", "to_judge": 3}] and layout.is_ground_truth(path)
    sheet = json.loads(path.read_text())
    assert sheet["context"]["origin_service"] == "payment" and len(sheet["items"]) == 3
    assert all(set(e) == {"id", "t0", "t1", "record", "relevant"} and e["relevant"] is None for e in sheet["items"])
    assert "cites" not in path.read_text()  # blind: no method name

    sheet["items"][0]["relevant"] = True
    sheet["items"][1]["relevant"] = False  # the third is left for later
    filled = tmp_path / "filled.json"
    filled.write_text(json.dumps(sheet))
    assert gold_add(layout, "INC-001", filled, annotator="human:jw", now="2026-10-09T10:00:00Z") == {"added": 2, "unjudged": 1}
    assert gold_todo_set(layout, "pilot", out)["incidents"][0]["to_judge"] == 1

    result = score_method(layout, "cites", "pilot", out)
    row = result["incidents"][0]
    assert row["evidence_existence"] == 0.75 and row["evidence_weak"]["n"] == 3
    assert row["evidence_gold"] == {"cited": 3, "judged": 2, "relevant": 1, "precision": 0.5, "coverage": 2 / 3}
    assert result["evidence"]["gold_precision"]["n"] == 1 and "weak" in result["evidence"]
    table = (out / "pilot" / "cites" / "table.md").read_text()
    assert "gold precision" in table and "weak" in table and "existence" in table


def test_eval_cli_checks_its_arguments_and_gold_add_refuses_an_agent(tmp_path, monkeypatch, capsys):
    import eval.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["gold-add", "--incident", "INC-001"])  # needs --file and --annotator
    with pytest.raises(SystemExit):
        cli.main(["leakage"])  # needs --set
    assert cli.main(["gold-todo", "--set", "pilot"]) == 0  # an empty set: nothing to judge
    sheet = tmp_path / "s.json"
    sheet.write_text(json.dumps({"incident_id": "INC-001",
                                 "items": [{"id": "s-" + "a" * 16, "t0": None, "t1": None, "relevant": True}]}))
    assert cli.main(["gold-add", "--incident", "INC-001", "--file", str(sheet), "--annotator", "agent:claude-code"]) == 2
    assert "human" in capsys.readouterr().err


def test_a_call_error_on_a_pilot_run_is_an_error_line_and_exit_2(tmp_path, monkeypatch, capsys):
    # decision 023 §5: the adapter raises CallError for API and transport errors; on the Pilot (no attempt ledger) the CLI
    # reports it like every other refusal instead of a traceback
    import eval.__main__ as cli
    from agent.harness import CallError

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    stored(tmp_path / "data/external")

    def overloaded(snapshot, incident_id):
        raise CallError("api_error", "HTTP 529 overloaded", usage={"tokens_in": 10})

    monkeypatch.setitem(METHODS, "overloaded", overloaded)
    assert cli.main(["run", "--method", "overloaded", "--set", "pilot"]) == 2
    err = capsys.readouterr().err
    assert err == "error: api_error: HTTP 529 overloaded\n"


def test_scoring_needs_the_leakage_audit_drops_lexicon_hits_and_reports_by_difficulty(tmp_path):
    # decision 015: an incident whose snapshot hits the lexicon enters no score; reports are layered by difficulty
    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    run_method(layout, "stat-anomaly", "pilot", out)
    with pytest.raises(LookupError, match="leakage"):
        score_method(layout, "stat-anomaly", "pilot", out)
    audit_set(layout, "pilot", out)
    difficulty = json.loads(layout.label_path("INC-001").with_name("leakage_audit.json").read_text())["difficulty"]
    result = score_method(layout, "stat-anomaly", "pilot", out)
    assert result["incidents"][0]["difficulty"] == difficulty and result["excluded"] == []
    assert result["by_difficulty"][difficulty]["n_incidents"] == 1
    assert set(result["by_difficulty"][difficulty]["metrics"]) == {"fault_type", "origin_top1", "affected_f1", "symptom_exact"}
    assert "by difficulty" in (out / "pilot" / "stat-anomaly" / "table.md").read_text()

    path = layout.label_path("INC-001").with_name("leakage_audit.json")
    path.write_text(json.dumps({**json.loads(path.read_text()), "lexicon_hits": 2}))
    result = score_method(layout, "stat-anomaly", "pilot", out)
    assert result["aggregate"]["n_incidents"] == 0 and result["incidents"] == []
    assert result["excluded"] == [{"incident_id": "INC-001", "reason": "lexicon_hits=2 (decision 015)"}]
    assert "INC-001" in (out / "pilot" / "stat-anomaly" / "table.md").read_text()


def test_failures_are_classified_from_the_transcript_and_counted_by_category(tmp_path, monkeypatch):
    # decision 022: a method may return (prediction, transcript); run writes the transcript next to the prediction
    from baselines.statistical import predict

    def wrong(snapshot, incident_id):
        pred = {**predict(snapshot, incident_id), "origin_candidates": ["cart"],
                "fault": {"fault_type": "error_response", "fault_family": None}}
        return pred, {"stop_reason": "submitted", "exposure": ["stats:payment:0-30"]}

    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    monkeypatch.setitem(METHODS, "wrong", wrong)
    run_method(layout, "wrong", "pilot", out)
    assert (out / "pilot" / "wrong" / "INC-001.transcript.json").exists()
    audit_set(layout, "pilot", out)
    result = score_method(layout, "wrong", "pilot", out)
    assert result["incidents"][0]["failure"] == "seen_misread"
    assert result["failures"]["n_failures"] == 1 and result["failures"]["by_category"]["seen_misread"] == 1
    assert result["failures"]["classified_without_review"] == 1
    assert "seen_misread" in (out / "pilot" / "wrong" / "table.md").read_text()


def test_llm_methods_refuse_to_run_until_the_model_and_budgets_are_approved(tmp_path, monkeypatch):
    # decisions 020 / 021 and MACHINE_POLICY: no paid call before the user approves the model, budgets and cost. The
    # committed config is approved since 2026-10-10 (decision 029, a local model); a proposed one is still refused.
    import json as _json

    import eval.runner as runner
    from eval.runner import LLM_CONFIG, load_llm_config

    config = _json.loads(LLM_CONFIG.read_text())
    assert set(config["budgets"]) == {"dump_all_proxy_tokens", "retrieval_queries", "retrieval_k", "agent_max_tool_calls",
                                      "agent_max_proxy_tokens", "agent_max_turns"}
    proposed = tmp_path / "proposed.json"
    proposed.write_text(_json.dumps({**config, "status": "proposed", "model": None}))
    monkeypatch.setattr(runner, "LLM_CONFIG", proposed)
    layout = stored(tmp_path / "data")
    for method in ("dump-all", "retrieval", "agent"):
        assert method in METHODS
        with pytest.raises(ValueError, match="approved"):
            run_method(layout, method, "pilot", tmp_path / "results")
    assert not (tmp_path / "results").exists()
    approved = tmp_path / "c.json"
    approved.write_text(_json.dumps({**config, "status": "approved", "model": "some-model", "provider": None}))
    with pytest.raises(ValueError, match="adapter"):
        load_llm_config(approved, need_client=True)


def test_gold_worksheets_belong_to_one_incident_and_unmerged_judgments_are_never_wiped(tmp_path, monkeypatch):
    from baselines.statistical import predict
    from collect.snapshot import open_snapshot
    from eval.runner import gold_add, gold_todo_set

    layout = stored(tmp_path / "data")
    snap = open_snapshot(layout.incident_dir("INC-001") / "normalized", layout)
    spans = [s["id"] for s in snap.spans()][:2]
    monkeypatch.setitem(METHODS, "cites", lambda s, i: {**predict(s, i), "evidence": [{"id": x} for x in spans]})
    out = tmp_path / "results"
    run_method(layout, "cites", "pilot", out)
    gold_todo_set(layout, "pilot", out)
    path = layout.label_path("INC-001").with_name("evidence_gold_todo.json")
    sheet = json.loads(path.read_text())
    sheet["items"][0]["relevant"] = True
    path.write_text(json.dumps(sheet))
    with pytest.raises(ValueError, match="not merged"):
        gold_todo_set(layout, "pilot", out)  # the filled sheet was not added yet
    other = tmp_path / "other.json"
    other.write_text(json.dumps({**sheet, "incident_id": "INC-002"}))
    with pytest.raises(ValueError, match="INC-002"):
        gold_add(layout, "INC-001", other, annotator="human:jw", now="2026-10-09T10:00:00Z")
    gold_add(layout, "INC-001", path, annotator="human:jw", now="2026-10-09T10:00:00Z")
    assert gold_todo_set(layout, "pilot", out)["incidents"][0]["to_judge"] == 1  # merged: a fresh sheet is fine


def test_the_table_marks_reviews_made_after_seeing_outputs_and_lists_differences_and_failures(tmp_path, monkeypatch):
    from baselines.statistical import predict

    layout = stored(tmp_path / "data")
    truth = layout.label_path("INC-001").parent
    reviewed = {**json.loads(layout.label_path("INC-001").read_text()),
                "telemetry_coverage": {"traces": "origin", "metrics": "none", "logs": "origin"},
                "labeling": {"method": "catalog+review", "labeled_at": "2026-10-09T09:00:00Z", "labeler": "human:jw"}}
    (truth / "label.reviewed.json").write_text(json.dumps(reviewed))
    (truth / "label_review.json").write_text(json.dumps({
        "review_version": 1, "incident_id": "INC-001", "reviewer": "human:jw", "reviewed_at": "2026-10-09T09:00:00Z",
        "fault_exercised": True, "saw_method_outputs": True,
        "differences": [{"field": "affected_services", "a_priori": ["payment", "checkout"], "reviewed": ["payment"],
                         "reason": "checkout shows no errors"}]}))
    monkeypatch.setitem(METHODS, "wrong", lambda s, i: ({**predict(s, i), "origin_candidates": ["cart"]},
                                                        {"stop_reason": "submitted", "exposure": []}))
    out = tmp_path / "results"
    run_method(layout, "wrong", "pilot", out)
    audit_set(layout, "pilot", out)
    result = score_method(layout, "wrong", "pilot", out)
    row = result["incidents"][0]
    assert row["saw_method_outputs"] is True and result["review_differences"]["INC-001"][0]["field"] == "affected_services"
    assert result["failures"]["share"]["not_seen"] == 1.0
    table = (out / "pilot" / "wrong" / "table.md").read_text()
    for text in ("reviewed after seeing method outputs: INC-001", "INC-001: affected_services", "| INC-001 |", "not_seen"):
        assert text in table, text


def test_compare_two_scored_methods_on_the_same_set(tmp_path, monkeypatch):
    from baselines.statistical import predict
    from eval.runner import compare_methods

    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    monkeypatch.setitem(METHODS, "wrong", lambda s, i: {**predict(s, i), "origin_candidates": ["cart"]})
    monkeypatch.setitem(METHODS, "right", lambda s, i: {**predict(s, i), "origin_candidates": ["payment"]})
    audit_set(layout, "pilot", out)
    for m in ("wrong", "right"):
        run_method(layout, m, "pilot", out)
        score_method(layout, m, "pilot", out)
    assert score_method(layout, "right", "pilot", out)["incidents"][0]["fault"] == "paymentFailure 100%"
    result = compare_methods("pilot", "right", "wrong", out, metrics=("origin_top1",), resamples=200)
    assert result["paired"]["origin_top1"]["mean_diff"] == 1.0 and "paymentFailure 100%" in result["lofo"]["origin_top1"]
    assert "right - wrong" in (out / "pilot" / "compare-right-vs-wrong.md").read_text()
    with pytest.raises(LookupError, match="score"):
        compare_methods("pilot", "right", "missing", out)


def test_a_difficulty_stratum_with_ten_run_groups_gets_intervals():
    # decision 023 §7: strata with >= 10 run groups report bootstrap intervals, smaller ones only means
    from eval.runner import STRATUM_MIN_RUN_GROUPS, difficulty_strata

    assert STRATUM_MIN_RUN_GROUPS == 10
    rows = [{"incident_id": f"INC-{i:03d}", "run_group_id": f"RG-{i:03d}", "difficulty": "easy" if i <= 10 else "hard",
             "fault_type": 1.0, "origin_top1": float(i % 2), "affected_f1": 0.5, "symptom_exact": 1.0} for i in range(1, 14)]
    out = difficulty_strata(rows)
    assert out["easy"]["n_incidents"] == 10 and out["easy"]["ci95"]["origin_top1"][0] < 0.5 < out["easy"]["ci95"]["origin_top1"][1]
    assert out["hard"]["n_incidents"] == 3 and out["hard"]["ci95"] is None and out["hard"]["metrics"]["fault_type"] == 1.0


def test_each_run_keeps_its_budgets_and_the_table_reports_usage_and_what_was_seen(tmp_path, monkeypatch):
    # SPEC §7, decision 024: budgets saved with the results; usage and measured exposure reported, never scored
    import math

    from baselines.statistical import predict
    from collect.snapshot import open_snapshot
    from eval.runner import SCOPES, exposure_of, method_budgets

    layout = stored(tmp_path / "data")
    out = tmp_path / "results"
    run_method(layout, "stat-anomaly", "pilot", out)
    assert json.loads((out / "pilot" / "stat-anomaly" / "run_config.json").read_text()) == {
        "method": "stat-anomaly", "split": "pilot", "model": None, "budgets": {}, "scope": SCOPES["stat-anomaly"]}
    budgets = {"dump_all_proxy_tokens": 1, "retrieval_queries": 2, "retrieval_k": 3, "agent_max_tool_calls": 4,
               "agent_max_proxy_tokens": 5, "agent_max_turns": 6}
    assert method_budgets("dump-all", {"budgets": budgets}) == {"proxy_tokens": 1}
    assert method_budgets("retrieval", {"budgets": budgets}) == {"queries": 2, "k": 3}
    assert method_budgets("agent", {"budgets": budgets}) == {"tool_calls": 4, "proxy_tokens": 5, "turns": 6}
    assert set(SCOPES) == set(METHODS)

    def looked(snapshot, incident_id):
        pred = predict(snapshot, incident_id)
        pred["usage"] = {**pred["usage"], "tokens_in": 1000, "tokens_out": 10, "proxy_tokens": 500, "tool_calls": 3,
                         "cost_usd": 0.5}
        span = next(snapshot.spans())["id"]
        return pred, {"stop_reason": "turn_limit", "exposure": [span, "t-" + "a" * 32, "stats:payment:0-1", span]}

    monkeypatch.setitem(METHODS, "looked", looked)
    run_method(layout, "looked", "pilot", out)
    audit_set(layout, "pilot", out)
    result = score_method(layout, "looked", "pilot", out)
    assert "usage" not in result["aggregate"]["metrics"] and "exposure" not in result["aggregate"]["metrics"]
    usage = result["usage"]
    assert usage["fields"]["tokens_in"] == {"n": 1, "mean": 1000, "median": 1000, "max": 1000}
    assert usage["fields"]["retrievals"]["mean"] == 0 and usage["cost_total"] == 0.5
    assert usage["stop_reasons"] == {"turn_limit": 1}
    snap = open_snapshot(layout.incident_dir("INC-001") / "normalized", layout)
    counts = {f["path"]: f["records"] for f in snap.meta["files"]}
    minutes = math.ceil((snap.window["end_ns"] - snap.window["start_ns"]) / 60e9)
    seen = result["incidents"][0]["exposure"]
    assert seen["records_seen"] == 1  # one span, counted once; a trace id is not a record
    assert seen["records_share"] == 1 / (counts["spans.jsonl"] + counts["logs.jsonl"] + counts["metric_points.jsonl"])
    assert seen["overview_share"] == 2 / (len(snap.services) * minutes)
    assert exposure_of(["stats:*"], snap)["overview_share"] == 1.0
    assert usage["exposure"]["records_seen"]["max"] == 1
    table = (out / "pilot" / "looked" / "table.md").read_text()
    assert "## Budgets, usage and visible data" in table and "turn_limit 1" in table and "| tokens_in | 1 |" in table
    stat = (out / "pilot" / "stat-anomaly" / "table.md")
    score_method(layout, "stat-anomaly", "pilot", out)
    assert SCOPES["stat-anomaly"] in stat.read_text() and "Budgets: none" in stat.read_text()
    (out / "pilot" / "looked" / "run_config.json").unlink()  # an older result: never filled in from today's settings
    score_method(layout, "looked", "pilot", out)
    assert "not recorded" in (out / "pilot" / "looked" / "table.md").read_text()


def test_a_withdrawn_incident_is_neither_run_nor_scored_and_the_table_says_why(tmp_path):
    from collect.pilot import withdraw

    layout = stored(tmp_path / "data")
    truth = layout.run_group_truth_dir("RG-001")
    (truth / "run.json").write_text(json.dumps({"run_group_id": "RG-001", "status": "valid", "incident_ids": ["INC-001"],
                                                "plan": {"split": "pilot"}}))
    withdraw(layout, "RG-001", reason="collected in the automatic power mode", decided_by="user", now="2026-10-09T03:00:00Z")
    assert incidents_in(layout, "pilot") == []
    out = tmp_path / "results"
    assert run_method(layout, "stat-anomaly", "pilot", out) == []
    result = score_method(layout, "stat-anomaly", "pilot", out)
    assert result["excluded"] == [{"incident_id": "INC-001", "reason": "withdrawn: collected in the automatic power mode"}]
