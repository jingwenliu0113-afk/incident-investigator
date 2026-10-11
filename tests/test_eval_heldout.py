"""Methods on the held-out set (decision 023 §5, §6): fail closed without the freeze and the verified incident list, each
(method, incident) once, retries only on API / transport errors, abstention for an incident left without a prediction."""

import json
import subprocess

import pytest

from collect.freeze import freeze_sha256
from collect.heldout import FREEZE_FILE, heldout_incidents, heldout_slots, write_once
from collect.layout import DataLayout
from eval.runner import HELDOUT_MAX_ATTEMPTS, METHODS, RETRYABLE, run_method, score_method
from heldout_fixtures import COMMIT, FREEZE_SHA, freeze_record, passing_freeze, write_audit, write_run


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_without_a_freeze_record_every_heldout_eval_path_refuses_and_changes_nothing(tmp_path, monkeypatch, capsys):
    import eval.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    layout = DataLayout(tmp_path / "data/external")
    write_run(layout, "RG-001", "paymentFailure", "100%", inc="INC-001", split="heldout", slot="H01", freeze_sha=FREEZE_SHA)
    sheet = tmp_path / "sheet.json"
    sheet.write_text(json.dumps({"incident_id": "INC-001", "items": []}))
    before = tree(tmp_path)
    calls = []

    def no_git(*a, **kw):
        calls.append(a)
        raise AssertionError("no git without a freeze record")

    monkeypatch.setattr(subprocess, "run", no_git)
    for args in (["run", "--method", "stat-anomaly", "--set", "heldout"],
                 ["score", "--method", "stat-anomaly", "--set", "heldout"],
                 ["leakage", "--set", "heldout"],
                 ["gold-todo", "--set", "heldout"],
                 ["compare", "--method", "agent", "--against", "stat-anomaly", "--set", "heldout"],
                 ["gate", "--method", "agent", "--against", "stat-anomaly", "--set", "heldout"],
                 ["gold-add", "--incident", "INC-001", "--file", str(sheet), "--annotator", "human:jw"]):
        assert cli.main(args) == 2, args
        err = capsys.readouterr().err
        assert "freeze" in err and "Traceback" not in err, args
    assert tree(tmp_path) == before and not (tmp_path / "data/external/results").exists()
    assert calls == []


def test_project_dir_none_refuses_heldout(tmp_path):
    from eval.runner import audit_set, heldout_guard, run_method, score_method

    layout = DataLayout(tmp_path / "data")
    with pytest.raises(PermissionError, match="project"):
        heldout_guard(layout, None)
    for fn in (run_method, score_method):
        with pytest.raises(PermissionError):
            fn(layout, "stat-anomaly", "heldout", tmp_path / "results")
    with pytest.raises(PermissionError):
        audit_set(layout, "heldout", tmp_path / "results")
    assert not (tmp_path / "results").exists()


# ---------------------------------------------------------------- with a passing freeze and a verified list

ENTRY = {"flag": "paymentFailure", "variant": "100%", "origin": "payment", "affected": ["payment", "checkout"],
         "symptom_kinds": ["errors"], "description": "orders fail", "notes": None}
PLAN = {"entries": [ENTRY], "removed": [{"flag": "cartFailure", "variant": "100%", "basis": "pipeline", "reason": "r",
                                         "decision": "docs/decisions/027-x.md", "evidence": {}}]}
FAULTS = [["paymentFailure", "100%"]]
SLOTS = {"k": 3, "faults": FAULTS, "slots": heldout_slots(FAULTS, k=3)}  # H01, H02 filled; H03 closed


