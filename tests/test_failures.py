"""Failure taxonomy v1 (decision 022): one category per failure, by a fixed order."""

from eval.failures import CATEGORIES, classify, origin_evidence_seen
from test_relevance import FAULT_ON, LABEL, S, SNAP, W0, sid

RIGHT = {"origin_top1": 1.0, "fault_type": 1.0}
WRONG_ORIGIN = {"origin_top1": 0.0, "fault_type": 1.0}
PRED = {"origin_candidates": ["cart"]}
REVIEWED = {**LABEL, "labeling": {"method": "catalog+review"},
            "telemetry_coverage": {"traces": "origin", "metrics": "none", "logs": "symptom_only"}}


def transcript(*exposure, stop="submitted"):
    return {"stop_reason": stop, "exposure": list(exposure)}


def test_the_categories_and_their_order():
    assert CATEGORIES == ("no_answer", "coverage", "mechanism", "not_seen", "seen_misread", "rule_limit")
    assert classify(PRED, REVIEWED, RIGHT, transcript(), SNAP) is None  # not a failure
    assert classify({"origin_candidates": []}, REVIEWED, WRONG_ORIGIN, None, SNAP) == "no_answer"
    assert classify(PRED, REVIEWED, WRONG_ORIGIN, transcript(sid(1), stop="turn_limit"), SNAP) == "no_answer"
    invisible = {**REVIEWED, "telemetry_coverage": {"traces": "symptom_only", "metrics": "none", "logs": "none"}}
    assert classify(PRED, invisible, WRONG_ORIGIN, transcript(sid(1)), SNAP) == "coverage"
    assert classify({"origin_candidates": ["payment"]}, REVIEWED, {"origin_top1": 1.0, "fault_type": 0.0},
                    transcript(), SNAP) == "mechanism"
    assert classify(PRED, REVIEWED, WRONG_ORIGIN, transcript(sid(3)), SNAP) == "not_seen"  # only a cart span
    assert classify(PRED, REVIEWED, WRONG_ORIGIN, transcript(sid(3), sid(1)), SNAP) == "seen_misread"
    assert classify(PRED, REVIEWED, WRONG_ORIGIN, None, SNAP) == "rule_limit"  # no exposure log (statistical baseline)


def test_coverage_needs_a_reviewed_label():
    a_priori = {**LABEL, "labeling": {"method": "catalog"}}
    assert classify(PRED, a_priori, WRONG_ORIGIN, transcript(sid(3)), SNAP) == "not_seen"


def test_what_counts_as_origin_evidence_in_the_fault_period():
    def seen(*exposure, offset=0.0):
        return origin_evidence_seen(list(exposure), SNAP, LABEL, clock_offset_s=offset)

    assert seen(sid(1)) and not seen(sid(4))  # a payment span in the fault period / in the normal period
    assert not seen(sid(1), offset=120.0)  # the data clock 120 s ahead: that span is before the fault
    assert seen(sid(5, "m"))  # a metric series of the origin
    assert seen("stats:payment:9-10") and not seen("stats:payment:0-9") and not seen("stats:cart:10-20")
    assert seen("stats:*")  # the overview block of dump-all and retrieval covers every service and minute
    assert not seen("s-" + "f" * 16)  # unresolved ids count for nothing
    assert FAULT_ON == W0 + 600 * S
