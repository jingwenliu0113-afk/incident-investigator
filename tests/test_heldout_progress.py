"""Held-out collection progress (decision 023 §4, §5.3): slots in slot order, invalid run groups counted per slot,
unexercised slots recollected once then closed, and any corrupt or foreign record stops collection."""

import json

import pytest

from collect.heldout import fresh_seed, heldout_runs, heldout_slots, next_slot, slot_status
from collect.layout import DataLayout
from heldout_fixtures import FREEZE_SHA, write_review, write_run

FAULTS = [["paymentFailure", "100%"], ["cartFailure", "100%"], ["adHighCpu", "on"], ["adManualGc", "on"]]
SLOTS = {"slots": heldout_slots(FAULTS, k=2)}
STATES = {"slots": SLOTS["slots"][:1]}


class Counter:
    def __init__(self):
        self.n = 0

    def __call__(self, prefix):
        self.n += 1
        return f"{prefix}-{self.n:03d}"


def held(layout, ids, slot, status="valid", exercised=None, **kw):
    """One held-out run group filling `slot` (a SLOTS entry); a valid one gets an incident, reviewed when `exercised`."""
    rg, inc = ids("RG"), None
    if status == "valid":
        inc = rg.replace("RG", "INC")
    write_run(layout, rg, slot["flag"], slot["variant"], status, inc=inc, split="heldout", slot=slot["slot"],
              freeze_sha=FREEZE_SHA, **kw)
    if exercised is not None:
        write_review(layout, inc, slot["flag"], slot["variant"], exercised=exercised)
    return rg


def states(layout, slots=SLOTS):
    return [s["state"] for s in slot_status(layout, slots, freeze_sha=FREEZE_SHA)]


def test_next_is_the_first_open_slot_in_slot_order(tmp_path):
    layout, ids = DataLayout(tmp_path), Counter()
    first = next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)
    assert first["slot"] == "H01" and (first["flag"], first["variant"]) == (SLOTS["slots"][0]["flag"], SLOTS["slots"][0]["variant"])
    held(layout, ids, SLOTS["slots"][0])
    assert next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)["slot"] == "H02"
    held(layout, ids, SLOTS["slots"][2])  # filled out of order: H02 is still next
    assert next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)["slot"] == "H02"
    assert next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)["skipped"] == []


def test_pilot_and_pre_split_run_groups_never_fill_a_slot(tmp_path):
    layout = DataLayout(tmp_path)
    slot = SLOTS["slots"][0]
    write_run(layout, "RG-001", slot["flag"], slot["variant"], inc="INC-001")
    write_run(layout, "RG-002", slot["flag"], slot["variant"], inc="INC-002", split=None)
    assert states(layout)[0] == "open" and heldout_runs(layout) == []


@pytest.mark.parametrize("kw, message", [
    ({"slot": None}, "slot"),
    ({"slot": "H99"}, "slot"),
    ({"flag": "adFailure"}, "slot"),
    ({"freeze_sha": "sha256:" + "a" * 64}, "freeze"),  # collected under another freeze record: never filtered out
    ({"injection_split": "pilot"}, "injection"),
], ids=["no-slot", "unknown-slot", "other-fault", "other-freeze", "split-disagrees"])
def test_a_corrupt_or_foreign_heldout_record_stops_everything(tmp_path, kw, message):
    layout = DataLayout(tmp_path)
    slot = SLOTS["slots"][0]
    args = {"inc": "INC-001", "split": "heldout", "slot": "H01", "freeze_sha": FREEZE_SHA, **kw}
    write_run(layout, "RG-001", args.pop("flag", slot["flag"]), slot["variant"], **args)
    with pytest.raises(ValueError, match=message):
        slot_status(layout, SLOTS, freeze_sha=FREEZE_SHA)
    with pytest.raises(ValueError):
        next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)