def incident(layout, n, slot, sha, *, exercised=True):
    """A held-out incident with a real (synthetic) snapshot, a reviewed label and a clean audit."""
    from collect.normalize import NormalizeInputs, normalize
    from collect.policy import load_policy
    from collect.rawfile import scan_raw_file
    from normalize_fixtures import HOST_END, HOST_START, write_raw
    from test_eval_runner import LABEL

    rg, inc = f"RG-{n:03d}", f"INC-{n:03d}"
    write_run(layout, rg, "paymentFailure", "100%", inc=inc, split="heldout", slot=slot, freeze_sha=sha)
    files = write_raw(layout.raw_dir(rg))
    scans = {s: scan_raw_file(p, s) for s, p in files.items()}
    normalize(NormalizeInputs(raw_dir=layout.raw_dir(rg), raw_sha256={k: v["sha256"] for k, v in scans.items()},
                              raw_duplicates={k: v["duplicates"] for k, v in scans.items()},
                              window_host=(HOST_START, HOST_END), clock_offsets=[0.0, 0.0]),
              load_policy(), incident_dir=layout.incident_dir(inc), report_path=layout.normalize_report_path(inc),
              staging_dir=layout.root / "staging" / inc)
    report = layout.normalize_report_path(inc)
    report.write_text(json.dumps({**json.loads(report.read_text()), "code": {"commit": COMMIT, "dirty": False}}))
    label = {**LABEL, "incident_id": inc, "run_group_id": rg, "user_symptom": {"kinds": ["errors"], "description": "orders fail"}}
    layout.label_path(inc).write_text(json.dumps(label))
    layout.manifest_path(inc).write_text(json.dumps({"incident_id": inc, "project": {"commit": COMMIT, "dirty": False}}))
    reviewed = {**label, "telemetry_coverage": {"traces": "origin", "metrics": "none", "logs": "origin"},
                "labeling": {"method": "catalog+review", "labeled_at": "2026-10-22T00:00:00Z", "labeler": "human:t"}}
    layout.label_path(inc).with_name("label.reviewed.json").write_text(json.dumps(reviewed))
    layout.label_path(inc).with_name("label_review.json").write_text(json.dumps(
        {"review_version": 1, "incident_id": inc, "fault_exercised": exercised, "saw_method_outputs": False,
         "differences": []}))
    write_audit(layout, inc)
    return inc


def heldout_set(tmp_path, monkeypatch):
    """PROJECT = tmp/proj (freeze record present and passing); data: H01, H02 listed, H03 closed; the list written."""
    project = tmp_path / "proj"
    (project / FREEZE_FILE).parent.mkdir(parents=True)
    (project / FREEZE_FILE).write_text(json.dumps(freeze_record()))
    passing_freeze(monkeypatch)
    sha = freeze_sha256(project)
    layout = DataLayout(tmp_path / "data")
    incident(layout, 50, "H01", sha)
    incident(layout, 51, "H02", sha)
    incident(layout, 52, "H03", sha, exercised=False)
    incident(layout, 53, "H03", sha, exercised=False)
    doc = heldout_incidents(layout, SLOTS, PLAN, freeze=freeze_record(), freeze_sha=sha, results_root=tmp_path / "results",
                            commit_check=lambda c: [], now="2026-10-25T00:00:00Z")
    write_once(layout.heldout_incidents_path, doc)
    return project, layout, tmp_path / "results"


def ledger(out, method):
    path = out / "heldout" / method / "attempts.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def counting(monkeypatch, name, behave):
    """Register a fake method `name`; `behave(incident, call_number)` returns its output or raises."""
    from baselines.statistical import predict

    calls = []

    def method(snapshot, incident_id):
        calls.append(incident_id)
        out = behave(incident_id, len(calls))
        return out if out is not None else predict(snapshot, incident_id)

    monkeypatch.setitem(METHODS, name, method)
    return calls


NOT_CLEAN = "the checkout is not clean (untracked or modified files): held-out work needs a clean checkout"


def test_a_failing_freeze_check_refuses_every_heldout_eval_command_and_changes_nothing(tmp_path, monkeypatch, capsys):
    # a freeze record exists, the list is written, and the check fails (here: a dirty checkout)
    import collect.freeze as freeze
    import eval.__main__ as cli

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    root = tmp_path / "cli"
    (root / "data").mkdir(parents=True)
    (root / "data/external").symlink_to(layout.root, target_is_directory=True)  # the CLI's data/external is this layout
    monkeypatch.setattr(cli, "PROJECT_DIR", root)
    counting(monkeypatch, "stat-anomaly", lambda inc, n: pytest.fail("a method ran under a failing freeze check"))
    monkeypatch.setattr(freeze, "check_freeze", lambda project_dir, run=None: (freeze_record(), [NOT_CLEAN]))
    sheet = tmp_path / "sheet.json"
    sheet.write_text(json.dumps({"incident_id": "INC-050", "items": []}))
    before = tree(layout.root)
    for args in (["run", "--method", "stat-anomaly", "--set", "heldout"],
                 ["score", "--method", "stat-anomaly", "--set", "heldout"],
                 ["leakage", "--set", "heldout"],
                 ["gold-todo", "--set", "heldout"],
                 ["compare", "--method", "agent", "--against", "stat-anomaly", "--set", "heldout"],
                 ["gate", "--method", "agent", "--against", "stat-anomaly", "--set", "heldout"],
                 ["gold-add", "--incident", "INC-050", "--file", str(sheet), "--annotator", "human:jw"]):
        assert cli.main(args) == 2, args
        err = capsys.readouterr().err
        assert "not clean" in err and "Traceback" not in err, args
    assert tree(layout.root) == before


