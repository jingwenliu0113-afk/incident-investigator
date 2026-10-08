"""Running containers vs the lock. Container dicts mirror real `docker inspect` output
(Docker 29.8.1, containerd image store) captured during the M1 smoke test."""

import copy

import pytest

from env.lock import pinned_images
from env.runtime import check_running
from lockfixtures import d, make_lock, tree  # noqa: F401

PROJECT = "ii-otel-demo"


def container(lock, service, *, platform=("linux", "arm64"), status="running", health="healthy", restarts=0):
    img = next(i for i in lock["images"] if service in i["services"])
    os_, arch = platform
    key = f"{os_}/{arch}"
    return {
        "Image": img["index_digest"],
        "Config": {"Image": pinned_images(lock)[service], "Labels": {
            "com.docker.compose.project": PROJECT, "com.docker.compose.service": service}},
        "ImageManifestDescriptor": {"mediaType": "application/vnd.oci.image.manifest.v1+json",
                                    "digest": img["platforms"].get(key, d("9")), "size": 1,
                                    "platform": {"architecture": arch, "os": os_}},
        "State": {"Status": status, **({"Health": {"Status": health}} if health else {})},
        "RestartCount": restarts,
        "Name": f"/{service}",
    }


@pytest.fixture
def lock(tree):
    up, proj = tree
    return make_lock(up, proj, project_name=PROJECT)


@pytest.fixture
def healthy(lock):
    return [container(lock, s) for s in pinned_images(lock)]


def test_all_locked_services_running_locked_arm64_images(lock, healthy):
    assert check_running(lock, healthy) == []


def test_missing_service(lock, healthy):
    problems = check_running(lock, [c for c in healthy if c["Config"]["Labels"]["com.docker.compose.service"] != "ad"])
    assert any("ad" in p and "no container" in p for p in problems)


def test_container_running_a_different_image(lock, healthy):
    bad = copy.deepcopy(healthy)
    bad[0]["Config"]["Image"] = "ghcr.io/open-telemetry/demo:latest-ad"
    bad[0]["Image"] = d("7")
    problems = check_running(lock, bad)
    assert any("latest-ad" in p for p in problems)
    assert any("index digest" in p for p in problems)


def test_platform_manifest_must_be_the_locked_one(lock, healthy):
    bad = copy.deepcopy(healthy)
    bad[0]["ImageManifestDescriptor"]["digest"] = d("8")
    assert any("manifest" in p for p in check_running(lock, bad))


def test_amd64_under_emulation_is_reported(lock, healthy):
    # e.g. DOCKER_DEFAULT_PLATFORM=linux/amd64 leaking in: right image, wrong platform
    bad = copy.deepcopy(healthy)
    svc = bad[0]["Config"]["Labels"]["com.docker.compose.service"]
    bad[0] = container(lock, svc, platform=("linux", "amd64"))
    assert any("linux/amd64" in p for p in check_running(lock, bad, expected_platform="linux/arm64"))


def test_missing_manifest_descriptor_cannot_be_confirmed(lock, healthy):
    bad = copy.deepcopy(healthy)
    del bad[0]["ImageManifestDescriptor"]
    assert any("manifest" in p for p in check_running(lock, bad))


@pytest.mark.parametrize("status, health, restarts, word", [
    ("exited", None, 0, "exited"),
    ("running", "unhealthy", 0, "unhealthy"),
    ("running", "starting", 0, "starting"),
    ("running", None, 3, "restarted"),
])
def test_unhealthy_states(lock, healthy, status, health, restarts, word):
    bad = copy.deepcopy(healthy)
    svc = bad[0]["Config"]["Labels"]["com.docker.compose.service"]
    bad[0] = container(lock, svc, status=status, health=health, restarts=restarts)
    assert any(word in p for p in check_running(lock, bad))


def test_running_without_healthcheck_is_fine(lock, healthy):
    ok = copy.deepcopy(healthy)
    ok[0]["State"].pop("Health")
    assert check_running(lock, ok) == []


def test_unlocked_extra_container_in_project(lock, healthy):
    extra = copy.deepcopy(healthy[0])
    extra["Config"]["Labels"]["com.docker.compose.service"] = "intruder"
    assert any("intruder" in p for p in check_running(lock, healthy + [extra]))


def test_containers_of_other_projects_are_ignored(lock, healthy):
    other = copy.deepcopy(healthy[0])
    other["Config"]["Labels"]["com.docker.compose.project"] = "someone-else"
    other["Config"]["Labels"]["com.docker.compose.service"] = "pgvector"
    assert check_running(lock, healthy + [other]) == []


# ---------------------------------------------------------------- review round 3

def test_failing_probes_masked_by_retries_are_reported():
    # Real `docker inspect` of product-catalog at the end of the 2026-10-08 smoke test: Docker still
    # says "healthy" because Retries=20, but the last 10 probes in a row failed.
    import json
    from pathlib import Path

    from env.lock import LOCK_PATH, PROJECT_DIR

    lock = json.loads((PROJECT_DIR / LOCK_PATH).read_text())
    pc = json.loads((Path(__file__).parent / "fixtures" / "inspect-product-catalog-failing-streak.json").read_text())
    pc["RestartCount"] = 0  # isolate the health signal
    problems = [p for p in check_running(lock, [pc]) if p.startswith("product-catalog")]
    assert any("failing" in p and "10" in p for p in problems), problems


def test_last_probe_failure_is_reported_even_without_streak(lock, healthy):
    bad = copy.deepcopy(healthy)
    bad[0]["State"]["Health"] = {"Status": "healthy", "FailingStreak": 0,
                                 "Log": [{"ExitCode": 0}, {"ExitCode": -1, "Output": "timeout"}]}
    assert any("failing" in p for p in check_running(lock, bad))


@pytest.mark.parametrize("spelling", ["linux/arm64", "linux/arm64/v8", "linux/aarch64"])
def test_expected_platform_spellings_are_normalised(lock, healthy, spelling):
    assert check_running(lock, healthy, expected_platform=spelling) == []


def test_normalize_platform():
    from env.registry import normalize_platform

    assert normalize_platform("linux/aarch64") == "linux/arm64"
    assert normalize_platform("linux/arm64/v8") == "linux/arm64"
    assert normalize_platform("linux/x86_64") == "linux/amd64"
    assert normalize_platform("linux/arm/v7") == "linux/arm/v7"


def test_services_without_healthcheck_are_listed(lock, healthy):
    from env.runtime import services_without_healthcheck

    some = copy.deepcopy(healthy)
    some[0]["State"].pop("Health")
    svc = some[0]["Config"]["Labels"]["com.docker.compose.service"]
    assert services_without_healthcheck(lock, some) == [svc]