def test_a_pilot_run_group_whose_injection_says_heldout_is_refused(tmp_path):
    layout = DataLayout(tmp_path)
    write_run(layout, "RG-001", "paymentFailure", "100%", inc="INC-001", injection_split="heldout")
    with pytest.raises(ValueError, match="injection"):
        heldout_runs(layout)


def test_a_valid_run_whose_injection_names_another_fault_is_refused(tmp_path):
    layout, slot = DataLayout(tmp_path), SLOTS["slots"][0]
    write_run(layout, "RG-001", slot["flag"], slot["variant"], inc="INC-001", split="heldout", slot="H01", freeze_sha=FREEZE_SHA)
    path = layout.injection_path("RG-001")
    path.write_text(json.dumps({**json.loads(path.read_text()), "fault": {"mechanism": "flagd", "flag": "x", "variant": "y"}}))
    with pytest.raises(ValueError, match="injection"):
        slot_status(layout, SLOTS, freeze_sha=FREEZE_SHA)


@pytest.mark.parametrize("runs, state", [
    ([("invalid", None), ("aborted_unstable", None), ("aborted_error", None)], "needs_person"),
    ([("invalid", None), ("aborted_up_failed", None)], "open"),
    ([("valid", False)], "open"),  # 016 §5: recollected once
    ([("valid", False), ("valid", False)], "closed"),  # 023 §5.3: closed by default and listed
    ([("invalid", None)] * 3 + [("valid", None)], "filled"),
    ([("valid", True)], "filled"),
    ([("valid", False), ("valid", None)], "filled"),
    ([("valid", False), ("valid", False)] + [("invalid", None)] * 3, "needs_person"),
    ([("valid", None), ("valid", None)], ValueError),  # one slot holds one incident
    ([("valid", False)] * 3, ValueError),
])
def test_slot_states_follow_filled_needs_person_closed_open(tmp_path, runs, state):
    layout, ids = DataLayout(tmp_path), Counter()
    for status, exercised in runs:
        held(layout, ids, SLOTS["slots"][0], status, exercised)
    if state is ValueError:
        with pytest.raises(ValueError):
            states(layout, STATES)
    else:
        assert states(layout, STATES) == [state]


def test_status_shows_counts_non_valid_run_groups_and_power_but_no_incident_or_valid_run_group_ids(tmp_path):
    layout, ids = DataLayout(tmp_path), Counter()
    bad = held(layout, ids, SLOTS["slots"][0], "invalid")
    good = held(layout, ids, SLOTS["slots"][0], power={"source": "AC Power", "settings": {"powermode": "2"}})
    (row,) = slot_status(layout, STATES, freeze_sha=FREEZE_SHA)
    assert row["state"] == "filled" and row["non_valid_run_groups"] == [bad]
    assert row["counts"] == {"usable": 1, "unexercised": 0, "non_valid": 1}
    assert row["power"] == [{"source": "AC Power", "settings": {"powermode": "2"}}]
    text = json.dumps(row)
    assert good not in text and "INC-" not in text


def test_next_skips_slots_that_need_a_person_and_stops_at_three_or_when_nothing_else_is_open(tmp_path):
    layout, ids = DataLayout(tmp_path), Counter()
    for _ in range(3):
        bad = held(layout, ids, SLOTS["slots"][0], "invalid")
    nxt = next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)
    assert nxt["slot"] == "H02" and nxt["skipped"] == [{"slot": "H01", "non_valid_run_groups": ["RG-001", "RG-002", bad]}]
    for _ in range(3):
        held(layout, ids, SLOTS["slots"][1], "aborted_unstable")
    nxt = next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)  # two slots wait for a person: collection goes on (023 §4)
    assert nxt["slot"] == "H03" and [s["slot"] for s in nxt["skipped"]] == ["H01", "H02"]
    for _ in range(3):
        held(layout, ids, SLOTS["slots"][2], "aborted_unstable")
    with pytest.raises(RuntimeError, match="3 slots"):
        next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)

    layout, ids = DataLayout(tmp_path / "b"), Counter()
    for _ in range(3):
        held(layout, ids, SLOTS["slots"][0], "invalid")
    for slot in SLOTS["slots"][1:]:
        held(layout, ids, slot)
    with pytest.raises(RuntimeError, match="H01"):  # nothing open, one waits for a person: not complete
        next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)

    layout, ids = DataLayout(tmp_path / "c"), Counter()
    held(layout, ids, SLOTS["slots"][0], exercised=False)
    held(layout, ids, SLOTS["slots"][0], exercised=False)
    for slot in SLOTS["slots"][1:]:
        held(layout, ids, slot)
    assert next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA) is None  # every slot filled or closed


