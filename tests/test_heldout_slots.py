"""The held-out slot list (decision 023 §4): K blocks, each a random permutation of the held-out faults, from master seed
20261009, numbered H01..; regenerated identically, so the committed order cannot be hand-edited."""

import collect.__main__ as cli
from collect.heldout import FAULT_MINUTES, HELDOUT_K, HELDOUT_MASTER_SEED, heldout_slots

FAULTS = [[f"f{i}", "on"] for i in range(10)]

# the order for the ten faults above and seed 20261009, block by block (pinned: Random(seed).random() only)
GOLDEN = [[5, 1, 4, 2, 3, 8, 0, 9, 7, 6], [9, 0, 8, 3, 6, 1, 7, 5, 4, 2], [4, 6, 1, 7, 5, 2, 3, 0, 9, 8],
          [5, 7, 8, 0, 9, 1, 2, 4, 3, 6], [6, 8, 1, 9, 4, 0, 2, 7, 3, 5]]


def test_k_blocks_each_a_permutation_numbered_from_h01():
    slots = heldout_slots(FAULTS, k=5)
    assert [s["slot"] for s in slots] == [f"H{n:02d}" for n in range(1, 51)]
    for block in range(1, 6):
        mine = [s for s in slots if s["block"] == block]
        assert len(mine) == 10 and sorted([s["flag"], s["variant"]] for s in mine) == sorted(FAULTS)
    assert set(slots[0]) == {"slot", "block", "flag", "variant"}


def test_the_order_is_fixed_by_the_master_seed():
    slots = heldout_slots(FAULTS)
    assert [[int(s["flag"][1:]) for s in slots if s["block"] == b] for b in range(1, 6)] == GOLDEN
    assert heldout_slots(FAULTS) == slots  # regenerated identically
    assert heldout_slots(FAULTS, seed=1) != slots


def test_the_count_follows_the_faults_kept_and_the_constants_are_the_user_decisions():
    assert len(heldout_slots(FAULTS[:8])) == 40 and heldout_slots(FAULTS[:8])[-1]["slot"] == "H40"
    assert HELDOUT_K == 5 and HELDOUT_MASTER_SEED == 20261009  # user decision 2026-10-09; decision 023 §4
    assert FAULT_MINUTES == cli.HELDOUT_FAULT_MINUTES == cli.PILOT_FAULT_MINUTES == 10  # decision 023 §3
