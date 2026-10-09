"""Run group orchestration (decision 009): gate → normal → fault on → fault off → recovery → drain → raw → down."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from collect.accounting import counter_key
from collect.policy import load_policy
from collect.provenance import power_problems
from collect.rungroup import Plan, normal_minutes, recovery_minutes, run_group

T0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
SUT = load_policy().raw["sut_services"]
E504 = "/api/x | HTTPError('504 Server Error: Gateway Timeout for url: /api/x')"
FLAGS = {"flags": {"paymentFailure": {"state": "ENABLED", "defaultVariant": "off",
                                      "variants": {"off": 0, "50%": 0.5, "100%": 1}}}}


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def time(self):
        return T0.timestamp() + self.t

    def now(self):
        return (T0 + timedelta(seconds=self.t)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Watch:
    def __init__(self, stack):
        self.stack = stack

    def seen(self):
        return list(self.stack.events)

    def stop(self):
        self.stack.calls.append("watch stopped")
        return list(self.stack.events)


class Stack:
    """Fake locked stack. `restart_at` / `fivexx_until` / `confirm` script its behaviour in clock minutes."""

    def __init__(self, clock, flag_path, *, restart_at=None, fivexx_until=0.0, confirm=True, power_at=None):
        self.clock, self.flag_path = clock, flag_path
        self.power_at = power_at or {}  # minute -> power facts from then on (decision 025 revision 2)
        self.restart_at, self.fivexx_until, self.confirm = restart_at, fivexx_until, confirm
        self.calls, self.events, self.n5xx, self.flag_writes = [], [], 0, []
        self.unseen = set()  # containers docker_stats never reported (decision 012)
        self.dropped = 0  # spans the memory_limiter dropped (decision 008 §6)

    def minute(self):
        return self.clock.t / 60

    def preflight(self):
        return []

    def provenance(self):
        return {"project": {"commit": "a" * 40, "dirty": False}, "env_lock": {"sha256": "sha256:" + "1" * 64}}

    def compose(self, args):
        self.calls.append(args)
        return 0

    def watch(self, path):
        self.calls.append("watch")
        return Watch(self)

    def verify_running(self, wait):
        self.calls.append("verify_running")
        return []

    def rescan_containers(self):
        self.calls.append("rescan")
        return {"updated": 28, "failed": []}

    def save_logs(self, services, out_dir):
        self.calls.append(("save_logs", tuple(services)))
        out_dir.mkdir(parents=True, exist_ok=True)
        for svc in services:
            (out_dir / f"{svc}.log").write_text("level=error msg=boom\n")
        return sorted(services)

    def sample(self, kind):
        ts = self.clock.now()
        if kind == "state":
            restarts = 1 if self.restart_at is not None and self.minute() >= self.restart_at else 0
            return {"kind": "state", "ts": ts, "containers": {
                "checkout": {"restarts": restarts, "status": "running", "health": "healthy", "streak": 0}}}
        if kind == "locust":
            if self.minute() < self.fivexx_until:
                self.n5xx += 1
            return {"kind": "locust", "ts": ts, "requests": 100, "failures": self.n5xx, "errors": {E504: self.n5xx}}
        if kind == "power":
            power = {"source": "AC Power", "settings": {"powermode": "2"}}
            for minute in sorted(self.power_at):
                if self.minute() >= minute:
                    power = self.power_at[minute]
            return {"kind": "power", "ts": ts, "power": power}
        return {"kind": "memcg", "ts": ts, "cgroups": {}}

    def ofrep(self, flag, context):
        self.calls.append(("ofrep", flag))
        doc = json.loads(self.flag_path.read_text())
        variant = doc["flags"][flag]["defaultVariant"] if self.confirm else "off"
        return variant, None

    def vm_time(self):
        return self.clock.time() + 0.25  # the Docker VM clock runs 250 ms ahead

    def finalize_raw(self, out_dir):
        self.calls.append("finalize_raw")
        return {"collector": {"container_id": "c", "restarts": 0, "stop_exit_code": 0, "stop_seconds": 1.0,
                              "cp_seconds": 1.0, "copied": True},
                "files": {sig: {"signal": sig, "bytes": 10, "parse_errors": 0, "wrong_signal_lines": 0}
                          for sig in ("traces", "metrics", "logs")},
                "container_minutes": {c: [(T0 + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M")
                                          for m in range(int(self.minute()) + 1)]
                                      for c in SUT if c not in self.unseen},
                # the collector's own counters: one export at up, one after the drain (decision 008 §6)
                "collector_snapshots": [
                    {"t": int(T0.timestamp()) * 10**9, "start": 1, "values": {}},
                    {"t": int(self.clock.time()) * 10**9, "start": 1, "values": {
                        counter_key("otelcol_processor_incoming_items",
                                    {"otel.signal": "traces", "processor": "memory_limiter"}): 10 + self.dropped,
                        counter_key("otelcol_processor_outgoing_items",
                                    {"otel.signal": "traces", "processor": "memory_limiter"}): 10}}],
                "sdk_errors": {"exports": {}, "errors": []}}


@pytest.fixture
def flag_path(tmp_path):
    p = tmp_path / "demo.flagd.json"
    p.write_bytes(json.dumps(FLAGS, indent=2).encode() + b"\n")
    return p


def plan(**over):
    kw = dict(run_group_id="RG-001", seed=7, flag="paymentFailure", variant="100%", fault_minutes=10)
    kw.update(over)
    return Plan(**kw)


def go(stack, clock, flag_path, tmp_path, **over):
    return run_group(plan(**over), stack, clock, flag_path=flag_path, work_dir=tmp_path / "work")


def test_normal_and_recovery_lengths_are_seeded_and_jittered():
    # decision 009 (amended): with a fixed recovery, fault_off would sit exactly 5 min before the window end
    assert normal_minutes(plan(seed=7)) == normal_minutes(plan(seed=7))
    assert normal_minutes(plan(seed=7)) != normal_minutes(plan(seed=8))
    assert all(10 <= normal_minutes(plan(seed=s)) <= 15 for s in range(50))
    assert recovery_minutes(plan(seed=7)) == recovery_minutes(plan(seed=7))
    assert all(5 <= recovery_minutes(plan(seed=s)) <= 10 for s in range(50))
    assert len({round(recovery_minutes(plan(seed=s)), 3) for s in range(50)}) > 40
    # the two draws are not the same number
    assert any(normal_minutes(plan(seed=s)) - 10 != recovery_minutes(plan(seed=s)) - 5 for s in range(5))


def test_clock_drift_over_one_second_invalidates_the_run(tmp_path, flag_path):
    clock = Clock()
    stack = Stack(clock, flag_path)
    drift = iter([0.25, 1.6])  # VM clock moved 1.35 s relative to the host during the run
    stack.vm_time = lambda: clock.time() + next(drift)
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and "clock_drift" in rec["reasons"]


def test_valid_run_follows_the_protocol_and_restores_the_flag_file(tmp_path, flag_path):
    clock = Clock()
    original = flag_path.read_bytes()
    stack = Stack(clock, flag_path, fivexx_until=3)  # cold-start 5xx in the first 3 minutes only
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "valid" and rec["reasons"] == []
    s = rec["schedule"]
    assert s["normal_start"] < s["fault_on"] < s["fault_off"] < s["end"]
    on, off = (datetime.fromisoformat(s[k]) for k in ("fault_on", "fault_off"))
    assert off - on == timedelta(minutes=10)
    end = datetime.fromisoformat(s["end"])
    assert abs((end - off).total_seconds() - recovery_minutes(plan()) * 60) <= 1  # timestamps are whole seconds
    assert rec["gate"]["pass"] is True
    assert rec["flag"]["on"]["confirmed"] and rec["flag"]["off"]["confirmed"]
    assert rec["flag"]["baseline_sha256"] != rec["flag"]["injected_sha256"]
    assert flag_path.read_bytes() == original  # restored byte-for-byte
    assert [c for c in stack.calls if c in (["up"], ["down", "--volumes"])] == [["up"], ["down", "--volumes"]]
    assert stack.calls.index("watch stopped") < stack.calls.index("finalize_raw") < stack.calls.index(["down", "--volumes"])
    assert rec["normal_period"]["clean"] is True
    assert abs(rec["clock_offset_seconds"][0] - 0.25) < 1e-6
    assert rec["incident_window"] == {"start": s["normal_start"], "end": s["end"]}
    assert rec["provenance"]["project"]["commit"] == "a" * 40  # recorded before `up` for the incident manifest
    # decision 012: every container is announced to docker_stats once the stack is up, before the warm-up
    assert stack.calls.index("verify_running") < stack.calls.index("rescan") < stack.calls.index(("ofrep", "paymentFailure"))
    assert rec["container_rescan"] == {"updated": 28, "failed": []} and rec["container_metric_gaps"] == {}
    assert rec["raw_accounting"]["flags"] == [] and rec["raw_accounting"]["snapshots"]["final"] is not None


def test_loss_on_the_raw_path_during_the_window_invalidates_the_run(tmp_path, flag_path):
    clock = Clock()
    stack = Stack(clock, flag_path)
    stack.dropped = 3
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and rec["reasons"] == ["raw_incomplete"]
    assert rec["raw_accounting"]["flags"] == ["memory_limiter_refused"]


def test_a_container_without_docker_stats_in_the_window_invalidates_the_run(tmp_path, flag_path):
    clock = Clock()
    stack = Stack(clock, flag_path)
    stack.unseen = {"shipping"}  # 2026-10-08 soak #3: started inside the receiver's list -> event-loop gap
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and "container_metrics_missing" in rec["reasons"]
    assert list(rec["container_metric_gaps"]) == ["shipping"]


def test_unstable_stack_is_aborted_before_any_fault(tmp_path, flag_path):
    clock = Clock()
    original = flag_path.read_bytes()
    stack = Stack(clock, flag_path, fivexx_until=60)  # 5xx never stop
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "aborted_unstable" and rec["gate"]["pass"] is False
    assert "schedule" not in rec and not any(isinstance(c, tuple) for c in stack.calls)  # flagd never touched
    assert flag_path.read_bytes() == original
    assert stack.calls[-1] == ["down", "--volumes"]
    assert clock.t <= (5 + 10 + 1) * 60  # warm-up + at most 10 extra minutes


def test_restart_in_the_normal_period_invalidates_the_run(tmp_path, flag_path):
    clock = Clock()
    stack = Stack(clock, flag_path, restart_at=8)  # after the gate (5 min), before fault_on (>= 15 min)
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and "normal_period_not_clean" in rec["reasons"]


def test_restart_during_the_fault_is_recorded_but_keeps_the_run_valid(tmp_path, flag_path):
    clock = Clock()
    stack = Stack(clock, flag_path, restart_at=22)  # inside the fault (fault_on >= 15 min, lasts 10 min)
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "valid"
    assert rec["fault_and_recovery"]["new_restarts"] == {"checkout": 1}


def test_a_power_mode_change_during_the_window_invalidates_the_run(tmp_path, flag_path):
    # decision 025 revisions 2, 3: the whole incident window is collected on AC power in the high power mode
    clock = Clock()
    stack = Stack(clock, flag_path, power_at={22: {"source": "AC Power", "settings": {"powermode": "0"}}})
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and rec["reasons"] == ["power_not_formal"]
    assert rec["power_not_formal"][0]["power"]["settings"] == {"powermode": "0"}
    clock = Clock()
    stack = Stack(clock, flag_path, power_at={22: None})  # pmset unreadable: never assumed formal
    assert "power_not_formal" in go(stack, clock, flag_path, tmp_path / "b")["reasons"]
    clock = Clock()  # before the window (warm-up): not judged; the preflight checks the start
    stack = Stack(clock, flag_path, power_at={1: {"source": "Battery Power", "settings": {"powermode": "2"}},
                                              4: {"source": "AC Power", "settings": {"powermode": "2"}}})
    rec = go(stack, clock, flag_path, tmp_path / "c")
    assert rec["status"] == "valid" and rec["power_samples"] >= 25  # about one a minute over 25-35 minutes


def test_unconfirmed_flag_change_invalidates_and_skips_the_fault(tmp_path, flag_path):
    clock = Clock()
    original = flag_path.read_bytes()
    stack = Stack(clock, flag_path, confirm=False)
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and "flag_unconfirmed" in rec["reasons"]
    assert flag_path.read_bytes() == original
    assert "finalize_raw" in stack.calls and stack.calls[-1] == ["down", "--volumes"]


def test_a_crash_still_restores_the_flag_copies_raw_and_tears_down(tmp_path, flag_path, monkeypatch):
    clock = Clock()
    original = flag_path.read_bytes()
    stack = Stack(clock, flag_path)
    real_sample = stack.sample

    def exploding(kind):
        if clock.t > 20 * 60:
            raise RuntimeError("daemon went away")
        return real_sample(kind)

    stack.sample = exploding
    with pytest.raises(RuntimeError) as info:
        go(stack, clock, flag_path, tmp_path)
    assert flag_path.read_bytes() == original
    assert "finalize_raw" in stack.calls and stack.calls[-1] == ["down", "--volumes"]
    # decision 009 §4: every run that started leaves a record, a crashed one too
    rec = info.value.run_record
    assert rec["status"] == "aborted_error" and "daemon went away" in rec["reasons"][0]
    assert rec["raw"] is not None and rec["down_exit_code"] == 0 and "events" in rec


def test_a_second_interrupt_cannot_skip_down_and_signals_are_masked_during_teardown(tmp_path, flag_path):
    import signal

    clock = Clock()
    stack = Stack(clock, flag_path)
    seen = {}
    real_compose = stack.compose

    def finalize(out_dir):
        stack.calls.append("finalize_raw")
        raise KeyboardInterrupt  # Ctrl-C while `compose stop -t 120` runs, and again in the teardown's retry

    def compose(args):
        if args == ["down", "--volumes"]:
            seen["sigint"] = signal.getsignal(signal.SIGINT)
        return real_compose(args)

    stack.finalize_raw, stack.compose = finalize, compose
    before = signal.getsignal(signal.SIGINT)
    with pytest.raises(KeyboardInterrupt) as info:
        go(stack, clock, flag_path, tmp_path)
    assert stack.calls[-1] == ["down", "--volumes"] and seen["sigint"] == signal.SIG_IGN
    assert signal.getsignal(signal.SIGINT) == before
    assert info.value.run_record["status"] == "aborted_error"


@pytest.mark.parametrize("error", [OSError("docker events did not start"), KeyboardInterrupt("signal 15")], ids=str)
def test_a_run_that_fails_before_compose_up_still_records_when_it_started(tmp_path, flag_path, error):
    # decision 009 §4: the stored record of every started run has its start time (held-out: after the freeze, 026 #24)
    clock = Clock()
    stack = Stack(clock, flag_path)

    def watch(path):
        raise error

    stack.watch = watch
    with pytest.raises(type(error)) as info:
        go(stack, clock, flag_path, tmp_path)
    rec = info.value.run_record
    assert rec["status"] == "aborted_error" and rec["up_at"] == clock.now()
    assert ["up"] not in stack.calls and ["down", "--volumes"] not in stack.calls  # nothing was started


def test_preflight_problems_refuse_to_start(tmp_path, flag_path):
    clock = Clock()
    stack = Stack(clock, flag_path)
    stack.preflight = lambda: ["1 other container is running: rtu-db"]
    with pytest.raises(RuntimeError, match="rtu-db"):
        go(stack, clock, flag_path, tmp_path)
    assert stack.calls == []


def test_sampling_errors_invalidate_the_run(tmp_path, flag_path):
    # a period we could not observe cannot be vouched for (same rule as the soak test)
    clock = Clock()
    stack = Stack(clock, flag_path)
    real_sample = stack.sample

    def flaky(kind):
        if kind == "locust" and 9 * 60 <= clock.t < 9 * 60 + 1:
            return {"kind": "error", "ts": clock.now(), "sampler": kind, "error": "docker exec failed"}
        return real_sample(kind)

    stack.sample = flaky
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and "sampling_errors" in rec["reasons"]


def test_sampling_errors_outside_the_normal_period_are_recorded_but_keep_the_run_valid(tmp_path, flag_path):
    # decision 009 §4: only the normal period decides validity; an OOM-restarting container during the fault can make a
    # memcg read fail, and that must not systematically drop restart-causing faults
    schedule = go(Stack(Clock(), flag_path), Clock(), flag_path, tmp_path / "ref")["schedule"]
    clock = Clock()
    stack = Stack(clock, flag_path)
    real_sample = stack.sample

    def flaky(kind):
        now = clock.now()
        if kind in ("memcg", "state") and schedule["fault_on"] < now < schedule["fault_off"]:
            return {"kind": "error", "ts": now, "sampler": kind, "error": "cgroup gone"}
        if kind == "memcg" and schedule["normal_start"] < now < schedule["fault_on"]:
            return {"kind": "error", "ts": now, "sampler": kind, "error": "cgroup gone"}  # memcg decides nothing
        return real_sample(kind)

    stack.sample = flaky
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "valid" and rec["sampling_errors"]


def test_verify_running_must_be_clean_before_the_warm_up(tmp_path, flag_path):
    # decision 009 §1/§3: the gate starts only after a clean verify-running
    clock = Clock()
    original = flag_path.read_bytes()
    stack = Stack(clock, flag_path)
    stack.verify_running = lambda wait: ["otel-collector: exited"]
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "aborted_unstable" and "verify-running" in rec["reasons"][0]
    assert "gate" not in rec and not [c for c in stack.calls if isinstance(c, tuple)]  # never queried flagd
    assert flag_path.read_bytes() == original and stack.calls[-1] == ["down", "--volumes"]


def test_unconfirmed_fault_off_invalidates_the_run(tmp_path, flag_path):
    clock = Clock()
    original = flag_path.read_bytes()
    stack = Stack(clock, flag_path)
    stack.ofrep = lambda flag, ctx: ("100%", None)  # flagd keeps serving the fault after the file is restored
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and rec["reasons"] == ["flag_unconfirmed"]
    assert rec["flag"]["on"]["confirmed"] and not rec["flag"]["off"]["confirmed"]
    assert flag_path.read_bytes() == original and stack.calls[-1] == ["down", "--volumes"]


def test_a_broken_event_stream_invalidates_the_run(tmp_path, flag_path):
    clock = Clock()
    stack = Stack(clock, flag_path)
    watch = Watch(stack)
    watch.stop = lambda: None  # EventWatch.stop() is None when `docker events` died: OOM kills could be missed
    stack.watch = lambda path: watch
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and "event_stream_missing" in rec["reasons"]


@pytest.mark.parametrize("bad", [{"stop_exit_code": 137}, {"copied": False}, {"restarts": 1}])
def test_incomplete_raw_invalidates_the_run(tmp_path, flag_path, bad):
    clock = Clock()
    stack = Stack(clock, flag_path)
    clean = stack.finalize_raw

    def finalize(out_dir):
        raw = clean(out_dir)
        raw["collector"].update(bad)
        return raw

    stack.finalize_raw = finalize
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "invalid" and rec["reasons"] == ["raw_incomplete"] and "incident_window" not in rec


def test_a_failing_teardown_step_still_copies_raw_tears_down_and_keeps_the_record(tmp_path, flag_path, monkeypatch):
    # review: an I/O error restoring the flag file skipped finalize_raw (raw lost at `down`) and dropped the record
    import collect.rungroup as rg

    clock = Clock()
    stack = Stack(clock, flag_path)
    real_write = rg.write_atomic
    writes = []

    def failing_write(path, content):
        writes.append(content)
        if len(writes) >= 2:  # fault on works; fault off and the teardown's restore hit ENOSPC
            raise OSError(28, "No space left on device")
        return real_write(path, content)

    monkeypatch.setattr(rg, "write_atomic", failing_write)
    with pytest.raises(OSError) as info:
        go(stack, clock, flag_path, tmp_path)
    rec = info.value.run_record
    assert "finalize_raw" in stack.calls and stack.calls[-1] == ["down", "--volumes"]
    assert rec["status"] == "aborted_error" and rec["raw"] is not None and rec["teardown_errors"]


def test_a_crash_while_judging_the_run_keeps_the_record(tmp_path, flag_path, monkeypatch):
    import collect.rungroup as rg

    def broken(*a, **kw):
        raise ValueError("unexpected counter shape")

    monkeypatch.setattr(rg, "account", broken)
    clock = Clock()
    stack = Stack(clock, flag_path)
    with pytest.raises(ValueError) as info:
        go(stack, clock, flag_path, tmp_path)
    rec = info.value.run_record
    assert rec["status"] == "aborted_error" and "unexpected counter shape" in rec["reasons"][-1]
    assert stack.calls[-1] == ["down", "--volumes"]


def test_logs_of_containers_that_restarted_are_kept_before_down(tmp_path, flag_path):
    # RG-001 (2026-10-08): grafana exited 1 during warm-up and nothing showed why once the stack was down
    clock = Clock()
    stack = Stack(clock, flag_path, restart_at=3)  # checkout restarts in the warm-up
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "aborted_unstable" and rec["restarted_logs"] == ["checkout"]
    assert stack.calls.index(("save_logs", ("checkout",))) < stack.calls.index(["down", "--volumes"])
    assert (tmp_path / "work" / "container-logs" / "checkout.log").exists()


def test_a_clean_run_saves_no_container_logs(tmp_path, flag_path):
    clock = Clock()
    stack = Stack(clock, flag_path)
    rec = go(stack, clock, flag_path, tmp_path)
    assert rec["status"] == "valid" and "restarted_logs" not in rec
    assert not any(isinstance(c, tuple) and c[0] == "save_logs" for c in stack.calls)


class SkewedStack(Stack):
    """The Docker VM clock runs 120 s ahead of the host: docker events, docker_stats minutes and the collector's
    counters are on the VM (data) clock, the schedule on the host clock."""

    SKEW = 120.0

    def vm_time(self):
        return self.clock.time() + self.SKEW

    def ofrep(self, flag, context):
        if not any(e["action"] == "oom" for e in self.events):  # at fault on: an OOM 60 s before it, in VM time
            vm = T0 + timedelta(seconds=self.clock.t - 60 + self.SKEW)
            self.events.append({"ts": vm.strftime("%Y-%m-%dT%H:%M:%SZ"), "service": "checkout", "action": "oom",
                                "exit_code": None})
        return super().ofrep(flag, context)

    def finalize_raw(self, out_dir):
        out = super().finalize_raw(out_dir)
        out["container_minutes"] = {c: [(T0 + timedelta(minutes=m, seconds=self.SKEW)).strftime("%Y-%m-%dT%H:%M")
                                         for m in range(int(self.minute()) + 2)] for c in out["container_minutes"]}
        for s in out["collector_snapshots"]:
            s["t"] += int(self.SKEW) * 10**9
        return out


def test_vm_clock_data_is_judged_against_the_schedule_through_the_measured_offset(tmp_path, flag_path):
    # docker events come from the daemon in the VM: an OOM 60 s before fault on (host) is in the normal period even though
    # its VM timestamp is 60 s after fault on; docker_stats minutes are VM minutes too (no false gaps)
    clock = Clock()
    rec = go(SkewedStack(clock, flag_path), clock, flag_path, tmp_path)
    assert abs(rec["clock_offset_seconds"][0] - 120.0) < 1e-6
    assert "normal_period_not_clean" in rec["reasons"] and rec["normal_period"]["kills"]
    assert "container_metrics_missing" not in rec["reasons"] and "raw_incomplete" not in rec["reasons"]


def test_the_window_end_is_checked_with_the_second_offset_like_the_published_snapshot():
    # decision 011 §3 N3: the published window ends at end + the second offset; VM 119.6 s ahead at the start, 120.5 s
    # at the end: the snapshot covers VM 12:36 completely, so a docker_stats gap there must invalidate the run
    from collect.rungroup import _judge

    minutes = [f"2026-10-08T12:{m:02d}" for m in range(0, 37) if m != 36]
    raw = {"collector": {"container_id": "c", "restarts": 0, "stop_exit_code": 0, "stop_seconds": 1.0, "cp_seconds": 1.0,
                         "copied": True},
           "files": {sig: {"signal": sig, "bytes": 10, "parse_errors": 0, "wrong_signal_lines": 0} for sig in ("traces", "metrics", "logs")},
           "container_minutes": {c: minutes for c in SUT}, "collector_snapshots": [], "sdk_errors": {"exports": {}, "errors": []}}
    record = {"clock_offset_seconds": [119.6, 120.5], "reasons": []}
    _judge(record, [], [], raw, {"normal_start": "2026-10-08T12:05:00Z", "end": "2026-10-08T12:35:00Z"})
    assert record["container_metric_gaps"] and all(v == ["12:36"] for v in record["container_metric_gaps"].values())


PILOT_PLAN_KEYS = {"run_group_id", "seed", "flag", "variant", "fault_minutes", "recovery_base_minutes",
                   "recovery_jitter_minutes", "warmup_minutes", "gate_extra_minutes", "normal_base_minutes",
                   "normal_jitter_minutes", "drain_minutes", "interval", "confirm_timeout", "split", "normal_minutes",
                   "recovery_minutes"}


@pytest.mark.parametrize("over", [
    {"split": "heldout"},  # no slot, no freeze record
    {"split": "heldout", "slot": "H01"},
    {"split": "heldout", "freeze_sha256": "sha256:" + "f" * 64},
    {"slot": "H01"},  # a Pilot run group never fills a held-out slot
    {"freeze_sha256": "sha256:" + "f" * 64},
    {"split": "test"},
], ids=str)
def test_a_heldout_plan_names_its_slot_and_freeze_and_no_other_plan_does(over):
    # decision 023 §4 / SPEC §10: the set, the slot and the freeze in force are fixed when the run group is planned
    with pytest.raises(ValueError):
        plan(**over)


def test_a_pilot_run_record_keeps_todays_plan_keys_and_a_heldout_one_adds_slot_and_freeze(tmp_path, flag_path):
    clock = Clock()
    rec = go(Stack(clock, flag_path), clock, flag_path, tmp_path)
    assert set(rec["plan"]) == PILOT_PLAN_KEYS  # Pilot records keep exactly their shape
    clock = Clock()
    rec = go(Stack(clock, flag_path), clock, flag_path, tmp_path / "h", split="heldout", slot="H07",
             freeze_sha256="sha256:" + "f" * 64)
    assert set(rec["plan"]) == PILOT_PLAN_KEYS | {"slot", "freeze_sha256"}
    assert rec["plan"]["slot"] == "H07" and rec["plan"]["split"] == "heldout"


def test_a_heldout_run_group_takes_the_same_preflight_and_window_power_check(tmp_path, flag_path):
    # decision 025 revisions 2, 3 hold for every formal set: a held-out plan goes through the same run_group
    held = {"split": "heldout", "slot": "H01", "freeze_sha256": "sha256:" + "f" * 64}
    clock = Clock()
    stack = Stack(clock, flag_path)
    stack.preflight = lambda: power_problems({"source": "AC Power", "settings": {"powermode": "0"}})
    with pytest.raises(RuntimeError, match="high power mode"):
        go(stack, clock, flag_path, tmp_path, **held)
    assert stack.calls == []
    clock = Clock()
    stack = Stack(clock, flag_path, power_at={22: {"source": "Battery Power", "settings": {"powermode": "2"}}})
    rec = go(stack, clock, flag_path, tmp_path / "b", **held)
    assert rec["status"] == "invalid" and rec["reasons"] == ["power_not_formal"] and rec["plan"]["slot"] == "H01"
    clock = Clock()
    rec = go(Stack(clock, flag_path), clock, flag_path, tmp_path / "c", **held)
    assert rec["status"] == "valid" and rec["power_samples"] >= 25
