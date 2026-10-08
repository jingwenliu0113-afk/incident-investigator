import subprocess
import json

import pytest

from env.cli import CliError, cmd_compose_cmd, cmd_pin, cmd_resolve, cmd_verify, load_spec
from env.lock import check_rendered, pinned_images
from env.registry import ResolvedImage
from lockfixtures import COMMIT, DEMO, OCI_INDEX, d, git_at, make_lock, rendered_for, tree  # noqa: F401

SPEC = {
    "upstream": {"repo": "https://github.com/open-telemetry/opentelemetry-demo", "tag": "3.1.0",
                 "commit": COMMIT, "demo_image_repo": DEMO},
    "project_name": "ii-otel-demo",
    "compose_files": [["upstream", "compose.yaml"]],
    "env_files": [["upstream", ".env"], ["project", "env/otel-demo.overrides.env"]],
    "pinned_override": "env/compose.pinned.yaml",
    "up_args": ["up", "--detach", "--no-build"],
    "required_platforms": ["linux/arm64", "linux/amd64"],
}


def fake_resolver(platforms=("linux/amd64", "linux/arm64")):
    def resolve(ref):
        return ResolvedImage(ref=ref, index_digest=d(str(len(ref) % 10)), media_type=OCI_INDEX,
                             platforms={p: d("c") for p in platforms})
    return resolve


def fake_compose(up, pins=None):
    """Mimics `docker compose config`: applies the pinned override when it is passed."""
    def runner(cmd, env):
        rendered = rendered_for(up)
        if any(arg.endswith("compose.pinned.yaml") for arg in cmd) and pins:
            for svc, ref in pins.items():
                rendered["services"][svc]["image"] = ref
        return json.dumps(rendered)
    return runner


@pytest.fixture
def project(tree):
    up, proj = tree
    (proj / "env" / "otel-demo.spec.json").write_text(json.dumps(SPEC))
    return up, proj


def test_load_spec_rejects_missing_fields(tmp_path):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps({k: v for k, v in SPEC.items() if k != "upstream"}))
    with pytest.raises(CliError, match="upstream"):
        load_spec(p)


def test_resolve_writes_lock_and_pinned_override(project):
    up, proj = project
    lock, problems = cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up),
                                 git_state=git_at(COMMIT), now="2026-10-08T00:00:00Z")
    assert problems == []
    on_disk = json.loads((proj / "env" / "otel-demo.lock.json").read_text())
    assert on_disk == lock
    assert on_disk["upstream"]["commit"] == COMMIT
    pinned = (proj / "env" / "compose.pinned.yaml").read_text()
    for svc, ref in pinned_images(lock).items():
        assert f'    image: "{ref}"' in pinned


def test_resolve_refuses_wrong_upstream_checkout(project):
    up, proj = project
    with pytest.raises(CliError, match="commit"):
        cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up),
                    git_state=git_at("f" * 40), now="2026-10-08T00:00:00Z")
    assert not (proj / "env" / "otel-demo.lock.json").exists()


def test_resolve_refuses_dirty_upstream_checkout(project):
    # A fault flag left in src/flagd by a previous run must never become the locked baseline.
    up, proj = project
    with pytest.raises(CliError, match="local changes"):
        cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up),
                    git_state=git_at(COMMIT, dirty=[" M src/flagd/demo.flagd.json"]), now="2026-10-08T00:00:00Z")
    assert not (proj / "env" / "otel-demo.lock.json").exists()


def test_resolve_does_not_write_a_lock_that_fails_checks(project):
    up, proj = project
    lock, problems = cmd_resolve(proj, up, resolve_image=fake_resolver(platforms=("linux/amd64",)),
                                 runner=fake_compose(up), git_state=git_at(COMMIT), now="2026-10-08T00:00:00Z")
    assert any("linux/arm64" in p for p in problems)
    assert not (proj / "env" / "otel-demo.lock.json").exists()


def test_resolve_renders_without_the_old_pinned_override(project):
    up, proj = project
    seen = []

    def runner(cmd, env):
        seen.append(cmd)
        return json.dumps(rendered_for(up))

    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=runner, git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    assert not any(arg.endswith("compose.pinned.yaml") for arg in seen[0])


def test_pin_regenerates_override_from_lock(project):
    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    pinned = proj / "env" / "compose.pinned.yaml"
    original = pinned.read_text()
    pinned.write_text("tampered\n")
    cmd_pin(proj)
    assert pinned.read_text() == original


def test_verify_clean_including_render(project):
    up, proj = project
    lock, _ = cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up),
                          git_state=git_at(COMMIT), now="2026-10-08T00:00:00Z")
    problems = cmd_verify(proj, up, runner=fake_compose(up, pinned_images(lock)), git_state=git_at(COMMIT))
    assert problems == []


def test_verify_detects_compose_not_applying_pins(project):
    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    problems = cmd_verify(proj, up, runner=fake_compose(up, pins=None), git_state=git_at(COMMIT))
    assert any("not pinned" in p for p in problems)


def test_verify_reports_schema_problems_instead_of_crashing(project):
    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    lock_path = proj / "env" / "otel-demo.lock.json"
    lock = json.loads(lock_path.read_text())
    del lock["startup"]
    lock_path.write_text(json.dumps(lock))
    problems = cmd_verify(proj, up, runner=fake_compose(up), git_state=git_at(COMMIT),
                          resolve_image=fake_resolver())
    assert problems and all(p.startswith("schema:") for p in problems)


def test_corrupt_lock_file_is_a_cli_error(project):
    up, proj = project
    (proj / "env" / "otel-demo.lock.json").write_text('{"lock_version": 1, "upstr')
    with pytest.raises(CliError, match="lock"):
        cmd_verify(proj, up, runner=None, git_state=git_at(COMMIT))


