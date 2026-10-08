"""Normalize one stored incident and write its provenance manifest (decisions 002, 009, 011).

Only this module reads the run record on the ground-truth side, and it passes on nothing but the raw
location, digests, duplicate counts, incident window and clock offsets: normalize itself stays GT-blind.
"""

from __future__ import annotations

import json

from collect.layout import DataLayout
from collect.normalize import FILES, NormalizeInputs, normalize
from collect.policy import POLICY_SHA256, Policy, load_policy
from collect.rawexport import check_raw_export
from collect.records import check_manifest
from collect.traffic import TRAFFIC_SERVICE


def find_run(layout: DataLayout, incident_id: str) -> dict:
    """The valid run record whose run group was cut into `incident_id`."""
    for path in sorted((layout.ground_truth_root / "run_groups").glob("RG-*/run.json")):
        run = json.loads(path.read_text())
        if incident_id in run.get("incident_ids", []) and run.get("status") == "valid":
            return run
    raise LookupError(f"no valid run group has incident {incident_id}")


def normalize_incident(layout: DataLayout, incident_id: str, *, lock_sha256: str, now: str,
                       policy: Policy | None = None, code: dict | None = None) -> dict:
    """`code`: git state of this checkout (taken here when not given); the normalizer must be a clean commit."""
    policy = policy or load_policy()
    if policy.raw.get("status") != "frozen":
        raise PermissionError(f"normalize policy v{policy.raw['version']} is {policy.raw.get('status')!r}, not frozen: "
                              "fault raw must not be opened before the rules are frozen (decision 011 §4)")
    if policy.sha256 != POLICY_SHA256:
        raise PermissionError(f"policy {policy.sha256} is not the pinned {POLICY_SHA256} (decision 011 §3 G0)")
    if code is None:
        from collect.provenance import project_git_state
        from env.lock import PROJECT_DIR

        code = project_git_state(PROJECT_DIR)
    if code.get("commit") is None or code.get("dirty"):
        raise PermissionError(f"normalize needs a clean, committed checkout so the snapshot names its code: {code}")
    run = find_run(layout, incident_id)
    rg = run["run_group_id"]
    export = json.loads(layout.raw_export_path(rg).read_text())
    if problems := check_raw_export(export):
        raise ValueError(f"raw export of {rg} is inconsistent: {problems}")
    if not export["complete"]:
        raise ValueError(f"raw export of {rg} is not complete: {export['flags']}")
    inputs = NormalizeInputs(
        raw_dir=layout.raw_dir(rg),
        raw_sha256={f["signal"]: f["sha256"] for f in export["files"]},
        raw_duplicates={f["signal"]: f["duplicates"] for f in export["files"]},
        window_host=(run["incident_window"]["start"], run["incident_window"]["end"]),
        clock_offsets=list(run["clock_offset_seconds"]))
    incident_dir = layout.incident_dir(incident_id)
    prov = run["provenance"]
    from env.lock import sha256_path

    manifest = {
        "manifest_version": 1,
        "incident_id": incident_id,
        "created_at": now,
        "project": prov["project"],
        "env_lock": prov["env_lock"],
        "machine": prov["machine"],
        "startup": {"compose_command": prov["compose_command"], "started_at": run["up_at"]},
        # the seed fixes the normal / recovery lengths, hence the fault schedule: it stays on the truth side (decision 002)
        "traffic": {"generator_service": TRAFFIC_SERVICE, "settings": prov["traffic_settings"], "seed": None,
                    "seed_applied": False},  # decision 003: Locust has no seed hook
        "window": dict(run["incident_window"]),
        "files": [],
    }
    flags = {k: {} for k in policy.raw["flag_keys"]}
    # the snapshot is write-once: every provenance problem must stop us before it is published
    if problems := check_manifest(manifest, formal=True, lock_sha256=lock_sha256, flag_catalog=flags):
        raise ValueError(f"manifest of {incident_id} fails the formal check: {problems}")
    report = normalize(inputs, policy, incident_dir=incident_dir, report_path=layout.normalize_report_path(incident_id),
                       staging_dir=layout.root / "staging" / f"normalize-{incident_id}", code=code)
    manifest["files"] = [{"path": f"normalized/{name}", "sha256": sha256_path(incident_dir / "normalized" / name),
                          "bytes": (incident_dir / "normalized" / name).stat().st_size} for name in FILES]
    if problems := check_manifest(manifest, formal=True, lock_sha256=lock_sha256, flag_catalog=flags):
        raise ValueError(f"manifest of {incident_id} fails the formal check: {problems}")
    layout.manifest_path(incident_id).write_text(json.dumps(manifest, indent=2) + "\n")
    return report
