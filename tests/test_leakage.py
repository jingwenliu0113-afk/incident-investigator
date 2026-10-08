"""Leakage audit v1 (SPEC Core §6, decision 015): what in the agent-readable snapshot gives the answer away."""

from eval.leakage import audit, template

S = 10**9
W0 = 1_791_460_000 * S  # window start, data clock
LABEL = {"incident_id": "INC-001", "origin_service": "payment", "fault_start": "2026-10-08T11:56:40Z",
         "fault_end": "2026-10-08T12:06:40Z", "injected_fault": {"fault_type": "error_response"}}
FAULT_ON = W0 + 600 * S  # 11:56:40Z = W0 + 10 min


class Snap:
    def __init__(self, spans=(), logs=()):
        self._spans, self._logs = list(spans), list(logs)
        self.window = {"start_ns": W0, "end_ns": W0 + 1800 * S}

    def spans(self):
        return iter(self._spans)

    def logs(self):
        return iter(self._logs)


def span(t, service, message=None, error=False, events=()):
    return {"id": f"s-{t:016x}"[-18:], "service": service, "start_time_unix_nano": t, "status_code": "error" if error else "unset",
            "status_message": message, "events": [{"name": e, "time_unix_nano": t} for e in events], "name": "op"}


def log(t, service, body, severity=17):
    return {"id": f"l-{t:016x}"[-18:], "service": service, "time_unix_nano": t, "observed_time_unix_nano": t,
            "severity_number": severity, "body": body, "event_name": None}


def test_templates_mask_ids_and_numbers_but_keep_words():
    assert template("order 3f2a9c1e-77aa-4b1c-9d2e-0123456789ab failed after 1250 ms") == "order <uuid> failed after <n> ms"
    assert template("trace 4bf92f3577b34da6a3ce929d0e0e4736 x") == "trace <hex> x"
    assert template("Payment request failed. Invalid token.") == "Payment request failed. Invalid token."
    # decision 015 revision 1: a whole word with a digit is one value (product ids, addresses), not letters around numbers
    assert template("Receive ListRecommendations for product ids:['0PUK6V6EV0', 'L9ECAV7KIM']") == \
        "Receive ListRecommendations for product ids:['<n>', '<n>']"
    assert template("GET /api/products/OLJCESPC7Z x=5, dial 10.0.0.5:50051 v1.2") == "GET /api/products/<n> x=<n>, dial <n>:<n> <n>"


def test_an_error_only_the_origin_emits_during_the_fault_is_easy():
    snap = Snap(logs=[log(W0 + 60 * S, "payment", "charged 12 USD", severity=9),
                      log(FAULT_ON + 30 * S, "payment", "Payment request failed. Invalid token. loyalty_level=gold"),
                      log(FAULT_ON + 90 * S, "payment", "Payment request failed. Invalid token. loyalty_level=gold")])
    out = audit(snap, LABEL)
    assert out["difficulty"] == "easy"
    top = out["fault_only_templates"][0]
    assert top["services"] == ["payment"] and top["fault"] == 2 and top["normal"] == 0 and top["error_level"]


def test_errors_only_downstream_of_the_origin_are_medium_and_nothing_new_is_hard():
    snap = Snap(spans=[span(FAULT_ON + 30 * S, "checkout", "failed to charge card: rpc error", error=True),
                       span(W0 + 30 * S, "checkout", "failed to get product", error=True),
                       span(FAULT_ON + 40 * S, "checkout", "failed to get product", error=True)])
    out = audit(snap, LABEL)
    assert out["difficulty"] == "medium" and [t["template"] for t in out["fault_only_templates"]] == [
        "failed to charge card: rpc error"]  # the product error also occurred before the fault: not fault-only
    assert out["origin_named"] == []  # no fault-only text names "payment"
    assert audit(Snap(spans=[span(W0 + 30 * S, "checkout", "ok")]), LABEL)["difficulty"] == "hard"


def test_fault_only_text_that_names_the_origin_is_listed_and_the_clock_offset_moves_the_window():
    snap = Snap(spans=[span(FAULT_ON + 31 * S, "checkout", "could not reach payment service", error=True)])
    out = audit(snap, LABEL)
    assert out["origin_named"] == ["could not reach payment service"]
    # the label is on the host clock; the snapshot on the data clock (VM 120 s ahead): the same span is now before the fault
    assert audit(snap, LABEL, clock_offset_s=120.0)["fault_only_templates"] == []


def test_lexicon_hits_and_new_keys_are_reported_for_review():
    snap = Snap(logs=[log(FAULT_ON + 5 * S, "cart", "flagd sync failed")])
    out = audit(snap, LABEL, new_attribute_keys={"traces/cart": ["app.retry.reason"]})
    assert out["lexicon_hits"] == 1 and out["new_attribute_keys"] == {"traces/cart": ["app.retry.reason"]}
