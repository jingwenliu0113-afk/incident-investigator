"""Evidence relevance (SPEC Core §9, decision 017): weak temporal / service labels and a blind human gold subset."""

import pytest

from eval.relevance import GOLD_PER_METHOD, check_gold, gold_sample, gold_score, merge_gold, weak_score

S = 10**9
W0 = 1_791_460_000 * S  # window start, data clock
FAULT_ON, FAULT_OFF = W0 + 600 * S, W0 + 1200 * S  # 11:56:40Z .. 12:06:40Z
LABEL = {"incident_id": "INC-001", "origin_service": "payment", "affected_services": ["payment", "checkout"],
         "fault_start": "2026-10-08T11:56:40Z", "fault_end": "2026-10-08T12:06:40Z"}


def sid(i, kind="s"):
    return f"{kind}-{i:016x}"


class Snap:
    def __init__(self, records):
        self.records = {r["id"]: r for r in records}
        self.window = {"start_ns": W0, "end_ns": W0 + 1800 * S}

    def spans(self):
        return (r for r in self.records.values() if r["id"].startswith("s-"))

    def resolve(self, evidence_id, t0=None, t1=None):
        if evidence_id.startswith("t-"):
            return {"trace_id": evidence_id[2:]} if any(s["trace_id"] == evidence_id[2:] for s in self.spans()) else None
        return self.records.get(evidence_id)


def span(i, t, service, trace="aa"):
    return {"id": sid(i), "trace_id": trace, "service": service, "start_time_unix_nano": t, "end_time_unix_nano": t + S}


SNAP = Snap([span(1, FAULT_ON + 30 * S, "payment", trace="1" * 32), span(3, FAULT_ON + 10 * S, "cart"),
             span(4, W0 + 60 * S, "payment"), span(6, FAULT_ON + 40 * S, "frontend", trace="1" * 32),
             {"id": sid(2, "l"), "service": "checkout", "time_unix_nano": FAULT_OFF + 30 * S, "observed_time_unix_nano": None},
             {"id": sid(5, "m"), "service": "payment", "metric": "x"}])


def test_weak_labels_are_temporal_with_a_60_s_tail_and_service_in_the_affected_set():
    cited = [{"id": sid(1)}, {"id": sid(2, "l")}, {"id": sid(3)}, {"id": sid(4)},
             {"id": sid(5, "m"), "t0": FAULT_ON + 100 * S, "t1": FAULT_ON + 200 * S},
             {"id": sid(5, "m")},  # a series without a range has no time
             {"id": "t-" + "1" * 32}, {"id": sid(404)}, {"id": sid(1)}]  # unresolved and repeated citations do not count  # unresolved and repeated citations do not count
    out = weak_score(cited, SNAP, LABEL)
    assert out["n"] == 7
    assert out["temporal"] == pytest.approx(5 / 7)  # all but s-4 (normal period) and m-5 without a range
    assert out["service"] == pytest.approx(6 / 7)  # all but cart
    assert out["origin"] == pytest.approx(5 / 7)  # s-1, s-4, both m-5, and the trace through payment
    assert out["weak"] == pytest.approx(4 / 7)  # s-1, l-2, m-5 with range, the trace
    late = weak_score([{"id": sid(2, "l")}], SNAP, {**LABEL, "fault_end": "2026-10-08T12:05:00Z"})
    assert late["temporal"] == 0.0  # 130 s after the fault: outside the tail


def test_the_fault_window_moves_with_the_measured_clock_offset_and_no_citation_gives_null():
    assert weak_score([{"id": sid(1)}], SNAP, LABEL, clock_offset_s=120.0)["temporal"] == 0.0  # data clock 120 s ahead
    assert weak_score([], SNAP, LABEL) == {"n": 0, "temporal": None, "service": None, "origin": None, "weak": None}
    assert weak_score([{"id": sid(404)}], SNAP, LABEL)["weak"] is None


def item(i, t0=None, t1=None):
    return {"id": sid(i), "t0": t0, "t1": t1}


def test_the_gold_sample_is_fixed_per_method_blind_and_skips_what_is_annotated():
    cited = {"stat-anomaly": [{"id": sid(i)} for i in range(12)], "agent": [{"id": sid(1)}, {"id": sid(99)}]}
    one = gold_sample("INC-001", {"stat-anomaly": cited["stat-anomaly"]}, annotated=set())
    assert len(one) == GOLD_PER_METHOD == 5
    both = gold_sample("INC-001", cited, annotated=set())
    assert set(map(str, one)) <= set(map(str, both))  # adding a method never changes another method's sample
    assert len(both) <= 7 and all(set(e) == {"id", "t0", "t1"} for e in both)  # no method name, no weak label
    assert gold_sample("INC-001", cited, annotated=set()) == both  # deterministic
    done = {(sid(1), None, None), (sid(99), None, None)}
    assert all((e["id"], e["t0"], e["t1"]) not in done for e in gold_sample("INC-001", cited, annotated=done))


def gold(*judged, annotator="human:jw"):
    return {"gold_version": 1, "incident_id": "INC-001",
            "items": [{"id": i, "t0": None, "t1": None, "relevant": r, "annotator": annotator,
                       "annotated_at": "2026-10-09T10:00:00Z"} for i, r in judged]}


def test_gold_precision_counts_only_judged_citations_and_reports_coverage():
    out = gold_score([{"id": sid(1)}, {"id": sid(3)}, {"id": sid(4)}, {"id": sid(404)}], SNAP,
                     gold((sid(1), True), (sid(3), False)))
    assert out == {"cited": 3, "judged": 2, "relevant": 1, "precision": 0.5, "coverage": pytest.approx(2 / 3)}
    assert gold_score([{"id": sid(4)}], SNAP, gold((sid(1), True)))["precision"] is None


def test_gold_judgments_are_human_append_only_and_schema_checked():
    doc = merge_gold(None, "INC-001", [{**item(1), "relevant": True}], annotator="human:jw", now="2026-10-09T10:00:00Z")
    assert check_gold(doc) == [] and doc["items"][0]["annotator"] == "human:jw"
    doc = merge_gold(doc, "INC-001", [{**item(1), "relevant": True}, {**item(3), "relevant": False}],
                     annotator="human:jw", now="2026-10-09T10:05:00Z")  # the same judgment again is fine
    assert [(e["id"], e["relevant"]) for e in doc["items"]] == [(sid(1), True), (sid(3), False)]
    with pytest.raises(ValueError, match="already judged"):
        merge_gold(doc, "INC-001", [{**item(1), "relevant": False}], annotator="human:other", now="2026-10-09T11:00:00Z")
    with pytest.raises(ValueError, match="human"):
        merge_gold(None, "INC-001", [{**item(1), "relevant": True}], annotator="agent:claude-code", now="2026-10-09T10:00:00Z")
    with pytest.raises(ValueError, match="relevant"):
        merge_gold(None, "INC-001", [{**item(1), "relevant": None}], annotator="human:jw", now="2026-10-09T10:00:00Z")
    assert check_gold({**doc, "items": [{**doc["items"][0], "extra": 1}]})  # additionalProperties: false
