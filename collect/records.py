"""Validation of the per-incident manifest and the per-run-group fault injection record."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS_DIR / name).read_text()))


def _schema_problems(doc: dict, name: str) -> list[str]:
    errors = sorted(_validator(name).iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [f"schema: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors]


def _timestamps(fields: Mapping[str, str]) -> tuple[dict[str, datetime], list[str]]:
    """Parse schema-shaped UTC timestamps; impossible dates become problems, not exceptions."""
    parsed, problems = {}, []
    for name, value in fields.items():
        try:
            parsed[name] = datetime.fromisoformat(value)
        except ValueError:
            problems.append(f"{name}: invalid timestamp {value!r}")
    return parsed, problems


def canonical_json_sha256(path: Path) -> str:
    """sha256 of a JSON file's content, independent of formatting and key order.

    Used for injection_record.flag_file: the same flag state is written compactly by
    flagd-ui's API and pretty-printed by its UI.
    """
    canonical = json.dumps(json.loads(Path(path).read_text()), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def load_flag_catalog(path: Path) -> dict[str, dict]:
    """Flags of a flagd file: {key: {"default": variant, "variants": {...}, "description": str}}."""
    flags = json.loads(Path(path).read_text())["flags"]
    return {
        key: {"default": f["defaultVariant"], "variants": f["variants"], "description": f.get("description", "")}
        for key, f in flags.items()
    }


def check_manifest(
    manifest: dict,
    *,
    formal: bool,
    lock_sha256: str | None = None,
    flag_catalog: Mapping[str, dict] | None = None,
) -> list[str]:
    problems = _schema_problems(manifest, "run_manifest.schema.json")
    if problems:
        return problems

    ts, problems = _timestamps({
        "created_at": manifest["created_at"],
        "startup/started_at": manifest["startup"]["started_at"],
        "window/start": manifest["window"]["start"],
        "window/end": manifest["window"]["end"],
    })
    if {"window/start", "window/end"} <= ts.keys() and ts["window/end"] <= ts["window/start"]:
        problems.append("window: end must be after start")

    if flag_catalog:
        text = json.dumps(manifest)
        problems += [f"manifest mentions fault flag {flag!r} (ground truth leak)" for flag in flag_catalog if flag in text]

    if formal:
        if manifest["project"]["commit"] is None:
            problems.append("formal run needs a project git commit")
        if manifest["project"]["dirty"]:
            problems.append("formal run needs a clean (non-dirty) project checkout")
        if lock_sha256 is None:
            problems.append("formal check needs the sha256 of the current env lock")
        elif manifest["env_lock"]["sha256"] != lock_sha256:
            problems.append(f"env lock sha256 {manifest['env_lock']['sha256']} does not match current lock {lock_sha256}")
        if manifest["machine"]["docker"] is None:
            problems.append("formal run needs docker engine facts (daemon was unreachable)")
    return problems


def check_injection(
    record: dict,
    flag_catalog: Mapping[str, dict],
    *,
    baseline_flag_sha256: str | None = None,
) -> list[str]:
    """`baseline_flag_sha256`: sha256 of the pinned upstream flag file, when known."""
    problems = _schema_problems(record, "fault_injection.schema.json")
    if problems:
        return problems

    flag_file = record["flag_file"]
    if flag_file["baseline_sha256"] == flag_file["injected_sha256"]:
        problems.append("flag file unchanged between baseline and injection; nothing was injected")
    if baseline_flag_sha256 is not None and flag_file["baseline_sha256"] != baseline_flag_sha256:
        problems.append(f"baseline flag file {flag_file['baseline_sha256']} is not the pinned one {baseline_flag_sha256}")

    fault = record["fault"]
    flag = flag_catalog.get(fault["flag"])
    if flag is None:
        problems.append(f"unknown flag {fault['flag']!r} (not in pinned flagd file)")
    elif fault["variant"] not in flag["variants"]:
        problems.append(f"flag {fault['flag']!r} has no variant {fault['variant']!r}")
    elif fault["variant"] == flag["default"]:
        problems.append(f"variant {fault['variant']!r} is the baseline default; that injects nothing")

    s, ts_problems = _timestamps({f"schedule/{k}": v for k, v in record["schedule"].items()})
    problems += ts_problems
    if not ts_problems and not (s["schedule/normal_start"] < s["schedule/fault_on"]
                                < s["schedule/fault_off"] <= s["schedule/end"]):
        problems.append("schedule must satisfy normal_start < fault_on < fault_off <= end")
    return problems
