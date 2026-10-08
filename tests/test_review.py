"""Label review: a priori (catalog) -> catalog+review against the frozen snapshot, by a person (decision 018)."""

import json

import pytest

from collect.review import apply_review, effective_label, review_sheet
from collect.traffic import TRAFFIC_PROFILES
from test_eval_runner import LABEL, stored
from test_records import manifest

NOW = "2026-10-09T09:00:00Z"
COVERAGE = {"traces": "origin", "metrics": "symptom_only", "logs": "origin"}


@pytest.fixture
def incident(tmp_path):
    layout = stored(tmp_path / "data")
    layout.manifest_path("INC-001").write_text(json.dumps(manifest(
        traffic={"generator_service": "load-generator", "settings": dict(TRAFFIC_PROFILES["locust-upstream-3.1.0"]),
                 "seed": None, "seed_applied": False})))
    rg = layout.run_group_truth_dir("RG-001")
    (rg / "run.json").write_text(json.dumps({
        "run_group_id": "RG-001", "status": "valid", "incident_ids": ["INC-001"],
        "events": [{"ts": "2026-10-08T11:48:30Z", "service": "grafana", "action": "die", "exit_code": 1},
                   {"ts": "2026-10-08T11:52:00Z", "service": "payment", "action": "oom", "exit_code": None}]}))
    return layout


def filled(layout, **changes):
    sheet = json.loads(layout.label_path("INC-001").with_name("label_review_todo.json").read_text())
    sheet["review"].update({"telemetry_coverage": COVERAGE, "fault_exercised": True, "saw_method_outputs": False}, **changes)
    return sheet


def test_the_worksheet_holds_the_a_priori_label_a_per_period_summary_and_the_run_events(incident):
    sheet = review_sheet(incident, "INC-001")
    path = incident.label_path("INC-001").with_name("label_review_todo.json")
    assert incident.is_ground_truth(path) and json.loads(path.read_text()) == sheet
    assert sheet["a_priori"]["origin_service"] == "payment" and sheet["a_priori"]["affected_services"] == LABEL["affected_services"]
    assert sheet["review"]["affected_services"] == LABEL["affected_services"]  # prefilled: only differences need editing
    assert sheet["review"]["telemetry_coverage"] == {"traces": None, "metrics": None, "logs": None}
    assert sheet["review"]["fault_exercised"] is None and sheet["review"]["saw_method_outputs"] is None
    summary = sheet["services"]
    assert set(summary["payment"]) == {"normal", "fault", "recovery"}
    assert set(summary["payment"]["fault"]) >= {"minutes", "spans_per_min", "error_ratio", "p95_server_ms_median",
                                                "p95_server_ms_max", "warn_logs_per_min", "cpu_mean", "memory_max_mib"}
    assert sheet["events"] == {"normal": [{"ts": "2026-10-08T11:48:30Z", "service": "grafana", "action": "die", "exit_code": 1}],
                               "fault": [{"ts": "2026-10-08T11:52:00Z", "service": "payment", "action": "oom", "exit_code": None}],
                               "recovery": []}
    assert sheet["checks"]  # decision 016 §5 / 018 §5: what to look at
    assert "origin_service" not in sheet["review"]  # the origin is not reviewable (decision 018 §2)


