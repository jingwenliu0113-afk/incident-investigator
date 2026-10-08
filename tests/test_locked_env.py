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


# ---------------------------------------------------------------- decision 004: product-catalog memory override

OVERRIDES = "env/compose.overrides.yaml"


def test_project_compose_override_is_locked_before_the_pinned_override(lock):
    files = [(f["root"], f["path"]) for f in lock["startup"]["compose_files"]]
    assert ("project", OVERRIDES) in files
    assert files.index(("project", OVERRIDES)) == len(files) - 2  # pinned override stays last
    entry = next(f for f in lock["startup"]["compose_files"] if f["path"] == OVERRIDES)
    assert entry["sha256"] and not entry.get("generated")


def _render(lock, drop=()):
    """`docker compose config` of the locked stack, optionally without some project compose files."""
    import shutil

    from env.cli import UPSTREAM_DIR
    from env.compose import render_config

    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    upstream = PROJECT_DIR / UPSTREAM_DIR
    if not upstream.exists():
        pytest.skip("upstream checkout not fetched")
    roots = {"upstream": upstream, "project": PROJECT_DIR}
    startup = lock["startup"]
    return render_config(
        upstream_dir=upstream,
        project_name=startup["project_name"],
        env_files=[roots[f["root"]] / f["path"] for f in startup["env_files"]],
        compose_files=[roots[f["root"]] / f["path"] for f in startup["compose_files"] if f["path"] not in drop],
    )


@pytest.mark.docker_cli
@pytest.mark.parametrize("service, mib", [("product-catalog", 128), ("checkout", 64)])  # decisions 004 / 007
def test_memory_limits_from_the_project_overlay_and_unchanged_gomemlimit(lock, service, mib):
    svc = _render(lock)["services"][service]
    assert int(svc["deploy"]["resources"]["limits"]["memory"]) == mib * 1024 * 1024
    assert svc["environment"]["GOMEMLIMIT"] == "16MiB"


@pytest.mark.docker_cli
def test_project_override_changes_nothing_but_memory_limits_and_the_raw_extras_mount(lock):
    from env.soak import RAW_CONFIG, RAW_EXTRAS_TARGET, RAW_SERVICE, WATCHED_SERVICES

    def leaves(node, path=()):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from leaves(v, path + (k,))
        elif isinstance(node, list):
            yield path, json.dumps(node, sort_keys=True)
        else:
            yield path, node

    rendered = _render(lock)
    with_override = dict(leaves(rendered))
    without = dict(leaves(_render(lock, drop=(OVERRIDES,))))
    changed = {p for p in with_override.keys() | without.keys() if with_override.get(p) != without.get(p)}
    # every limit the overlay changes is judged by the soak test's R6 (decision 004 revision), plus the collector's
    # extras layer (decision 008); nothing else changes
    assert changed == {("services", svc, "deploy", "resources", "limits", "memory") for svc in WATCHED_SERVICES} | {
        ("services", RAW_SERVICE, "volumes")}
    assert set(WATCHED_SERVICES) == {"product-catalog", "checkout"}
    vols = {v["target"]: v for v in rendered["services"][RAW_SERVICE]["volumes"]}
    before = {v["target"]: v for v in json.loads(without[("services", RAW_SERVICE, "volumes")])}
    assert vols[RAW_EXTRAS_TARGET]["source"] == str(PROJECT_DIR / RAW_CONFIG)  # replaces the upstream extras stub
    assert {t: v for t, v in vols.items() if t != RAW_EXTRAS_TARGET} == {
        t: v for t, v in before.items() if t != RAW_EXTRAS_TARGET}  # the other collector mounts stay as upstream


def test_locked_stack_exports_raw_telemetry(lock):
    from env.soak import raw_export_expected

    assert raw_export_expected(lock)  # decision 008: the lock records env/otelcol-config-raw.yml with its sha256


def test_lock_sha256_is_the_sha256_of_the_committed_lock_file(lock):
    from env.lock import LOCK_PATH, lock_sha256, sha256_path

    # manifests, raw exports and soak reports name the environment by this digest (decision 001)
    assert lock_sha256(lock) == sha256_path(PROJECT_DIR / LOCK_PATH)