def test_without_the_list_or_with_an_unapproved_model_nothing_runs_or_is_written(tmp_path, monkeypatch):
    import eval.runner as runner
    from env import soak

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    listed = layout.heldout_incidents_path.read_text()
    layout.heldout_incidents_path.unlink()
    with pytest.raises(PermissionError, match="heldout-list"):
        run_method(layout, "stat-anomaly", "heldout", out, project_dir=project)
    layout.heldout_incidents_path.write_text(listed)
    committed = runner.LLM_CONFIG
    proposed = tmp_path / "proposed.json"
    proposed.write_text(json.dumps({**json.loads(committed.read_text()), "status": "proposed", "model": None}))
    monkeypatch.setattr(runner, "LLM_CONFIG", proposed)
    for method in ("agent", "dump-all", "retrieval"):
        with pytest.raises(ValueError, match="approved"):  # an unapproved model never runs (NEXT A1)
            run_method(layout, method, "heldout", out, project_dir=project)
    assert not (out / "heldout").exists()
    # approved 2026-10-10 (decision 029), inference host gpu-server since 2026-10-11 (029 revision 1): refused outside
    # tools/with-remote-ollama; the same settings on host local are refused at the Mac heavy lock
    from eval.inference_host import NotWrapped

    monkeypatch.setattr(runner, "LLM_CONFIG", committed)
    monkeypatch.delenv("II_INFERENCE_HOST", raising=False)

    def busy(project_dir):
        raise soak.LockNotHeld("Mac heavy lock not held; run via ./tools/with-mac-lock (MACHINE_POLICY.md)")

    monkeypatch.setattr(soak, "require_heavy_lock", busy)
    for method in ("agent", "dump-all", "retrieval"):
        with pytest.raises(NotWrapped, match="with-remote-ollama"):
            run_method(layout, method, "heldout", out, project_dir=project)
    local = tmp_path / "local.json"
    doc = json.loads(committed.read_text())
    local.write_text(json.dumps({**doc, "ollama": {**doc["ollama"], "host": "local"}}))
    monkeypatch.setattr(runner, "LLM_CONFIG", local)
    for method in ("agent", "dump-all", "retrieval"):
        with pytest.raises(soak.LockNotHeld):
            run_method(layout, method, "heldout", out, project_dir=project)
    assert not (out / "heldout").exists()


def test_only_listed_incidents_run_once_each(tmp_path, monkeypatch):
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    calls = counting(monkeypatch, "fake", lambda inc, n: None)
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == []
    assert calls == ["INC-050", "INC-051"]  # never the excluded INC-052 / INC-053 of the closed slot H03
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == [] and calls == ["INC-050", "INC-051"]
    config = json.loads((out / "heldout/fake/run_config.json").read_text())
    assert config["freeze_sha256"] == freeze_sha256(project) and config["heldout_incidents_sha256"].startswith("sha256:")
    assert [(e["incident_id"], e["attempt"], e["event"], e.get("outcome")) for e in ledger(out, "fake")] == [
        ("INC-050", 1, "start", None), ("INC-050", 1, "end", "ok"), ("INC-051", 1, "start", None), ("INC-051", 1, "end", "ok")]
    assert not (out / "heldout/fake/run.lock").exists()


def test_a_resumed_run_needs_the_same_configuration_and_a_lock_waits_for_a_person(tmp_path, monkeypatch):
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    counting(monkeypatch, "fake", lambda inc, n: None)
    (out / "heldout/fake").mkdir(parents=True)
    (out / "heldout/fake/run.lock").write_text('{"pid": 1}\n')  # a killed run left its lock
    with pytest.raises(FileExistsError, match="person"):
        run_method(layout, "fake", "heldout", out, project_dir=project)
    assert (out / "heldout/fake/run.lock").read_text() == '{"pid": 1}\n' and ledger(out, "fake") == []
    (out / "heldout/fake/run.lock").unlink()
    (out / "heldout/fake/run_config.json").write_text(json.dumps({"method": "fake", "model": "other"}))
    with pytest.raises(ValueError, match="run_config"):
        run_method(layout, "fake", "heldout", out, project_dir=project)
    assert not (out / "heldout/fake/run.lock").exists()


