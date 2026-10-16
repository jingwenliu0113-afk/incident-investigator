"""The SPEC Gate analysis (decision 023 §7): conditions 2 and 3 from the decision-022 failures, condition 1 read from the
paired comparison `eval compare` wrote, the descriptive per-fault table, and `python -m eval gate`."""

import json

import pytest

from eval.gate import (GATE_BOOTSTRAP, condition_1, condition_2, condition_3, coverage, fault_directions, per_fault,
                       verdict)

MAIN = ("fault_type", "origin_top1", "affected_f1", "symptom_exact")


def row(n, fault, origin_top1, failure, *, fault_type=1, reviewed=True, **metrics):
    return {"incident_id": f"INC-{n:03d}", "run_group_id": f"RG-{n:03d}", "fault": fault, "origin_top1": origin_top1,
            "fault_type": fault_type, "affected_f1": metrics.get("affected_f1", 1.0),
            "symptom_exact": metrics.get("symptom_exact", 1), "failure": failure, "label_reviewed": reviewed}


# ---------------------------------------------------------------- condition 2: a reproducible stable failure

def test_a_fault_with_origin_wrong_on_half_its_incidents_mostly_in_one_category_is_a_stable_failure():
    rows = [row(1, "f1", 0, "seen_misread"), row(2, "f1", 0, "seen_misread"), row(3, "f1", 0, "not_seen"),
            row(4, "f1", 1, None), row(5, "f1", 1, None)]
    out = condition_2(rows, {"f1": 5})
    f1 = out["by_fault"]["f1"]
    assert (f1["k"], f1["threshold"], f1["origin_wrong"]) == (5, 3, 3)  # ceil(5 / 2) = 3
    assert f1["categories"] == {"not_seen": 1, "seen_misread": 2} and f1["majority_category"] == "seen_misread"
    assert f1["met"] and out["met"] and out["faults_met"] == ["f1"]


def test_too_few_wrong_incidents_no_majority_category_or_a_tie_is_not_a_stable_failure():
    two = [row(1, "f", 0, "seen_misread"), row(2, "f", 0, "seen_misread")] + [row(n, "f", 1, None) for n in (3, 4, 5)]
    assert not condition_2(two, {"f": 5})["met"]  # 2 < ceil(5 / 2)
    spread = [row(1, "f", 0, "seen_misread"), row(2, "f", 0, "not_seen"), row(3, "f", 0, "no_answer")]
    out = condition_2(spread + [row(4, "f", 1, None), row(5, "f", 1, None)], {"f": 5})
    assert out["by_fault"]["f"]["majority_category"] is None and not out["met"]
    tie = [row(n, "f", 0, c) for n, c in enumerate(["not_seen", "not_seen", "seen_misread", "seen_misread"], 1)]
    assert not condition_2(tie + [row(5, "f", 1, None)], {"f": 5})["met"]  # 2 of 4 is not more than half


def test_only_a_wrong_origin_counts_and_an_abstention_is_a_wrong_origin():
    # a fault-type-only failure (022 mechanism) has the origin right; an abstention scores origin_top1 = 0 (013 §2)
    rows = [row(1, "f", 1, "mechanism", fault_type=0), row(2, "f", 1, "mechanism", fault_type=0),
            row(3, "f", 0, "no_answer"), row(4, "f", 1, None), row(5, "f", 1, None)]
    assert condition_2(rows, {"f": 5})["by_fault"]["f"]["origin_wrong"] == 1
    abstaining = [row(n, "f", 0, "no_answer") for n in (1, 2, 3)] + [row(4, "f", 1, None), row(5, "f", 1, None)]
    out = condition_2(abstaining, {"f": 5})["by_fault"]["f"]
    assert out["met"] and out["majority_category"] == "no_answer"  # any 022 category, as 023 §7 is written


def test_the_majority_category_is_taken_over_the_wrong_origins_only():
    # 023 §7 "這些失敗中過半": the origin-wrong incidents; fault-type-only failures (mechanism) are not among them
    rows = [row(1, "f", 0, "seen_misread"), row(2, "f", 0, "seen_misread"), row(3, "f", 0, "not_seen"),
            row(4, "f", 1, "mechanism", fault_type=0), row(5, "f", 1, "mechanism", fault_type=0)]
    out = condition_2(rows, {"f": 5})["by_fault"]["f"]
    assert out["categories"] == {"not_seen": 1, "seen_misread": 2}  # no mechanism count
    assert out["majority_category"] == "seen_misread" and out["met"]  # 2 of 3, not 2 of 5


