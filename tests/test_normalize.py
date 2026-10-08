"""raw -> canonical snapshot (decision 011): rules, window, ids, determinism, fail-closed checks."""

import base64
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from collect.layout import DataLayout
from collect.normalize import NormalizeError, NormalizeInputs, check_snapshot, normalize
from collect.policy import Policy, load_policy
from collect.rawfile import scan_raw_file
from normalize_fixtures import (HOST_END, HOST_START, OFFSETS, S, T0, gauge_line, kv, log, logs_line, raw_lines, res,
                                span, traces_line, write_raw)


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
    assert report["removed"]["X7"]["logs"] == 2 and report["removed"]["X5"]["logs"] == 1
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

    # `code` is the normalizer's own git state (commit / dirty): nothing from the run group or its label
    assert list(inspect.signature(normalize).parameters) == ["inputs", "policy", "incident_dir", "report_path", "staging_dir",
                                                             "code"]
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
from collect.policy import Policy, load_policy
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


def run_with(tmp_path, extra: dict[str, list[str]]):
    """normalize the standard fixture raw plus `extra` lines per signal."""
    layout = DataLayout(tmp_path / "data")
    raw_dir = layout.raw_dir("RG-001")
    raw_dir.mkdir(parents=True)
    scans = {}
    for sig, lines_ in raw_lines().items():
        (raw_dir / f"{sig}.jsonl").write_text("\n".join(lines_ + extra.get(sig, [])) + "\n")
        scans[sig] = scan_raw_file(raw_dir / f"{sig}.jsonl", sig)
    inputs = NormalizeInputs(raw_dir=raw_dir, raw_sha256={k: v["sha256"] for k, v in scans.items()},
                             raw_duplicates={k: v["duplicates"] for k, v in scans.items()},
                             window_host=(HOST_START, HOST_END), clock_offsets=list(OFFSETS))
    report = normalize(inputs, load_policy(), incident_dir=layout.incident_dir("INC-001"),
                       report_path=layout.normalize_report_path("INC-001"), staging_dir=layout.root / "staging" / "n")
    return layout.incident_dir("INC-001") / "normalized", report


