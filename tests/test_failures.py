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


def test_label_times_map_onto_the_data_clock_exactly_as_the_snapshot_window_does():
    # clock audit: int() on the offset vs normalize's round() put fault_on 1 ns before minute 10 of the window
    from collect.normalize import host_to_data_ns

    offset = 120.3000000006
    start = host_to_data_ns("2026-10-08T11:46:40Z", offset)  # how normalize sets window.start_ns
    assert start == host_to_data_ns("2026-10-08T11:46:40Z", 0.0) + round(offset * 1e9)

    class Win:
        window = {"start_ns": start}

        def resolve(self, i):
            return None

    label = {"origin_service": "payment", "fault_start": "2026-10-08T11:56:40Z", "fault_end": "2026-10-08T12:06:40Z"}
    assert not origin_evidence_seen(["stats:payment:0-9"], Win(), label, clock_offset_s=offset)  # normal minutes only
    assert origin_evidence_seen(["stats:payment:10-10"], Win(), label, clock_offset_s=offset)
