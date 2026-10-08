"""Reading a frozen snapshot (decision 011 §5): one entry point, verified bytes, evidence ids, rendering, derived views."""

import os

import pytest

from collect.derive import DERIVE_VERSION, point_deltas, service_minute_stats
from collect.layout import DataLayout
from collect.normalize import NormalizeInputs, normalize
from collect.policy import load_policy
from collect.rawfile import scan_raw_file
from collect.snapshot import SnapshotError, open_snapshot, proxy_tokens, render_v1
from normalize_fixtures import HOST_END, HOST_START, S, T0, write_raw


@pytest.fixture
def snap_dir(tmp_path):
    layout = DataLayout(tmp_path / "data")
    files = write_raw(layout.raw_dir("RG-001"))
    scans = {sig: scan_raw_file(p, sig) for sig, p in files.items()}
    inputs = NormalizeInputs(raw_dir=layout.raw_dir("RG-001"), raw_sha256={k: v["sha256"] for k, v in scans.items()},
                             raw_duplicates={k: v["duplicates"] for k, v in scans.items()},
                             window_host=(HOST_START, HOST_END), clock_offsets=[0.0, 0.0])
    normalize(inputs, load_policy(), incident_dir=layout.incident_dir("INC-001"),
              report_path=layout.normalize_report_path("INC-001"), staging_dir=layout.root / "staging" / "n")
    return layout, layout.incident_dir("INC-001") / "normalized"


def test_open_snapshot_only_opens_agent_readable_verified_snapshots(snap_dir, tmp_path):
    layout, norm = snap_dir
    snap = open_snapshot(norm, layout)
    assert len(list(snap.spans())) == 3 and snap.window["start_ns"] == T0 + 60 * S
    with pytest.raises(SnapshotError, match="readable"):
        open_snapshot(layout.raw_dir("RG-001"), layout)
    os.chmod(norm / "logs.jsonl", 0o644)
    (norm / "logs.jsonl").write_text((norm / "logs.jsonl").read_text().replace("cache hit", "cache HIT"))
    with pytest.raises(SnapshotError, match="sha256"):
        open_snapshot(norm, layout)


def test_resolve_evidence_ids(snap_dir):
    layout, norm = snap_dir
    snap = open_snapshot(norm, layout)
    span = next(snap.spans())
    assert snap.resolve(span["id"])["span_id"] == span["span_id"]
    assert snap.resolve("t-" + span["trace_id"]) is not None
    log = next(snap.logs())
    assert snap.resolve(log["id"]) == log
    series = next(snap.series())
    t = next(p["time_unix_nano"] for p in snap.points() if p["series_id"] == series["id"])
    assert snap.resolve(series["id"], t, t) is not None
    assert snap.resolve(series["id"], T0 + 9000 * S, T0 + 9001 * S) is None  # no point in that range
    assert snap.resolve("s-" + "0" * 16) is None and snap.resolve("l-ffffffffffffffff") is None
    assert snap.resolve("r-" + "0" * 16) is None  # resource ids are not citable
    assert snap.resolve("nonsense") is None


def test_render_v1_is_compact_relative_and_bounded(snap_dir):
    layout, norm = snap_dir
    snap = open_snapshot(norm, layout)
    span = next(snap.spans())
    line = render_v1(span, snap.window["start_ns"])
    assert line.startswith(span["id"] + " ") and "+001:00.000" in line  # 120 s after T0 = 60 s into the window (+MMM:SS.mmm)
    with_event = {**span, "events": [{"time_unix_nano": snap.window["start_ns"] + 60_007_000_000, "name": "message"}]}
    rendered = render_v1(with_event, snap.window["start_ns"])
    assert '"time":"+001:00.007"' in rendered and "unix_nano" not in rendered  # decision 011 §5: every time is relative
    assert "null" not in line and len(line.encode()) <= 1024
    huge = {**span, "attributes": {"k": "x" * 5000}}
    assert len(render_v1(huge, snap.window["start_ns"]).encode()) <= 1024
    assert proxy_tokens("abcd") == 1 and proxy_tokens("abcde") == 2 and proxy_tokens("") == 0


