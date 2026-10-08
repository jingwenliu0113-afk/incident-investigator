"""Container image reference parsing, following Docker's normalisation rules.

Only what the env lock needs: split a reference into registry / repository /
tag / digest, know which host serves the registry API, and render a
digest-pinned reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DOCKER_HUB = "docker.io"
DOCKER_HUB_API = "registry-1.docker.io"
_DOCKER_HUB_ALIASES = {"docker.io", "index.docker.io"}

# Always used with fullmatch (a plain `$` would also accept a trailing newline).
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_TAG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
_PATH_COMPONENT_RE = re.compile(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*")


def is_sha256_digest(value: str) -> bool:
    return bool(_DIGEST_RE.fullmatch(value))


@dataclass(frozen=True)
class ImageRef:
    registry: str
    repository: str
    tag: str | None
    digest: str | None
    # The name exactly as written (without tag/digest), e.g. "postgres" rather
    # than "docker.io/library/postgres", so pinned refs stay readable.
    name: str

    @property
    def api_host(self) -> str:
        return DOCKER_HUB_API if self.registry == DOCKER_HUB else self.registry

    @property
    def reference(self) -> str:
        """What to ask the registry for: the digest if known, else the tag."""
        return self.digest or self.tag or "latest"

    def pinned(self, digest: str) -> str:
        if not is_sha256_digest(digest):
            raise ValueError(f"not a sha256 digest: {digest!r}")
        tag = f":{self.tag}" if self.tag else ""
        return f"{self.name}{tag}@{digest}"

    def __str__(self) -> str:
        out = self.name
        if self.tag:
            out += f":{self.tag}"
        if self.digest:
            out += f"@{self.digest}"
        return out


def parse_image_ref(text: str) -> ImageRef:
    if not text or text != text.strip():
        raise ValueError(f"invalid image reference: {text!r}")

    rest, digest = text, None
    if "@" in rest:
        rest, digest = rest.split("@", 1)
        if not is_sha256_digest(digest):
            raise ValueError(f"invalid digest in {text!r}")

    name, tag = rest, None
    last_slash = rest.rfind("/")
    colon = rest.rfind(":")
    if colon > last_slash:
        name, tag = rest[:colon], rest[colon + 1 :]
        if not _TAG_RE.fullmatch(tag):
            raise ValueError(f"invalid tag in {text!r}")
    if tag is None and digest is None:
        tag = "latest"

    first, _, remainder = name.partition("/")
    if remainder and ("." in first or ":" in first or first == "localhost"):
        registry, repository = first, remainder
    else:
        registry, repository = DOCKER_HUB, name
    if registry in _DOCKER_HUB_ALIASES:
        registry = DOCKER_HUB
        if "/" not in repository:
            repository = f"library/{repository}"

    if not repository or not all(_PATH_COMPONENT_RE.fullmatch(c) for c in repository.split("/")):
        raise ValueError(f"invalid repository in {text!r}")

    return ImageRef(registry=registry, repository=repository, tag=tag, digest=digest, name=name)
