"""The held-out fault plan (decision 023 §1): the Pilot plan plus only the differences Pilot review found, and removals
only on Pilot validation evidence (user decision 5), never on a method score."""

import json

import pytest

from collect.heldout import PLAN_FILE, build_heldout_plan, pilot_evidence, pilot_problems, plan_entries
from collect.layout import DataLayout
from collect.pilot import PILOT, planned
from heldout_fixtures import a_priori, complete_pilot, write_audit, write_review, write_run

CART = ("cartFailure", "100%")
SHIP = ("intlShippingSlowdown", "10sec")
OTHERS = [e for e in PILOT if (e["flag"], e["variant"]) not in (CART, SHIP)]
WIDER = ["cart", "checkout", "frontend", "frontend-proxy"]
DECISION = "docs/decisions/027-a-pipeline-bug.md"


def pilot(tmp_path, cart=({},), ship=({},), ship_invalid=0):
    """Every other fault: one clean, exercised, blind review. `cart` / `ship`: one review per dict (write_review keywords,
    plus `hits` for the leakage audit); `ship_invalid` non-valid run groups of intlShippingSlowdown."""
    layout = DataLayout(tmp_path / "data")
    n = complete_pilot(layout, OTHERS)
    for fault, reviews in ((CART, cart), (SHIP, ship)):
        for kw in reviews:
            kw = dict(kw)
            hits = kw.pop("hits", 0)
            write_run(layout, f"RG-{n:03d}", *fault, inc=f"INC-{n:03d}")
            write_review(layout, f"INC-{n:03d}", *fault, **kw)
            write_audit(layout, f"INC-{n:03d}", hits)
            n += 1
    for _ in range(ship_invalid):
        write_run(layout, f"RG-{n:03d}", *SHIP, status="invalid")
        n += 1
    return layout


def build(layout, amend=(), remove=(), decisions=(DECISION,)):
    return build_heldout_plan(pilot_evidence(layout), {"amend": list(amend), "remove": list(remove)},
                              decision_files=set(decisions), methods_with_results=["stat-anomaly"])


def amendment(value=WIDER, field="affected_services", reason="checkout and the edge time out on EmptyCart", fault=CART):
    return {"flag": fault[0], "variant": fault[1], "field": field, "value": value, "reason": reason}


def entry_of(plan, fault):
    return next(e for e in plan["entries"] if (e["flag"], e["variant"]) == fault)


def test_the_heldout_plan_is_read_only_from_an_explicit_project_directory(tmp_path):
    with pytest.raises(LookupError, match="no fault plan"):
        planned("heldout", "paymentFailure", "100%", project_dir=tmp_path)  # not written yet (after the Pilot review)
    with pytest.raises(LookupError):
        planned("heldout", "paymentFailure", "100%")  # never from an implicit directory
    (tmp_path / PLAN_FILE).parent.mkdir(parents=True)
    (tmp_path / PLAN_FILE).write_text(json.dumps({"entries": [dict(PILOT[0], affected=["payment"])]}))
    assert planned("heldout", "paymentFailure", "100%", project_dir=tmp_path)["affected"] == ["payment"]
    assert planned("heldout", "cartFailure", "100%", project_dir=tmp_path) is None
    assert plan_entries(tmp_path)[0]["flag"] == "paymentFailure"


def test_without_amendments_the_plan_is_the_pilot_plan_in_pilot_order(tmp_path):
    plan = build(pilot(tmp_path))
    assert plan["entries"] == [dict(e) for e in PILOT]
    assert plan["amended"] == plan["removed"] == plan["not_absorbed"] == []
    assert plan["methods_with_pilot_results"] == ["stat-anomaly"] and plan["decision"] == "023 §1"
    assert list(plan) == ["heldout_plan_version", "decision", "source", "entries", "amended", "not_absorbed", "removed",
                          "methods_with_pilot_results"]


