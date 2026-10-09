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
    assert row["counts"] == {"usable": 1, "unexercised": 0, "non_valid": 1, "withdrawn": 0}
    assert row["power"] == [{"source": "AC Power", "settings": {"powermode": "2"}}]
    text = json.dumps(row)
    assert good not in text and "INC-" not in text


def test_next_skips_slots_that_need_a_person_and_stops_at_three_or_when_nothing_else_is_open(tmp_path):
    layout, ids = DataLayout(tmp_path), Counter()
    for _ in range(3):
        bad = held(layout, ids, SLOTS["slots"][0], "invalid")
    nxt = next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)
    assert nxt["slot"] == "H02" and nxt["skipped"] == [{"slot": "H01", "non_valid_run_groups": ["RG-001", "RG-002", bad]}]
    for slot in SLOTS["slots"][1:3]:
        for _ in range(3):
            held(layout, ids, slot, "aborted_unstable")
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


def test_a_withdrawn_run_group_neither_fills_its_slot_nor_counts_as_an_invalid_attempt(tmp_path):
    # decision 025 revision 3 holds for the held-out set: kept on disk, counted for no set, not an invalid attempt
    from collect.pilot import withdraw

    layout, ids, slot = DataLayout(tmp_path), Counter(), SLOTS["slots"][0]
    held(layout, ids, slot, "invalid")
    held(layout, ids, slot, "invalid")
    gone = held(layout, ids, slot, exercised=True)
    withdraw(layout, gone, reason="the power mode changed in the window", decided_by="user", now=WITHDRAWN_AT)
    (row,) = slot_status(layout, STATES, freeze_sha=FREEZE_SHA)
    assert row["state"] == "open" and row["non_valid_run_groups"] == ["RG-001", "RG-002"]
    assert row["counts"] == {"usable": 0, "unexercised": 0, "non_valid": 2, "withdrawn": 1} and row["power"] == []
    assert gone not in json.dumps(row) and "INC-" not in json.dumps(row)  # a withdrawn run group's id is not shown either
    assert next_slot(layout, SLOTS, freeze_sha=FREEZE_SHA)["slot"] == "H01"  # collected again, new run group, new seed
    held(layout, ids, slot)
    assert states(layout, STATES) == ["filled"]  # one usable incident: the withdrawn one is not a second

    layout, ids = DataLayout(tmp_path / "b"), Counter()
    first = held(layout, ids, slot, exercised=False)
    withdraw(layout, first, reason="r", decided_by="user", now=WITHDRAWN_AT)
    held(layout, ids, slot, exercised=False)
    assert states(layout, STATES) == ["open"]  # one unexercised incident counts: recollected once more (016 §5)
    for _ in range(3):
        held(layout, ids, slot, "invalid")
    assert states(layout, STATES) == ["needs_person"]  # the invalid ones still count, the withdrawn one does not
