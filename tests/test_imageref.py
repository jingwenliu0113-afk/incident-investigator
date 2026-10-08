import pytest

from env.imageref import ImageRef, parse_image_ref

DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize(
    "text, registry, repository, tag",
    [
        ("postgres:18.4", "docker.io", "library/postgres", "18.4"),
        ("grafana/grafana:13.1.0", "docker.io", "grafana/grafana", "13.1.0"),
        ("docker.io/library/postgres:18.4", "docker.io", "library/postgres", "18.4"),
        ("ghcr.io/open-telemetry/demo:3.1.0-frontend", "ghcr.io", "open-telemetry/demo", "3.1.0-frontend"),
        ("quay.io/jaegertracing/jaeger:2.19.0", "quay.io", "jaegertracing/jaeger", "2.19.0"),
        (
            "ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib:0.159.0",
            "ghcr.io",
            "open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib",
            "0.159.0",
        ),
        ("localhost:5000/foo/bar:dev", "localhost:5000", "foo/bar", "dev"),
        ("localhost/foo", "localhost", "foo", "latest"),
        ("postgres", "docker.io", "library/postgres", "latest"),
    ],
)
def test_parse_tagged_refs(text, registry, repository, tag):
    ref = parse_image_ref(text)
    assert ref.registry == registry
    assert ref.repository == repository
    assert ref.tag == tag
    assert ref.digest is None


def test_parse_digest_only_ref_has_no_default_tag():
    ref = parse_image_ref(f"ghcr.io/open-telemetry/demo@{DIGEST}")
    assert ref.tag is None
    assert ref.digest == DIGEST


def test_parse_tag_and_digest():
    ref = parse_image_ref(f"postgres:18.4@{DIGEST}")
    assert (ref.repository, ref.tag, ref.digest) == ("library/postgres", "18.4", DIGEST)


def test_registry_api_host_for_docker_hub_differs_from_name():
    assert parse_image_ref("postgres:18.4").api_host == "registry-1.docker.io"
    assert parse_image_ref("ghcr.io/a/b:1").api_host == "ghcr.io"


def test_reference_for_api_prefers_digest():
    assert parse_image_ref("ghcr.io/a/b:1").reference == "1"
    assert parse_image_ref(f"ghcr.io/a/b:1@{DIGEST}").reference == DIGEST


def test_pinned_keeps_original_name_and_tag_for_readability():
    ref = parse_image_ref("postgres:18.4")
    assert ref.pinned(DIGEST) == f"postgres:18.4@{DIGEST}"
    ref = parse_image_ref("ghcr.io/open-telemetry/demo:3.1.0-ad")
    assert ref.pinned(DIGEST) == f"ghcr.io/open-telemetry/demo:3.1.0-ad@{DIGEST}"


def test_pinned_rejects_non_sha256_digest():
    with pytest.raises(ValueError):
        parse_image_ref("postgres:18.4").pinned("sha256:short")


def test_str_roundtrip():
    for text in ["postgres:18.4", "ghcr.io/a/b:1", f"quay.io/x/y:2@{DIGEST}"]:
        assert str(parse_image_ref(text)) == text


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "Postgres:18.4",  # repository must be lowercase
        "ghcr.io/a/b:",  # empty tag
        "ghcr.io/a/b@sha256:xyz",  # malformed digest
        "ghcr.io/a/b:bad tag",
    ],
)
def test_parse_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_image_ref(bad)


def test_imageref_is_hashable_value_object():
    a = parse_image_ref("ghcr.io/a/b:1")
    b = parse_image_ref("ghcr.io/a/b:1")
    assert a == b
    assert len({a, b}) == 1
    assert isinstance(a, ImageRef)


@pytest.mark.parametrize("text, repository", [
    ("docker.io/postgres:18.4", "library/postgres"),
    ("index.docker.io/postgres:18.4", "library/postgres"),
    ("index.docker.io/library/postgres:18.4", "library/postgres"),
    ("docker.io/grafana/grafana:13.1.0", "grafana/grafana"),
])
def test_explicit_docker_hub_host_is_normalised(text, repository):
    ref = parse_image_ref(text)
    assert (ref.registry, ref.repository) == ("docker.io", repository)
    assert ref.api_host == "registry-1.docker.io"
    assert str(ref) == text  # written name kept for readability


def test_digest_with_trailing_newline_is_rejected():
    from env.imageref import is_sha256_digest

    assert not is_sha256_digest(DIGEST + "\n")
    with pytest.raises(ValueError):
        parse_image_ref(f"ghcr.io/a/b@{DIGEST}\n")