def test_a_review_writes_a_separate_catalog_review_label_and_records_each_difference_with_its_reason(incident):
    review_sheet(incident, "INC-001")
    before = incident.label_path("INC-001").read_text()
    sheet = filled(incident, affected_services=["payment", "checkout", "frontend"],
                   reasons={"affected_services": "frontend /api/checkout 500s in the fault period"})
    out = apply_review(incident, "INC-001", sheet, reviewer="human:jw", now=NOW)
    reviewed = json.loads(incident.label_path("INC-001").with_name("label.reviewed.json").read_text())
    assert reviewed["labeling"] == {"method": "catalog+review", "labeled_at": NOW, "labeler": "human:jw"}
    assert reviewed["affected_services"] == ["payment", "checkout", "frontend"] and reviewed["telemetry_coverage"] == COVERAGE
    assert reviewed["origin_service"] == "payment" and reviewed["fault_start"] == LABEL["fault_start"]
    assert incident.label_path("INC-001").read_text() == before  # the a priori label never changes
    record = json.loads(incident.label_path("INC-001").with_name("label_review.json").read_text())
    assert record == out and record["differences"] == [
        {"field": "affected_services", "a_priori": LABEL["affected_services"], "reviewed": ["payment", "checkout", "frontend"],
         "reason": "frontend /api/checkout 500s in the fault period"}]
    assert record["fault_exercised"] is True and record["saw_method_outputs"] is False and record["reviewer"] == "human:jw"
    with pytest.raises(FileExistsError):
        apply_review(incident, "INC-001", sheet, reviewer="human:jw", now=NOW)


@pytest.mark.parametrize("change, message", [
    ({"affected_services": ["payment"]}, "reason"),  # a difference without a reason
    ({"telemetry_coverage": {"traces": None, "metrics": None, "logs": None}}, "telemetry_coverage"),
    ({"fault_exercised": None}, "fault_exercised"),
    ({"saw_method_outputs": "no"}, "saw_method_outputs"),
    ({"origin_service": "checkout", "reasons": {"origin_service": "looked like it"}}, "origin"),
    ({"affected_services": ["checkout"], "reasons": {"affected_services": "x"}}, "origin_service"),  # check_label: origin in affected
])
def test_a_review_that_breaks_the_rules_is_refused_and_writes_nothing(incident, change, message):
    review_sheet(incident, "INC-001")
    with pytest.raises(ValueError, match=message):
        apply_review(incident, "INC-001", filled(incident, **change), reviewer="human:jw", now=NOW)
    assert not incident.label_path("INC-001").with_name("label.reviewed.json").exists()
    with pytest.raises(ValueError, match="human"):
        apply_review(incident, "INC-001", filled(incident), reviewer="agent:claude-code", now=NOW)


def test_the_effective_label_is_the_reviewed_one_and_an_unexercised_fault_is_excluded(incident):
    label, excluded = effective_label(incident, "INC-001")
    assert label["labeling"]["method"] == "catalog" and excluded is None
    review_sheet(incident, "INC-001")
    apply_review(incident, "INC-001", filled(incident, fault_exercised=False), reviewer="human:jw", now=NOW)
    label, excluded = effective_label(incident, "INC-001")
    assert label["labeling"]["method"] == "catalog+review" and "not exercised" in excluded


def test_scores_use_the_reviewed_label_and_say_how_many_were_reviewed(incident, tmp_path):
    from eval.runner import audit_set, run_method, score_method

    out = tmp_path / "results"
    run_method(incident, "stat-anomaly", "pilot", out)
    audit_set(incident, "pilot", out)
    assert score_method(incident, "stat-anomaly", "pilot", out)["labels"] == {"reviewed": 0, "a_priori": 1}
    review_sheet(incident, "INC-001")
    apply_review(incident, "INC-001", filled(incident, affected_services=["payment"],
                                             reasons={"affected_services": "only payment errs"}), reviewer="human:jw", now=NOW)
    result = score_method(incident, "stat-anomaly", "pilot", out)
    assert result["labels"] == {"reviewed": 1, "a_priori": 0}
    assert "reviewed" in (out / "pilot" / "stat-anomaly" / "table.md").read_text()