def test_a_missing_cell_never_lowers_the_threshold():
    # held-out: K is the design's (5 slots); with one cell missing 2 wrong of 4 scored is still below ceil(5 / 2)
    rows = [row(1, "f", 0, "seen_misread"), row(2, "f", 0, "seen_misread"), row(3, "f", 1, None), row(4, "f", 1, None)]
    out = condition_2(rows, {"f": 5})["by_fault"]["f"]
    assert (out["k"], out["threshold"], out["n_scored"], out["met"]) == (5, 3, 4, False)
    # the condition as 023 §7 writes it, for any K (held-out K is the design's slot count)
    assert condition_2([row(1, "g", 0, "not_seen")], {"g": 1})["met"]


def test_on_the_pilot_one_incident_of_a_fault_cannot_show_a_reproducible_failure():
    # the Pilot's K is the scored count; with K < 2 one wrong origin would be "ceil(K / 2)" by itself: not evaluated
    one = condition_2([row(1, "g", 0, "not_seen")], {"g": 1}, min_k=2)
    g = one["by_fault"]["g"]
    assert (g["evaluable"], g["met"], one["met"], one["not_evaluable"], one["faults_met"]) == (False, False, False, ["g"], [])
    two = condition_2([row(1, "g", 0, "not_seen"), row(2, "g", 0, "not_seen")], {"g": 2}, min_k=2)
    assert two["met"] and two["by_fault"]["g"]["evaluable"] and two["not_evaluable"] == []
    with pytest.raises(ValueError, match="category"):  # still refused: a wrong origin without a category
        condition_2([row(1, "g", 0, None)], {"g": 1}, min_k=2)


def test_a_wrong_origin_without_a_failure_category_is_refused():
    with pytest.raises(ValueError, match="category"):
        condition_2([row(1, "f", 0, None)], {"f": 1})


# ---------------------------------------------------------------- condition 3 and the coverage share

def test_reasoning_failures_must_be_more_than_half_of_all_failures():
    rows = [row(1, "f", 0, "seen_misread"), row(2, "f", 0, "not_seen"), row(3, "f", 1, "mechanism", fault_type=0),
            row(4, "f", 1, None)]
    out = condition_3(rows)
    assert out["n_failures"] == 3 and out["by_category"] == {"not_seen": 1, "seen_misread": 1}
    assert out["share"] == pytest.approx(2 / 3) and out["met"]
    half = [row(1, "f", 0, "seen_misread"), row(2, "f", 0, "coverage")]
    assert condition_3(half)["share"] == 0.5 and not condition_3(half)["met"]  # > 0.5, not >= 0.5
    none = condition_3([row(1, "f", 1, None)])
    assert none == {"n_failures": 0, "by_category": {"not_seen": 0, "seen_misread": 0}, "share": None, "met": False}


def test_the_coverage_share_is_descriptive_and_counts_failures_classified_without_review():
    rows = [row(1, "f", 0, "coverage"), row(2, "f", 0, "not_seen", reviewed=False), row(3, "f", 1, None)]
    out = coverage(rows)
    assert out == {"n_scored": 3, "n_failures": 2, "coverage": 1, "share": 0.5, "classified_without_review": 1}
    assert "met" not in out and coverage([])["share"] is None


# ---------------------------------------------------------------- condition 1 read from `eval compare`

def compare_doc(lower, *, mean=0.2, n=50):
    return {"paired": {"origin_top1": {"metric": "origin_top1", "n": n, "n_run_groups": n, "mean_diff": mean,
                                       "ci95": [lower, 0.4], "only_in_one": [], "bootstrap": dict(GATE_BOOTSTRAP)}}}


def test_condition_1_needs_a_positive_lower_bound_against_every_statistical_baseline():
    assert GATE_BOOTSTRAP == {"seed": 0, "resamples": 10_000}  # decision 013 §3
    one = condition_1({"stat-anomaly": compare_doc(0.05)})
    assert one["met"] and one["by_baseline"]["stat-anomaly"]["lower_bound"] == 0.05
    assert not condition_1({"stat-anomaly": compare_doc(0.0)})["met"]  # the lower bound must be > 0
    both = condition_1({"stat-anomaly": compare_doc(0.05), "stat-graph": compare_doc(-0.01)})
    assert not both["met"] and both["by_baseline"]["stat-graph"]["met"] is False
    assert not condition_1({})["met"]


