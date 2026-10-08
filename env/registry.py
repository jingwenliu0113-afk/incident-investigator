"""Resolve image tags to content digests through the OCI distribution API.

Talks to registries directly over HTTPS (anonymous pull tokens), so pinning
works without a running Docker daemon. The digest is always recomputed from
the manifest bytes and cross-checked against the registry's header.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from env.imageref import ImageRef

INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
ACCEPT = ", ".join(INDEX_TYPES + MANIFEST_TYPES)


class RegistryError(RuntimeError):
    pass


class ImageNotFound(RegistryError):
    pass


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]  # keys lower-cased
    body: bytes


class Transport(Protocol):
    def get(self, url: str, headers: dict[str, str]) -> HttpResponse: ...


class UrllibTransport:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return HttpResponse(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
            except urllib.error.HTTPError as e:
                return HttpResponse(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read())
        # refused / DNS / TLS / timeout (URLError, OSError); truncated body or bad status line (HTTPException)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise RegistryError(f"GET {url}: {type(e).__name__}: {e}") from e


@dataclass(frozen=True)
class ResolvedImage:
    ref: str
    index_digest: str
    media_type: str
    platforms: dict[str, str] = field(default_factory=dict)


def platform_key(os_: str, arch: str, variant: str | None = None) -> str:
    if arch == "arm64" and variant in (None, "", "v8"):
        variant = None
    return f"{os_}/{arch}" + (f"/{variant}" if variant else "")


_ARCH_ALIASES = {"aarch64": "arm64", "x86_64": "amd64"}  # uname / `docker info` spellings


def normalize_platform(text: str) -> str:
    """'linux/aarch64', 'linux/arm64/v8' -> 'linux/arm64'; same keys as the lock uses."""
    os_, _, rest = text.partition("/")
    arch, _, variant = rest.partition("/")
    return platform_key(os_, _ARCH_ALIASES.get(arch, arch), variant or None)


def _sha256(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _json(body: bytes, what: str) -> dict:
    try:
        doc = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise RegistryError(f"{what}: response is not JSON ({e})") from e
    if not isinstance(doc, dict):
        raise RegistryError(f"{what}: unexpected JSON {type(doc).__name__}")
    return doc


_CHALLENGE_PARAM = re.compile(r'(\w+)="([^"]*)"')


class _Session:
    """One repository on one registry; caches the bearer token."""

    def __init__(self, ref: ImageRef, transport: Transport):
        self.ref = ref
        self.transport = transport
        self.token: str | None = None

    def get(self, path: str, accept: str | None = None) -> HttpResponse:
        url = f"https://{self.ref.api_host}/v2/{self.ref.repository}/{path}"
        resp = self.transport.get(url, self._headers(accept))
        if resp.status == 401 and self.token is None:
            self.token = self._fetch_token(resp.headers.get("www-authenticate", ""))
            resp = self.transport.get(url, self._headers(accept))
        if resp.status == 404:
            raise ImageNotFound(f"{self.ref}: {path} not found")
        if resp.status != 200:
            raise RegistryError(f"{self.ref}: GET {path} -> HTTP {resp.status}")
        return resp

    def _headers(self, accept: str | None) -> dict[str, str]:
        headers = {}
        if accept:
            headers["Accept"] = accept
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _fetch_token(self, challenge: str) -> str:
        if not challenge.lower().startswith("bearer "):
            raise RegistryError(f"{self.ref}: unsupported auth challenge {challenge!r}")
        params = dict(_CHALLENGE_PARAM.findall(challenge))
        realm = params.pop("realm", None)
        if not realm:
            raise RegistryError(f"{self.ref}: auth challenge without realm")
        params.setdefault("scope", f"repository:{self.ref.repository}:pull")
        query = urllib.parse.urlencode({k: params[k] for k in ("service", "scope") if k in params})
        resp = self.transport.get(f"{realm}?{query}", {})
        if resp.status != 200:
            raise RegistryError(f"{self.ref}: token request -> HTTP {resp.status}")
        payload = _json(resp.body, f"{self.ref}: token response")
        token = payload.get("token") or payload.get("access_token")
        if not token:
            raise RegistryError(f"{self.ref}: token response without token")
        return token


def resolve(ref: ImageRef, transport: Transport) -> ResolvedImage:
    session = _Session(ref, transport)
    resp = session.get(f"manifests/{ref.reference}", ACCEPT)

    digest = _sha256(resp.body)
    header_digest = resp.headers.get("docker-content-digest")
    if header_digest and header_digest != digest:
        raise RegistryError(f"{ref}: digest mismatch (header {header_digest}, content {digest})")
    if ref.digest and ref.digest != digest:
        raise RegistryError(f"{ref}: digest mismatch (requested {ref.digest}, content {digest})")

    doc = _json(resp.body, f"{ref}: manifest")
    media_type = doc.get("mediaType") or resp.headers.get("content-type", "").split(";")[0]

    if media_type in INDEX_TYPES:
        platforms: dict[str, str] = {}
        for entry in doc.get("manifests", []):
            p = entry.get("platform") or {}
            if p.get("os", "unknown") == "unknown":
                continue  # buildx attestation manifests
            key = platform_key(p["os"], p["architecture"], p.get("variant"))
            if key in platforms:
                raise RegistryError(f"{ref}: duplicate platform {key} in index")
            platforms[key] = entry["digest"]
    elif media_type in MANIFEST_TYPES:
        config = _json(session.get(f"blobs/{doc['config']['digest']}").body, f"{ref}: image config")
        platforms = {platform_key(config["os"], config["architecture"], config.get("variant")): digest}
    else:
        raise RegistryError(f"{ref}: unsupported manifest media type {media_type!r}")

    return ResolvedImage(ref=str(ref), index_digest=digest, media_type=media_type, platforms=platforms)
