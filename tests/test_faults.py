"""Fault injection through the flagd file (decision 009 §5)."""

import copy
import json
import os

import pytest

from collect.faults import check_context, inject, ofrep_code, parse_ofrep, write_atomic, write_in_place
from collect.records import canonical_json_sha256

DOC = {"$schema": "https://flagd.dev/schema/v0/flags.json", "flags": {
    "paymentFailure": {"state": "ENABLED", "defaultVariant": "off",
                       "variants": {"off": 0, "10%": 0.1, "100%": 1}},
    "productCatalogFailure": {"state": "ENABLED", "defaultVariant": "off", "variants": {"off": False, "on": True},
                              "targeting": {"if": [{"==": [{"var": "product_id"}, "OLJCESPC7Z"]}, "off", "off"]}},
}}


def test_inject_switches_the_default_variant_without_touching_the_input():
    before = copy.deepcopy(DOC)
    out = inject(DOC, "paymentFailure", "100%")
    assert out["flags"]["paymentFailure"]["defaultVariant"] == "100%"
    assert out["flags"]["productCatalogFailure"] == DOC["flags"]["productCatalogFailure"]
    assert DOC == before


def test_inject_uses_the_targeting_rule_when_the_flag_has_one():
    # research notes §2: only changing defaultVariant does nothing for productCatalogFailure
    out = inject(DOC, "productCatalogFailure", "on")
    flag = out["flags"]["productCatalogFailure"]
    assert flag["targeting"]["if"][1] == "on" and flag["defaultVariant"] == "off"


@pytest.mark.parametrize("flag, variant", [("nope", "on"), ("paymentFailure", "200%"), ("paymentFailure", "off")])
def test_inject_rejects_unknown_or_no_op_changes(flag, variant):
    with pytest.raises(ValueError):
        inject(DOC, flag, variant)


def test_write_atomic_replaces_the_file_with_a_newer_mtime_and_leaves_no_temp(tmp_path):
    path = tmp_path / "demo.flagd.json"
    path.write_text(json.dumps(DOC))
    os.utime(path, (1, 1))  # flagd only reloads when the mtime moves forward
    write_atomic(path, inject(DOC, "paymentFailure", "100%"))
    assert json.loads(path.read_text())["flags"]["paymentFailure"]["defaultVariant"] == "100%"
    assert path.stat().st_mtime > 1
    assert [p.name for p in tmp_path.iterdir()] == ["demo.flagd.json"]
    assert canonical_json_sha256(path) != "sha256:" + "0" * 64


def test_write_atomic_restores_exact_original_bytes(tmp_path):
    path = tmp_path / "demo.flagd.json"
    original = b'{\n  "flags": {}\n}\n'
    path.write_bytes(original)
    write_atomic(path, {"flags": {"x": 1}})
    write_atomic(path, original)
    assert path.read_bytes() == original


def test_ofrep_check_code_and_response():
    code = ofrep_code("productCatalogFailure", check_context("productCatalogFailure"))
    assert "http://flagd:8016/ofrep/v1/evaluate/flags/productCatalogFailure" in code
    assert "OLJCESPC7Z" in code  # the targeting rule only fires for this product
    assert check_context("paymentFailure") == {}
    assert parse_ofrep('{"key":"paymentFailure","value":1,"variant":"100%","reason":"STATIC"}') == ("100%", 1)
    with pytest.raises(ValueError):
        parse_ofrep('{"errorCode":"FLAG_NOT_FOUND"}')


def test_write_in_place_keeps_the_inode_and_writes_exact_bytes(tmp_path):
    # a file watcher bound to the file keeps seeing it: no rename, the same inode is truncated and rewritten
    path = tmp_path / "demo.flagd.json"
    path.write_text(json.dumps(DOC, indent=2) + "\n")
    inode, original = path.stat().st_ino, path.read_bytes()
    write_in_place(path, inject(DOC, "paymentFailure", "100%"))
    assert path.stat().st_ino == inode and json.loads(path.read_text()) == inject(DOC, "paymentFailure", "100%")
    write_in_place(path, original)
    assert path.read_bytes() == original and path.stat().st_ino == inode
    assert sorted(p.name for p in tmp_path.iterdir()) == ["demo.flagd.json"]
