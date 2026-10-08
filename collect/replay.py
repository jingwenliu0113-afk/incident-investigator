"""Day 1 #6: analyse an incident from its frozen snapshot alone, with the live system deleted.

Refuses while any container of the project still exists; then verifies the snapshot bytes, checks that
every record id resolves (evidence existence), and computes the shared derived views from the snapshot.
"""

from __future__ import annotations

from collections.abc import Callable

from collect.derive import service_minute_stats
from collect.layout import DataLayout
from collect.normalize import check_snapshot
from collect.policy import load_policy
from collect.snapshot import open_snapshot


def replay(layout: DataLayout, incident_id: str, *, live_containers: Callable[[], list[str]]) -> dict:
    if running := live_containers():
        raise RuntimeError(f"the live system is still running ({', '.join(running)}); `compose down --volumes` first")
    path = layout.incident_dir(incident_id) / "normalized"
    snap = open_snapshot(path, layout)
    records = {f["path"]: f["records"] for f in snap.meta["files"]}
    ids = [r["id"] for gen in (snap.spans(), snap.logs(), snap.series(), snap.points()) for r in gen]
    every_id_resolves = all(snap.resolve(i) is not None for i in ids)
    stats = service_minute_stats(snap)
    errors = {svc: sum(m["error_spans"] for m in minutes.values()) for svc, minutes in stats["services"].items()}
    return {"incident_id": incident_id, "content_sha256": snap.meta["content_sha256"], "records": records,
            "every_id_resolves": every_id_resolves, "checks": check_snapshot(path, load_policy()),
            "error_spans_by_service": {k: v for k, v in sorted(errors.items()) if v}, "derive_version": stats["version"]}
