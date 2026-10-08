"""Baseline soak test evaluation — pass criteria R1–R6 are fixed in docs/decisions/004."""

import os

import pytest

from env.soak import (
    EventWatch,
    LockNotHeld,
    count_5xx,
    debug_exporter_minutes,
    evaluate,
    is_ambient,
    parse_docker_events,
    parse_memcg_dump,
    require_heavy_lock,
)

MiB = 1024 * 1024
LIMIT = 64 * MiB
W0, W1 = "2026-10-08T10:05:00Z", "2026-10-08T10:08:00Z"  # 3-minute window keeps fixtures small


def state(ts, *, restarts=0, health="healthy", streak=0, extra=None):
    containers = {
        "product-catalog": {"restarts": restarts, "status": "running", "health": health, "streak": streak},
        "cart": {"restarts": 0, "status": "running", "health": None, "streak": None},  # no healthcheck
    }
    containers.update(extra or {})
    return {"kind": "state", "ts": ts, "containers": containers}


def memcg(ts, *, current=30 * MiB, oom_kill=0, max_events=0, extra=None):
    return {"kind": "memcg", "ts": ts, "cgroups": {
        "product-catalog": {"current": current, "max": LIMIT, "oom_kill": oom_kill, "max_events": max_events},
        "cart": {"current": 50 * MiB, "max": 160 * MiB, "oom_kill": 0, "max_events": 0},
        **(extra or {}),
    }}


def locust(ts, *, requests, errors):
    return {"kind": "locust", "ts": ts, "requests": requests, "failures": sum(errors.values()), "errors": errors}


ASK = "/prompt | gaierror(-2, 'Name or service not known')"
E504 = "/api/products/X | HTTPError('504 Server Error: Gateway Timeout for url: /api/products/X')"


def healthy_run():
    return [
        state("2026-10-08T10:00:30Z"), memcg("2026-10-08T10:00:30Z"),
        locust("2026-10-08T10:00:30Z", requests=10, errors={E504: 3}),  # warm-up 5xx: recorded, not judged
        state("2026-10-08T10:05:00Z"), memcg("2026-10-08T10:05:00Z"),
        locust("2026-10-08T10:05:00Z", requests=300, errors={E504: 3, ASK: 20}),
        state("2026-10-08T10:06:30Z"), memcg("2026-10-08T10:06:30Z", current=40 * MiB),
        state("2026-10-08T10:08:00Z"), memcg("2026-10-08T10:08:00Z"),
        locust("2026-10-08T10:08:00Z", requests=480, errors={E504: 3, ASK: 36}),
    ]


FLOW = {s: {"10:05", "10:06", "10:07"} for s in ("traces", "metrics", "logs")}


def run(samples, flow=FLOW, events=(), limits=None):
    return evaluate(samples, window_start=W0, window_end=W1, limits=limits or {"product-catalog": LIMIT},
                    flow_minutes=flow, events=None if events is None else list(events))


def test_stable_baseline_passes_all_criteria():
    report = run(healthy_run())
    assert report["pass"] is True
    assert {k: v["pass"] for k, v in report["criteria"].items()} == {f"R{i}": True for i in range(1, 7)}
    assert report["ambient"]["ask_agent"] == 16
    assert report["warmup"]["http_5xx"] == 3


def test_r1_any_restart_since_up_fails_even_during_warmup():
    samples = healthy_run()
    samples[0] = state("2026-10-08T10:00:30Z", restarts=1)
    samples[3] = state("2026-10-08T10:05:00Z", restarts=1)
    samples[6] = state("2026-10-08T10:06:30Z", restarts=1)
    samples[8] = state("2026-10-08T10:08:00Z", restarts=1)
    report = run(samples)
    assert report["criteria"]["R1"]["pass"] is False and report["pass"] is False
    assert "product-catalog" in report["criteria"]["R1"]["detail"]


def test_r2_oom_kill_fails():
    samples = healthy_run()
    samples[9] = memcg("2026-10-08T10:08:00Z", oom_kill=1)
    assert run(samples)["criteria"]["R2"]["pass"] is False


def test_r3_5xx_inside_window_fails_but_warmup_5xx_does_not():
    samples = healthy_run()
    samples[10] = locust("2026-10-08T10:08:00Z", requests=480, errors={E504: 5, ASK: 36})
    report = run(samples)
    assert report["criteria"]["R3"]["pass"] is False
    assert report["criteria"]["R3"]["value"] == 2


