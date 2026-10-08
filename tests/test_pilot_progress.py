"""Where the Pilot collection stands and what to collect next (decision 016 §5, decision 009 §4)."""

import json

import pytest

from collect.layout import DataLayout
from collect.pilot import MAX_INVALID_ATTEMPTS, PLANS, next_planned, plan_status


def run_group(layout, rg, flag, variant, status, inc=None, split="pilot", exercised=None):
    truth = layout.run_group_truth_dir(rg)
    truth.mkdir(parents=True)
    plan = {"run_group_id": rg, "seed": 1, "flag": flag, "variant": variant, "fault_minutes": 10}
    if split is not None:
        plan["split"] = split
    (truth / "run.json").write_text(json.dumps({"run_group_id": rg, "plan": plan, "status": status,
                                                "incident_ids": [inc] if inc else []}))
    if exercised is not None:
        d = layout.label_path(inc).parent
        d.mkdir(parents=True, exist_ok=True)
        (d / "label_review.json").write_text(json.dumps({"fault_exercised": exercised}))
        (d / "label.reviewed.json").write_text("{}")


def test_status_follows_the_plan_order_and_next_is_the_first_without_a_usable_incident(tmp_path):
    layout = DataLayout(tmp_path)
    assert next_planned(layout, "pilot")["flag"] == "paymentFailure"
    run_group(layout, "RG-001", "paymentFailure", "100%", "aborted_unstable", split=None)  # before --set existed: pilot
    run_group(layout, "RG-002", "paymentFailure", "100%", "valid", inc="INC-001")
    status = plan_status(layout, "pilot")
    assert [s["flag"] for s in status] == [e["flag"] for e in PLANS["pilot"]]
    assert status[0]["incident"] == "INC-001" and status[0]["run_groups"] == [("RG-001", "aborted_unstable"), ("RG-002", "valid")]
    assert next_planned(layout, "pilot")["flag"] == "productCatalogFailure"


def test_an_unexercised_fault_is_collected_once_more_and_repeated_failures_stop_for_a_person(tmp_path):
    layout = DataLayout(tmp_path)
    run_group(layout, "RG-001", "paymentFailure", "100%", "valid", inc="INC-001", exercised=False)
    assert next_planned(layout, "pilot")["flag"] == "paymentFailure"  # decision 016 §5: recollect once
    run_group(layout, "RG-002", "paymentFailure", "100%", "valid", inc="INC-002", exercised=False)
    with pytest.raises(RuntimeError, match="paymentFailure"):
        next_planned(layout, "pilot")

    layout = DataLayout(tmp_path / "b")
    for i in range(MAX_INVALID_ATTEMPTS):
        run_group(layout, f"RG-00{i + 1}", "paymentFailure", "100%", "invalid")
    with pytest.raises(RuntimeError, match="invalid"):
        next_planned(layout, "pilot")


def test_run_groups_of_another_set_or_off_the_plan_do_not_count(tmp_path):
    layout = DataLayout(tmp_path)
    run_group(layout, "RG-001", "paymentFailure", "100%", "valid", inc="INC-001", split="heldout")
    run_group(layout, "RG-002", "cartFailure", "10%", "valid", inc="INC-002")
    assert next_planned(layout, "pilot")["flag"] == "paymentFailure"
    assert plan_status(layout, "pilot")[3]["run_groups"] == []  # cartFailure 100%


def test_when_every_fault_has_an_incident_there_is_nothing_next(tmp_path):
    layout = DataLayout(tmp_path)
    for i, e in enumerate(PLANS["pilot"], 1):
        run_group(layout, f"RG-{i:03d}", e["flag"], e["variant"], "valid", inc=f"INC-{i:03d}")
    assert next_planned(layout, "pilot") is None


def test_next_and_status_commands(tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    layout = DataLayout(tmp_path / "data/external")
    assert cli.main(["next", "--set", "pilot"]) == 0
    assert capsys.readouterr().out.strip() == "--flag paymentFailure --variant 100%"
    for i in range(MAX_INVALID_ATTEMPTS):
        run_group(layout, f"RG-00{i + 1}", "paymentFailure", "100%", "aborted_unstable")
    assert cli.main(["next", "--set", "pilot"]) == 3 and "run records" in capsys.readouterr().err
    assert cli.main(["status", "--set", "pilot"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["run_groups"][2] == ["RG-003", "aborted_unstable"]


def test_process_runs_normalize_replay_and_label_once_each(tmp_path, monkeypatch, capsys):
    import collect.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    calls = []

    def normalize(layout, inc):
        calls.append("normalize")
        snap = layout.incident_dir(inc) / "normalized"
        snap.mkdir(parents=True)
        (snap / "snapshot.json").write_text("{}")
        return {"content_sha256": "sha256:x"}

    def label(layout, inc, labeler):
        calls.append("label")
        layout.label_path(inc).parent.mkdir(parents=True, exist_ok=True)
        layout.label_path(inc).write_text("{}")
        return {"label": "written"}

    replay_ok = {"every_id_resolves": True, "checks": []}
    monkeypatch.setattr(cli, "_normalize", normalize)
    monkeypatch.setattr(cli, "_label", label)
    monkeypatch.setattr(cli, "_replay", lambda layout, inc: calls.append("replay") or replay_ok)
    assert cli.main(["process", "--incident", "INC-001", "--labeler", "agent:claude-code"]) == 0
    assert calls == ["normalize", "replay", "label"]
    assert cli.main(["process", "--incident", "INC-001", "--labeler", "agent:claude-code"]) == 0
    assert calls == ["normalize", "replay", "label", "replay"]  # done steps are skipped; the replay check always runs
    out = capsys.readouterr().out
    assert "already done" in out

    replay_ok["checks"] = ["a live container is still running"]
    assert cli.main(["process", "--incident", "INC-001", "--labeler", "agent:claude-code"]) == 1  # no label on a failed replay