class Draws:
    def __init__(self, *values):
        self.values = list(values)

    def randrange(self, n):
        assert n == 2**31
        return self.values.pop(0)


def test_a_fresh_seed_is_never_one_any_run_group_used(tmp_path):
    layout = DataLayout(tmp_path)
    write_run(layout, "RG-001", "paymentFailure", "100%", inc="INC-001", seed=11)
    write_run(layout, "RG-002", "cartFailure", "100%", "invalid", seed=12, split="heldout", slot="H02", freeze_sha=FREEZE_SHA)
    assert fresh_seed(layout, Draws(11, 12, 13)) == 13
    assert 0 <= fresh_seed(layout) < 2**31


WITHDRAWN_AT = "2026-10-22T00:00:00Z"


def hand_withdrawal(layout, rg, incident_ids):
    """A withdrawn.json written by hand, as collect.pilot.withdraw would write it."""
    from collect.pilot import WITHDRAWAL

    (layout.run_group_truth_dir(rg) / WITHDRAWAL).write_text(json.dumps(
        {"run_group_id": rg, "incident_ids": incident_ids, "reason": "by hand", "decided_by": "x",
         "withdrawn_at": WITHDRAWN_AT}))


@pytest.mark.parametrize("exercised", [True, False, None], ids=["exercised", "unexercised", "unreviewed"])
def test_a_heldout_run_group_is_never_withdrawn(tmp_path, exercised):
    # decision 026 #30: 023 has no withdrawal and decision 025 revision 3 withdrew one Pilot run group; a held-out
    # withdrawal would reopen a filled, closed or lexicon-hit slot with no limit (023 §2, §4, §5.3)
    from collect.pilot import WITHDRAWAL, withdraw

    layout, ids, slot = DataLayout(tmp_path), Counter(), SLOTS["slots"][0]
    gone = held(layout, ids, slot, exercised=exercised)
    before = states(layout, STATES)
    with pytest.raises(ValueError, match="never withdrawn"):
        withdraw(layout, gone, reason="the power mode changed in the window", decided_by="user", now=WITHDRAWN_AT)
    assert not (layout.run_group_truth_dir(gone) / WITHDRAWAL).exists() and states(layout, STATES) == before


@pytest.mark.parametrize("status, incident_ids", [("valid", None), ("valid", ["INC-009"]), ("invalid", [])],
                         ids=["matching", "other-incident", "invalid-run-group"])
def test_a_withdrawal_record_on_a_heldout_run_group_stops_every_heldout_step(tmp_path, status, incident_ids):
    # written by hand anyway: fail closed (never filtered), a person decides in a new decision
    layout, ids, slot = DataLayout(tmp_path), Counter(), SLOTS["slots"][0]
    rg = held(layout, ids, slot, status, exercised=True if status == "valid" else None)
    hand_withdrawal(layout, rg, incident_ids if incident_ids is not None else [rg.replace("RG", "INC")])
    for check in (lambda: slot_status(layout, SLOTS, freeze_sha=FREEZE_SHA),
                  lambda: next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA), lambda: heldout_runs(layout),
                  lambda: fresh_seed(layout)):
        with pytest.raises(ValueError, match="never withdrawn"):
            check()


# ---------------------------------------------------------------- user decision 2026-10-10: a needs-person slot (026 #11)

ACKED_AT = "2026-10-22T01:00:00Z"


