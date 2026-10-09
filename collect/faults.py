"""Fault injection through the flagd file (decision 009 §5).

flagd polls the bind-mounted file every second and reloads only when the mtime moves forward, and may
stop watching if a poll sees a half-written file (research notes §3): always write a fresh temp file in
the same directory and os.replace() it. The injected value is confirmed through flagd's OFREP API from
inside the compose network (docker exec), never through Envoy.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

OFREP_URL = "http://flagd:8016/ofrep/v1/evaluate/flags/"

# Flags whose fault is switched through a targeting rule ({"if": [cond, then, else]}) and the evaluation
# context that makes the rule fire, so the confirmation sees the injected value.
_TARGETED = {"productCatalogFailure": {"product_id": "OLJCESPC7Z"}}


def inject(doc: dict, flag: str, variant: str) -> dict:
    """A copy of the flagd document in which `flag` serves `variant` while the fault is on."""
    out = copy.deepcopy(doc)
    f = out["flags"].get(flag)
    if f is None:
        raise ValueError(f"unknown flag {flag!r}")
    if variant not in f["variants"]:
        raise ValueError(f"flag {flag!r} has no variant {variant!r}")
    rule = f.get("targeting")
    if rule is not None:
        if not (isinstance(rule, dict) and set(rule) == {"if"} and len(rule["if"]) == 3):
            raise ValueError(f"unsupported targeting rule on {flag!r}")
        if rule["if"][1] == variant:
            raise ValueError(f"{flag!r} already serves {variant!r}; that injects nothing")
        rule["if"][1] = variant
    else:
        if f["defaultVariant"] == variant:
            raise ValueError(f"{flag!r} already serves {variant!r}; that injects nothing")
        f["defaultVariant"] = variant
    return out


def write_atomic(path: Path, content: dict | bytes) -> None:
    """Replace `path` atomically (same directory, fsync, os.replace); bytes are written verbatim."""
    path = Path(path)
    data = content if isinstance(content, bytes) else (json.dumps(content, indent=2) + "\n").encode()
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_in_place(path: Path, content: dict | bytes) -> None:
    """Rewrite `path` on the same inode (truncate, write, fsync): a watcher bound to the file keeps seeing it."""
    data = content if isinstance(content, bytes) else (json.dumps(content, indent=2) + "\n").encode()
    with Path(path).open("r+b") as f:
        f.seek(0)
        f.write(data)
        f.truncate()
        f.flush()
        os.fsync(f.fileno())


def check_context(flag: str) -> dict:
    return dict(_TARGETED.get(flag, {}))


def ofrep_code(flag: str, context: dict) -> str:
    """Python run inside a container on the compose network (load-generator has python) to evaluate `flag`."""
    body = json.dumps({"context": context})
    return ("import urllib.request\n"
            f"req = urllib.request.Request({OFREP_URL + flag!r}, data={body!r}.encode(), "
            "headers={'Content-Type': 'application/json'}, method='POST')\n"
            "print(urllib.request.urlopen(req, timeout=5).read().decode())")


def parse_ofrep(text: str) -> tuple[str, object]:
    """(variant, value) of an OFREP evaluation response."""
    data = json.loads(text)
    if "variant" not in data:
        raise ValueError(f"OFREP evaluation failed: {text[:200]}")
    return data["variant"], data.get("value")