def test_r4_failing_streak_masked_as_healthy_fails():
    samples = healthy_run()
    samples[6] = state("2026-10-08T10:06:30Z", streak=3)
    assert run(samples)["criteria"]["R4"]["pass"] is False


def test_r4_unhealthy_fails_and_containers_without_healthcheck_are_ignored():
    samples = healthy_run()
    samples[6] = state("2026-10-08T10:06:30Z", health="unhealthy")
    assert run(samples)["criteria"]["R4"]["pass"] is False
    assert run(healthy_run())["criteria"]["R4"]["pass"] is True  # cart has no healthcheck


def test_r5_missing_signal_minute_fails():
    flow = {**FLOW, "logs": {"10:05", "10:07"}}
    report = run(healthy_run(), flow=flow)
    assert report["criteria"]["R5"]["pass"] is False
    assert "logs" in report["criteria"]["R5"]["detail"] and "10:06" in report["criteria"]["R5"]["detail"]


@pytest.mark.parametrize("current, max_events, ok", [
    (40 * MiB, 0, True),
    (int(0.85 * LIMIT), 0, False),  # p95 >= 80 % of the limit: sits near the ceiling
    (40 * MiB, 12, False),  # hit memory.max inside the window
])
def test_r6_memory_headroom(current, max_events, ok):
    samples = healthy_run()
    samples[4] = memcg("2026-10-08T10:05:00Z", current=current)
    samples[7] = memcg("2026-10-08T10:06:30Z", current=current, max_events=max_events)
    samples[9] = memcg("2026-10-08T10:08:00Z", current=current, max_events=max_events)
    assert run(samples)["criteria"]["R6"]["pass"] is ok


def test_r2_oom_event_fails_even_when_the_memcg_counter_was_reset():
    # 2026-10-08 soak #1: checkout was OOM-killed at 10:01:05Z; the restart recreated its cgroup,
    # so every later memcg sample showed oom_kill=0. Docker's oom event is what survives.
    events = [{"ts": "2026-10-08T10:01:05Z", "service": "checkout", "action": "oom", "exit_code": None},
              {"ts": "2026-10-08T10:01:05Z", "service": "checkout", "action": "die", "exit_code": 137}]
    report = run(healthy_run(), events=events)
    assert report["criteria"]["R2"]["pass"] is False and report["pass"] is False
    assert "checkout" in report["criteria"]["R2"]["detail"]


def test_r2_needs_the_event_stream_and_ignores_clean_exits():
    clean = [{"ts": "2026-10-08T10:01:05Z", "service": "cart", "action": "die", "exit_code": 0}]
    assert run(healthy_run(), events=clean)["criteria"]["R2"]["pass"] is True
    sigkill = [{"ts": "2026-10-08T10:01:05Z", "service": "cart", "action": "die", "exit_code": 137}]
    assert run(healthy_run(), events=sigkill)["criteria"]["R2"]["pass"] is False  # OOM killer suspected
    missing = run(healthy_run(), events=None)["criteria"]["R2"]
    assert missing["pass"] is False and "event" in missing["detail"]


def test_r6_judges_every_service_whose_limit_the_overlay_changed():
    co = 64 * MiB
    samples = healthy_run()
    for i, ts in ((4, "2026-10-08T10:05:00Z"), (7, "2026-10-08T10:06:30Z"), (9, "2026-10-08T10:08:00Z")):
        samples[i] = memcg(ts, extra={"checkout": {"current": int(0.9 * co), "max": co, "oom_kill": 0, "max_events": 0}})
    report = run(samples, limits={"product-catalog": LIMIT, "checkout": co})
    assert report["criteria"]["R6"]["pass"] is False
    assert "checkout" in report["criteria"]["R6"]["detail"] and "product-catalog" in report["criteria"]["R6"]["detail"]
    # a watched service without samples cannot pass
    assert run(healthy_run(), limits={"product-catalog": LIMIT, "checkout": co})["criteria"]["R6"]["pass"] is False
    assert run(healthy_run(), limits={"product-catalog": LIMIT})["criteria"]["R6"]["pass"] is True


def test_window_without_samples_cannot_pass():
    samples = [s for s in healthy_run() if s["ts"] < W0]
    report = run(samples)
    assert report["pass"] is False