def test_two_interleaved_runs_never_both_start_an_attempt(tmp_path, monkeypatch):
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    refused = []

    def behave(inc, n):
        if n == 1:
            with pytest.raises(FileExistsError):
                run_method(layout, "fake", "heldout", out, project_dir=project)
            refused.append(inc)

    counting(monkeypatch, "fake", behave)
    run_method(layout, "fake", "heldout", out, project_dir=project)
    assert refused == ["INC-050"]
    starts = [(e["incident_id"], e["attempt"]) for e in ledger(out, "fake") if e["event"] == "start"]
    assert starts == [("INC-050", 1), ("INC-051", 1)]


USAGE = {"tokens_in": 100, "tokens_out": 10, "cost_usd": 0.01, "latency_s": 1.5}


def fail(reason, usage=USAGE):
    from agent.harness import CallError

    raise CallError(reason, "HTTP 503", usage=dict(usage))


def test_api_and_transport_errors_are_retried_once_in_the_same_run_and_recorded(tmp_path, monkeypatch):
    assert RETRYABLE == ("api_error", "transport_error") and HELDOUT_MAX_ATTEMPTS == 2
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    calls = counting(monkeypatch, "fake", lambda inc, n: fail("api_error") if inc == "INC-050" and n == 1 else None)
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == []
    assert calls == ["INC-050", "INC-050", "INC-051"]
    events = [e for e in ledger(out, "fake") if e["incident_id"] == "INC-050"]
    assert [(e["attempt"], e["event"], e.get("outcome")) for e in events] == [
        (1, "start", None), (1, "end", "api_error"), (2, "start", None), (2, "end", "ok")]
    assert events[1]["usage"] == USAGE and events[1]["detail"]

    project, layout, out = heldout_set(tmp_path / "b", monkeypatch)
    calls = counting(monkeypatch, "fake", lambda inc, n: fail("transport_error") if inc == "INC-050" else None)
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == ["INC-050"]
    assert calls == ["INC-050", "INC-050", "INC-051"]
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == ["INC-050"] and len(calls) == 3  # no third try


def test_any_other_error_closes_the_incident_without_a_retry(tmp_path, monkeypatch):
    project, layout, out = heldout_set(tmp_path, monkeypatch)

    def behave(inc, n):
        if n == 1:
            raise RuntimeError("parser bug")

    calls = counting(monkeypatch, "fake", behave)
    with pytest.raises(RuntimeError):
        run_method(layout, "fake", "heldout", out, project_dir=project)
    assert ledger(out, "fake")[-1]["outcome"] == "error" and not (out / "heldout/fake/run.lock").exists()
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == ["INC-050"]
    assert calls == ["INC-050", "INC-051"]

    project, layout, out = heldout_set(tmp_path / "b", monkeypatch)
    calls = counting(monkeypatch, "fake", lambda inc, n: fail("invalid_request"))  # an API answer that is not retryable
    with pytest.raises(Exception):
        run_method(layout, "fake", "heldout", out, project_dir=project)
    assert [e.get("outcome") for e in ledger(out, "fake")] == [None, "error"] and calls == ["INC-050"]


def test_an_interrupted_attempt_is_never_repeated(tmp_path, monkeypatch):
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    (out / "heldout/fake").mkdir(parents=True)
    (out / "heldout/fake/attempts.jsonl").write_text(json.dumps(
        {"incident_id": "INC-050", "attempt": 1, "event": "start", "at": "2026-10-26T00:00:00Z"}) + "\n")
    calls = counting(monkeypatch, "fake", lambda inc, n: None)
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == ["INC-050"] and calls == ["INC-051"]


def test_an_invalid_prediction_is_recorded_and_stops_the_run(tmp_path, monkeypatch):
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    counting(monkeypatch, "fake", lambda inc, n: {"prediction_version": 1, "incident_id": inc})
    with pytest.raises(ValueError, match="invalid prediction"):
        run_method(layout, "fake", "heldout", out, project_dir=project)
    assert ledger(out, "fake")[-1]["outcome"] == "invalid_prediction" and not (out / "heldout/fake/INC-050.json").exists()
    calls = counting(monkeypatch, "fake", lambda inc, n: None)  # the same method now answers validly
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == ["INC-050"]  # closed: no second attempt
    assert calls == ["INC-051"]
    unanswered = score_method(layout, "fake", "heldout", out, project_dir=project)["heldout"]["unanswered"]
    assert unanswered == [{"incident_id": "INC-050", "attempts": ["invalid_prediction"]}]


