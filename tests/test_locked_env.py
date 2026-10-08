"""Guards on the committed lock itself (env/otel-demo.lock.json), not on the tooling."""

import json

import pytest

from env.lock import LOCK_PATH, PROJECT_DIR, check_lock


@pytest.fixture(scope="module")
def lock():
    path = PROJECT_DIR / LOCK_PATH
    if not path.exists():
        pytest.skip("no lock yet (python -m env resolve)")
    return json.loads(path.read_text())


def test_committed_lock_passes_checks(lock):
    assert check_lock(lock) == []


def test_every_run_group_starts_from_clean_containers_and_volumes(lock):
    # Prometheus declares VOLUME /prometheus; `up --force-recreate` alone reuses that anonymous
    # volume, so metrics from earlier runs would leak into the next snapshot (decision 001).
    args = lock["startup"]["up_args"]
    for flag in ("--force-recreate", "--renew-anon-volumes", "--no-build", "--remove-orphans"):
        assert flag in args, flag


def test_lock_pins_release_commit_and_both_platforms(lock):
    assert lock["upstream"]["commit"] == "dedc0178918e260823323b8d95005a8cb924b007"
    assert set(lock["required_platforms"]) == {"linux/arm64", "linux/amd64"}
    assert len(lock["images"]) == 28
