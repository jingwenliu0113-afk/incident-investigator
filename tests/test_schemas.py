"""Portability guards for every regex in schemas/*.json.

jsonschema (Python) evaluates `pattern` with re.search, where a bare `$` also matches before a
trailing newline and `\\d` matches non-ASCII digits. Patterns must behave the same in Python and
ECMA-262 (the JSON Schema dialect), so they end with `(?!\\n)$` and use [0-9].
"""

import json
from pathlib import Path

import pytest

SCHEMAS = sorted((Path(__file__).resolve().parent.parent / "schemas").glob("*.json"))


def _patterns(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pattern" and isinstance(v, str):
                yield path, v
            else:
                yield from _patterns(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _patterns(v, f"{path}/{i}")


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda p: p.name)
def test_schema_patterns_are_strictly_anchored_and_ascii(schema):
    patterns = list(_patterns(json.loads(schema.read_text())))
    assert patterns, f"{schema.name} has no patterns?"
    for where, pat in patterns:
        assert "\\d" not in pat, f"{schema.name}{where}: use [0-9] instead of \\d: {pat}"
        if pat.endswith("$"):
            assert pat.endswith("(?!\\n)$"), f"{schema.name}{where}: end with (?!\\n)$: {pat}"


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda p: p.name)
def test_schemas_are_valid_draft_2020_12(schema):
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(json.loads(schema.read_text()))