def test_the_real_harness_reaches_the_ledger_with_the_usage_before_a_failed_turn(tmp_path, monkeypatch):
    from agent.harness import investigate
    from test_agent_harness import Failing, tool

    project, layout, out = heldout_set(tmp_path, monkeypatch)

    def agent(snapshot, incident_id):
        model = Failing(3, [tool("search_spans", {"status": "error"})], [tool("search_spans", {"status": "error"}, "t2")])
        return investigate(snapshot, incident_id, model, cache_root=tmp_path / "cache", method={"name": "agent", "version": "1"},
                           price_per_mtok={"input": 1.0, "output": 1.0})

    monkeypatch.setitem(METHODS, "scripted-agent", agent)
    assert run_method(layout, "scripted-agent", "heldout", out, project_dir=project) == ["INC-050", "INC-051"]
    ends = [e for e in ledger(out, "scripted-agent") if e["event"] == "end"]
    assert len(ends) == 4 and {e["outcome"] for e in ends} == {"api_error"}
    assert all(e["usage"]["tokens_in"] == 200 and e["usage"]["tokens_out"] == 20 for e in ends)


def test_scoring_counts_an_incident_left_without_a_prediction_as_an_abstention(tmp_path, monkeypatch):
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    with pytest.raises(LookupError, match="not run"):
        score_method(layout, "fake", "heldout", out, project_dir=project)
    counting(monkeypatch, "fake", lambda inc, n: fail("api_error") if inc == "INC-051" else None)
    run_method(layout, "fake", "heldout", out, project_dir=project)
    from eval.runner import audit_set

    with pytest.raises(PermissionError, match="pinned"):
        audit_set(layout, "heldout", out, project_dir=project)  # the list pins the audits
    result = score_method(layout, "fake", "heldout", out, project_dir=project)
    assert result["aggregate"]["n_incidents"] == 2  # kept in the denominator (013 §2)
    row = next(r for r in result["incidents"] if r["incident_id"] == "INC-051")
    assert row["origin_top1"] == 0 and row["fault_type"] == 0 and row["failure"] == "no_answer"
    held = result["heldout"]
    assert held["unanswered"] == [{"incident_id": "INC-051", "attempts": ["api_error", "api_error"]}]
    assert [e["incident_id"] for e in held["excluded"]] == ["INC-052", "INC-053"]
    assert held["closed_slots"][0]["slot"] == "H03" and held["removed_faults"][0]["flag"] == "cartFailure"
    assert held["freeze_sha256"] == freeze_sha256(project)
    assert result["usage"]["failed_attempts"] == {"count": 2, "tokens_in": 200, "tokens_out": 20, "cost_usd": 0.02,
                                                  "latency_s": 3.0}
    table = (out / "heldout/fake/table.md").read_text()
    for text in ("H03", "cartFailure", "INC-051", "Failed attempts: 2"):
        assert text in table, text


def test_scoring_waits_while_a_listed_incident_may_still_be_attempted(tmp_path, monkeypatch):
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    counting(monkeypatch, "fake", lambda inc, n: None)
    run_method(layout, "fake", "heldout", out, project_dir=project)
    (out / "heldout/fake/INC-051.json").unlink()  # as if INC-051 had not been attempted
    lines = [line for line in (out / "heldout/fake/attempts.jsonl").read_text().splitlines() if "INC-051" not in line]
    (out / "heldout/fake/attempts.jsonl").write_text("\n".join(lines) + "\n")
    with pytest.raises(LookupError, match="INC-051"):
        score_method(layout, "fake", "heldout", out, project_dir=project)


@pytest.mark.parametrize("key", ["freeze_sha256", "heldout_incidents_sha256"])
def test_scoring_needs_a_run_made_under_this_freeze_record_and_incident_list(tmp_path, monkeypatch, key):
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    counting(monkeypatch, "fake", lambda inc, n: None)
    run_method(layout, "fake", "heldout", out, project_dir=project)
    path = out / "heldout/fake/run_config.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), key: "sha256:old"}))
    with pytest.raises(PermissionError, match="another freeze record or incident list"):
        score_method(layout, "fake", "heldout", out, project_dir=project)
    assert not (out / "heldout/fake/scores.json").exists()


