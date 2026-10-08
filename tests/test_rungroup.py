"""Run group orchestration (decision 009): gate → normal → fault on → fault off → recovery → drain → raw → down."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from collect.policy import load_policy
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

    def __init__(self, clock, flag_path, *, restart_at=None, fivexx_until=0.0, confirm=True):
        self.clock, self.flag_path = clock, flag_path
        self.restart_at, self.fivexx_until, self.confirm = restart_at, fivexx_until, confirm
        self.calls, self.events, self.n5xx, self.flag_writes = [], [], 0, []
        self.unseen = set()  # containers docker_stats never reported (decision 012)

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
                                      for c in SUT if c not in self.unseen}}


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
    with pytest.raises(RuntimeError):
        go(stack, clock, flag_path, tmp_path)
    assert flag_path.read_bytes() == original
    assert "finalize_raw" in stack.calls and stack.calls[-1] == ["down", "--volumes"]


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
