"""Talks to real registries. Deselect offline with: pytest -m 'not network'."""

import pytest

from env.imageref import parse_image_ref
from env.registry import ImageNotFound, UrllibTransport, resolve

pytestmark = pytest.mark.network


@pytest.mark.parametrize("ref", [
    "ghcr.io/open-feature/flagd:v0.16.0",  # ghcr anonymous token
    "postgres:18.4",  # Docker Hub library image
    "quay.io/jaegertracing/jaeger:2.19.0",  # quay
])
def test_resolve_real_multiarch_images(ref):
    r = resolve(parse_image_ref(ref), UrllibTransport())
    assert {"linux/arm64", "linux/amd64"} <= set(r.platforms)
    # resolving by the digest returns the same content
    again = resolve(parse_image_ref(parse_image_ref(ref).pinned(r.index_digest)), UrllibTransport())
    assert again.index_digest == r.index_digest


def test_resolve_real_missing_tag():
    with pytest.raises(ImageNotFound):
        resolve(parse_image_ref("ghcr.io/open-telemetry/demo:0.0.0-does-not-exist"), UrllibTransport())