def test_heldout_gold_worksheets_are_written_for_the_listed_incidents_only(tmp_path, monkeypatch):
    from eval.runner import gold_todo_set

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    assert [r["incident_id"] for r in gold_todo_set(layout, "heldout", out, project_dir=project)["incidents"]] == [
        "INC-050", "INC-051"]
    sheets = {inc for inc in ("INC-050", "INC-051", "INC-052", "INC-053")
              if layout.label_path(inc).with_name("evidence_gold_todo.json").exists()}
    assert sheets == {"INC-050", "INC-051"}  # never the excluded incidents of the closed slot H03


def test_scoring_is_refused_while_a_heldout_run_of_the_method_holds_its_lock(tmp_path, monkeypatch):
    # decision 026 #19: an attempt still in flight is not an interrupted one; a lock left by a killed run waits for a person
    project, layout, out = heldout_set(tmp_path, monkeypatch)
    seen = []

    def behave(inc, n):
        if inc == "INC-051":  # the last listed incident: every other one already has its prediction
            with pytest.raises(LookupError, match="run.lock"):
                score_method(layout, "fake", "heldout", out, project_dir=project)
            seen.append((out / "heldout/fake/scores.json").exists())

    counting(monkeypatch, "fake", behave)
    assert run_method(layout, "fake", "heldout", out, project_dir=project) == []
    assert seen == [False]  # nothing scored while INC-051 was in flight
    assert score_method(layout, "fake", "heldout", out, project_dir=project)["heldout"]["unanswered"] == []
    (out / "heldout/fake/run.lock").write_text('{"pid": 1}\n')  # a killed run left its lock
    with pytest.raises(LookupError, match="person"):
        score_method(layout, "fake", "heldout", out, project_dir=project)


def test_a_crash_between_the_two_files_of_an_attempt_leaves_no_prediction_and_an_abstention(tmp_path, monkeypatch):
    # the prediction file is written last: it alone marks a complete attempt (decision 026 #18)
    import collect.faults as faults
    from baselines.statistical import predict

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    monkeypatch.setitem(METHODS, "llm-like", lambda snapshot, inc: (predict(snapshot, inc),
                                                                    {"stop_reason": "submitted", "exposure": []}))
    real, writes = faults.write_atomic, []

    def killed_between(path, doc):
        writes.append(path.name)
        if len(writes) == 2:
            raise KeyboardInterrupt  # SIGTERM between the attempt's two files
        return real(path, doc)

    monkeypatch.setattr(faults, "write_atomic", killed_between)
    with pytest.raises(KeyboardInterrupt):
        run_method(layout, "llm-like", "heldout", out, project_dir=project)
    assert writes == ["INC-050.transcript.json", "INC-050.json"]
    assert not (out / "heldout/llm-like/INC-050.json").exists() and not (out / "heldout/llm-like/run.lock").exists()
    monkeypatch.setattr(faults, "write_atomic", real)
    assert run_method(layout, "llm-like", "heldout", out, project_dir=project) == ["INC-050"]  # never attempted again
    result = score_method(layout, "llm-like", "heldout", out, project_dir=project)
    assert result["heldout"]["unanswered"] == [{"incident_id": "INC-050", "attempts": ["interrupted"]}]
    row = next(r for r in result["incidents"] if r["incident_id"] == "INC-050")
    # an abstention is scored as no answer: the transcript of its unfinished attempt describes nothing that was scored
    assert row["failure"] == "no_answer" and row["stop_reason"] is None and row["exposure"] is None


