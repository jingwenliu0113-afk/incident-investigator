"""Normalize policy v1 (decision 011 §3): fixed before any fault raw is opened."""

import re

import pytest

from collect.policy import POLICY_PATH, POLICY_SHA256, Policy, load_policy
from collect.records import canonical_json_sha256, load_flag_catalog
from env.lock import PROJECT_DIR, sha256_path

UPSTREAM = PROJECT_DIR / "env/upstream/opentelemetry-demo"


@pytest.fixture(scope="module")
def policy() -> Policy:
    return load_policy()


def test_policy_file_is_pinned():
    # any change to a rule changes this digest: update it only together with decision 011 (and v2 rules after freeze)
    assert sha256_path(POLICY_PATH) == POLICY_SHA256


def test_flag_keys_and_flag_file_are_the_pinned_upstream_ones(policy):
    path = UPSTREAM / policy.raw["flag_file"]["path"]
    if not path.exists():
        pytest.skip("upstream checkout not fetched")
    assert sorted(load_flag_catalog(path)) == policy.raw["flag_keys"]
    assert canonical_json_sha256(path) == policy.raw["flag_file"]["canonical_sha256"]


def test_services_are_the_18_sut_services_and_never_overlap_the_excluded(policy):
    assert len(policy.sut_services) == 18
    assert not set(policy.sut_services) & set(policy.raw["excluded_services"])
    assert {"load-generator", "flagd", "frontend-web"} <= set(policy.raw["excluded_services"])


def test_every_fault_artifact_template_matches_its_example_and_cites_real_upstream_code(policy):
    for fa in policy.raw["fault_artifacts"]:
        assert re.fullmatch(fa["pattern"], fa["example"]), fa["id"]
        assert policy.is_fault_artifact(fa["example"]) == fa["id"]
        file, line = fa["source"].rsplit(":", 1)
        path = UPSTREAM / file
        if not path.exists():
            pytest.skip("upstream checkout not fetched")
        text = path.read_text().splitlines()[int(line) - 1]
        assert fa["source_text"] in text and fa["source_text"] in fa["example"], (fa["id"], text)
    assert policy.is_fault_artifact("Payment request failed. Invalid token. demo.user_context.loyalty_level=gold") is None


@pytest.mark.parametrize("text, expected", [
    ("Error: Product Catalog Fail Feature Flag Enabled", "Error: Product Catalog Fail Enabled"),
    ("evaluating paymentFailure now", "evaluating now"),
    ("PAYMENTFAILURE", ""),
    ("calling flagd:8013", "calling:8013"),
    ("openfeature provider ready", "provider ready"),
    ("downloadFailure is not a flag", "downloadFailure is not a flag"),
    ("TCP flags set", "TCP flags set"),
    ("paymentFailures", "paymentFailures"),  # bounded by alphanumerics: not the token
])
def test_lexicon_deletes_tokens_silently(policy, text, expected):
    out, n = policy.scrub(text)
    assert out == expected and (n > 0) == (text != expected)
    assert "[" not in out  # no sentinel that would itself appear only during faults


def test_flag_attribute_keys_and_denied_scopes(policy):
    assert policy.is_flag_key("feature_flag.key") and policy.is_flag_key("demo.feature_flag.recommendation_cache")
    assert policy.is_flag_key("openfeature.provider") and policy.is_flag_key("flagd.reason")
    assert not policy.is_flag_key("demo.recommendation.cache_hit")  # Class B: kept by design
    assert policy.scope_denied("dev.openfeature.contrib.hooks.otel") and not policy.scope_denied("checkout")


def test_control_plane_routes(policy):
    assert policy.control_plane({"rpc.service": "flagd.evaluation.v1.Service"})
    assert policy.control_plane({"server.address": "flagd"}) and policy.control_plane({"upstream_cluster": "flagservice"})
    assert policy.control_plane({"url.path": "/ofrep/v1/evaluate/flags/x"})
    assert policy.control_plane({"url.full": "http://frontend-proxy:8080/feature/api/read"})
    assert not policy.control_plane({"url.path": "/api/cart", "server.address": "cart"})
    assert not policy.control_plane({"url.full": "http://frontend-proxy:8080/api/products/1"})
