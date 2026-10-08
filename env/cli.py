"""`python -m env <command>` — pin, verify and launch the locked OTel Demo.

    fetch-upstream   shallow-clone the upstream tag into env/upstream/ and check its commit
    resolve          render compose from the spec, resolve every image digest, write lock + pinned override
    pin              regenerate env/compose.pinned.yaml from the lock
    verify           check the checkout, file checksums, pinned override and rendered config against the lock
    compose          run `docker compose <args>` for the locked stack with a sanitized env
                     (`up` expands to the locked args and is refused if `verify` would fail)
    compose-cmd      print that command instead of running it
    verify-running   check the running containers: locked image, locked platform manifest, running/healthy
    soak             baseline soak test (decision 004); must run under ./tools/with-mac-lock

Bringing the stack up for a formal incident collection must go through
./tools/with-mac-lock (see MACHINE_POLICY.md); this module never does that itself.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from collect.accounting import account
from env import compose, soak
from env.compose import ComposeError, compose_command, pinned_override_yaml, render_config, service_images
from env.imageref import parse_image_ref
from env.lock import (
    LOCK_PATH,
    PROJECT_DIR,
    GitProbe,
    _git_state,
    build_lock,
    check_lock,
    check_rendered,
    lock_sha256,
    pinned_images,
    upstream_git_problems,
    verify_against_disk,
)
from env.registry import RegistryError, ResolvedImage, UrllibTransport, normalize_platform, resolve
from env.runtime import check_running, services_without_healthcheck

SPEC_PATH = "env/otel-demo.spec.json"
UPSTREAM_DIR = "env/upstream/opentelemetry-demo"

ImageResolver = Callable[[str], ResolvedImage]

_FILE_LIST = {"type": "array", "items": {"type": "array", "prefixItems": [
    {"enum": ["upstream", "project"]}, {"type": "string", "minLength": 1}], "minItems": 2, "maxItems": 2}}
_SPEC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["upstream", "project_name", "compose_files", "env_files", "pinned_override", "up_args",
                 "required_platforms"],
    "properties": {
        "upstream": {"type": "object", "required": ["repo", "tag", "commit", "demo_image_repo"]},
        "project_name": {"type": "string"},
        "compose_files": {**_FILE_LIST, "minItems": 1},
        "env_files": _FILE_LIST,
        "pinned_override": {"type": "string"},
        "up_args": {"type": "array", "items": {"type": "string"}},
        "required_platforms": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}


class CliError(RuntimeError):
    pass


def load_spec(path: Path) -> dict:
    spec = json.loads(Path(path).read_text())
    errors = list(Draft202012Validator(_SPEC_SCHEMA).iter_errors(spec))
    if errors:
        raise CliError("invalid spec: " + "; ".join(e.message for e in errors))
    return spec


def _load_lock(project_dir: Path) -> dict:
    path = project_dir / LOCK_PATH
    if not path.exists():
        raise CliError(f"no lock at {path}; run `python -m env resolve` first")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise CliError(f"lock {path} is not valid JSON ({e}); restore it from git or re-run `python -m env resolve`") from e


def _roots(project_dir: Path, upstream_dir: Path) -> dict[str, Path]:
    return {"upstream": Path(upstream_dir), "project": Path(project_dir)}


def _registry_resolver() -> ImageResolver:
    transport = UrllibTransport()
    return lambda ref: resolve(parse_image_ref(ref), transport)


def cmd_resolve(
    project_dir: Path,
    upstream_dir: Path,
    *,
    resolve_image: ImageResolver | None = None,
    runner: compose.Runner = compose._run,
    git_state: GitProbe = _git_state,
    now: str | None = None,
) -> tuple[dict, list[str]]:
    spec = load_spec(project_dir / SPEC_PATH)
    # Everything on disk gets hashed into the lock, so the checkout must be pristine:
    # a flag left on by a previous run must never become the baseline.
    if problems := upstream_git_problems(git_state(upstream_dir), spec["upstream"]["commit"]):
        raise CliError("refusing to resolve: " + "; ".join(problems))

    roots = _roots(project_dir, upstream_dir)
    rendered = render_config(
        upstream_dir=upstream_dir,
        project_name=spec["project_name"],
        env_files=[roots[r] / p for r, p in spec["env_files"]],
        compose_files=[roots[r] / p for r, p in spec["compose_files"]],
        runner=runner,
    )
    resolve_image = resolve_image or _registry_resolver()
    resolved = {ref: resolve_image(ref) for ref in sorted(set(service_images(rendered).values()))}

    lock = build_lock(
        upstream=spec["upstream"],
        project_name=spec["project_name"],
        compose_files=[tuple(f) for f in spec["compose_files"]],
        env_files=[tuple(f) for f in spec["env_files"]],
        pinned_override=spec["pinned_override"],
        up_args=spec["up_args"],
        rendered=rendered,
        resolved=resolved,
        required_platforms=spec["required_platforms"],
        upstream_dir=upstream_dir,
        project_dir=project_dir,
        generated_at=now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    problems = check_lock(lock)
    if problems:
        return lock, problems
    (project_dir / LOCK_PATH).write_text(json.dumps(lock, indent=2) + "\n")
    cmd_pin(project_dir, lock=lock)
    return lock, []


def cmd_pin(project_dir: Path, *, lock: dict | None = None) -> Path:
    lock = lock or _load_lock(project_dir)
    entry = lock["startup"]["compose_files"][-1]
    path = project_dir / entry["path"]
    path.write_text(pinned_override_yaml(pinned_images(lock), source=LOCK_PATH))
    return path


def cmd_verify(
    project_dir: Path,
    upstream_dir: Path,
    *,
    runner: compose.Runner | None = compose._run,
    git_state: GitProbe = _git_state,
    resolve_image: ImageResolver | None = None,
) -> list[str]:
    lock = _load_lock(project_dir)
    if problems := check_lock(lock):
        return problems  # a malformed lock cannot be rendered or resolved
    problems = verify_against_disk(lock, upstream_dir, project_dir, git_state=git_state)
    if runner is not None:
        try:
            problems += check_rendered(lock, render_config(**_compose_kwargs(lock, project_dir, upstream_dir),
                                                           runner=runner))
        except ComposeError as e:
            problems.append(f"render: {e}")
    if resolve_image is not None:
        for img in lock["images"]:
            pinned = parse_image_ref(img["ref"]).pinned(img["index_digest"])
            try:
                resolve_image(pinned)
            except RegistryError as e:
                problems.append(f"registry: {pinned}: {e}")
    return problems


def _compose_kwargs(lock: dict, project_dir: Path, upstream_dir: Path) -> dict:
    roots = _roots(project_dir, upstream_dir)
    startup = lock["startup"]
    return {
        "upstream_dir": upstream_dir,
        "project_name": startup["project_name"],
        "env_files": [roots[f["root"]] / f["path"] for f in startup["env_files"]],
        "compose_files": [roots[f["root"]] / f["path"] for f in startup["compose_files"]],
    }


def cmd_compose_cmd(project_dir: Path, upstream_dir: Path, args: Sequence[str]) -> list[str]:
    lock = _load_lock(project_dir)
    if list(args) == ["up"]:
        args = lock["startup"]["up_args"]
    return compose_command(**_compose_kwargs(lock, project_dir, upstream_dir), args=args)


# Subcommands that cannot start or resume containers; everything else (up, start, run, scale,
# watch, unpause, ...) is only allowed while the checkout still matches the lock.
_SAFE_WITHOUT_VERIFY = {"config", "cp", "down", "events", "exec", "images", "kill", "logs", "ls", "pause",
                        "port", "ps", "pull", "rm", "stats", "stop", "top", "version", "wait"}


def _exec(cmd: list[str], env: dict[str, str]) -> int:
    return subprocess.run(cmd, env=env).returncode


def cmd_compose_exec(
    project_dir: Path,
    upstream_dir: Path,
    args: Sequence[str],
    *,
    execute: Callable[[list[str], dict[str, str]], int] = _exec,
    base_env: dict[str, str] | None = None,
    git_state: GitProbe = _git_state,
) -> int:
    """Run docker compose for the locked stack with a sanitized environment.

    Anything that may start containers is refused unless the checkout still matches
    the lock (e.g. a flag file left modified by a previous run).
    """
    if not args or args[0] not in _SAFE_WITHOUT_VERIFY:
        problems = verify_against_disk(_load_lock(project_dir), upstream_dir, project_dir, git_state=git_state)
        if problems:
            raise CliError("refusing to start: lock verification failed:\n  " + "\n  ".join(problems))
    cmd = cmd_compose_cmd(project_dir, upstream_dir, args)
    return execute(cmd, compose.sanitized_env(os.environ if base_env is None else base_env))


def _inspect_project(project_dir: Path, upstream_dir: Path) -> Callable[[dict], list[dict]]:
    def inspect(lock: dict) -> list[dict]:
        env = compose.sanitized_env(os.environ)
        ps = cmd_compose_cmd(project_dir, upstream_dir, ["ps", "--all", "--quiet"])
        ids = subprocess.run(ps, env=env, check=True, capture_output=True, text=True).stdout.split()
        if not ids:
            return []
        out = subprocess.run(["docker", "inspect", *ids], env=env, check=True, capture_output=True, text=True).stdout
        return json.loads(out)
    return inspect


def cmd_verify_running(
    project_dir: Path,
    upstream_dir: Path,
    *,
    wait: float = 0,
    expected_platform: str | None = None,
    inspect: Callable[[dict], list[dict]] | None = None,
    check: Callable[..., list[str]] = check_running,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[str], list[str]]:
    """Running containers vs the lock; with `wait`, poll every 5 s until clean or timed out.

    Returns (problems, locked services without a healthcheck, i.e. only checked for 'running').
    """
    lock = _load_lock(project_dir)
    if problems := check_lock(lock):
        return problems, []
    inspect = inspect or _inspect_project(project_dir, upstream_dir)
    deadline = clock() + wait
    while True:
        containers = inspect(lock)
        problems = check(lock, containers, expected_platform=expected_platform)
        if not problems or clock() >= deadline:
            return problems, services_without_healthcheck(lock, containers) if not problems else []
        sleep(5)


MIN_SOAK_MINUTES = 30  # decision 004


def cmd_soak(
    project_dir: Path,
    upstream_dir: Path,
    *,
    minutes: float,
    warmup_minutes: float,
    out_dir: Path,
    drain_minutes: float = 3,
    interval: float = 15,
    lock_dir: Path = soak.HEAVY_LOCK_DIR,
    compose_exec: Callable[..., int] | None = None,
) -> dict:
    """Baseline soak test (decision 004): up -> healthy -> warm-up -> sampled window -> down -> verdict."""
    soak.require_heavy_lock(project_dir, lock_dir=lock_dir)
    compose_exec = compose_exec or cmd_compose_exec
    lock = _load_lock(project_dir)
    env = compose.sanitized_env(os.environ)
    if leftover := soak.project_container_ids(lock, env):
        # `up --force-recreate` would stop them itself (exit-137 deaths look like OOM kills to R2),
        # and the measurement must start from a fresh stack
        raise CliError(f"{len(leftover)} {lock['startup']['project_name']} container(s) already exist "
                       f"({', '.join(sorted(set(leftover.values())))}); run `python -m env compose down --volumes` first")
    out_dir.mkdir(parents=True)
    samples: list[dict] = []
    samples_file = (out_dir / "samples.jsonl").open("a")

    def record(sample: dict) -> None:
        samples.append(sample)
        samples_file.write(json.dumps(sample) + "\n")
        samples_file.flush()

    raw_expected = soak.raw_export_expected(lock)
    watch = soak.EventWatch(out_dir / "docker-events.jsonl", project=lock["startup"]["project_name"], env=env)
    up_at = soak._now()
    report: dict = {"pass": False, "up_at": up_at, "env_lock_sha256": lock_sha256(lock)}
    try:
        if (up_rc := compose_exec(project_dir, upstream_dir, ["up"])) != 0:
            # containers started before the failure keep running (unless-stopped): `finally` still tears down
            report["aborted"] = f"compose up failed (exit {up_rc})"
            return report
        platform = _engine_platform()
        problems, _ = cmd_verify_running(project_dir, upstream_dir, wait=300, expected_platform=platform)
        (out_dir / "initial-verify-running.json").write_text(json.dumps(problems, indent=2) + "\n")
        report.update(platform=platform, initial_verify_running=problems)
        sampler = soak.Sampler(lock, soak.project_container_ids(lock, env), env)

        def take(kinds: tuple[str, ...]) -> None:
            for kind in kinds:
                try:
                    record(getattr(sampler, kind)())
                except (subprocess.CalledProcessError, ValueError, KeyError, StopIteration) as e:
                    record({"kind": "error", "ts": soak._now(), "sampler": kind, "error": str(e)[:300]})

        warm_end = time.monotonic() + warmup_minutes * 60
        while time.monotonic() < warm_end:
            take(("state", "memcg"))
            time.sleep(interval)
        take(("state", "memcg", "locust"))
        window_start = samples[-1]["ts"]
        window_end_at = time.monotonic() + minutes * 60
        i = 1
        while time.monotonic() < window_end_at:
            time.sleep(interval)
            take(("state",) + (("memcg",) if i % 2 == 0 else ()) + (("locust",) if i % 4 == 0 else ()))
            i += 1
        take(("state", "memcg", "locust"))
        window_end = samples[-1]["ts"]
        if raw_expected:
            time.sleep(drain_minutes * 60)  # decision 008 §4: late spans and one more 60 s metric cycle reach /raw
        events = watch.stop()  # before the collector stop: its exit is judged by R7, not as a death in R2

        collector_log = ""
        try:
            logs = cmd_compose_cmd(project_dir, upstream_dir, ["logs", "--no-log-prefix", "--since", up_at])
            collector_log = soak._run(logs + ["otel-collector"], env)
            (out_dir / "otel-collector.log").write_text(collector_log)
            (out_dir / "product-catalog.log").write_text(soak._run(logs + ["product-catalog"], env))
            (out_dir / "docker-inspect.json").write_text(soak._run(["docker", "inspect", *sampler.ids], env))
        except (subprocess.CalledProcessError, OSError) as e:
            report["aborted"] = f"capture failed: {str(e)[:300]}"
        if raw_expected:
            report["raw"] = soak.finalize_raw(lambda args: compose_exec(project_dir, upstream_dir, args), lock, env, out_dir)
        try:
            rendered = render_config(**_compose_kwargs(lock, project_dir, upstream_dir))
            limits = {svc: int(rendered["services"][svc]["deploy"]["resources"]["limits"]["memory"])
                      for svc in soak.WATCHED_SERVICES}
        except (KeyError, ComposeError, subprocess.CalledProcessError) as e:
            limits = {svc: 0 for svc in soak.WATCHED_SERVICES}
            report["aborted"] = report.get("aborted", "") + f" memory limit unknown: {e}"
        report.update(soak.evaluate(samples, window_start=window_start, window_end=window_end,
                                    limits=limits, flow_minutes=soak.debug_exporter_minutes(collector_log),
                                    events=events, raw=report.get("raw")))
        report.update(docker_events=events, opensearch=soak.opensearch_rejections(collector_log),
                      sampling_errors=[s for s in samples if s["kind"] == "error"])
        if raw := report.get("raw"):  # decision 008 §6: reported for the window, not judged
            report["raw_accounting"] = account(raw.get("collector_snapshots") or [], raw.get("sdk_errors") or [],
                                               raw["files"], start_ns=soak.ts_ns(window_start),
                                               end_ns=soak.ts_ns(window_end))
        if report.get("aborted") or report["sampling_errors"]:
            report["pass"] = False
    finally:
        samples_file.close()
        report.setdefault("docker_events", watch.stop())  # before `down`: teardown deaths are not part of the record
        if raw_expected and "raw" not in report:  # a broken run still keeps whatever raw telemetry exists
            try:
                report["raw"] = soak.finalize_raw(lambda args: compose_exec(project_dir, upstream_dir, args), lock, env, out_dir)
            except Exception as e:  # noqa: BLE001 - teardown must still run
                report["raw_error"] = str(e)[:300]
        down_rc = compose_exec(project_dir, upstream_dir, ["down", "--volumes"])
        report["teardown"] = {"down_exit_code": down_rc,
                              "verify": verify_against_disk(lock, upstream_dir, project_dir)}
        soak.write_report(out_dir, report)
    return report


def cmd_fetch_upstream(project_dir: Path, upstream_dir: Path, *, git_state: GitProbe = _git_state) -> str:
    spec = load_spec(project_dir / SPEC_PATH)
    up = spec["upstream"]
    if not upstream_dir.exists():
        upstream_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", up["tag"], up["repo"],
                        str(upstream_dir)], check=True)
    state = git_state(upstream_dir)
    if problems := upstream_git_problems(state, up["commit"]):
        raise CliError(f"{upstream_dir}: " + "; ".join(problems) + f" (tag {up['tag']} moved?)" * (state.head != up["commit"]))
    return state.head


def _engine_platform() -> str:
    out = subprocess.run(["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"],
                         check=True, capture_output=True, text=True).stdout.strip()
    return normalize_platform(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m env", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--upstream-dir", type=Path, default=PROJECT_DIR / UPSTREAM_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch-upstream")
    sub.add_parser("resolve")
    sub.add_parser("pin")
    verify = sub.add_parser("verify")
    verify.add_argument("--online", action="store_true", help="also confirm every digest is still pullable")
    verify.add_argument("--no-render", action="store_true", help="skip the `docker compose config` check")
    vr = sub.add_parser("verify-running")
    vr.add_argument("--wait", type=float, default=0, help="poll up to this many seconds for all containers to be healthy")
    vr.add_argument("--platform", help="expected platform, e.g. linux/arm64 (default: the Docker engine's)")
    sk = sub.add_parser("soak")
    sk.add_argument("--minutes", type=float, default=MIN_SOAK_MINUTES)
    sk.add_argument("--warmup-minutes", type=float, default=5)
    sk.add_argument("--interval", type=float, default=15)
    sk.add_argument("--drain-minutes", type=float, default=3, help="raw export only: keep running after the window")
    sk.add_argument("--out", type=Path)
    for name in ("compose", "compose-cmd"):
        sub.add_parser(name).add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)

    project_dir, upstream_dir = PROJECT_DIR, ns.upstream_dir.resolve()
    try:
        if ns.command == "fetch-upstream":
            print(f"{upstream_dir} @ {cmd_fetch_upstream(project_dir, upstream_dir)}")
        elif ns.command == "resolve":
            lock, problems = cmd_resolve(project_dir, upstream_dir)
            if problems:
                print("lock NOT written:", *problems, sep="\n  ", file=sys.stderr)
                return 1
            print(f"wrote {LOCK_PATH} ({len(lock['images'])} images) and {lock['startup']['compose_files'][-1]['path']}")
        elif ns.command == "pin":
            print(f"wrote {cmd_pin(project_dir)}")
        elif ns.command == "verify":
            problems = cmd_verify(project_dir, upstream_dir, runner=None if ns.no_render else compose._run,
                                  resolve_image=_registry_resolver() if ns.online else None)
            if problems:
                print("lock verification FAILED:", *problems, sep="\n  ", file=sys.stderr)
                return 1
            print("lock verified")
        elif ns.command == "verify-running":
            platform = normalize_platform(ns.platform or _engine_platform())
            problems, unchecked = cmd_verify_running(project_dir, upstream_dir, wait=ns.wait,
                                                     expected_platform=platform)
            if problems:
                print("running stack does NOT match the lock / is not healthy:", *problems, sep="\n  ", file=sys.stderr)
                return 1
            print(f"all locked services run the locked {platform} images, are running, never restarted, "
                  f"and pass their healthchecks; no healthcheck (checked as running only): {', '.join(unchecked) or '-'}")
        elif ns.command == "soak":
            if ns.minutes < MIN_SOAK_MINUTES:
                raise CliError(f"a baseline soak window must be at least {MIN_SOAK_MINUTES} minutes (decision 004)")
            out = ns.out or project_dir / "data/external/soak" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            report = cmd_soak(project_dir, upstream_dir, minutes=ns.minutes, warmup_minutes=ns.warmup_minutes,
                              out_dir=out, interval=ns.interval, drain_minutes=ns.drain_minutes)
            print((out / "report.md").read_text() if (out / "report.md").exists() else json.dumps(report, indent=2))
            return 0 if report.get("pass") and not report["teardown"]["verify"] else 1
        elif ns.command == "compose":
            return cmd_compose_exec(project_dir, upstream_dir, ns.args or ["config"])
        elif ns.command == "compose-cmd":
            print(shlex.join(cmd_compose_cmd(project_dir, upstream_dir, ns.args or ["config"])))
    except subprocess.CalledProcessError as e:
        print(f"error: {e}\n{(e.stderr or e.output or '').strip()}", file=sys.stderr)
        return 2
    except (CliError, ComposeError, RegistryError, soak.LockNotHeld, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