def ack(layout, slot="H01", **kw):
    from collect.heldout import acknowledge_slot_failures

    slots = kw.pop("slots", SLOTS)
    args = {"freeze_sha": FREEZE_SHA, "reason": "grafana plugin download timed out", "decided_by": "user", "now": ACKED_AT,
            **kw}
    return acknowledge_slot_failures(layout, slots, slot, **args)


def ack_lines(layout):
    from collect.pilot import ACKS

    path = layout.ground_truth_root / ACKS
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def row(layout, slot="H01", slots=SLOTS):
    return next(s for s in slot_status(layout, slots, freeze_sha=FREEZE_SHA) if s["slot"] == slot)


def test_after_a_person_looked_a_needs_person_slot_is_collected_again_and_three_new_failures_stop_it_again(tmp_path):
    # user decision 2026-10-10 (026 "待使用者決定" 1, option b, like the Pilot's ack-failures of decision 016)
    layout, ids, slot = DataLayout(tmp_path), Counter(), SLOTS["slots"][0]
    failed = [held(layout, ids, slot, status) for status in ("invalid", "aborted_unstable", "aborted_error")]
    assert row(layout)["state"] == "needs_person"
    record = ack(layout)
    assert record == {"split": "heldout", "slot": "H01", "flag": slot["flag"], "variant": slot["variant"],
                      "run_groups": failed, "reason": "grafana plugin download timed out", "decided_by": "user",
                      "acknowledged_at": ACKED_AT, "freeze_sha256": FREEZE_SHA}
    assert ack_lines(layout) == [record]  # ground-truth side, append-only
    status = row(layout)
    assert status["state"] == "open" and status["acknowledged_run_groups"] == failed
    assert status["non_valid_run_groups"] == failed and status["counts"]["non_valid"] == 3  # nothing deleted or uncounted
    assert all((layout.run_group_truth_dir(rg) / "run.json").exists() for rg in failed)
    assert next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)["slot"] == "H01"
    with pytest.raises(ValueError, match="needs a person"):  # nothing left to acknowledge
        ack(layout)
    again = [held(layout, ids, slot, "invalid") for _ in range(2)]
    assert row(layout)["state"] == "open"
    with pytest.raises(ValueError, match="needs a person"):  # two new failures: not yet a person's slot
        ack(layout)
    again.append(held(layout, ids, slot, "aborted_unstable"))
    assert row(layout)["state"] == "needs_person"  # three new failures stop it again
    assert next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)["skipped"][0]["slot"] == "H01"
    assert ack(layout, now="2026-10-23T00:00:00Z")["run_groups"] == again  # only the new failures
    assert len(ack_lines(layout)) == 2 and row(layout)["acknowledged_run_groups"] == failed + again


def test_an_acknowledgment_is_refused_for_an_unknown_slot_nothing_to_acknowledge_or_once_the_list_exists(tmp_path):
    layout, ids, slots = DataLayout(tmp_path), Counter(), SLOTS["slots"]
    with pytest.raises(ValueError, match="H99"):
        ack(layout, "H99")
    with pytest.raises(ValueError, match="needs a person"):  # no failure at all
        ack(layout)
    for _ in range(2):
        held(layout, ids, slots[0], "invalid")
    with pytest.raises(ValueError, match="needs a person"):  # open with two failures
        ack(layout)
    for _ in range(3):
        held(layout, ids, slots[1], "invalid")
    held(layout, ids, slots[1])
    with pytest.raises(ValueError, match="needs a person"):  # filled: its failures need no person
        ack(layout, "H02")
    for _ in range(3):
        held(layout, ids, slots[2], "invalid")
    for kw in ({"reason": " "}, {"decided_by": ""}):
        with pytest.raises(ValueError, match="reason and who decided"):
            ack(layout, "H03", **kw)
    held(layout, ids, slots[3], exercised=False)
    held(layout, ids, slots[3], exercised=False)
    for _ in range(2):
        held(layout, ids, slots[3], "invalid")
    assert row(layout, "H04")["state"] == "closed"
    with pytest.raises(ValueError, match="needs a person"):  # closed: its failures need no person (026 #11)
        ack(layout, "H04")
    layout.heldout_incidents_path.write_text("{}")  # 023 §5.5 / §6: the list never changes
    with pytest.raises(ValueError, match="heldout_incidents.json"):
        ack(layout, "H03")
    assert ack_lines(layout) == []