# ---------------------------------------------------------------- parsing helpers

def test_count_5xx_and_ambient_classification():
    errors = {E504: 2, ASK: 5, "/ | ConnectionRefusedError(111, 'Connection refused')": 1,
              "/api/cart | HTTPError('500 Server Error: Internal Server Error for url: /api/cart')": 1,
              "/api/x | HTTPError('404 Client Error: Not Found')": 1}
    assert count_5xx(errors) == 3
    assert is_ambient(ASK) and not is_ambient(E504)
    assert is_ambient("/prompt | NameResolutionError(...)")


def test_parse_memcg_dump():
    ids = {"aaa": "product-catalog", "bbb": "cart"}
    text = ("aaa current=31457280 max=67108864 oom_kill=0 max_events=4\n"
            "bbb current=1048576 max=max oom_kill=0 max_events=0\n"
            "ccc current=1 max=1 oom_kill=0 max_events=0\n")  # not ours: ignored
    parsed = parse_memcg_dump(text, ids)
    assert parsed["product-catalog"] == {"current": 31457280, "max": 67108864, "oom_kill": 0, "max_events": 4}
    assert parsed["cart"]["max"] is None
    assert set(parsed) == {"product-catalog", "cart"}


def test_parse_docker_events():
    lines = [
        # `docker events --format '{{json .}}'` as emitted by Docker 29 (fields trimmed)
        '{"status":"oom","id":"812f","Type":"container","Action":"oom","Actor":{"ID":"812f","Attributes":'
        '{"com.docker.compose.project":"ii-otel-demo","com.docker.compose.service":"checkout","name":"checkout"}},'
        '"scope":"local","time":1791453665,"timeNano":1791453665918945430}',
        '{"status":"die","id":"812f","Type":"container","Action":"die","Actor":{"ID":"812f","Attributes":'
        '{"com.docker.compose.project":"ii-otel-demo","com.docker.compose.service":"checkout","exitCode":"137"}},'
        '"time":1791453665,"timeNano":1791453665927352888}',
        '{"Type":"container","Action":"die","Actor":{"ID":"aa","Attributes":{"name":"musing_cray","exitCode":"0"}},'
        '"time":1791453700,"timeNano":1791453700000000000}',  # sampler helper container: not a compose service
        "not json",
    ]
    assert parse_docker_events("\n".join(lines), project="ii-otel-demo") == [
        {"ts": "2026-10-08T10:01:05Z", "service": "checkout", "action": "oom", "exit_code": None},
        {"ts": "2026-10-08T10:01:05Z", "service": "checkout", "action": "die", "exit_code": 137},
    ]


def test_event_watch_runs_docker_events_for_the_project_and_parses_what_it_wrote(tmp_path):
    started = {}

    class FakeProc:
        exited_early = False

        def __init__(self, cmd, stdout, stderr, env):
            started.update(cmd=cmd, env=env)
            stdout.write('{"Type":"container","Action":"oom","Actor":{"Attributes":{"com.docker.compose.project":'
                         '"p","com.docker.compose.service":"cart"}},"timeNano":1791453665000000000}\n')

        def poll(self):
            return 1 if self.exited_early else None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    watch = EventWatch(tmp_path / "docker-events.jsonl", project="p", env={"PATH": "/bin"}, popen=FakeProc)
    cmd = started["cmd"]
    assert cmd[:2] == ["docker", "events"] and "label=com.docker.compose.project=p" in cmd
    assert "event=oom" in cmd and "event=die" in cmd
    events = watch.stop()
    assert events == [{"ts": "2026-10-08T10:01:05Z", "service": "cart", "action": "oom", "exit_code": None}]
    assert watch.stop() == events  # idempotent: safe to call again from a finally block

    FakeProc.exited_early = True  # e.g. the daemon went away: the stream has a hole, R2 cannot be judged
    assert EventWatch(tmp_path / "e2.jsonl", project="p", env={}, popen=FakeProc).stop() is None