def test_x8_reaches_every_visible_string(tmp_path):
    # decision 011 §3 X8: "in all visible strings" -- keys, metric metadata, severity text, scope version, trace state, bytes
    w = T0 + 120 * S
    blob = base64.b64encode(b"cartFailure=on").decode()
    sp = span("4" * 32, "5" * 16, w, "Charge", attrs={"app.ofrep.enabled": True})
    sp["attributes"] += [{"key": "cfg", "value": {"kvlistValue": {"values": kv({"paymentFailure": "on", "mode": "x"})}}},
                         {"key": "blob", "value": {"bytesValue": blob}}]
    sp["traceState"] = "vendor=1,flagd=2"
    sp["links"] = [{"traceId": "6" * 32, "spanId": "6" * 16, "traceState": "flagd=3"}]
    line = json.loads(traces_line(res("payment"), [sp]))
    line["resourceSpans"][0]["scopeSpans"][0]["scope"]["version"] = "1.0 flagd"
    rec = log(w, "charged", severity=9)
    rec["severityText"] = "INFO flagd"
    metric = json.loads(gauge_line(res("cart"), "app.cart.adds", [{"timeUnixNano": str(w), "asInt": "1"}]))
    m = metric["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]
    m["description"], m["unit"] = "set by flagd", "{flagd}"
    norm, report = run_with(tmp_path, {
        "traces": [json.dumps(line)],
        "logs": [logs_line(res("payment"), [rec])],
        "metrics": [json.dumps(metric), gauge_line(res("cart"), "app.flagd.sync", [{"timeUnixNano": str(w), "asInt": "1"}])],
    })
    s5 = next(x for x in lines(norm / "spans.jsonl") if x["span_id"] == "5" * 16)
    assert s5["attributes"]["app.enabled"] is True and s5["attributes"]["cfg"] == {"mode": "x"}
    assert base64.b64decode(s5["attributes"]["blob"]["$bytes"]) == b"on"
    assert s5["scope"]["version"] == "1.0" and "flagd" not in (s5["trace_state"] + s5["links"][0]["trace_state"])
    assert any(x["severity_text"] == "INFO" for x in lines(norm / "logs.jsonl"))
    series = {x["metric"]: x for x in lines(norm / "metric_series.jsonl")}
    assert series["app.cart.adds"]["description"] == "set by" and "flagd" not in series["app.cart.adds"]["unit"]
    assert "app.flagd.sync" not in series  # a flag-named metric goes with its series (X5), names are not rewritten
    assert report["removed"]["X8_key"]["traces"] == 1


def test_check_snapshot_sees_through_escapes_and_bytes(setup, tmp_path):
    # the last line of defence greps decoded strings, not only the escaped JSON bytes
    norm, _ = run(setup)
    copy = tmp_path / "copy"
    shutil.copytree(norm, copy)
    for p in copy.iterdir():
        os.chmod(p, 0o644)
    policy = load_policy()
    series = lines(copy / "metric_series.jsonl")
    series[0]["description"] = "evaluations\npaymentFailure"
    (copy / "metric_series.jsonl").write_text("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in series))
    spans = lines(copy / "spans.jsonl")
    spans[0]["attributes"]["blob"] = {"$bytes": base64.b64encode(b"cartFailure=on").decode()}
    (copy / "spans.jsonl").write_text("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in spans))
    problems = check_snapshot(copy, policy)
    assert any(p.startswith("metric_series.jsonl: line 1: lexicon") for p in problems)
    assert any(p.startswith("spans.jsonl: line 1: lexicon") for p in problems)


def test_point_values_encode_non_finite_doubles_and_proto3_zero_defaults():
    # decision 011 §2: one encoding for NaN / ±Infinity everywhere; null means absent, and a proto3 double omitted
    # by OTLP JSON was 0 (only the `optional` histogram sum / min / max may be absent)
    from collect.normalize import _point_values, _validators

    h = _point_values("histogram", {"count": "2", "sum": "NaN", "min": "-Infinity", "max": "Infinity",
                                    "bucketCounts": ["1", "1"], "explicitBounds": [1.0]})
    assert h["sum"] == {"$double": "NaN"} and h["min"] == {"$double": "-Infinity"} and h["max"] == {"$double": "Infinity"}
    assert _point_values("histogram", {"count": "0"})["sum"] is None
    e = _point_values("exponential_histogram", {"count": "1", "sum": "Infinity"})
    assert e["sum"] == {"$double": "Infinity"} and e["zero_threshold"] == 0
    sm = _point_values("summary", {"count": "3", "quantileValues": [{}, {"quantile": 1.0, "value": "NaN"}]})
    assert sm["sum"] == 0 and sm["quantile_values"] == [{"quantile": 0, "value": 0},
                                                        {"quantile": 1.0, "value": {"$double": "NaN"}}]
    v = _validators()["metric_points.jsonl"]
    base = {"id": "p-" + "0" * 16, "series_id": "m-" + "0" * 16, "service": "cart", "metric": "x",
            "start_time_unix_nano": 1, "time_unix_nano": 2, "flags": 0, "first_in_window": False}
    assert not list(v.iter_errors({**base, "kind": "histogram", **h}))
    assert not list(v.iter_errors({**base, "kind": "exponential_histogram", **e}))
    assert not list(v.iter_errors({**base, "kind": "summary", **sm}))
    assert list(v.iter_errors({**base, "kind": "histogram", **h, "sum": "NaN"}))  # a bare string is not a double
    assert list(v.iter_errors({**base, "kind": "summary", **sm, "sum": None}))  # a summary always has a sum


def test_every_removal_is_counted_by_rule_signal_service_and_minute(setup):
    # decision 011 §3: rule x signal x service x minute, including attribute-level removals and privacy
    _, report = run(setup)
    detail = report["removed_detail"]
    assert report["removed"]["X9_hash"]["traces"] == 1  # user.email -> user.hash on the checkout span
    assert detail["X9_hash"]["traces"]["by_service"] == {"checkout": 1}
    assert detail["X5_attribute"]["traces"]["by_service"]["checkout"] >= 1
    assert detail["X5_event"]["traces"]["by_service"] == {"checkout": 1}
    assert sum(detail["X8_token"]["logs"]["by_minute"].values()) == report["tokens_deleted"]["logs"] == 1
    assert "untimed" not in detail["X5_attribute"]["traces"]["by_minute"]


def test_report_lists_attribute_keys_and_the_ones_the_soak_inventory_never_saw(setup):
    # decision 011 §3: a deny-list keeps unknown keys; new keys are listed on the ground-truth side for the audit
    layout, inputs = setup
    p = load_policy()
    no_inventory = Policy({k: v for k, v in p.raw.items() if k != "attribute_key_inventory"}, p.sha256)
    report = normalize(inputs, no_inventory, incident_dir=layout.incident_dir("INC-001"),
                       report_path=layout.normalize_report_path("INC-001"), staging_dir=layout.root / "staging" / "n1")
    assert "rpc.service" in report["attribute_keys"]["traces/checkout"]
    assert report["new_attribute_keys"] is None  # a calibrating policy has no inventory
    inventory = {k: [x for x in v if x != "rpc.service"] for k, v in report["attribute_keys"].items()}
    with_inventory = Policy({**p.raw, "attribute_key_inventory": inventory}, p.sha256)
    out = normalize(inputs, with_inventory, incident_dir=layout.incident_dir("INC-009"),
                    report_path=layout.normalize_report_path("INC-009"), staging_dir=layout.root / "staging" / "n9")
    assert out["new_attribute_keys"] == {"traces/checkout": ["rpc.service"]}


def test_the_report_has_a_pinned_shape(setup):
    from jsonschema import Draft202012Validator

    layout, _ = setup
    _, report = run(setup)
    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas/normalize_report.schema.json").read_text())
    assert list(Draft202012Validator(schema).iter_errors(report)) == []
    on_disk = json.loads(layout.normalize_report_path("INC-001").read_text())
    assert list(Draft202012Validator(schema).iter_errors(on_disk)) == []
    assert list(Draft202012Validator(schema).iter_errors({**report, "removed": {"X5": {"traces": -1}}}))


def test_harness_probe_containers_are_dropped_as_harness_not_unknown(tmp_path):
    # the soak / run-group memcg probe is our own container; docker_stats may catch it (soak #4)
    scope = "github.com/open-telemetry/opentelemetry-collector-contrib/receiver/dockerstatsreceiver"
    probe = gauge_line(res(None, **{"container.name": "ii-probe-memcg-0123456789ab"}), "container.cpu.utilization",
                       [{"timeUnixNano": str(T0 + 120 * S), "asInt": "1"}], scope=scope)
    _, report = run_with(tmp_path, {"metrics": [probe]})
    assert report["unknown_services"] == {}
    assert report["removed_detail"]["X1"]["metrics"]["by_service"]["harness-probe"] == 1


def test_privacy_rules_also_apply_to_the_key_left_after_scrubbing(tmp_path):
    # review: "ofrep.user.email" scrubs to "user.email" and slipped past the privacy rules checked on the raw key
    w = T0 + 120 * S
    sp = span("4" * 32, "5" * 16, w, "Charge", attrs={"ofrep.user.email": "a@b.c", "flagd.demo.payment.card_cvv": 123})
    norm, report = run_with(tmp_path, {"traces": [traces_line(res("payment"), [sp])]})
    s5 = next(x for x in lines(norm / "spans.jsonl") if x["span_id"] == "5" * 16)
    assert "user.email" not in s5["attributes"] and s5["attributes"]["user.hash"] == hashlib.sha256(b"a@b.c").hexdigest()
    assert not any("cvv" in k for k in s5["attributes"])


def test_a_report_that_fails_its_schema_never_leaves_a_published_snapshot(setup, monkeypatch):
    import collect.normalize as nz

    layout, _ = setup

    class Refuse:
        def iter_errors(self, report):
            yield type("E", (), {"message": "forced"})()

    monkeypatch.setattr(nz, "_report_validator", lambda: Refuse())
    with pytest.raises(NormalizeError, match="schema"):
        run(setup)
    assert not (layout.incident_dir("INC-001") / "normalized").exists()  # write-once: nothing to retry around
    monkeypatch.undo()
    run(setup)
