"""Normalize policy v1 (decision 011 §3): the leakage and attribution rules, fixed before any fault raw is opened.

The rules live in collect/canonical_policy.v1.json; this module compiles them. POLICY_SHA256 pins the file:
changing any rule changes the digest and must go through decision 011 (and, after the freeze, a v2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

POLICY_PATH = Path(__file__).resolve().parent / "canonical_policy.v1.json"
POLICY_SHA256 = "sha256:c2ced86338a0d8bd4328af3fc97b1769118e369ae34c2626e5d18e5ec7560ef9"

# Separators a deleted token takes with it, so "Fail Feature Flag Enabled" becomes "Fail Enabled".
_SEP = r" _.\-:/=,;"


@dataclass
class Policy:
    raw: dict
    sha256: str
    _lexicon: re.Pattern = field(init=False, repr=False)
    _flag_keys: list[re.Pattern] = field(init=False, repr=False)
    _scope_deny: list[re.Pattern] = field(init=False, repr=False)
    _artifacts: list[tuple[str, re.Pattern]] = field(init=False, repr=False)

    def __post_init__(self):
        tokens = "|".join([re.escape(k) for k in self.raw["flag_keys"]] + self.raw["lexicon_extra"])
        # a token bounded by non-alphanumerics, taking one separator with it (the one before, else the one after)
        self._lexicon = re.compile(
            rf"[{_SEP}](?:{tokens})(?![A-Za-z0-9])|(?<![A-Za-z0-9])(?:{tokens})(?![A-Za-z0-9])[{_SEP}]?", re.IGNORECASE)
        self._flag_keys = [re.compile(p) for p in self.raw["flag_key_patterns"]]
        self._scope_deny = [re.compile(p) for p in self.raw["scope_deny_patterns"]]
        self._artifacts = [(fa["id"], re.compile(fa["pattern"])) for fa in self.raw["fault_artifacts"]]
        cp = self.raw["control_plane"]
        self._peers = set(cp["peer_hosts"])
        self._clusters = set(cp["clusters"])

    @property
    def sut_services(self) -> list[str]:
        return self.raw["sut_services"]

    def scrub(self, text: str) -> tuple[str, int]:
        """X8: silently delete lexicon tokens; returns (text, number of tokens deleted)."""
        return self._lexicon.subn("", text)

    def lexicon_hit(self, text: str) -> bool:
        return self._lexicon.search(text) is not None

    def is_flag_key(self, key: str) -> bool:
        """X5: attribute keys / event names that carry flag instrumentation."""
        return any(p.search(key) for p in self._flag_keys)

    def scope_denied(self, scope_name: str | None) -> bool:
        return bool(scope_name) and any(p.search(scope_name) for p in self._scope_deny)

    def is_fault_artifact(self, text: str) -> str | None:
        """X7: id of the Class A template that names the injection itself, if any."""
        return next((fa_id for fa_id, p in self._artifacts if p.fullmatch(text)), None)

    def control_plane(self, attrs: dict) -> bool:
        """X4: telemetry of control-plane / infrastructure routes (flagd, flagd-ui, collector, jaeger, …)."""
        cp = self.raw["control_plane"]
        rpc = attrs.get("rpc.service")
        if isinstance(rpc, str) and any(rpc.startswith(p) for p in cp["rpc_service_prefixes"]):
            return True
        for key in cp["peer_keys"]:
            v = attrs.get(key)
            if isinstance(v, str) and v.split(":", 1)[0] in self._peers:
                return True
        if any(isinstance(attrs.get(k), str) and attrs[k] in self._clusters for k in cp["cluster_keys"]):
            return True
        for key in cp["path_keys"]:
            v = attrs.get(key)
            if not isinstance(v, str):
                continue
            path = urlsplit(v).path if "://" in v else v
            if any(path.startswith(p) for p in cp["path_prefixes"]):
                return True
        return False


def load_policy(path: Path = POLICY_PATH) -> Policy:
    from env.lock import sha256_path  # one hashing convention for every digest in the project

    return Policy(json.loads(Path(path).read_text()), sha256_path(path))
