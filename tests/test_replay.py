"""Day 1 #6: with the live system gone, the frozen snapshot alone supports the analysis."""

import pytest

from collect.replay import replay
from test_snapshot import snap_dir  # noqa: F401  (fixture)


def test_replay_needs_the_live_system_gone_and_uses_only_the_snapshot(snap_dir):  # noqa: F811
    layout, norm = snap_dir
    with pytest.raises(RuntimeError, match="still running"):
        replay(layout, "INC-001", live_containers=lambda: ["checkout"])
    out = replay(layout, "INC-001", live_containers=lambda: [])
    assert out["records"]["spans.jsonl"] == 3
    assert out["every_id_resolves"] is True and out["checks"] == []
    assert out["error_spans_by_service"] == {"checkout": 1}