@pytest.mark.parametrize("change, message", [
    ({"field": "origin"}, "cannot be amended"),
    ({"field": "variant"}, "cannot be amended"),
    ({"flag": "kafkaQueueProblems", "variant": "on"}, "not a Pilot fault"),  # no new fault
    ({"variant": "10%"}, "not a Pilot fault"),  # no new variant
])
def test_only_the_reviewable_fields_of_pilot_faults_can_be_amended(tmp_path, change, message):
    with pytest.raises(ValueError, match=message):
        build(pilot(tmp_path, cart=({"affected_services": WIDER},)), amend=[{**amendment(), **change}])


def test_a_fault_is_amended_or_removed_never_both_and_each_field_once(tmp_path):
    layout = pilot(tmp_path, cart=({"affected_services": WIDER},), ship=({"exercised": False}, {"exercised": False}))
    with pytest.raises(ValueError, match="both"):
        build(layout, amend=[amendment(fault=CART)],
              remove=[{"flag": "cartFailure", "variant": "100%", "basis": "pipeline", "reason": "x", "decision": DECISION},
                      {"flag": "intlShippingSlowdown", "variant": "10sec", "basis": "not_exercised", "reason": "x"}])
    with pytest.raises(ValueError, match="twice"):
        build(layout, amend=[amendment(), amendment()],
              remove=[{"flag": "intlShippingSlowdown", "variant": "10sec", "basis": "not_exercised", "reason": "x"}])


SLOW = {"kinds": ["latency"], "description": "orders slow down while carts are emptied"}


@pytest.mark.parametrize("reviews, amend, ok", [
    ([{"affected_services": WIDER}, {"affected_services": WIDER}], amendment(), True),
    ([{"affected_services": WIDER}], amendment(value=list(reversed(WIDER))), True),  # lists compare sorted
    ([{"user_symptom": SLOW}], amendment(field="user_symptom", value=SLOW), True),
    ([{"user_symptom": SLOW}], amendment(field="user_symptom", value={"kinds": ["latency"], "description": "x"}), False),
    ([{"user_symptom": SLOW}], amendment(field="user_symptom", value=SLOW["description"]), False),  # the whole object
    ([{"affected_services": WIDER}, {}], amendment(), False),  # two eligible reviews disagree
    ([{}, {"affected_services": WIDER, "exercised": False}], amendment(), False),  # only an unexercised review saw it
    ([{}, {"affected_services": WIDER, "saw": True}], amendment(), False),  # only a review that saw method outputs
    ([{}], amendment(), False),  # no difference was found at all
    ([{"affected_services": WIDER}], amendment(reason="  "), False),
    ([{"affected_services": WIDER}], amendment(reason="as seen in INC-001"), False),  # no id in committed text
    ([{"notes": "slow EmptyCart, see RG-002"}], amendment(field="notes", value="slow EmptyCart, see RG-002"), False),
    ([{"affected_services": ["checkout", "frontend"]}], amendment(value=["checkout", "frontend"]), False),  # origin kept
    ([{"affected_services": ["cart", "load-generator"]}], amendment(value=["cart", "load-generator"]), False),  # SUT only
    ([{"user_symptom": {"kinds": ["none", "errors"], "description": "x"}}],
     amendment(field="user_symptom", value={"kinds": ["none", "errors"], "description": "x"}), False),
], ids=["agreed", "order", "symptom", "symptom-other", "description-only", "disagree", "unexercised", "saw", "no-diff",
        "no-reason", "id-reason", "id-value", "origin", "non-sut", "none-and-errors"])
def test_only_differences_that_every_exercised_blind_review_found_are_absorbed(tmp_path, reviews, amend, ok):
    layout = pilot(tmp_path, cart=reviews)
    if not ok:
        with pytest.raises(ValueError):
            build(layout, amend=[amend])
        return
    plan = build(layout, amend=[amend])
    field = amend["field"]
    entry = entry_of(plan, CART)
    if field == "affected_services":
        assert sorted(entry["affected"]) == sorted(amend["value"])
    else:
        assert {"kinds": entry["symptom_kinds"], "description": entry["description"]} == amend["value"]
    assert entry["origin"] == "cart"
    (record,) = plan["amended"]
    assert record["field"] == field and record["reviews"] == len(reviews) and record["reason"] == amend["reason"]
    assert record["a_priori"] == a_priori(*CART)[field]