def test_verify_without_lock_is_an_error(project):
    up, proj = project
    with pytest.raises(CliError, match="lock"):
        cmd_verify(proj, up, runner=fake_compose(up), git_state=git_at(COMMIT))


def test_compose_cmd_is_built_from_lock_with_absolute_paths(project):
    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    cmd = cmd_compose_cmd(proj, up, ["ps"])
    assert cmd[:2] == ["docker", "compose"]
    assert cmd[cmd.index("--project-name") + 1] == "ii-otel-demo"
    files = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-f"]
    assert files == [str(up / "compose.yaml"), str(proj / "env" / "compose.pinned.yaml")]
    env_files = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--env-file"]
    assert env_files == [str(up / ".env"), str(proj / "env" / "otel-demo.overrides.env")]
    assert cmd[-1] == "ps"


def test_compose_exec_runs_locked_command_with_sanitized_env(project):
    from env.cli import cmd_compose_exec

    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    seen = {}

    def execute(cmd, env):
        seen["cmd"], seen["env"] = cmd, env
        return 3

    rc = cmd_compose_exec(proj, up, ["ps"], execute=execute,
                          base_env={"PATH": "/bin", "DEMO_VERSION": "latest", "COMPOSE_FILE": "x.yaml"})
    assert rc == 3
    assert seen["cmd"] == cmd_compose_cmd(proj, up, ["ps"])
    assert seen["env"] == {"PATH": "/bin"}


def test_compose_exec_refuses_when_lock_verification_fails(project):
    from env.cli import cmd_compose_exec

    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    (up / "src" / "flagd" / "demo.flagd.json").write_text('{"flags": {"x": "left on"}}')
    with pytest.raises(CliError, match="src/flagd"):
        cmd_compose_exec(proj, up, ["up"], execute=lambda cmd, env: 0, base_env={},
                         git_state=git_at(COMMIT))


@pytest.mark.parametrize("args, verified", [
    (["up"], True), (["start"], True), (["scale", "flagd=1"], True), (["watch"], True), (["unpause"], True),
    (["ps"], False), (["logs", "flagd"], False), (["down", "--volumes"], False), (["config"], False),
    (["exec", "flagd", "ls"], False), (["stop"], False),
])
def test_compose_exec_verifies_everything_except_known_safe_subcommands(project, args, verified):
    from env.cli import cmd_compose_exec

    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    (up / "src" / "flagd" / "demo.flagd.json").write_text('{"flags": {"x": "left on"}}')
    run = lambda: cmd_compose_exec(proj, up, args, execute=lambda cmd, env: 0, base_env={},  # noqa: E731
                                   git_state=git_at(COMMIT))
    if verified:
        with pytest.raises(CliError, match="refusing"):
            run()
    else:
        assert run() == 0


def test_compose_cmd_up_uses_locked_up_args(project):
    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    assert cmd_compose_cmd(proj, up, ["up"])[-3:] == ["up", "--detach", "--no-build"]


# ---------------------------------------------------------------- check_rendered (pure)

def test_check_rendered(tree):
    up, proj = tree
    lock = make_lock(up, proj)
    pins = pinned_images(lock)
    good = {"services": {s: {"image": r} for s, r in pins.items()}}
    assert check_rendered(lock, good) == []

    unpinned = {"services": {**good["services"], "ad": {"image": f"{DEMO}:3.1.0-ad"}}}
    assert any("ad" in p and "not pinned" in p for p in check_rendered(lock, unpinned))

    extra = {"services": {**good["services"], "intruder": {"image": "x:1"}}}
    assert any("intruder" in p for p in check_rendered(lock, extra))

    missing = {"services": {s: v for s, v in good["services"].items() if s != "flagd"}}
    assert any("flagd" in p for p in check_rendered(lock, missing))


# ---------------------------------------------------------------- verify-running

def test_verify_running_polls_until_healthy_or_timeout(project):
    from env.cli import cmd_verify_running

    up, proj = project
    cmd_resolve(proj, up, resolve_image=fake_resolver(), runner=fake_compose(up), git_state=git_at(COMMIT),
                now="2026-10-08T00:00:00Z")
    calls, slept = [], []

    def inspect(lock):
        calls.append(1)
        return ["starting"] if len(calls) < 3 else []

    problems, _ = cmd_verify_running(proj, up, wait=60, inspect=inspect, check=lambda lock, cs, **kw: cs,
                                     sleep=slept.append, clock=lambda: len(slept) * 5.0)
    assert problems == [] and len(calls) == 3

    calls.clear(), slept.clear()
    problems, _ = cmd_verify_running(proj, up, wait=10, inspect=lambda lock: ["still starting"],
                                     check=lambda lock, cs, **kw: cs, sleep=slept.append,
                                     clock=lambda: len(slept) * 5.0)
    assert problems == ["still starting"]


@pytest.mark.parametrize("exc, needle", [
    (subprocess.CalledProcessError(1, ["docker", "inspect"], output="", stderr="Cannot connect to the Docker daemon"),
     "Cannot connect to the Docker daemon"),
    (FileNotFoundError(2, "No such file or directory", "docker"), "docker"),
])
def test_main_reports_docker_failures_with_exit_code_2(monkeypatch, capsys, exc, needle):
    import env.cli as cli

    def boom(*a, **kw):
        raise exc

    monkeypatch.setattr(cli, "cmd_verify_running", boom)
    monkeypatch.setattr(cli, "_engine_platform", lambda: "linux/arm64")
    assert cli.main(["verify-running"]) == 2
    assert needle in capsys.readouterr().err
