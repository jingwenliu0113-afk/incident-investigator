"""Physical layout of collected data (all under gitignored data/external/).

    data/external/
    ├── incidents/<INC-nnn>/
    │   ├── normalized/               the ONLY agent/baseline-readable data (is_agent_readable)
    │   └── manifest.json             provenance only (people and eval)
    ├── raw/<RG-nnn>/                 raw telemetry of one run group + raw_export.json (decision 008)
    └── ground_truth/                 NEVER mounted or readable by agents/baselines
        ├── run_groups/<RG-nnn>/injection.json
        └── incidents/<INC-nnn>/label.json

IDs are opaque counters so a path never reveals the fault. Which raw run group an incident was
cut from is recorded only on the ground-truth side.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

INCIDENT_ID = re.compile(r"INC-[0-9]{3,}")  # always fullmatch: ASCII digits, no trailing newline
RUN_GROUP_ID = re.compile(r"RG-[0-9]{3,}")


def _checked(value: str, pattern: re.Pattern, kind: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {kind} {value!r} (expected {pattern.pattern})")
    return value


@dataclass(frozen=True)
class DataLayout:
    root: Path

    @property
    def incidents_root(self) -> Path:
        return self.root / "incidents"

    @property
    def ground_truth_root(self) -> Path:
        return self.root / "ground_truth"

    def incident_dir(self, incident_id: str) -> Path:
        return self.incidents_root / _checked(incident_id, INCIDENT_ID, "incident id")

    def manifest_path(self, incident_id: str) -> Path:
        return self.incident_dir(incident_id) / "manifest.json"

    def run_group_truth_dir(self, run_group_id: str) -> Path:
        return self.ground_truth_root / "run_groups" / _checked(run_group_id, RUN_GROUP_ID, "run group id")

    def injection_path(self, run_group_id: str) -> Path:
        return self.run_group_truth_dir(run_group_id) / "injection.json"

    @property
    def raw_root(self) -> Path:
        return self.root / "raw"

    def raw_dir(self, run_group_id: str) -> Path:
        return self.raw_root / _checked(run_group_id, RUN_GROUP_ID, "run group id")

    def raw_export_path(self, run_group_id: str) -> Path:
        return self.raw_dir(run_group_id) / "raw_export.json"

    def is_agent_readable(self, path: Path) -> bool:
        """Allow-list (decision 008 §5): only incidents/<INC>/normalized/** may reach an agent or baseline.

        Decided by file identity like is_ground_truth: symlinks are resolved, letter case is folded,
        and anything that may alias a ground-truth file (extra hard links) is refused.
        """
        if self.is_ground_truth(path):
            return False
        resolved, incidents = Path(path).resolve(), self.incidents_root.resolve()
        base = [p.casefold() for p in incidents.parts]
        if [p.casefold() for p in resolved.parts[: len(base)]] != base:
            return False
        rest = resolved.parts[len(base):]
        return (len(rest) >= 2 and rest[0].isascii() and INCIDENT_ID.fullmatch(rest[0].upper()) is not None
                and rest[1].casefold() == "normalized")

    def normalize_report_path(self, incident_id: str) -> Path:
        """What normalize removed and why (decision 011): ground-truth side, it reveals where the fault was."""
        return (self.ground_truth_root / "incidents" / _checked(incident_id, INCIDENT_ID, "incident id")
                / "normalize_report.json")

    def label_path(self, incident_id: str) -> Path:
        return (self.ground_truth_root / "incidents" / _checked(incident_id, INCIDENT_ID, "incident id")
                / "label.json")

    def is_ground_truth(self, path: Path) -> bool:
        """Is `path` (or what it points to) inside the ground-truth tree?

        Decided by file identity, not spelling: symlinks are resolved, letter-case variants
        count (macOS APFS is case-insensitive by default), and a regular file with more than
        one hard link is refused because it may alias a ground-truth file.
        """
        resolved, truth = Path(path).resolve(), self.ground_truth_root.resolve()
        folded, truth_folded = [p.casefold() for p in resolved.parts], [p.casefold() for p in truth.parts]
        if folded[: len(truth_folded)] == truth_folded:
            return True
        if truth.exists() and any(c.exists() and os.path.samefile(c, truth) for c in (resolved, *resolved.parents)):
            return True
        return resolved.is_file() and resolved.stat().st_nlink > 1
