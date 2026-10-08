"""The OTel Demo environment lock: build it, check it, verify a checkout against it.

The lock (env/otel-demo.lock.json) is the single record of *which* environment
an incident was collected in. Run manifests reference it by sha256.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from env.compose import pinned_override_yaml, service_images
from env.imageref import parse_image_ref
from env.registry import ResolvedImage

LOCK_VERSION = 1
PROJECT_DIR = Path(__file__).resolve().parent.parent
LOCK_PATH = "env/otel-demo.lock.json"
SCHEMA_PATH = PROJECT_DIR / "schemas" / "env_lock.schema.json"
FLOATING_TAGS = ("latest", "main", "master", "nightly", "edge")


@dataclass(frozen=True)
class GitState:
    head: str
    dirty: tuple[str, ...]  # `git status --porcelain` lines: modified, deleted, untracked and ignored files


GitProbe = Callable[[Path], GitState]


# ---------------------------------------------------------------- hashing

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def lock_sha256(lock: dict) -> str:
    """sha256 of the lock as `python -m env resolve` writes it; names the environment in every record."""
    return "sha256:" + hashlib.sha256((json.dumps(lock, indent=2) + "\n").encode()).hexdigest()


def sha256_path(path: Path) -> str:
    """sha256 of a file, or of a directory tree (relative names + file hashes)."""
    path = Path(path)
    if not path.is_dir():
        return _sha256_file(path)
    h = hashlib.sha256()
    files = sorted((p.relative_to(path).as_posix(), p) for p in path.rglob("*") if p.is_file())
    for rel, p in files:
        h.update(f"{rel}\0{_sha256_file(p)}\n".encode())
    return "sha256:" + h.hexdigest()


# ---------------------------------------------------------------- build

def _classify(source: str, roots: Mapping[str, Path]) -> tuple[str, str]:
    resolved = Path(source).resolve()
    for root, base in roots.items():
        try:
            return root, resolved.relative_to(base.resolve()).as_posix()
        except ValueError:
            continue
    return "host", source


def bind_mounts(rendered: dict, upstream_dir: Path, project_dir: Path) -> list[dict]:
    roots = {"upstream": Path(upstream_dir), "project": Path(project_dir)}
    out = []
    for service, svc in (rendered.get("services") or {}).items():
        for vol in svc.get("volumes") or []:
            if vol.get("type") != "bind":
                continue
            root, rel = _classify(vol["source"], roots)
            if root == "host":
                kind, digest = "host", None
            else:
                src = roots[root] / rel
                if not src.exists():
                    raise FileNotFoundError(f"bind source for {service} missing: {src}")
                kind, digest = ("dir" if src.is_dir() else "file"), sha256_path(src)
            out.append({
                "service": service,
                "target": vol["target"],
                "source": {"root": root, "path": rel},
                "kind": kind,
                "sha256": digest,
                "read_only": bool(vol.get("read_only", False)),
            })
    return sorted(out, key=lambda m: (m["service"], m["target"]))


def _file_entries(files: Sequence[tuple[str, str]], roots: Mapping[str, Path]) -> list[dict]:
    return [{"root": root, "path": path, "sha256": sha256_path(roots[root] / path)} for root, path in files]


def build_lock(
    *,
    upstream: Mapping[str, str],
    project_name: str,
    compose_files: Sequence[tuple[str, str]],
    env_files: Sequence[tuple[str, str]],
    pinned_override: str,
    up_args: Sequence[str],
    rendered: dict,
    resolved: Mapping[str, ResolvedImage],
    required_platforms: Sequence[str],
    upstream_dir: Path,
    project_dir: Path,
    generated_at: str,
) -> dict:
    roots = {"upstream": Path(upstream_dir), "project": Path(project_dir)}

    by_ref: dict[str, list[str]] = {}
    for service, ref in service_images(rendered).items():
        by_ref.setdefault(ref, []).append(service)
    images = []
    for ref in sorted(by_ref):
        r = resolved[ref]
        images.append({
            "ref": ref,
            "services": sorted(by_ref[ref]),
            "index_digest": r.index_digest,
            "media_type": r.media_type,
            "platforms": dict(sorted(r.platforms.items())),
        })

    return {
        "lock_version": LOCK_VERSION,
        "generated_at": generated_at,
        "upstream": dict(upstream),
        "startup": {
            "project_name": project_name,
            "compose_files": _file_entries(compose_files, roots)
            + [{"root": "project", "path": pinned_override, "sha256": None, "generated": True}],
            "env_files": _file_entries(env_files, roots),
            "up_args": list(up_args),
        },
        "required_platforms": list(required_platforms),
        "images": images,
        "bind_mounts": bind_mounts(rendered, upstream_dir, project_dir),
    }


def pinned_images(lock: dict) -> dict[str, str]:
    out = {}
    for img in lock["images"]:
        pinned = parse_image_ref(img["ref"]).pinned(img["index_digest"])
        for service in img["services"]:
            out[service] = pinned
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- check (pure)

def _schema_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def check_lock(lock: dict) -> list[str]:
    errors = sorted(_schema_validator().iter_errors(lock), key=lambda e: list(e.absolute_path))
    if errors:
        return [f"schema: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors]

    problems = []
    up = lock["upstream"]
    seen_services: dict[str, str] = {}
    for img in lock["images"]:
        try:
            ref = parse_image_ref(img["ref"])
        except ValueError as e:
            problems.append(f"image {img['ref']!r}: {e}")
            continue
        for platform in lock["required_platforms"]:
            if platform not in img["platforms"]:
                problems.append(f"image {img['ref']} has no {platform} manifest")
        tag = ref.tag or ""
        if f"{ref.registry}/{ref.repository}" == up["demo_image_repo"]:
            if not tag.startswith(f"{up['tag']}-"):
                problems.append(f"demo image {img['ref']} does not match upstream tag {up['tag']}")
        elif tag in FLOATING_TAGS or any(tag.startswith(f"{t}-") for t in FLOATING_TAGS):
            problems.append(f"image {img['ref']} uses a floating tag")
        for service in img["services"]:
            if service in seen_services:
                problems.append(f"service {service} mapped to both {seen_services[service]} and {img['ref']}")
            seen_services[service] = img["ref"]

    compose_files = lock["startup"]["compose_files"]
    generated = [i for i, f in enumerate(compose_files) if f.get("generated")]
    if generated != [len(compose_files) - 1]:
        problems.append("the generated pinned override must be the single, last compose file")
    for f in compose_files + lock["startup"]["env_files"]:
        if bool(f.get("generated")) == (f["sha256"] is not None):
            problems.append(f"{f['path']}: sha256 must be null iff the file is generated")
    for m in lock["bind_mounts"]:
        if m["source"]["root"] != "host" and m["sha256"] is None:
            problems.append(f"bind mount {m['source']['path']} for {m['service']} has no checksum")
    return problems


def check_rendered(lock: dict, rendered: dict) -> list[str]:
    """Does `docker compose config` (with the pinned override) run exactly the locked images?"""
    expected = pinned_images(lock)
    actual = {name: svc.get("image") for name, svc in (rendered.get("services") or {}).items()}
    problems = [f"service {s} is in the lock but not in the rendered config" for s in sorted(expected.keys() - actual.keys())]
    problems += [f"service {s} is rendered but not in the lock" for s in sorted(actual.keys() - expected.keys())]
    for s in sorted(expected.keys() & actual.keys()):
        if actual[s] != expected[s]:
            problems.append(f"service {s} image not pinned to the lock: {actual[s]} (expected {expected[s]})")
    return problems


# ---------------------------------------------------------------- verify (disk)

def _git_state(upstream_dir: Path) -> GitState:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(upstream_dir), *args],
                              check=True, capture_output=True, text=True).stdout

    head = git("rev-parse", "HEAD").strip()
    # --ignored: bind-mount directory hashes include git-ignored files too (e.g. Finder's .DS_Store)
    dirty = tuple(line for line in git("status", "--porcelain", "--untracked-files=all", "--ignored").splitlines()
                  if line)
    return GitState(head=head, dirty=dirty)


def upstream_git_problems(state: GitState, commit: str) -> list[str]:
    problems = []
    if state.head != commit:
        problems.append(f"upstream checkout is at commit {state.head}, lock requires {commit}")
    if state.dirty:
        problems.append("upstream checkout has local changes (restore with `git checkout -- . && git clean -fdx` "
                        "inside it): " + "; ".join(state.dirty))
    return problems


def _check_checksum(label: str, path: Path, expected: str) -> str | None:
    if not path.exists():
        return f"{label}: missing ({path})"
    actual = sha256_path(path)
    if actual != expected:
        return f"{label}: checksum mismatch (lock {expected}, disk {actual})"
    return None


def verify_against_disk(
    lock: dict, upstream_dir: Path, project_dir: Path, *, git_state: GitProbe = _git_state
) -> list[str]:
    problems = check_lock(lock)
    if problems:
        return problems
    roots = {"upstream": Path(upstream_dir), "project": Path(project_dir)}

    try:
        problems += upstream_git_problems(git_state(Path(upstream_dir)), lock["upstream"]["commit"])
    except (OSError, subprocess.CalledProcessError) as e:
        problems.append(f"upstream checkout: cannot read git state ({e})")

    startup = lock["startup"]
    for f in startup["compose_files"] + startup["env_files"]:
        if f.get("generated"):
            continue
        if p := _check_checksum(f"{f['root']}:{f['path']}", roots[f["root"]] / f["path"], f["sha256"]):
            problems.append(p)
    for m in lock["bind_mounts"]:
        src = m["source"]
        if src["root"] == "host":
            continue
        label = f"bind mount {src['root']}:{src['path']} ({m['service']})"
        if p := _check_checksum(label, roots[src["root"]] / src["path"], m["sha256"]):
            problems.append(p)

    pinned_entry = startup["compose_files"][-1]
    pinned_path = roots[pinned_entry["root"]] / pinned_entry["path"]
    expected = pinned_override_yaml(pinned_images(lock), source=LOCK_PATH)
    if not pinned_path.exists() or pinned_path.read_text() != expected:
        problems.append(f"{pinned_entry['path']} is missing or stale; regenerate with `python -m env pin`")
    return problems
