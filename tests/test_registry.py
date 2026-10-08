import hashlib
import json

import pytest

from env.imageref import parse_image_ref
from env.registry import (
    HttpResponse,
    ImageNotFound,
    RegistryError,
    platform_key,
    resolve,
)

OCI_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def digest_of(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def d(ch: str) -> str:
    return "sha256:" + ch * 64


class FakeTransport:
    """Routes GETs by URL; records every request for assertions."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def get(self, url, headers):
        self.requests.append((url, dict(headers)))
        handler = self.routes.get(url)
        if handler is None:
            return HttpResponse(404, {}, b'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}')
        return handler(headers) if callable(handler) else handler


def index_body(media_type=OCI_INDEX):
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": media_type,
            "manifests": [
                {"mediaType": OCI_MANIFEST, "digest": d("1"), "size": 1,
                 "platform": {"os": "linux", "architecture": "amd64"}},
                {"mediaType": OCI_MANIFEST, "digest": d("2"), "size": 1,
                 "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
                # buildx provenance attestation: must be ignored
                {"mediaType": OCI_MANIFEST, "digest": d("3"), "size": 1,
                 "platform": {"os": "unknown", "architecture": "unknown"},
                 "annotations": {"vnd.docker.reference.type": "attestation-manifest"}},
            ],
        }
    ).encode()


GHCR_URL = "https://ghcr.io/v2/open-telemetry/demo/manifests/3.1.0-ad"


def test_resolve_index_lists_platforms_and_skips_attestations():
    body = index_body()
    t = FakeTransport({GHCR_URL: HttpResponse(200, {"content-type": OCI_INDEX,
                                                     "docker-content-digest": digest_of(body)}, body)})
    r = resolve(parse_image_ref("ghcr.io/open-telemetry/demo:3.1.0-ad"), t)
    assert r.index_digest == digest_of(body)
    assert r.media_type == OCI_INDEX
    assert r.platforms == {"linux/amd64": d("1"), "linux/arm64": d("2")}
    assert r.ref == "ghcr.io/open-telemetry/demo:3.1.0-ad"


def test_resolve_sends_accept_for_index_and_manifest_types():
    body = index_body()
    t = FakeTransport({GHCR_URL: HttpResponse(200, {"content-type": OCI_INDEX}, body)})
    resolve(parse_image_ref("ghcr.io/open-telemetry/demo:3.1.0-ad"), t)
    accept = t.requests[0][1]["Accept"]
    for mt in (OCI_INDEX, DOCKER_LIST, OCI_MANIFEST, "application/vnd.docker.distribution.manifest.v2+json"):
        assert mt in accept


def test_resolve_handles_bearer_challenge():
    body = index_body(DOCKER_LIST)

    def manifest(headers):
        if headers.get("Authorization") != "Bearer tok123":
            return HttpResponse(401, {"www-authenticate":
                'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",'
                'scope="repository:library/postgres:pull"'}, b"")
        return HttpResponse(200, {"content-type": DOCKER_LIST}, body)

    token_url = ("https://auth.docker.io/token?service=registry.docker.io"
                 "&scope=repository%3Alibrary%2Fpostgres%3Apull")
    t = FakeTransport({
        "https://registry-1.docker.io/v2/library/postgres/manifests/18.4": manifest,
        token_url: HttpResponse(200, {}, json.dumps({"token": "tok123"}).encode()),
    })
    r = resolve(parse_image_ref("postgres:18.4"), t)
    assert r.platforms["linux/arm64"] == d("2")
    assert [u for u, _ in t.requests].count(token_url) == 1


def test_resolve_accepts_access_token_field():
    body = index_body()

    def manifest(headers):
        if headers.get("Authorization") != "Bearer abc":
            return HttpResponse(401, {"www-authenticate": 'Bearer realm="https://q.io/t",service="q.io"'}, b"")
        return HttpResponse(200, {"content-type": OCI_INDEX}, body)

    t = FakeTransport({
        "https://q.io/v2/x/y/manifests/1": manifest,
        "https://q.io/t?service=q.io&scope=repository%3Ax%2Fy%3Apull": HttpResponse(
            200, {}, json.dumps({"access_token": "abc"}).encode()),
    })
    assert resolve(parse_image_ref("q.io/x/y:1"), t).index_digest == digest_of(body)


def test_resolve_single_manifest_reads_platform_from_config_blob():
    config = json.dumps({"os": "linux", "architecture": "arm64"}).encode()
    manifest = json.dumps({"schemaVersion": 2, "mediaType": OCI_MANIFEST,
                           "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                                      "digest": digest_of(config), "size": len(config)},
                           "layers": []}).encode()
    t = FakeTransport({
        "https://ghcr.io/v2/a/b/manifests/1": HttpResponse(200, {"content-type": OCI_MANIFEST}, manifest),
        f"https://ghcr.io/v2/a/b/blobs/{digest_of(config)}": HttpResponse(200, {}, config),
    })
    r = resolve(parse_image_ref("ghcr.io/a/b:1"), t)
    assert r.media_type == OCI_MANIFEST
    assert r.index_digest == digest_of(manifest)
    assert r.platforms == {"linux/arm64": digest_of(manifest)}


def test_resolve_rejects_header_digest_mismatch():
    body = index_body()
    t = FakeTransport({GHCR_URL: HttpResponse(200, {"content-type": OCI_INDEX,
                                                     "docker-content-digest": d("f")}, body)})
    with pytest.raises(RegistryError, match="digest mismatch"):
        resolve(parse_image_ref("ghcr.io/open-telemetry/demo:3.1.0-ad"), t)


def test_resolve_rejects_content_not_matching_requested_digest():
    body = index_body()
    url = f"https://ghcr.io/v2/open-telemetry/demo/manifests/{d('e')}"
    t = FakeTransport({url: HttpResponse(200, {"content-type": OCI_INDEX}, body)})
    with pytest.raises(RegistryError, match="digest mismatch"):
        resolve(parse_image_ref(f"ghcr.io/open-telemetry/demo:3.1.0-ad@{d('e')}"), t)


def test_resolve_missing_tag_raises_image_not_found():
    with pytest.raises(ImageNotFound):
        resolve(parse_image_ref("ghcr.io/open-telemetry/demo:9.9.9-nope"), FakeTransport({}))


def test_resolve_other_http_errors_raise_registry_error():
    t = FakeTransport({GHCR_URL: HttpResponse(500, {}, b"boom")})
    with pytest.raises(RegistryError):
        resolve(parse_image_ref("ghcr.io/open-telemetry/demo:3.1.0-ad"), t)


def test_resolve_rejects_duplicate_platforms_in_index():
    body = json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [
        {"digest": d("1"), "platform": {"os": "linux", "architecture": "arm64"}},
        {"digest": d("2"), "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
    ]}).encode()
    t = FakeTransport({GHCR_URL: HttpResponse(200, {"content-type": OCI_INDEX}, body)})
    with pytest.raises(RegistryError, match="duplicate platform"):
        resolve(parse_image_ref("ghcr.io/open-telemetry/demo:3.1.0-ad"), t)


@pytest.mark.parametrize("os_, arch, variant, key", [
    ("linux", "amd64", None, "linux/amd64"),
    ("linux", "arm64", None, "linux/arm64"),
    ("linux", "arm64", "v8", "linux/arm64"),
    ("linux", "arm", "v7", "linux/arm/v7"),
])
def test_platform_key_normalises_arm64_v8(os_, arch, variant, key):
    assert platform_key(os_, arch, variant) == key


def test_network_failures_become_registry_errors():
    from env.registry import UrllibTransport

    # port 9 on localhost: connection refused, no network needed
    with pytest.raises(RegistryError):
        resolve(parse_image_ref("127.0.0.1:9/a/b:1"), UrllibTransport(timeout=2))


def test_non_json_manifest_body_is_a_registry_error():
    t = FakeTransport({GHCR_URL: HttpResponse(200, {"content-type": OCI_INDEX}, b"<html>rate limited</html>")})
    with pytest.raises(RegistryError):
        resolve(parse_image_ref("ghcr.io/open-telemetry/demo:3.1.0-ad"), t)


@pytest.mark.parametrize("raw", [
    b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nshort",  # connection drops mid-body: IncompleteRead
    b"GARBAGE\r\n\r\n",  # BadStatusLine
])
def test_broken_http_responses_become_registry_errors(raw):
    import socket
    import threading

    from env.registry import UrllibTransport

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(65536)
        conn.sendall(raw)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    try:
        with pytest.raises(RegistryError):
            UrllibTransport(timeout=5).get(f"http://127.0.0.1:{srv.getsockname()[1]}/v2/", {})
    finally:
        srv.close()