def test_the_verdict_is_a_gate_decision_only_on_the_heldout_set():
    met = {"met": True}
    held = verdict(met, met, met, "heldout")
    assert held["kind"] == "gate_decision" and held["all_met"] and held["decision"] == "pass"
    assert "Gate decision" in held["statement"] and "first-run" in held["statement"]
    assert verdict(met, {"met": False}, met, "heldout")["decision"] == "not_passed"
    pilot = verdict(met, met, met, "pilot")
    assert pilot["kind"] == "diagnostic" and pilot["decision"] is None and pilot["all_met"]
    assert "NOT a Gate decision" in pilot["statement"]


# ---------------------------------------------------------------- the per-fault table (descriptive)

def test_the_equal_weight_mean_counts_each_fault_once_and_lists_the_missing_cells():
    rows = [row(1, "f1", 1, None), row(2, "f1", 1, None), row(3, "f1", 1, None), row(4, "f2", 0, "not_seen")]
    missing = [{"fault": "f2", "slot": "H07", "reason": "closed"}, {"fault": "f3", "slot": None, "reason": "removed"}]
    out = per_fault(rows, {"f1": 3, "f2": 2, "f3": None}, missing, MAIN)
    assert out["faults"]["f1"] == {"n": 3, "k": 3, "means": {"fault_type": 1.0, "origin_top1": 1.0, "affected_f1": 1.0,
                                                              "symptom_exact": 1.0}}
    assert out["faults"]["f2"]["k"] == 2 and out["faults"]["f3"] == {"n": 0, "k": 0, "means": {m: None for m in MAIN}}
    assert out["equal_weight"]["n_faults"] == 2 and out["equal_weight"]["means"]["origin_top1"] == 0.5
    assert out["incident_mean"]["origin_top1"] == 0.75 and out["missing"] == missing
    # K is never below what was scored (a fault outside the design keeps its own count)
    assert per_fault([row(1, "x", 1, None)], {}, [], MAIN)["faults"]["x"]["k"] == 1
    assert per_fault([], {}, [], MAIN)["equal_weight"] == {"n_faults": 0, "means": {m: None for m in MAIN}}


def test_each_fault_reports_k_of_k_right_for_both_methods_and_the_direction_of_the_difference():
    # 023 §7 robustness report: per fault, origin_top1 right k of K for each method and the sign of a - b (no threshold)
    a = [row(1, "f1", 1, None), row(2, "f1", 1, None), row(3, "f1", 0, "not_seen"), row(4, "f2", 0, "not_seen"),
         row(5, "f2", 0, "not_seen"), row(6, "f3", 1, None)]
    b = [row(1, "f1", 0, "coverage"), row(2, "f1", 1, None), row(3, "f1", 0, "coverage"), row(4, "f2", 1, None),
         row(5, "f2", 0, "coverage"), row(6, "f3", 1, None)]
    out = fault_directions(a, b, {"f1": 5, "f2": 5, "f3": 5, "f4": 5}, {"f1": 5, "f2": 5, "f3": 5, "f4": 5})
    assert out["f1"] == {"a": {"right": 2, "scored": 3, "k": 5}, "b": {"right": 1, "scored": 3, "k": 5}, "n_paired": 3,
                         "mean_diff": pytest.approx(1 / 3), "direction": "+"}
    assert (out["f2"]["a"]["right"], out["f2"]["b"]["right"], out["f2"]["direction"]) == (0, 1, "-")
    assert out["f3"]["direction"] == "0"
    assert out["f4"] == {"a": {"right": 0, "scored": 0, "k": 5}, "b": {"right": 0, "scored": 0, "k": 5}, "n_paired": 0,
                         "mean_diff": None, "direction": None}  # a missing cell: no direction
    # only the incidents scored for both give the direction; each method's k counts its own scored incidents
    one_sided = fault_directions([row(1, "f", 1, None), row(2, "f", 1, None)], [row(2, "f", 1, None)], {"f": 2}, {"f": 2})
    assert one_sided["f"]["n_paired"] == 1 and one_sided["f"]["direction"] == "0" and one_sided["f"]["a"]["right"] == 2


# ---------------------------------------------------------------- `eval gate` over written scores and comparisons

CONFIG = {"model": "scripted", "budgets": {"agent_max_tool_calls": 40, "agent_max_proxy_tokens": 120_000,
                                           "agent_max_turns": 30, "dump_all_proxy_tokens": 120_000,
                                           "retrieval_queries": 8, "retrieval_k": 25}}


