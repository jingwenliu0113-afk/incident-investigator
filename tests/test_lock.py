import copy
import json

import pytest

from env.lock import (
    LOCK_VERSION,
    bind_mounts,
    check_lock,
    pinned_images,
    sha256_path,
    verify_against_disk,
)
from env.registry import ResolvedImage
from lockfixtures import COMMIT, DEMO, OCI_INDEX, d, git_at, make_lock, rendered_for, resolved_all, sha, tree, write_pinned  # noqa: F401


# ---------------------------------------------------------------- hashing

def test_sha256_path_file(tmp_path):
    f = tmp_path / "x"
    f.write_bytes(b"hello")
    assert sha256_path(f) == sha(b"hello")


def test_sha256_path_dir_depends_on_names_and_contents(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "one.json").write_text("1")
    (a / "sub").mkdir()
    (a / "sub" / "two.json").write_text("2")
    h1 = sha256_path(a)
    (a / "sub" / "two.json").write_text("2!")
    h2 = sha256_path(a)
    (a / "sub" / "two.json").write_text("2")
    (a / "sub" / "two.json").rename(a / "sub" / "three.json")
    h3 = sha256_path(a)
    assert len({h1, h2, h3}) == 3
    (a / "sub" / "three.json").rename(a / "sub" / "two.json")
    assert sha256_path(a) == h1


# ---------------------------------------------------------------- bind mounts

def test_bind_mounts_hash_upstream_sources_and_mark_host_binds(tree):
    up, proj = tree
    mounts = bind_mounts(rendered_for(up), up, proj)
    by_target = {(m["service"], m["target"]): m for m in mounts}
    flagd = by_target[("flagd", "/etc/flagd")]
    assert flagd["source"] == {"root": "upstream", "path": "src/flagd"}
    assert flagd["kind"] == "dir"
    assert flagd["sha256"] == sha256_path(up / "src" / "flagd")
    host = by_target[("otel-collector", "/hostfs")]
    assert host["source"] == {"root": "host", "path": "/"}
    assert host["sha256"] is None
    # named volumes are not bind mounts
    assert ("otel-collector", "/data") not in by_target
    # deterministic order
    assert mounts == sorted(mounts, key=lambda m: (m["service"], m["target"]))


# ---------------------------------------------------------------- build + check