def test_the_review_commands_write_the_sheet_and_refuse_an_agent_reviewer(incident, tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli

    root = incident.root
    monkeypatch.setattr(cli, "DataLayout", lambda _: incident)
    assert cli.main(["review-sheet", "--incident", "INC-001"]) == 0
    sheet = tmp_path / "filled.json"
    sheet.write_text(json.dumps(filled(incident)))
    assert cli.main(["review", "--incident", "INC-001", "--file", str(sheet), "--reviewer", "agent:claude-code"]) == 2
    assert "person" in capsys.readouterr().err
    assert cli.main(["review", "--incident", "INC-001", "--file", str(sheet), "--reviewer", "human:jw"]) == 0
    assert (root / "ground_truth" / "incidents" / "INC-001" / "label.reviewed.json").exists()


def test_a_sheet_is_applied_only_to_its_own_incident_and_never_overwritten(incident):
    review_sheet(incident, "INC-001")
    with pytest.raises(FileExistsError, match="worksheet"):
        review_sheet(incident, "INC-001")  # a half-filled sheet is never wiped
    review_sheet(incident, "INC-001", overwrite=True)
    with pytest.raises(ValueError, match="INC-002"):
        apply_review(incident, "INC-001", {**filled(incident), "incident_id": "INC-002"}, reviewer="human:jw", now=NOW)
    apply_review(incident, "INC-001", filled(incident), reviewer="human:jw", now=NOW)
    with pytest.raises(FileExistsError, match="reviewed"):
        review_sheet(incident, "INC-001", overwrite=True)


def test_every_reviewable_field_that_changes_needs_a_reason(incident):
    review_sheet(incident, "INC-001")
    sheet = filled(incident)
    sheet["review"]["user_symptom"] = {**sheet["review"]["user_symptom"], "description": "orders fail at checkout"}
    sheet["review"]["notes"] = "checked the traces"
    with pytest.raises(ValueError, match="user_symptom"):
        apply_review(incident, "INC-001", sheet, reviewer="human:jw", now=NOW)
    sheet["review"]["reasons"] = {"user_symptom": "the description names where it fails"}
    with pytest.raises(ValueError, match="notes"):
        apply_review(incident, "INC-001", sheet, reviewer="human:jw", now=NOW)
    sheet["review"]["reasons"]["notes"] = "review note"
    record = apply_review(incident, "INC-001", sheet, reviewer="human:jw", now=NOW)
    assert [d["field"] for d in record["differences"]] == ["user_symptom", "notes"]


def test_container_events_are_on_the_data_clock(incident):
    # docker events come from the daemon in the Docker VM: the data clock, not the host clock of the label
    report = incident.normalize_report_path("INC-001")
    r = json.loads(report.read_text())
    r["window"]["clock_offsets"] = [120.0, 120.0]
    report.write_text(json.dumps(r))
    run = incident.run_group_truth_dir("RG-001") / "run.json"
    rec = json.loads(run.read_text())
    rec["events"] = [{"ts": "2026-10-08T11:51:00Z", "service": "payment", "action": "die", "exit_code": 1}]
    run.write_text(json.dumps(rec))
    sheet = review_sheet(incident, "INC-001")
    assert sheet["events"]["normal"] and not sheet["events"]["fault"]  # the fault starts at 11:52 on the data clock


def test_per_minute_rates_count_only_the_part_of_the_last_minute_inside_the_window():
    # clock audit: a partial last minute counted as a whole one made a fake ~11% traffic drop in the recovery
    from collect.review import _summary

    S, M = 10**9, 60 * 10**9

    class Snap:
        services = ["cart"]
        window = {"start_ns": 0, "end_ns": 27 * M + 7 * S}

        def spans(self):
            for m in range(28):
                n = 60 if m < 27 else 7  # one span per second for the whole window
                for k in range(n):
                    yield {"service": "cart", "start_time_unix_nano": m * M + k * S, "end_time_unix_nano": m * M + k * S + 1,
                           "status_code": "unset", "kind": "server"}

        def logs(self):
            return iter(())

        def series(self):
            return iter(())

        def points(self):
            return iter(())

    out = _summary(Snap(), 10 * M, 20 * M)["cart"]
    assert out["normal"]["spans_per_min"] == out["fault"]["spans_per_min"] == out["recovery"]["spans_per_min"] == 60.0