def test_debug_exporter_minutes():
    log = "\n".join([
        '2026-10-08T10:05:01.1Z\tinfo\tTraces\t{"otelcol.component.id": "debug", "spans": 7}',
        '2026-10-08T10:05:40.0Z\tinfo\tMetrics\t{"otelcol.component.id": "debug", "data points": 9}',
        '2026-10-08T10:06:02.0Z\tinfo\tLogs\t{"otelcol.component.id": "debug", "log records": 2}',
        '2026-10-08T10:06:03.0Z\terror\tinternal/queue_sender.go:62\tExporting failed.\t{"otelcol.component.id": "opensearch"}',
        '2026-10-08T10:06:04.0Z\tinfo\tTraces\t{"otelcol.component.id": "debug", "spans": 0}',  # empty batch: no flow
    ])
    assert debug_exporter_minutes(log) == {"traces": {"10:05"}, "metrics": {"10:05"}, "logs": {"10:06"}}


# ---------------------------------------------------------------- heavy lock guard

def test_require_heavy_lock(tmp_path):
    lock_dir = tmp_path / "lock"
    with pytest.raises(LockNotHeld):
        require_heavy_lock(tmp_path, lock_dir=lock_dir)
    lock_dir.mkdir()
    (lock_dir / "owner.txt").write_text(f"pid={os.getpid()}\nstarted_at=x\ncwd={tmp_path}\ncommand=soak\n")
    require_heavy_lock(tmp_path, lock_dir=lock_dir)  # held by a live process for this project
    (lock_dir / "owner.txt").write_text(f"pid={os.getpid()}\nstarted_at=x\ncwd=/elsewhere\ncommand=bench\n")
    with pytest.raises(LockNotHeld, match="elsewhere"):
        require_heavy_lock(tmp_path, lock_dir=lock_dir)


def test_soak_command_refuses_to_start_without_the_heavy_lock(tmp_path):
    from env.cli import cmd_soak

    started = []
    with pytest.raises(LockNotHeld):
        cmd_soak(tmp_path, tmp_path, minutes=30, warmup_minutes=5, out_dir=tmp_path / "out",
                 lock_dir=tmp_path / "no-lock", compose_exec=lambda *a, **kw: started.append(a) or 0)
    assert started == []  # nothing was brought up
    assert not (tmp_path / "out").exists()


def test_soak_cli_rejects_windows_shorter_than_30_minutes(capsys):
    from env.cli import main

    assert main(["soak", "--minutes", "10"]) == 2
    assert "30" in capsys.readouterr().err


@pytest.fixture
def soak_env(monkeypatch):
    """cmd_soak with Docker, the lock check and the clock replaced; `calls` records the order of side effects."""
    import json

    import env.cli as cli
    import env.soak as soak_mod
    from env.lock import LOCK_PATH, PROJECT_DIR

    real_lock = json.loads((PROJECT_DIR / LOCK_PATH).read_text())
    monkeypatch.setattr(soak_mod, "require_heavy_lock", lambda *a, **kw: {})
    monkeypatch.setattr(cli, "_load_lock", lambda project_dir: real_lock)
    monkeypatch.setattr(cli, "_engine_platform", lambda: "linux/arm64")
    monkeypatch.setattr(cli, "cmd_verify_running", lambda *a, **kw: ([], []))
    monkeypatch.setattr(cli, "verify_against_disk", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "render_config", lambda **kw: {"services": {svc: {"deploy": {"resources": {"limits": {
        "memory": LIMIT}}}} for svc in soak_mod.WATCHED_SERVICES}})
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    calls = []
    existing = {}  # project containers present before `up`

    def container_ids(lock, env):
        return dict(existing) if ["up"] not in calls else {"id1": "product-catalog", "id2": "load-generator"}

    monkeypatch.setattr(soak_mod, "project_container_ids", container_ids)

    class FakeWatch:
        events: list | None = []

        def __init__(self, path, *, project, env):
            calls.append(f"watch {project}")

        def stop(self):
            calls.append("watch stopped")
            return FakeWatch.events

    monkeypatch.setattr(soak_mod, "EventWatch", FakeWatch)

    class Env:
        pass

    e = Env()
    e.cli, e.soak, e.calls, e.watch, e.existing = cli, soak_mod, calls, FakeWatch, existing
    e.compose_exec = lambda p, u, args: calls.append(args) or 0
    return e