def test_leakage_needs_the_freeze_compare_the_same_list_and_gold_add_a_listed_incident(tmp_path, monkeypatch):
    from eval.runner import audit_set, compare_methods, gold_add

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    for name in ("a", "b"):
        counting(monkeypatch, name, lambda inc, n: None)
        run_method(layout, name, "heldout", out, project_dir=project)
        score_method(layout, name, "heldout", out, project_dir=project)
    result = compare_methods("heldout", "a", "b", out, layout=layout, project_dir=project, metrics=("origin_top1",),
                             resamples=50)
    assert result["heldout"]["closed_slots"][0]["slot"] == "H03" and result["heldout"]["removed_faults"]
    assert "H03" in (out / "heldout/compare-a-vs-b.md").read_text()
    # like the gate (023 "Gate 計算 / 輸出", 026 #23): no incident or run group id, a closed slot or an excluded incident
    # keeps its slot and reason (the gate reads this file and sits next to it)
    reason = "fault not exercised twice: closed by default (decision 023 §5.3)"
    assert result["heldout"]["closed_slots"] == [{"slot": "H03", "flag": "paymentFailure", "variant": "100%",
                                                  "reason": reason}]
    assert [set(e) for e in result["heldout"]["excluded"]] == [{"slot", "reason"}] * 2
    for name in ("compare-a-vs-b.json", "compare-a-vs-b.md"):
        raw = (out / "heldout" / name).read_bytes()
        assert b"INC-" not in raw and b"RG-" not in raw, name
    with pytest.raises(PermissionError):
        compare_methods("heldout", "a", "b", out, metrics=("origin_top1",), resamples=50)  # no layout / project
    scores = out / "heldout/b/scores.json"
    scores.write_text(json.dumps({**json.loads(scores.read_text()), "heldout": {"freeze_sha256": "sha256:old"}}))
    with pytest.raises(PermissionError, match="b"):
        compare_methods("heldout", "a", "b", out, layout=layout, project_dir=project, metrics=("origin_top1",), resamples=50)

    sheet = tmp_path / "sheet.json"
    sheet.write_text(json.dumps({"incident_id": "INC-052", "items": []}))
    with pytest.raises(PermissionError, match="list"):
        gold_add(layout, "INC-052", sheet, annotator="human:jw", now="2026-10-27T00:00:00Z", project_dir=project)
    sheet.write_text(json.dumps({"incident_id": "INC-050", "items": []}))
    assert gold_add(layout, "INC-050", sheet, annotator="human:jw", now="2026-10-27T00:00:00Z",
                    project_dir=project) == {"added": 0, "unjudged": 0}

    layout2 = DataLayout(tmp_path / "fresh")
    incident(layout2, 60, "H01", freeze_sha256(project))
    assert audit_set(layout2, "heldout", out / "x", project_dir=project)["incidents"][0]["incident_id"] == "INC-060"


# ---------------------------------------------------------------- no held-out withdrawal (decision 026 #30)

def hand_withdrawal(layout, rg, inc):
    from collect.pilot import WITHDRAWAL

    (layout.run_group_truth_dir(rg) / WITHDRAWAL).write_text(json.dumps(
        {"run_group_id": rg, "incident_ids": [inc], "reason": "by hand", "decided_by": "x",
         "withdrawn_at": "2026-10-26T00:00:00Z"}))


def test_a_heldout_withdrawal_record_written_anyway_stops_the_audit_and_every_run_and_score(tmp_path, monkeypatch):
    from collect.pilot import withdraw
    from eval.runner import audit_set

    project, layout, out = heldout_set(tmp_path, monkeypatch)
    for name in ("ran", "fresh"):
        counting(monkeypatch, name, lambda inc, n: None)
    run_method(layout, "ran", "heldout", out, project_dir=project)
    with pytest.raises(ValueError, match="never withdrawn"):
        withdraw(layout, "RG-050", reason="r", decided_by="user", now="2026-10-26T00:00:00Z")
    hand_withdrawal(layout, "RG-050", "INC-050")
    before = tree(out)
    for fn, method in ((run_method, "fresh"), (score_method, "ran")):
        with pytest.raises(PermissionError, match="never withdrawn"):
            fn(layout, method, "heldout", out, project_dir=project)
    assert tree(out) == before and not (out / "heldout/fresh").exists()

    fresh = DataLayout(tmp_path / "fresh")  # before the list: the leakage audit stops too and rewrites nothing
    incident(fresh, 60, "H01", freeze_sha256(project))
    incident(fresh, 61, "H02", freeze_sha256(project))
    hand_withdrawal(fresh, "RG-061", "INC-061")
    audits = [fresh.label_path(i).with_name("leakage_audit.json") for i in ("INC-060", "INC-061")]
    before = [a.read_bytes() for a in audits]
    with pytest.raises(ValueError, match="never withdrawn"):
        audit_set(fresh, "heldout", out / "x", project_dir=project)
    assert [a.read_bytes() for a in audits] == before and not (out / "x").exists()
