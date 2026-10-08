"""One incident through the whole pipeline without Docker: stored run group -> normalize -> a priori label -> leakage
audit -> statistical baseline -> scores -> label review -> gold worksheet -> scores on the reviewed label (Week 1:
"we can make, freeze, label and replay a credible incident"; decisions 011, 013-018, 022)."""

import json

from collect.incident import normalize_incident
from collect.labeling import catalog_label_from_plan
from collect.layout import DataLayout
from collect.pilot import next_planned, plan_status
from collect.rawexport import build_raw_export
from collect.rawfile import scan_raw_file
from collect.review import apply_review, review_sheet
from collect.traffic import TRAFFIC_PROFILES
from eval.runner import audit_set, gold_add, gold_todo_set, run_method, score_method
from normalize_fixtures import HOST_END, HOST_START, write_raw
from test_incident import CODE, LOCK, PROVENANCE, frozen

FAULT_ON, FAULT_OFF = "2026-10-08T11:50:00Z", "2026-10-08T11:55:00Z"  # inside the fixture's 11:47:40-11:56:40 window


def stored_run_group(root):
    layout = DataLayout(root)
    files = write_raw(layout.raw_dir("RG-001"))
    scans = {sig: scan_raw_file(p, sig) for sig, p in files.items()}
    collector = {"container_id": "c", "restarts": 0, "stop_exit_code": 0, "stop_seconds": 1.0, "cp_seconds": 1.0, "copied": True}
    layout.raw_export_path("RG-001").write_text(json.dumps(build_raw_export("RG-001", LOCK, collector, scans)))
    truth = layout.run_group_truth_dir("RG-001")
    truth.mkdir(parents=True)
    provenance = {**PROVENANCE, "traffic_settings": dict(TRAFFIC_PROFILES["locust-upstream-3.1.0"])}
    schedule = {"normal_start": HOST_START, "fault_on": FAULT_ON, "fault_off": FAULT_OFF, "end": HOST_END}
    run = {"run_group_id": "RG-001", "status": "valid", "incident_ids": ["INC-001"], "raw_dir": "raw/RG-001",
           "plan": {"seed": 7, "flag": "paymentFailure", "variant": "100%", "split": "pilot"},
           "up_at": "2026-10-08T11:40:00Z", "clock_offset_seconds": [0.0, 0.0],
           "incident_window": {"start": HOST_START, "end": HOST_END}, "provenance": provenance, "env_lock_sha256": LOCK,
           "events": [{"ts": "2026-10-08T11:51:00Z", "service": "payment", "action": "die", "exit_code": 1}]}
    (truth / "run.json").write_text(json.dumps(run))
    injection = {"injection_version": 1, "run_group_id": "RG-001", "incident_ids": ["INC-001"], "split": "pilot", "seed": 7,
                 "fault": {"mechanism": "flagd", "flag": "paymentFailure", "variant": "100%"}, "schedule": schedule,
                 "controller": {"method": "flagd-file"},
                 "flag_file": {"baseline_sha256": "sha256:" + "b" * 64, "injected_sha256": "sha256:" + "c" * 64}}
    layout.injection_path("RG-001").write_text(json.dumps(injection))
    return layout


def test_one_incident_through_the_whole_pipeline(tmp_path):
    layout = stored_run_group(tmp_path / "data")
    out = tmp_path / "results"

    normalize_incident(layout, "INC-001", lock_sha256=LOCK, now="2026-10-08T13:00:00Z", policy=frozen(), code=CODE)
    label = catalog_label_from_plan(layout, "INC-001", labeler="agent:claude-code", now="2026-10-08T13:01:00Z")
    assert label["origin_service"] == "payment" and label["fault_start"] == FAULT_ON
    assert plan_status(layout, "pilot")[0]["incident"] == "INC-001"
    assert next_planned(layout, "pilot")["flag"] == "productCatalogFailure"  # the Pilot moves on

    leak = audit_set(layout, "pilot", out)
    assert leak["incidents"][0]["lexicon_hits"] == 0
    run_method(layout, "stat-anomaly", "pilot", out)
    first = score_method(layout, "stat-anomaly", "pilot", out)
    assert first["labels"] == {"reviewed": 0, "a_priori": 1} and first["aggregate"]["n_incidents"] == 1
    assert first["incidents"][0]["failure"] in (None, "rule_limit", "no_answer", "mechanism")

    sheet = review_sheet(layout, "INC-001")
    assert sheet["events"]["fault"][0]["service"] == "payment" and "payment" in sheet["services"]
    sheet["review"].update(telemetry_coverage={"traces": "origin", "metrics": "none", "logs": "origin"},
                           fault_exercised=True, saw_method_outputs=True)
    apply_review(layout, "INC-001", sheet, reviewer="human:test", now="2026-10-08T14:00:00Z")

    todo = gold_todo_set(layout, "pilot", out)
    worksheet = json.loads(layout.label_path("INC-001").with_name("evidence_gold_todo.json").read_text())
    assert len(worksheet["items"]) == todo["incidents"][0]["to_judge"]
    for item in worksheet["items"]:
        item["relevant"] = True
    filled = tmp_path / "filled.json"
    filled.write_text(json.dumps(worksheet))
    gold_add(layout, "INC-001", filled, annotator="human:test", now="2026-10-08T14:10:00Z")

    final = score_method(layout, "stat-anomaly", "pilot", out)
    assert final["labels"] == {"reviewed": 1, "a_priori": 0}
    row = final["incidents"][0]
    if worksheet["items"]:
        assert row["evidence_gold"]["judged"] == len(worksheet["items"]) and row["evidence_gold"]["precision"] == 1.0
    table = (out / "pilot" / "stat-anomaly" / "table.md").read_text()
    for section in ("origin_top1", "by difficulty", "Failures", "gold precision", "Labels: 1 reviewed"):
        assert section in table
    # nothing from the ground-truth side reached the agent-readable snapshot
    readable = layout.incident_dir("INC-001") / "normalized"
    assert not any(n in p.read_text() for p in readable.iterdir() for n in ("paymentFailure", "origin_service", "fault_on"))
