"""raw -> canonical snapshot (decision 011): rules, window, ids, determinism, fail-closed checks."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from collect.layout import DataLayout
from collect.normalize import NormalizeError, NormalizeInputs, check_snapshot, normalize
from collect.policy import load_policy
from collect.rawfile import scan_raw_file
from normalize_fixtures import HOST_END, HOST_START, OFFSETS, S, T0, write_raw


@pytest.fixture
def setup(tmp_path):
    layout = DataLayout(tmp_path / "data")
    raw_dir = layout.raw_dir("RG-001")
    files = write_raw(raw_dir)
    scans = {sig: scan_raw_file(p, sig) for sig, p in files.items()}
    inputs = NormalizeInputs(raw_dir=raw_dir, raw_sha256={sig: s["sha256"] for sig, s in scans.items()},
                             raw_duplicates={sig: s["duplicates"] for sig, s in scans.items()},
                             window_host=(HOST_START, HOST_END), clock_offsets=list(OFFSETS))
    return layout, inputs


def run(setup, **kw):
    layout, inputs = setup
    out = layout.incident_dir("INC-001")
    report = normalize(inputs, load_policy(), incident_dir=out, report_path=layout.normalize_report_path("INC-001"),
                       staging_dir=layout.root / "staging" / "normalize-INC-001", **kw)
    return out / "normalized", report


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_spans_follow_the_rules(setup):
    norm, report = run(setup)
    spans = {s["span_id"]: s for s in lines(norm / "spans.jsonl")}
    assert set(spans) == {"a" * 16, "9" * 16, "7" * 16}
    a = spans["a" * 16]
    assert a["id"] == "s-" + "a" * 16 and a["service"] == "checkout" and a["kind"] == "server"
    assert "feature_flag.key" not in a["attributes"] and a["attributes"]["rpc.service"] == "oteldemo.CheckoutService"
    assert "user.email" not in a["attributes"] and a["attributes"]["user.hash"] == hashlib.sha256(b"x@y.z").hexdigest()
    assert a["status_code"] == "error" and a["status_message"] == "failed to charge card: on"
    assert [e["name"] for e in a["events"]] == ["message"]  # the flag-evaluation event is gone
    assert spans["9" * 16]["parent_span_id"] == "f" * 16  # X1 does not cascade; the parent id stays as it was
    removed = report["removed"]
    assert removed["X4"]["traces"] == 3  # root b, child c, late child d (its root e is outside the window)
    assert removed["X1"]["traces"] == 1 and removed["X6"]["traces"] == 1
    assert report["signals"]["traces"]["duplicates"] == 1 and report["signals"]["traces"]["out_of_window"] == 2


def test_logs_follow_the_rules(setup):
    norm, report = run(setup)
    bodies = sorted(r["body"] for r in lines(norm / "logs.jsonl"))
    assert bodies == sorted(["Payment request failed. Invalid token. demo.user_context.loyalty_level=gold",  # Class C kept
                             "Error: Product Catalog Fail Enabled",  # tokens deleted, no sentinel
                             "get_product_list: cache hit",  # Class B kept
                             "no event time"])
    assert report["removed"]["X7"]["logs"] == 1 and report["removed"]["X5"]["logs"] == 1
    assert report["removed"]["X4"]["logs"] == 1  # the log inside the removed control-plane span
    assert report["removed"]["X1"]["logs"] == 1
    assert report["tokens_deleted"]["logs"] == 1
    assert all(r["id"].startswith("l-") and len(r["id"]) == 18 for r in lines(norm / "logs.jsonl"))


def test_metrics_follow_the_rules(setup):
    norm, report = run(setup)
    series = {s["id"]: s for s in lines(norm / "metric_series.jsonl")}
    assert sorted((s["service"], s["metric"]) for s in series.values()) == [
        ("astronomy-db", "postgresql.backends"), ("cart", "app.cart.items"), ("checkout", "container.cpu.utilization")]
    points = lines(norm / "metric_points.jsonl")
    assert len(points) == 4 and all(p["series_id"] in series for p in points)
    cart = sorted((p for p in points if p["metric"] == "app.cart.items"), key=lambda p: p["time_unix_nano"])
    assert [p["first_in_window"] for p in cart] == [True, False] and [p["value"] for p in cart] == [1, 2]
    for rule in ("X1", "X2", "X3", "X5", "X10"):
        assert report["removed"][rule]["metrics"] >= 1, rule


def test_window_uses_the_data_clock_and_both_offsets(setup):
    layout, inputs = setup
    inputs.clock_offsets = [30.0, 30.4]  # the VM clock runs 30 s ahead: the window moves with it
    norm, report = run((layout, inputs))
    snap = json.loads((norm / "snapshot.json").read_text())
    assert snap["window"] == {"start_ns": T0 + 90 * S, "end_ns": T0 + 630 * S + 400_000_000}
    inputs2 = NormalizeInputs(**{**inputs.__dict__, "clock_offsets": [0.0, 1.5]})
    with pytest.raises(NormalizeError, match="drift"):
        normalize(inputs2, load_policy(), incident_dir=layout.incident_dir("INC-002"),
                  report_path=layout.normalize_report_path("INC-002"), staging_dir=layout.root / "staging" / "n2")


def test_output_is_deterministic_and_published_write_once(setup, tmp_path):
    norm, _ = run(setup)
    first = {p.name: p.read_bytes() for p in norm.iterdir()}
    assert sorted(first) == ["logs.jsonl", "metric_points.jsonl", "metric_series.jsonl", "resources.jsonl",
                             "snapshot.json", "spans.jsonl"]
    assert all(not os.access(p, os.W_OK) for p in norm.iterdir())  # 0444
    with pytest.raises(NormalizeError, match="exists"):
        run(setup)
    # a second normalize of the same raw elsewhere gives identical bytes
    layout2 = DataLayout(tmp_path / "again")
    layout, inputs = setup
    out2 = layout2.incident_dir("INC-001")
    normalize(inputs, load_policy(), incident_dir=out2, report_path=layout2.normalize_report_path("INC-001"),
              staging_dir=layout2.root / "staging" / "n")
    assert {p.name: p.read_bytes() for p in (out2 / "normalized").iterdir()} == first


def test_snapshot_descriptor_and_report_stay_on_their_sides(setup):
    norm, report = run(setup)
    layout, _ = setup
    snap = json.loads((norm / "snapshot.json").read_text())
    assert snap["canonical_schema"] == "ctel/1" and len(snap["services"]) == 18
    text = (norm / "snapshot.json").read_text()
    for leak in ("RG-001", "INC-001", "raw", "offset"):
        assert leak not in text
    assert layout.is_ground_truth(layout.normalize_report_path("INC-001"))
    assert json.loads(layout.normalize_report_path("INC-001").read_text())["raw_sha256"]
    assert layout.is_agent_readable(norm / "spans.jsonl")


def test_dedupe_matches_the_raw_scan(setup):
    _, report = run(setup)
    layout, inputs = setup
    for sig in ("traces", "metrics", "logs"):
        assert report["signals"][sig]["duplicates"] == inputs.raw_duplicates[sig]


def test_raw_must_be_exactly_what_the_export_recorded(setup):
    layout, inputs = setup
    (inputs.raw_dir / "logs.jsonl").write_text("{}\n")
    with pytest.raises(NormalizeError, match="sha256"):
        run(setup)


def test_check_snapshot_fails_closed(setup):
    norm, _ = run(setup)
    policy = load_policy()
    assert check_snapshot(norm, policy) == []
    bad = norm.parent / "tampered"
    bad.mkdir()
    for p in norm.iterdir():
        (bad / p.name).write_bytes(p.read_bytes())
    (bad / "logs.jsonl").write_text((bad / "logs.jsonl").read_text() + json.dumps({"x": "paymentFailure"}) + "\n")
    (bad / "extra.txt").write_text("hi")
    problems = check_snapshot(bad, policy)
    assert any("lexicon" in p for p in problems) and any("extra.txt" in p for p in problems)


def test_check_snapshot_validates_every_record_against_the_schema(setup):
    norm, _ = run(setup)
    bad = norm.parent / "schema-broken"
    bad.mkdir()
    for p in norm.iterdir():
        (bad / p.name).write_bytes(p.read_bytes())
    spans = [json.loads(x) for x in (bad / "spans.jsonl").read_text().splitlines()]
    del spans[0]["status_code"]
    spans[1]["kind"] = "sideways"
    (bad / "spans.jsonl").write_text("".join(json.dumps(x) + "\n" for x in spans))
    problems = check_snapshot(bad, load_policy())
    assert sum("schema" in p for p in problems) >= 2


def test_normalize_is_ground_truth_blind(setup, monkeypatch):
    import builtins
    import inspect

    assert list(inspect.signature(normalize).parameters) == ["inputs", "policy", "incident_dir", "report_path", "staging_dir"]
    layout, inputs = setup
    opened = []
    real_open = builtins.open

    def spy(file, mode="r", *a, **kw):
        opened.append((str(file), mode))
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy)
    run(setup)
    truth = str(layout.ground_truth_root.resolve())
    reads = [f for f, mode in opened if "r" in mode and str(Path(f).resolve()).startswith(truth)]
    assert reads == []  # only the report is written there; nothing on the ground-truth side is read


def test_output_does_not_depend_on_python_hash_seed(setup, tmp_path):
    import subprocess
    import sys

    norm, _ = run(setup)
    layout, inputs = setup
    script = f"""
import sys; sys.path[:0] = [{str(Path(__file__).resolve().parent.parent)!r}, {str(Path(__file__).resolve().parent)!r}]
from pathlib import Path
from collect.layout import DataLayout
from collect.normalize import NormalizeInputs, normalize
from collect.policy import load_policy
lay = DataLayout(Path({str(tmp_path / 'seeded')!r}))
inputs = NormalizeInputs(raw_dir=Path({str(inputs.raw_dir)!r}), raw_sha256={inputs.raw_sha256!r},
                         raw_duplicates={inputs.raw_duplicates!r}, window_host={inputs.window_host!r},
                         clock_offsets={inputs.clock_offsets!r})
normalize(inputs, load_policy(), incident_dir=lay.incident_dir("INC-001"), report_path=lay.normalize_report_path("INC-001"),
          staging_dir=lay.root / "staging" / "n")
"""
    subprocess.run([sys.executable, "-c", script], check=True, env={**os.environ, "PYTHONHASHSEED": "12345"})
    other = tmp_path / "seeded" / "incidents" / "INC-001" / "normalized"
    assert {p.name: p.read_bytes() for p in other.iterdir()} == {p.name: p.read_bytes() for p in norm.iterdir()}
