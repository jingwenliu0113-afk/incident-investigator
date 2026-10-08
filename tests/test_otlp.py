"""OTLP JSON helpers shared by the raw scan and normalize (decisions 008 §7, 011 §2)."""

import math

import pytest

from collect.otlp import any_value, attributes, enum, log_key, nanos, point_key, series_key, span_key


def test_any_value_is_lossless():
    assert any_value({"stringValue": "x"}) == "x"
    assert any_value({"boolValue": False}) is False
    assert any_value({"intValue": "9007199254740993"}) == 9007199254740993  # int64 as a decimal string
    assert any_value({"intValue": 7}) == 7
    assert any_value({"doubleValue": 1.5}) == 1.5
    assert any_value({"doubleValue": "NaN"}) == {"$double": "NaN"}
    assert any_value({"doubleValue": "-Infinity"}) == {"$double": "-Infinity"}
    assert any_value({"bytesValue": "AQI="}) == {"$bytes": "AQI="}
    assert any_value({"arrayValue": {"values": [{"intValue": "1"}, {"stringValue": "a"}]}}) == [1, "a"]
    assert any_value({"kvlistValue": {"values": [{"key": "k", "value": {"boolValue": True}}]}}) == {"k": True}
    assert any_value({}) is None and any_value(None) is None
    assert any_value({"arrayValue": {}}) == []


def test_any_value_rejects_keys_that_would_collide_with_the_typed_markers():
    with pytest.raises(ValueError):
        any_value({"kvlistValue": {"values": [{"key": "$double", "value": {"stringValue": "x"}}]}})


def test_attributes_keep_the_first_of_duplicate_keys_and_count_them():
    counts = {}
    out = attributes([{"key": "a", "value": {"intValue": "1"}}, {"key": "a", "value": {"intValue": "2"}},
                      {"key": "b", "value": {"stringValue": "\ud800x"}}], counts)
    assert out == {"a": 1, "b": "�x"}
    assert counts == {"duplicate_keys": 1, "lone_surrogates": 1}


def test_enums_accept_numbers_and_names():
    assert enum("span_kind", 2) == "server" and enum("span_kind", "SPAN_KIND_CLIENT") == "client"
    assert enum("span_kind", None) == "unspecified"
    assert enum("status_code", 2) == "error" and enum("status_code", "STATUS_CODE_OK") == "ok"
    assert enum("temporality", 2) == "cumulative" and enum("temporality", None) is None
    with pytest.raises(ValueError):
        enum("span_kind", 9)


def test_nanos():
    assert nanos("1791453665000000000") == 1791453665000000000
    assert nanos(0) is None and nanos(None) is None and nanos("x") is None


def test_dedupe_keys_match_decision_008():
    span = {"traceId": "a" * 32, "spanId": "b" * 16, "name": "x"}
    assert span_key(span) == ("span", "a" * 32, "b" * 16)
    res = {"attributes": [{"key": "service.name", "value": {"stringValue": "cart"}}]}
    p = {"startTimeUnixNano": "1", "timeUnixNano": "2", "attributes": [{"key": "k", "value": {"stringValue": "v"}}]}
    k = point_key(res, {"name": "s", "version": "1"}, "m", p)
    assert k[0] == "point" and k[-2:] == ("1", "2")
    assert series_key(res, {"name": "s", "version": "1"}, "m", p) == k[:-2]
    rec = {"timeUnixNano": "5", "body": {"stringValue": "hi"}}
    assert log_key(res, rec) == log_key(res, dict(rec))
    assert log_key(res, rec) != log_key(res, {**rec, "timeUnixNano": "6"})
    assert not math.isnan(len(log_key(res, rec)))