@pytest.mark.parametrize("reviews, why", [
    ([{"affected_services": WIDER}], "not absorbed"),
    ([{}, {"affected_services": WIDER, "exercised": False}], "not_exercised"),
    ([{}, {"affected_services": WIDER, "saw": True}], "saw_method_outputs"),
    ([{}, {"affected_services": WIDER}], "reviews disagree"),
])
def test_differences_not_absorbed_are_recorded_as_counts_without_values(tmp_path, reviews, why):
    plan = build(pilot(tmp_path, cart=reviews))
    assert plan["not_absorbed"] == [{"flag": "cartFailure", "variant": "100%", "field": "affected_services", "reviews": 1,
                                     "why": why}]
    assert entry_of(plan, CART) == dict(PILOT[3])


REMOVE = {"flag": "intlShippingSlowdown", "variant": "10sec", "reason": "no non-US order in either fault period"}


@pytest.mark.parametrize("ship, invalid, removal, ok", [
    ([{"exercised": False}, {"exercised": False}], 0, {"basis": "not_exercised"}, True),
    ([{"exercised": False}], 0, {"basis": "not_exercised"}, False),  # 016 §5: one recollection first
    ([], 3, {"basis": "invalid_rate"}, True),
    ([], 2, {"basis": "invalid_rate"}, False),
    ([{"hits": 2}], 0, {"basis": "lexicon_hits"}, True),
    ([{"hits": 2}, {}], 0, {"basis": "lexicon_hits"}, False),  # a clean exercised incident exists
    ([{}], 0, {"basis": "pipeline"}, False),  # pipeline / label need a decision
    ([{}], 0, {"basis": "pipeline", "decision": "docs/decisions/099-missing.md"}, False),  # not at HEAD
    ([{}], 0, {"basis": "label", "decision": DECISION}, True),
    ([{}], 0, {"basis": "score"}, False),  # never a method score
    ([{}], 0, {"basis": "not_exercised"}, False),  # it passes: no evidence for removal
    ([{}], 0, {"basis": "not_exercised", "reason": ""}, False),
], ids=["not-exercised", "one-unexercised", "invalid", "two-invalid", "lexicon", "lexicon-clean", "no-decision",
        "decision-missing", "label", "score", "passes", "no-reason"])
def test_a_fault_is_removed_only_on_pilot_validation_evidence(tmp_path, ship, invalid, removal, ok):
    layout = pilot(tmp_path, ship=ship, ship_invalid=invalid)
    if not ok:
        with pytest.raises(ValueError):
            build(layout, remove=[{**REMOVE, **removal}])
        return
    plan = build(layout, remove=[{**REMOVE, **removal}])
    assert SHIP not in [(e["flag"], e["variant"]) for e in plan["entries"]] and len(plan["entries"]) == 9
    (record,) = plan["removed"]
    assert record["basis"] == removal["basis"] and record["decision"] == removal.get("decision")
    assert set(record["evidence"]) == {"reviewed_exercised", "reviewed_unexercised", "non_valid_run_groups",
                                       "lexicon_hit_incidents"}
    assert record["evidence"]["non_valid_run_groups"] == invalid


def test_a_kept_fault_needs_a_reviewed_exercised_pilot_incident(tmp_path):
    with pytest.raises(ValueError, match="intlShippingSlowdown"):
        build(pilot(tmp_path, ship=({"exercised": False}, {"exercised": False})))
    with pytest.raises(ValueError, match="intlShippingSlowdown"):
        build(pilot(tmp_path / "b", ship=()))


def test_pilot_problems_name_unreviewed_incidents_and_faults_never_exercised(tmp_path):
    layout = pilot(tmp_path, ship=({"exercised": False},))
    assert pilot_problems(layout, removed=set()) == [
        "intlShippingSlowdown 10sec: no reviewed Pilot incident with fault_exercised = true (decision 023 §1)"]
    assert pilot_problems(layout, removed={SHIP}) == []
    write_run(layout, "RG-050", *CART, inc="INC-050")  # valid, not reviewed yet
    assert any("INC-050" in p and "review" in p for p in pilot_problems(layout, removed={SHIP}))