def test_an_acknowledgment_keeps_the_closed_and_unexercised_handling(tmp_path):
    # 023 §5.3: two unexercised incidents close a slot; an acknowledgment only restarts the invalid count (026 #12, #13)
    layout, ids, slot = DataLayout(tmp_path), Counter(), SLOTS["slots"][0]
    held(layout, ids, slot, exercised=False)
    held(layout, ids, slot, exercised=False)
    for _ in range(3):
        held(layout, ids, slot, "invalid")
    assert states(layout, STATES) == ["needs_person"]
    ack(layout, slots=STATES)
    assert states(layout, STATES) == ["closed"]  # not reopened: no third incident

    layout, ids = DataLayout(tmp_path / "b"), Counter()
    held(layout, ids, slot, exercised=False)
    for _ in range(3):
        held(layout, ids, slot, "invalid")
    ack(layout, slots=STATES)
    assert states(layout, STATES) == ["open"]  # the one recollection (016 §5) is still the only one
    held(layout, ids, slot, exercised=False)
    assert states(layout, STATES) == ["closed"]


def test_the_three_slot_stop_counts_slots_that_need_a_person_after_acknowledgments(tmp_path):
    layout, ids = DataLayout(tmp_path), Counter()
    for slot in SLOTS["slots"][:3]:
        for _ in range(3):
            held(layout, ids, slot, "invalid")
    with pytest.raises(RuntimeError, match="3 slots"):
        next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)
    ack(layout, "H02")
    nxt = next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)
    assert nxt["slot"] == "H02" and [s["slot"] for s in nxt["skipped"]] == ["H01", "H03"]


def write_ack_line(layout, record):
    from collect.pilot import ACKS

    path = layout.ground_truth_root / ACKS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write((record if isinstance(record, str) else json.dumps(record)) + "\n")


def heldout_ack(slot, run_groups, **kw):
    return {"split": "heldout", "slot": slot["slot"], "flag": slot["flag"], "variant": slot["variant"],
            "run_groups": run_groups, "reason": "r", "decided_by": "user", "acknowledged_at": ACKED_AT,
            "freeze_sha256": FREEZE_SHA, **kw}


@pytest.mark.parametrize("make", [
    lambda s, bad, good, other: heldout_ack({**s, "slot": "H99"}, bad),
    lambda s, bad, good, other: heldout_ack(s, bad, freeze_sha256="sha256:" + "a" * 64),
    lambda s, bad, good, other: heldout_ack(s, bad, flag="adFailure"),  # not the slot's fault
    lambda s, bad, good, other: heldout_ack(s, [good]),  # a valid run group
    lambda s, bad, good, other: heldout_ack(s, [other]),  # another slot's run group
    lambda s, bad, good, other: heldout_ack(s, []),
    lambda s, bad, good, other: heldout_ack(s, [bad[0], bad[0]]),
    lambda s, bad, good, other: {"split": "pilot", "flag": s["flag"], "variant": s["variant"], "run_groups": bad,
                                 "reason": "r", "decided_by": "user", "acknowledged_at": ACKED_AT},
    lambda s, bad, good, other: {"split": "pilot", "flag": s["flag"], "variant": s["variant"], "run_groups": [good],
                                 "reason": "r", "decided_by": "user", "acknowledged_at": ACKED_AT},
    lambda s, bad, good, other: (heldout_ack(s, bad), heldout_ack(s, bad)),  # two lines, the same run groups
    lambda s, bad, good, other: "not json",
    lambda s, bad, good, other: "[]",
    lambda s, bad, good, other: {"split": "heldout", "slot": "H01", "run_groups": "RG-001"},
    lambda s, bad, good, other: {"split": "pilot", "flag": s["flag"], "variant": s["variant"], "run_groups": [1]},
], ids=["unknown-slot", "other-freeze", "other-fault", "valid-run-group", "other-slot", "empty", "twice", "pilot-names-heldout",
        "pilot-names-heldout-valid", "acknowledged-twice", "malformed", "json-array", "run-groups-not-a-list",
        "run-group-not-a-string"])