def pilot_incidents(root, specs):
    """One stored Pilot incident per (flag, variant, origin): synthetic snapshot, a priori label, clean audit."""
    from heldout_fixtures import write_audit
    from test_eval_runner import LABEL, stored

    layout = None
    for n, (flag, variant, origin) in enumerate(specs, 1):
        inc, rg = f"INC-{n:03d}", f"RG-{n:03d}"
        layout = stored(root, inc=inc, rg=rg)
        layout.label_path(inc).write_text(json.dumps({
            **LABEL, "incident_id": inc, "run_group_id": rg, "origin_service": origin, "affected_services": [origin],
            "injected_fault": {**LABEL["injected_fault"], "flag": flag, "variant": variant}}))
        write_audit(layout, inc)
    return layout


def methods(monkeypatch, agent_origin: dict, stat_origin: dict):
    """'agent' (its approval is faked: no model is called) and 'stat-anomaly' answer the given origin per incident."""
    import eval.runner as runner
    from eval.runner import METHODS

    monkeypatch.setattr(runner, "load_llm_config", lambda *a, **k: CONFIG)
    monkeypatch.setitem(METHODS, "agent", answering("agent", agent_origin, True))
    monkeypatch.setitem(METHODS, "stat-anomaly", answering("stat-anomaly", stat_origin, False))


def answering(name, origins, transcript):
    """A fake method `name` answering origins[incident] (with a transcript like an LLM method when `transcript`)."""
    from agent.harness import _abstain

    def run(snapshot, inc):
        pred = {**_abstain(inc, {"name": name, "version": "test"}), "usage": {},
                "fault": {"fault_type": "error_response", "fault_family": None},
                "origin_candidates": [origins[inc]], "affected_services": [origins[inc]],
                "user_symptom": {"kinds": ["errors"]}}
        return (pred, {"stop_reason": "submitted", "exposure": []}) if transcript else pred
    return run


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []


def contents(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


THREE = [("paymentFailure", "100%", "payment"), ("paymentFailure", "100%", "payment"), ("cartFailure", "100%", "cart")]


def test_every_registered_method_is_an_llm_method_or_a_statistical_baseline():
    from eval.runner import LLM_METHODS, METHODS, STATISTICAL_BASELINES

    assert STATISTICAL_BASELINES == ("stat-anomaly",)
    assert set(METHODS) == set(LLM_METHODS) | set(STATISTICAL_BASELINES)


def test_on_the_pilot_the_gate_is_a_diagnostic_read_from_written_scores_and_comparisons(tmp_path, monkeypatch):
    from eval.runner import compare_methods, gate_methods, run_method, score_method

    layout = pilot_incidents(tmp_path / "data", [("paymentFailure", "100%", "payment"),
                                                 ("paymentFailure", "100%", "payment"), ("cartFailure", "100%", "cart")])
    out = tmp_path / "results"
    methods(monkeypatch, {"INC-001": "cart", "INC-002": "cart", "INC-003": "cart"},
            {"INC-001": "checkout", "INC-002": "checkout", "INC-003": "checkout"})
    with pytest.raises(LookupError, match="cannot be evaluated yet"):  # no Agent scores yet
        gate_methods("pilot", "agent", "stat-anomaly", out)
    assert files(out) == []
    for m in ("agent", "stat-anomaly"):
        run_method(layout, m, "pilot", out)
        score_method(layout, m, "pilot", out)
    before = files(out)
    with pytest.raises(LookupError, match="eval compare"):
        gate_methods("pilot", "agent", "stat-anomaly", out)
    compare_methods("pilot", "agent", "stat-anomaly", out, metrics=("origin_top1",), resamples=200)
    with pytest.raises(ValueError, match="10000"):  # decision 013 §3: only the frozen bootstrap decides
        gate_methods("pilot", "agent", "stat-anomaly", out)
    for bad in (("stat-anomaly", "stat-anomaly"), ("agent", "dump-all")):
        with pytest.raises(ValueError):
            gate_methods("pilot", *bad, out)
    assert files(out) == sorted(before + ["pilot/compare-agent-vs-stat-anomaly.json", "pilot/compare-agent-vs-stat-anomaly.md"])

    compare_methods("pilot", "agent", "stat-anomaly", out, metrics=("origin_top1",))
    result = gate_methods("pilot", "agent", "stat-anomaly", out)
    assert result["kind"] == "diagnostic" and result["decision"] is None and "NOT a Gate decision" in result["statement"]
    c = result["conditions"]
    assert c["1"]["by_baseline"]["stat-anomaly"]["mean_diff"] == pytest.approx(1 / 3) and not c["1"]["met"]
    pay = c["2"]["by_fault"]["paymentFailure 100%"]
    assert (pay["k"], pay["threshold"], pay["origin_wrong"], pay["majority_category"]) == (2, 1, 2, "not_seen")
    assert c["2"]["met"] and c["3"]["share"] == 1.0 and c["3"]["met"] and not result["all_met"]
    d = result["descriptive"]
    assert d["coverage"]["share"] == 0.0 and d["coverage"]["classified_without_review"] == 2
    assert d["per_fault"]["agent"]["equal_weight"]["means"]["origin_top1"] == 0.5  # (0 + 1) / 2 faults; incidents: 1/3
    assert {m["fault"] for m in d["per_fault"]["agent"]["missing"]} == {
        "productCatalogFailure on", "paymentUnreachable on", "intlShippingSlowdown 10sec",
        "productCatalogLockContention on", "adHighCpu on", "adManualGc on", "emailMemoryLeak 1000x",
        "recommendationCacheFailure on"}  # planned Pilot faults without a scored incident
    assert set(d["per_fault"]) == {"agent", "stat-anomaly"}
    # 023 §7 robustness report: origin_top1 right k of K per fault for both methods and the direction of the difference
    by = d["fault_directions"]["stat-anomaly"]
    assert (by["paymentFailure 100%"]["a"], by["paymentFailure 100%"]["b"], by["paymentFailure 100%"]["direction"]) == (
        {"right": 0, "scored": 2, "k": 2}, {"right": 0, "scored": 2, "k": 2}, "0")
    assert (by["cartFailure 100%"]["a"]["right"], by["cartFailure 100%"]["b"]["right"], by["cartFailure 100%"]["direction"]) \
        == (1, 0, "+")
    saved = json.loads((out / "pilot/agent/gate.json").read_text())
    assert saved == json.loads(json.dumps(result))
    text = (out / "pilot/agent/gate.md").read_text()
    assert "NOT a Gate decision" in text and "not_seen" in text and "equal weight" in text
    assert "| cartFailure 100% | 1 / 1 | 0 / 1 | 1 | + |" in text and "scored / K" in text and "n / K" not in text
    written = {name: (out / "pilot/agent" / name).read_bytes() for name in ("gate.json", "gate.md")}

    # the baseline scored again after the comparison (023 §6: every method is): the comparison no longer describes it
    stat = out / "pilot/stat-anomaly/scores.json"
    stat.write_text(json.dumps({**json.loads(stat.read_text()), "rescored": True}, indent=2) + "\n")
    with pytest.raises(LookupError, match="again"):
        gate_methods("pilot", "agent", "stat-anomaly", out)
    # the Agent's scores rewritten after the comparison
    scores = out / "pilot/agent/scores.json"
    scores.write_text(json.dumps({**json.loads(scores.read_text()), "rescored": True}, indent=2) + "\n")
    with pytest.raises(LookupError, match="again"):
        gate_methods("pilot", "agent", "stat-anomaly", out)
    scores.write_text(json.dumps({**json.loads(scores.read_text()), "method": "dump-all"}, indent=2) + "\n")
    with pytest.raises(ValueError, match="dump-all"):  # a scores.json is read only as the method and set it names
        gate_methods("pilot", "agent", "stat-anomaly", out)
    # a held-out scores.json under the Pilot path, with a comparison computed from it: never read as the Pilot's
    scores.write_text(json.dumps({**json.loads(scores.read_text()), "method": "agent", "split": "heldout"}, indent=2) + "\n")
    compare_methods("pilot", "agent", "stat-anomaly", out, metrics=("origin_top1",))
    with pytest.raises(ValueError, match="heldout"):
        gate_methods("pilot", "agent", "stat-anomaly", out)
    # a comparison of the same two files the other way round (stat-anomaly - agent) is not agent - stat-anomaly
    scores.write_text(json.dumps({**json.loads(scores.read_text()), "split": "pilot"}, indent=2) + "\n")
    compare_methods("pilot", "stat-anomaly", "agent", out, metrics=("origin_top1",))
    (out / "pilot/compare-agent-vs-stat-anomaly.json").write_bytes(
        (out / "pilot/compare-stat-anomaly-vs-agent.json").read_bytes())
    with pytest.raises(LookupError, match="again"):
        gate_methods("pilot", "agent", "stat-anomaly", out)
    assert {name: (out / "pilot/agent" / name).read_bytes() for name in ("gate.json", "gate.md")} == written


def test_without_agent_scores_the_gate_names_the_missing_llm_results_not_a_paid_approval(tmp_path):
    # 013 F13 item 5 (fixed 2026-10-16): the LLM methods run on a local model (decision 029); the message only says the
    # Agent's results must exist on the set, nothing about a paid approval or the old NEXT A1; the behavior is unchanged
    from eval.runner import gate_methods

    with pytest.raises(LookupError) as raised:
        gate_methods("pilot", "agent", "stat-anomaly", tmp_path / "results")
    message = str(raised.value)
    assert "cannot be evaluated yet: agent has no scores on the pilot set" in message
    assert "`python -m eval run|score --method agent --set pilot` first" in message
    assert "the LLM method's results must exist on the pilot set" in message
    assert "paid" not in message and "NEXT A1" not in message and "approved" not in message
    assert message.endswith("nothing was written") and not (tmp_path / "results").exists()


def test_the_gate_compares_the_agent_with_every_registered_statistical_baseline(tmp_path, monkeypatch):
    import eval.runner as runner
    from eval.runner import compare_methods, gate_methods, run_method, score_method

    layout = pilot_incidents(tmp_path / "data", THREE)
    out = tmp_path / "results"
    truth = {"INC-001": "payment", "INC-002": "payment", "INC-003": "cart"}
    methods(monkeypatch, truth, {inc: "checkout" for inc in truth})  # the Agent always right, stat-anomaly always wrong
    monkeypatch.setattr(runner, "STATISTICAL_BASELINES", ("stat-anomaly", "stat-b"))  # a second one registered
    monkeypatch.setitem(runner.METHODS, "stat-b", answering("stat-b", truth, False))  # as right as the Agent
    for m in ("agent", "stat-anomaly"):
        run_method(layout, m, "pilot", out)
        score_method(layout, m, "pilot", out)
    compare_methods("pilot", "agent", "stat-anomaly", out, metrics=("origin_top1",))
    before = contents(out)
    with pytest.raises(LookupError, match="stat-b"):  # the second baseline has no scores: refused, not skipped
        gate_methods("pilot", "agent", "stat-anomaly", out)
    assert contents(out) == before
    run_method(layout, "stat-b", "pilot", out)
    score_method(layout, "stat-b", "pilot", out)
    before = contents(out)
    with pytest.raises(LookupError, match="stat-b"):  # scores but no comparison
        gate_methods("pilot", "agent", "stat-anomaly", out)
    assert contents(out) == before

    compare_methods("pilot", "agent", "stat-b", out, metrics=("origin_top1",))
    result = gate_methods("pilot", "agent", "stat-anomaly", out)
    by = result["conditions"]["1"]["by_baseline"]
    assert result["baselines"] == ["stat-anomaly", "stat-b"] and set(by) == {"stat-anomaly", "stat-b"}
    assert by["stat-anomaly"]["met"] and by["stat-anomaly"]["lower_bound"] == 1.0
    assert by["stat-b"]["lower_bound"] == 0.0 and not by["stat-b"]["met"] and not result["conditions"]["1"]["met"]
    assert set(result["descriptive"]["fault_directions"]) == {"stat-anomaly", "stat-b"}
    # --against may name either baseline: the other one is compared all the same
    assert set(gate_methods("pilot", "agent", "stat-b", out)["conditions"]["1"]["by_baseline"]) == {"stat-anomaly", "stat-b"}


def test_on_the_pilot_a_fault_scored_once_is_not_evaluated_for_condition_2(tmp_path, monkeypatch, capsys):
    import eval.__main__ as cli
    from eval.runner import compare_methods, run_method, score_method

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    layout = pilot_incidents(tmp_path / "data/external", [("paymentFailure", "100%", "payment")])
    out = tmp_path / "data/external/results"
    methods(monkeypatch, {"INC-001": "cart"}, {"INC-001": "cart"})  # the Agent wrong on the fault's only incident
    for m in ("agent", "stat-anomaly"):
        run_method(layout, m, "pilot", out)
        score_method(layout, m, "pilot", out)
    compare_methods("pilot", "agent", "stat-anomaly", out, metrics=("origin_top1",))
    assert cli.main(["gate", "--method", "agent", "--against", "stat-anomaly", "--set", "pilot"]) == 0
    printed = capsys.readouterr().out
    c2 = json.loads((out / "pilot/agent/gate.json").read_text())["conditions"]["2"]
    pay = c2["by_fault"]["paymentFailure 100%"]
    assert (pay["k"], pay["origin_wrong"], pay["evaluable"], pay["met"]) == (1, 1, False, False) and not c2["met"]
    assert c2["not_evaluable"] == ["paymentFailure 100%"]
    for text in (printed, (out / "pilot/agent/gate.md").read_text()):
        assert "one incident cannot show reproducibility" in text


def test_nothing_is_written_when_gate_md_cannot_be_rendered_and_gate_json_is_written_last(tmp_path, monkeypatch):
    import collect.faults
    import eval.runner as runner
    from eval.runner import compare_methods, gate_methods, run_method, score_method

    layout = pilot_incidents(tmp_path / "data", THREE)
    out = tmp_path / "results"
    methods(monkeypatch, {"INC-001": "cart", "INC-002": "cart", "INC-003": "cart"}, {i: "cart" for i in
                                                                                    ("INC-001", "INC-002", "INC-003")})
    for m in ("agent", "stat-anomaly"):
        run_method(layout, m, "pilot", out)
        score_method(layout, m, "pilot", out)
    compare_methods("pilot", "agent", "stat-anomaly", out, metrics=("origin_top1",))
    render = runner._gate_md

    def broken(result):
        raise RuntimeError("cannot render")

    monkeypatch.setattr(runner, "_gate_md", broken)
    before = contents(out)
    with pytest.raises(RuntimeError):
        gate_methods("pilot", "agent", "stat-anomaly", out)
    assert contents(out) == before  # no gate.json without its gate.md

    order, atomic = [], collect.faults.write_atomic

    def recording(path, content):
        order.append(path.name)
        atomic(path, content)

    monkeypatch.setattr(runner, "_gate_md", render)
    monkeypatch.setattr(collect.faults, "write_atomic", recording)
    result = gate_methods("pilot", "agent", "stat-anomaly", out)
    assert order == ["gate.md", "gate.json"]  # each replaced atomically; the decision record last
    assert json.loads((out / "pilot/agent/gate.json").read_text()) == json.loads(json.dumps(result))
    assert (out / "pilot/agent/gate.md").read_text() == render(result)


def test_every_score_reports_the_per_fault_table_and_its_missing_cells(tmp_path, monkeypatch):
    from eval.runner import run_method, score_method

    layout = pilot_incidents(tmp_path / "data", [("paymentFailure", "100%", "payment"), ("cartFailure", "100%", "cart")])
    out = tmp_path / "results"
    methods(monkeypatch, {"INC-001": "payment", "INC-002": "payment"}, {"INC-001": "payment", "INC-002": "cart"})
    run_method(layout, "stat-anomaly", "pilot", out)
    result = score_method(layout, "stat-anomaly", "pilot", out)
    table = result["by_fault"]
    assert table["faults"]["paymentFailure 100%"]["means"]["origin_top1"] == 1.0
    assert table["faults"]["cartFailure 100%"] == {"n": 1, "k": 1, "means": {"fault_type": 1.0, "origin_top1": 1.0,
                                                                              "affected_f1": 1.0, "symptom_exact": 1.0}}
    assert len(table["missing"]) == 8 and table["equal_weight"]["n_faults"] == 2
    text = (out / "pilot/stat-anomaly/table.md").read_text()
    assert "Per fault" in text and "| paymentFailure 100% | 1 / 1 |" in text and "adHighCpu on" in text


def test_on_the_heldout_set_the_gate_is_the_decision_with_the_design_k(tmp_path, monkeypatch):
    from eval.runner import compare_methods, gate_methods, run_method, score_method
    from test_eval_heldout import heldout_set

    project, layout, out = heldout_set(tmp_path, monkeypatch)  # INC-050 (H01), INC-051 (H02) listed; H03 closed; K = 3
    methods(monkeypatch, {"INC-050": "cart", "INC-051": "cart"}, {"INC-050": "payment", "INC-051": "payment"})
    with pytest.raises(PermissionError):
        gate_methods("heldout", "agent", "stat-anomaly", out)  # no layout / project: the freeze cannot be checked
    with pytest.raises(LookupError, match="cannot be evaluated yet"):
        gate_methods("heldout", "agent", "stat-anomaly", out, layout=layout, project_dir=project)
    for m in ("agent", "stat-anomaly"):
        assert run_method(layout, m, "heldout", out, project_dir=project) == []
        score_method(layout, m, "heldout", out, project_dir=project)
    compare_methods("heldout", "agent", "stat-anomaly", out, layout=layout, project_dir=project, metrics=("origin_top1",))
    result = gate_methods("heldout", "agent", "stat-anomaly", out, layout=layout, project_dir=project)
    assert result["kind"] == "gate_decision" and result["decision"] == "not_passed"
    assert "Gate decision" in result["statement"] and "first-run" in result["statement"]
    c = result["conditions"]
    assert c["1"]["by_baseline"]["stat-anomaly"]["ci95"] == [-1.0, -1.0] and not c["1"]["met"]
    pay = c["2"]["by_fault"]["paymentFailure 100%"]
    assert (pay["k"], pay["threshold"], pay["n_scored"], pay["origin_wrong"], pay["met"]) == (3, 2, 2, 2, True)
    assert c["3"]["met"] and result["heldout"]["freeze_sha256"].startswith("sha256:")
    missing = result["descriptive"]["per_fault"]["agent"]["missing"]
    assert {(m["fault"], m["slot"]) for m in missing} == {("paymentFailure 100%", "H03"), ("cartFailure 100%", None)}
    assert "closed" in next(m["reason"] for m in missing if m["slot"] == "H03")
    assert json.loads((out / "heldout/agent/scores.json").read_text())["by_fault"]["missing"] == missing
    assert "Gate decision" in (out / "heldout/agent/gate.md").read_text()
    pay_dir = result["descriptive"]["fault_directions"]["stat-anomaly"]["paymentFailure 100%"]
    assert (pay_dir["a"], pay_dir["b"], pay_dir["direction"]) == (
        {"right": 0, "scored": 2, "k": 3}, {"right": 2, "scored": 2, "k": 3}, "-")  # K = the design's slots
    # the held-out gate output lists no incident or run group id (the closed slot keeps its slot, fault and reason)
    assert result["heldout"]["closed_slots"] == [{"slot": "H03", "flag": "paymentFailure", "variant": "100%",
                                                  "reason": "fault not exercised twice: closed by default (decision 023 §5.3)"}]
    written = {name: (out / "heldout/agent" / name).read_bytes() for name in ("gate.json", "gate.md")}
    for raw in written.values():
        assert b"INC-" not in raw and b"RG-" not in raw

    # stat-anomaly scored again on fewer incidents (same freeze and list): first the comparison is stale ...
    scores = out / "heldout/stat-anomaly/scores.json"
    doc = json.loads(scores.read_text())
    scores.write_text(json.dumps({**doc, "incidents": [r for r in doc["incidents"] if r["incident_id"] != "INC-051"]},
                                 indent=2) + "\n")
    with pytest.raises(LookupError, match="again"):
        gate_methods("heldout", "agent", "stat-anomaly", out, layout=layout, project_dir=project)
    # ... and compared again, the two methods are not scored on the same incidents: no Gate decision
    compare_methods("heldout", "agent", "stat-anomaly", out, layout=layout, project_dir=project, metrics=("origin_top1",))
    with pytest.raises(ValueError, match="every listed incident"):
        gate_methods("heldout", "agent", "stat-anomaly", out, layout=layout, project_dir=project)
    assert {name: (out / "heldout/agent" / name).read_bytes() for name in ("gate.json", "gate.md")} == written

    scores.write_text(json.dumps({**json.loads(scores.read_text()), "heldout": {"freeze_sha256": "sha256:old"}}))
    with pytest.raises(PermissionError, match="stat-anomaly"):
        gate_methods("heldout", "agent", "stat-anomaly", out, layout=layout, project_dir=project)


def test_the_cli_reports_that_the_gate_cannot_be_evaluated_without_agent_scores_and_writes_nothing(tmp_path, monkeypatch,
                                                                                                  capsys):
    import eval.__main__ as cli

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    pilot_incidents(tmp_path / "data/external", [("paymentFailure", "100%", "payment")])
    before = files(tmp_path)
    assert cli.main(["gate", "--method", "agent", "--against", "stat-anomaly", "--set", "pilot"]) == 2
    err = capsys.readouterr().err
    assert "cannot be evaluated yet" in err and "Traceback" not in err
    assert files(tmp_path) == before
    assert cli.main(["gate", "--method", "stat-anomaly", "--against", "stat-anomaly", "--set", "pilot"]) == 2
    assert "agent" in capsys.readouterr().err


def test_the_cli_prints_a_summary_that_says_a_pilot_gate_is_not_a_gate_decision(tmp_path, monkeypatch, capsys):
    import eval.__main__ as cli
    from eval.runner import compare_methods, run_method, score_method

    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    layout = pilot_incidents(tmp_path / "data/external", [("paymentFailure", "100%", "payment")])
    out = tmp_path / "data/external/results"
    methods(monkeypatch, {"INC-001": "payment"}, {"INC-001": "cart"})
    for m in ("agent", "stat-anomaly"):
        run_method(layout, m, "pilot", out)
        score_method(layout, m, "pilot", out)
    compare_methods("pilot", "agent", "stat-anomaly", out, metrics=("origin_top1",))
    assert cli.main(["gate", "--method", "agent", "--against", "stat-anomaly", "--set", "pilot"]) == 0
    text = capsys.readouterr().out
    assert "NOT a Gate decision" in text and "condition 1" in text and "gate.json" in text
    assert (out / "pilot/agent/gate.json").exists() and (out / "pilot/agent/gate.md").exists()