def test_service_minute_stats_and_point_deltas(snap_dir):
    layout, norm = snap_dir
    snap = open_snapshot(norm, layout)
    stats = service_minute_stats(snap)
    assert stats["version"] == DERIVE_VERSION
    checkout = stats["services"]["checkout"]
    assert sum(m["spans"] for m in checkout.values()) == 1 and sum(m["error_spans"] for m in checkout.values()) == 1
    deltas = point_deltas([{"start_time_unix_nano": 1, "time_unix_nano": 10, "value": 5, "first_in_window": True},
                           {"start_time_unix_nano": 1, "time_unix_nano": 20, "value": 8, "first_in_window": False},
                           {"start_time_unix_nano": 15, "time_unix_nano": 30, "value": 2, "first_in_window": False}],
                          monotonic=True)
    assert deltas == [{"time_unix_nano": 20, "delta": 3, "reset": False}, {"time_unix_nano": 30, "delta": 2, "reset": True}]
    # an UpDownCounter (cumulative, not monotonic) may go down: only a new start time is a reset
    updown = [{"start_time_unix_nano": 1, "time_unix_nano": t, "value": v, "first_in_window": t == 10}
              for t, v in ((10, 10), (20, 7), (30, 9))]
    assert point_deltas(updown, monotonic=False) == [{"time_unix_nano": 20, "delta": -3, "reset": False},
                                                     {"time_unix_nano": 30, "delta": 2, "reset": False}]
    assert DERIVE_VERSION == 2


def test_lone_surrogates_are_cleaned_in_every_field_so_readers_never_crash(tmp_path):
    import json

    from normalize_fixtures import raw_lines
    layout = DataLayout(tmp_path / "data")
    raw_dir = layout.raw_dir("RG-001")
    raw_dir.mkdir(parents=True)
    scans = {}
    for sig, lines in raw_lines().items():
        if sig == "traces":
            lines = [ln.replace('"Charge"', '"GET \\ud800/x"') for ln in lines]
        (raw_dir / f"{sig}.jsonl").write_text("\n".join(lines) + "\n")
        scans[sig] = scan_raw_file(raw_dir / f"{sig}.jsonl", sig)
    inputs = NormalizeInputs(raw_dir=raw_dir, raw_sha256={k: v["sha256"] for k, v in scans.items()},
                             raw_duplicates={k: v["duplicates"] for k, v in scans.items()},
                             window_host=(HOST_START, HOST_END), clock_offsets=[0.0, 0.0])
    report = normalize(inputs, load_policy(), incident_dir=layout.incident_dir("INC-001"),
                       report_path=layout.normalize_report_path("INC-001"), staging_dir=layout.root / "staging" / "n")
    snap = open_snapshot(layout.incident_dir("INC-001") / "normalized", layout)
    names = [sp["name"] for sp in snap.spans()]
    assert "GET \ufffd/x" in names and report["value_fixes"]["lone_surrogates"] >= 1
    for sp in snap.spans():
        assert proxy_tokens(render_v1(sp, snap.window["start_ns"])) > 0


def test_evidence_existence_counts_cited_ids_that_resolve_in_the_snapshot(snap_dir):
    # SPEC §9 Existence: does each cited log / trace / metric really exist (relevance is a separate layer)
    from eval.evidence import existence

    layout, norm = snap_dir
    snap = open_snapshot(norm, layout)
    span, series = next(snap.spans()), next(snap.series())
    t = next(p["time_unix_nano"] for p in snap.points() if p["series_id"] == series["id"])
    cited = [{"id": span["id"]}, {"id": "t-" + span["trace_id"]}, {"id": series["id"], "t0": t, "t1": t},
             {"id": series["id"], "t0": T0 + 9000 * S, "t1": T0 + 9001 * S}, {"id": "l-" + "f" * 16}]
    out = existence(cited, snap)
    assert out == {"cited": 5, "resolved": 3, "rate": 0.6, "unresolved": [series["id"], "l-" + "f" * 16]}
    assert existence([], snap) == {"cited": 0, "resolved": 0, "rate": None, "unresolved": []}