def test_a_corrupt_or_foreign_acknowledgment_stops_every_heldout_step(tmp_path, make):
    # fail closed like every held-out record (026 #12): never filtered, never ignored
    layout, ids, slots = DataLayout(tmp_path), Counter(), SLOTS["slots"]
    bad = [held(layout, ids, slots[0], "invalid") for _ in range(3)]
    other = held(layout, ids, slots[1], "invalid")
    good = held(layout, ids, slots[2])
    lines = make(slots[0], bad, good, other)
    for line in lines if isinstance(lines, tuple) else (lines,):
        write_ack_line(layout, line)
    for check in (lambda: slot_status(layout, SLOTS, freeze_sha=FREEZE_SHA),
                  lambda: next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA), lambda: ack(layout)):
        with pytest.raises(ValueError, match="acknowledg"):
            check()


@pytest.mark.parametrize("before, named", [
    (2, lambda bad: bad[:1]),  # an open slot, acknowledged early
    (2, lambda bad: bad),
    (3, lambda bad: bad[:1]),  # a slot that needs a person, acknowledged in part
    (3, lambda bad: bad[:2]),
    (4, lambda bad: [bad[0], bad[2], bad[3]]),  # three of four, one skipped
], ids=["open-one", "open-two", "needs-person-one", "needs-person-two", "skips-one"])
def test_an_acknowledgment_the_writer_never_writes_stops_every_heldout_step(tmp_path, before, named):
    # 026 #11: only a slot that needs a person is acknowledged, all its unacknowledged failures at once, so a hand-written
    # record never acknowledges early or in part and recounts the slot sooner: fail closed, not accepted
    layout, ids, slot = DataLayout(tmp_path), Counter(), SLOTS["slots"][0]
    bad = [held(layout, ids, slot, "invalid") for _ in range(before)]
    write_ack_line(layout, heldout_ack(slot, named(bad)))
    held(layout, ids, slot, "invalid")
    for check in (lambda: slot_status(layout, SLOTS, freeze_sha=FREEZE_SHA),
                  lambda: next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA), lambda: ack(layout)):
        with pytest.raises(ValueError, match="acknowledg"):
            check()


def test_a_heldout_acknowledgment_and_a_pilot_one_never_touch_each_other(tmp_path):
    from collect.pilot import acknowledge_failures, next_planned, plan_status

    layout, ids = DataLayout(tmp_path), Counter()
    for _ in range(3):
        ids("RG")
        write_run(layout, f"RG-{ids.n:03d}", "paymentFailure", "100%", "invalid")  # the Pilot's first fault
    for _ in range(3):
        held(layout, ids, SLOTS["slots"][0], "invalid")
    ack(layout)
    with pytest.raises(RuntimeError):  # the Pilot fault still waits for its own acknowledgment (decision 016)
        next_planned(layout, "pilot")
    assert plan_status(layout, "pilot")[0]["acknowledged"] == []
    layout, ids = DataLayout(tmp_path / "b"), Counter()
    for _ in range(3):
        ids("RG")
        write_run(layout, f"RG-{ids.n:03d}", "paymentFailure", "100%", "invalid")
    for _ in range(3):
        held(layout, ids, SLOTS["slots"][0], "invalid")
    acknowledge_failures(layout, "pilot", "paymentFailure", "100%", reason="r", decided_by="user", now=ACKED_AT)
    assert next_planned(layout, "pilot")["flag"] == "paymentFailure"
    assert row(layout)["state"] == "needs_person" and row(layout)["acknowledged_run_groups"] == []