def test_build_lock_produces_valid_lock(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    assert lock["lock_version"] == LOCK_VERSION
    assert check_lock(lock) == []
    assert lock["upstream"]["commit"] == COMMIT
    files = lock["startup"]["compose_files"]
    assert files[0] == {"root": "upstream", "path": "compose.yaml", "sha256": sha256_path(up / "compose.yaml")}
    assert files[-1] == {"root": "project", "path": "env/compose.pinned.yaml", "sha256": None, "generated": True}
    assert lock["startup"]["env_files"][1]["sha256"] == sha256_path(proj / "env" / "otel-demo.overrides.env")


def test_build_lock_groups_services_by_image_and_records_platform_digests(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    refs = [img["ref"] for img in lock["images"]]
    assert refs == sorted(refs)
    ad = next(i for i in lock["images"] if i["ref"] == f"{DEMO}:3.1.0-ad")
    assert ad["services"] == ["ad"]
    assert ad["index_digest"] == d("1")
    assert ad["platforms"] == {"linux/amd64": d("a"), "linux/arm64": d("b")}


def test_pinned_images_maps_services_to_digest_refs(tree):
    up, proj = tree
    pins = pinned_images(make_lock(up, proj))
    assert pins["ad"] == f"{DEMO}:3.1.0-ad@{d('1')}"
    assert set(pins) == {"ad", "flagd", "flagd-ui", "otel-collector"}


def test_build_lock_fails_when_an_image_was_not_resolved(tree):
    up, proj = tree
    resolved = resolved_all()
    del resolved[f"{DEMO}:3.1.0-ad"]
    with pytest.raises(KeyError):
        make_lock(up, proj, resolved=resolved)


def test_check_lock_flags_missing_required_platform(tree):
    up, proj = tree
    resolved = resolved_all()
    ref = f"{DEMO}:3.1.0-ad"
    resolved[ref] = ResolvedImage(ref=ref, index_digest=d("1"), media_type=OCI_INDEX,
                                  platforms={"linux/amd64": d("a")})
    problems = check_lock(make_lock(up, proj, resolved=resolved))
    assert any("linux/arm64" in p and ref in p for p in problems)


def test_check_lock_flags_demo_images_not_matching_upstream_tag(tree):
    # The 3.1.0 checkout defaults to DEMO_VERSION=latest -> ':latest-ad'; that must never be locked.
    up, proj = tree
    rendered = rendered_for(up)
    rendered["services"]["ad"]["image"] = f"{DEMO}:latest-ad"
    resolved = resolved_all()
    resolved[f"{DEMO}:latest-ad"] = resolved.pop(f"{DEMO}:3.1.0-ad")
    problems = check_lock(make_lock(up, proj, rendered=rendered, resolved=resolved))
    assert any("latest-ad" in p for p in problems)


def test_check_lock_flags_floating_latest_tags_on_third_party_images(tree):
    up, proj = tree
    rendered = rendered_for(up)
    rendered["services"]["flagd"]["image"] = "ghcr.io/open-feature/flagd:latest"
    resolved = resolved_all()
    resolved["ghcr.io/open-feature/flagd:latest"] = resolved.pop("ghcr.io/open-feature/flagd:v0.16.0")
    problems = check_lock(make_lock(up, proj, rendered=rendered, resolved=resolved))
    assert any("floating tag" in p for p in problems)


def test_check_lock_rejects_schema_violations(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    broken = copy.deepcopy(lock)
    broken["upstream"]["commit"] = "not-a-sha"
    assert check_lock(broken)
    broken = copy.deepcopy(lock)
    broken["images"][0]["index_digest"] = "sha256:short"
    assert check_lock(broken)
    broken = copy.deepcopy(lock)
    del broken["startup"]
    assert check_lock(broken)


def test_check_lock_requires_pinned_override_last(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    files = lock["startup"]["compose_files"]
    files.insert(0, files.pop())
    assert any("pinned override" in p for p in check_lock(lock))


def test_lock_is_json_serialisable_and_stable(tree):
    up, proj = tree
    a = json.dumps(make_lock(up, proj), sort_keys=True)
    b = json.dumps(make_lock(up, proj), sort_keys=True)
    assert a == b


# ---------------------------------------------------------------- verify on disk

def test_verify_against_disk_clean(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    write_pinned(lock, proj)
    assert verify_against_disk(lock, up, proj, git_state=git_at(COMMIT)) == []


def test_verify_detects_wrong_upstream_commit(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    write_pinned(lock, proj)
    problems = verify_against_disk(lock, up, proj, git_state=git_at("0" * 40))
    assert any("commit" in p for p in problems)


def test_verify_detects_flag_file_left_modified_by_a_previous_run(tree):
    # flagd-ui mounts src/flagd read-write; a toggled flag must not leak into the next run.
    up, proj = tree
    lock = make_lock(up, proj)
    write_pinned(lock, proj)
    (up / "src" / "flagd" / "demo.flagd.json").write_text('{"flags": {"adFailure": "on"}}\n')
    problems = verify_against_disk(lock, up, proj, git_state=git_at(COMMIT))
    assert any("src/flagd" in p for p in problems)


def test_verify_detects_edited_override_env(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    write_pinned(lock, proj)
    (proj / "env" / "otel-demo.overrides.env").write_text("DEMO_VERSION=latest\n")
    problems = verify_against_disk(lock, up, proj, git_state=git_at(COMMIT))
    assert any("otel-demo.overrides.env" in p for p in problems)


def test_verify_detects_stale_or_missing_pinned_override(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    problems = verify_against_disk(lock, up, proj, git_state=git_at(COMMIT))
    assert any("compose.pinned.yaml" in p for p in problems)
    (proj / "env" / "compose.pinned.yaml").write_text("services: {}\n")
    problems = verify_against_disk(lock, up, proj, git_state=git_at(COMMIT))
    assert any("compose.pinned.yaml" in p for p in problems)


def test_verify_reports_missing_upstream_file(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    write_pinned(lock, proj)
    (up / "compose.yaml").unlink()
    problems = verify_against_disk(lock, up, proj, git_state=git_at(COMMIT))
    assert any("compose.yaml" in p and "missing" in p for p in problems)


def test_verify_reports_local_changes_in_upstream_checkout(tree):
    # e.g. flagd-ui left demo.flagd.json.tmp behind, or someone edited a file that is not a bind mount
    up, proj = tree
    lock = make_lock(up, proj)
    write_pinned(lock, proj)
    problems = verify_against_disk(lock, up, proj, git_state=git_at(COMMIT, dirty=["?? src/flagd/demo.flagd.json.tmp"]))
    assert any("local changes" in p and "demo.flagd.json.tmp" in p for p in problems)


def test_real_git_probe_sees_modified_and_untracked_files(tmp_path):
    import subprocess

    from env.lock import _git_state

    repo = tmp_path / "repo"
    (repo / "src" / "flagd").mkdir(parents=True)
    (repo / "src" / "flagd" / "demo.flagd.json").write_text('{"flags": {}}\n')

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    clean = _git_state(repo)
    assert len(clean.head) == 40 and clean.dirty == ()

    (repo / "src" / "flagd" / "demo.flagd.json").write_text('{"flags": {"paymentFailure": "on"}}\n')
    (repo / "src" / "flagd" / "demo.flagd.json.tmp").write_text("x")
    dirty = _git_state(repo)
    assert any("src/flagd/demo.flagd.json" in line and not line.endswith(".tmp") for line in dirty.dirty)
    assert any(line.endswith("demo.flagd.json.tmp") for line in dirty.dirty)


def test_real_git_probe_sees_ignored_files_that_change_bind_mount_hashes(tmp_path):
    # upstream .gitignore ignores .DS_Store (Finder creates it) and `*~`, but the bind-mount
    # directory hash includes every file, so ignored files must count as local changes too.
    import subprocess

    from env.lock import _git_state

    repo = tmp_path / "repo"
    (repo / "src" / "flagd").mkdir(parents=True)
    (repo / "src" / "flagd" / "demo.flagd.json").write_text('{"flags": {}}\n')
    (repo / ".gitignore").write_text(".DS_Store\n*~\n")

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    (repo / "src" / "flagd" / ".DS_Store").write_bytes(b"\0")
    (repo / "src" / "flagd" / "demo.flagd.json~").write_text("backup")
    dirty = _git_state(repo).dirty
    assert any(line.endswith("src/flagd/.DS_Store") for line in dirty)
    assert any(line.endswith("src/flagd/demo.flagd.json~") for line in dirty)


def test_restore_hint_also_removes_ignored_files():
    from env.lock import GitState, upstream_git_problems

    problems = upstream_git_problems(GitState(head=COMMIT, dirty=("!! src/flagd/.DS_Store",)), COMMIT)
    assert any("git clean -fdx" in p for p in problems)


def test_check_lock_reports_unparseable_image_ref_instead_of_raising(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    lock["images"][0]["ref"] = "Postgres:18.4"
    assert any("Postgres:18.4" in p for p in check_lock(lock))