def test_soak_still_reports_and_tears_down_when_docker_disappears_mid_run(tmp_path, monkeypatch, soak_env):
    # 2026-10-08 dry run: another workload ran `docker desktop stop` mid-run; capture failed,
    # nothing about the initial health check survived. Partial evidence must always be written.
    import json
    import subprocess

    cli, soak_mod, calls = soak_env.cli, soak_env.soak, soak_env.calls
    monkeypatch.setattr(cli, "cmd_verify_running", lambda *a, **kw: (["product-catalog: health starting"], []))

    class DeadSampler:
        def __init__(self, *a, **kw):
            self.ids = {"id1": "product-catalog"}

        def _fail(self):
            raise subprocess.CalledProcessError(1, ["docker"], stderr="failed to connect to the docker API")

        state = memcg = locust = _fail

    monkeypatch.setattr(soak_mod, "Sampler", DeadSampler)
    monkeypatch.setattr(soak_mod, "_run", lambda *a, **kw: DeadSampler()._fail())
    soak_env.watch.events = None  # the event stream broke along with the daemon
    out = tmp_path / "out"
    report = cli.cmd_soak(tmp_path, tmp_path, minutes=0, warmup_minutes=0, out_dir=out, compose_exec=soak_env.compose_exec)
    # oom/die events are watched from before `up` (an early OOM kill must not be missed) until before `down`
    assert calls[:2] == ["watch ii-otel-demo", ["up"]] and calls[-1] == ["down", "--volumes"]
    assert "watch stopped" in calls[2:-1]
    assert report["pass"] is False
    assert json.loads((out / "initial-verify-running.json").read_text()) == ["product-catalog: health starting"]
    assert (out / "report.md").exists() and "FAILED" in (out / "report.md").read_text()
    assert "capture" in report.get("aborted", "") or report.get("sampling_errors")


def test_soak_judges_r2_on_the_watched_docker_events(tmp_path, monkeypatch, soak_env):
    # soak #1: the restart reset checkout's cgroup (oom_kill=0 in every later sample); only Docker's oom event survives.
    cli, soak_mod = soak_env.cli, soak_env.soak

    class GoodSampler:
        def __init__(self, *a, **kw):
            self.ids = {"id1": "product-catalog", "id2": "load-generator"}

        def state(self):
            return state(soak_mod._now())

        def memcg(self):
            return memcg(soak_mod._now())

        def locust(self):
            return locust(soak_mod._now(), requests=10, errors={})

    monkeypatch.setattr(soak_mod, "Sampler", GoodSampler)
    monkeypatch.setattr(soak_mod, "_run", lambda *a, **kw: "")
    oom = {"ts": "2026-10-08T10:01:05Z", "service": "checkout", "action": "oom", "exit_code": None}
    soak_env.watch.events = [oom]
    report = cli.cmd_soak(tmp_path, tmp_path, minutes=0, warmup_minutes=0, out_dir=tmp_path / "out",
                          compose_exec=soak_env.compose_exec)
    assert report["criteria"]["R2"]["pass"] is False and "checkout" in report["criteria"]["R2"]["detail"]
    assert report["docker_events"] == [oom]


def test_failed_up_still_stops_the_watch_tears_down_and_reports(tmp_path, soak_env):
    # containers started before the failure keep running (unless-stopped): `down` and a report are still needed
    out = tmp_path / "out"
    report = soak_env.cli.cmd_soak(tmp_path, tmp_path, minutes=0, warmup_minutes=0, out_dir=out,
                                   compose_exec=lambda p, u, args: soak_env.calls.append(args) or (1 if args == ["up"] else 0))
    assert soak_env.calls == ["watch ii-otel-demo", ["up"], "watch stopped", ["down", "--volumes"]]
    assert report["pass"] is False and "compose up failed" in report["aborted"]
    assert "FAILED" in (out / "report.md").read_text()


def test_soak_refuses_to_start_over_existing_project_containers(tmp_path, soak_env):
    # `up --force-recreate` would SIGKILL / stop them itself: their exit-137 deaths would look like OOM kills (R2),
    # and the measurement would not start from a fresh stack
    from env.cli import CliError

    soak_env.existing.update({"old1": "checkout"})
    with pytest.raises(CliError, match="down --volumes"):
        soak_env.cli.cmd_soak(tmp_path, tmp_path, minutes=0, warmup_minutes=0, out_dir=tmp_path / "out",
                              compose_exec=soak_env.compose_exec)
    assert soak_env.calls == []
    assert not (tmp_path / "out").exists()
