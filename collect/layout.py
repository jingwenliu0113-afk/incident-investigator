"""Physical layout of collected data (all under gitignored data/external/).

    data/external/
    ├── incidents/<INC-nnn>/          agent/baseline-readable side
    │   ├── raw/ normalized/
    │   └── manifest.json             provenance only
    └── ground_truth/                 NEVER mounted or readable by agents/baselines
        └── run_groups/<RG-nnn>/injection.json

IDs are opaque counters so a path never reveals the fault.
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
