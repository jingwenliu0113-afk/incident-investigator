"""One run group (decision 009): up → warm-up → stability gate → normal → fault on → fault off → recovery → drain → raw → down.

The stack and the clock are injected (`Stack` / `Clock` below) so the protocol is testable without Docker.
The flagd file is always restored byte-for-byte, raw telemetry is always copied out before `down`, and
`down` always runs, whatever happens in between. Validity follows decision 009 §4.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import signal
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from collect.accounting import account
from collect.faults import check_context, inject, write_atomic
from collect.layout import DataLayout
from collect.rawexport import SIGNALS, build_raw_export, check_raw_export, raw_flags
from collect.records import _schema_problems, canonical_json_sha256
from collect.policy import load_policy
from collect.validity import container_metric_gaps, gate, period_observations


@dataclass(frozen=True)
class Plan:
    run_group_id: str
    seed: int
    flag: str
    variant: str
    fault_minutes: float
    recovery_base_minutes: float = 5
    recovery_jitter_minutes: float = 5
    warmup_minutes: float = 5
    gate_extra_minutes: float = 10
    normal_base_minutes: float = 10
    normal_jitter_minutes: float = 5
    drain_minutes: float = 3
    interval: float = 15  # seconds between state samples; Locust and memcg every 4th
    confirm_timeout: float = 10  # seconds for flagd to serve the new variant


MAX_CLOCK_DRIFT = 1.0  # seconds the host <-> VM offset may move during a run (decision 009, amended)


def _draws(plan: Plan) -> tuple[float, float]:
    rng = random.Random(plan.seed)
    return rng.uniform(0, plan.normal_jitter_minutes), rng.uniform(0, plan.recovery_jitter_minutes)


def normal_minutes(plan: Plan) -> float:
    """decision 002 / 009: a fixed normal period would leak fault_on through the window length."""
    return plan.normal_base_minutes + _draws(plan)[0]


def recovery_minutes(plan: Plan) -> float:
    """decision 009 (amended): a fixed recovery would put fault_off at a fixed distance from the window end."""
    return plan.recovery_base_minutes + _draws(plan)[1]


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...
    def time(self) -> float: ...
    def now(self) -> str: ...


class Stack(Protocol):
    def preflight(self) -> list[str]: ...
    def provenance(self) -> dict: ...  # project / lock / machine / compose command / traffic settings (decision 002)
    def compose(self, args: list[str]) -> int: ...
    def watch(self, path: Path): ...  # .seen() / .stop() like env.soak.EventWatch
    def verify_running(self, wait: float) -> list[str]: ...
    def rescan_containers(self) -> dict: ...  # env.soak.rescan_container_metrics (decision 012)
    def sample(self, kind: str) -> dict: ...  # "state" | "locust" | "memcg", shaped like env.soak.Sampler
    def ofrep(self, flag: str, context: dict) -> tuple[str, object]: ...
    def vm_time(self) -> float: ...
    def finalize_raw(self, out_dir: Path) -> dict: ...  # env.soak.finalize_raw


_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP")


def _mask_signals() -> dict:
    """Ignore interrupts while tearing down; children (`compose stop` / `down`) inherit SIG_IGN too."""
    try:
        return {name: signal.signal(getattr(signal, name), signal.SIG_IGN) for name in _SIGNALS}
    except ValueError:  # not the main thread: nothing to mask
        return {}


def _restore_signals(saved: dict) -> None:
    for name, handler in saved.items():
        signal.signal(getattr(signal, name), handler)


def _ns(ts: str) -> int:
    return int(datetime.fromisoformat(ts).timestamp()) * 10**9


def _sha(doc_bytes: bytes, scratch: Path) -> str:
    scratch.write_bytes(doc_bytes)
    try:
        return canonical_json_sha256(scratch)
    finally:
        scratch.unlink()


def _serving(doc: dict, flag: str) -> str:
    """Variant a confirmation query (with check_context) sees for `flag` in this document."""
    f = doc["flags"][flag]
    return f["targeting"]["if"][1] if f.get("targeting") else f["defaultVariant"]


def run_group(plan: Plan, stack: Stack, clock: Clock, *, flag_path: Path, work_dir: Path) -> dict:
    if problems := stack.preflight():
        raise RuntimeError("not starting: " + "; ".join(problems))
    original = flag_path.read_bytes()
    baseline = json.loads(original)
    injected = inject(baseline, plan.flag, plan.variant)  # validates flag / variant before anything starts
    work_dir.mkdir(parents=True)
    injected_bytes = (json.dumps(injected, indent=2) + "\n").encode()

    record: dict = {
        "run_group_id": plan.run_group_id,
        "plan": {**asdict(plan), "normal_minutes": round(normal_minutes(plan), 3),
                 "recovery_minutes": round(recovery_minutes(plan), 3)},
        "status": None,
        "reasons": [],
        "flag": {"path": flag_path.name, "baseline_sha256": _sha(original, work_dir / ".flag.json"),
                 "injected_sha256": _sha(injected_bytes, work_dir / ".flag.json")},
        "harness_flag_queries": [],
        "clock_offset_seconds": [],
        "provenance": stack.provenance(),
    }
    samples: list[dict] = []
    samples_file = (work_dir / "samples.jsonl").open("a")

    def take(kinds: tuple[str, ...]) -> None:
        for kind in kinds:
            s = stack.sample(kind)
            samples.append(s)
            samples_file.write(json.dumps(s) + "\n")
        samples_file.flush()

    def run_until(deadline: float) -> None:
        i = 0
        while clock.monotonic() < deadline:
            take(("state",) + (("locust", "memcg") if i % 4 == 0 else ()))
            clock.sleep(min(plan.interval, max(deadline - clock.monotonic(), 0)))
            i += 1

    def offset() -> float:
        before = clock.time()
        vm = stack.vm_time()
        after = clock.time()
        return vm - (before + after) / 2

    def switch(content: bytes, expect: str, label: str) -> tuple[str, float, bool]:
        """Write the flag file, then poll flagd until it serves `expect` (decision 009 §5)."""
        written_at, host_t, mono_t = clock.now(), clock.time(), clock.monotonic()
        write_atomic(flag_path, content)
        confirmed = False
        while True:
            record["harness_flag_queries"].append({"ts": clock.now(), "flag": plan.flag})
            variant, _ = stack.ofrep(plan.flag, check_context(plan.flag))
            if variant == expect:
                confirmed = True
                break
            if clock.monotonic() - mono_t >= plan.confirm_timeout:
                break
            clock.sleep(0.5)
        record["flag"][label] = {"written_at": written_at, "confirmed": confirmed,
                                 "latency_seconds": round(clock.time() - host_t, 3)}
        return written_at, mono_t, confirmed

    watch, raw, up_started, events, crashed = None, None, False, None, False
    times: dict[str, str] = {}
    try:
        watch = stack.watch(work_dir / "docker-events.jsonl")
        record["up_at"] = clock.now()
        up_started = True
        if (rc := stack.compose(["up"])) != 0:
            record["status"] = "aborted_up_failed"
            record["reasons"].append(f"compose up exit {rc}")
            return record
        record["initial_verify_running"] = problems = stack.verify_running(300)
        if problems:  # decision 009 §1/§3: the gate starts only after a clean verify-running
            record["status"] = "aborted_unstable"
            record["reasons"].append("verify-running not clean after 300 s: " + "; ".join(problems[:10]))
            return record
        record["container_rescan"] = stack.rescan_containers()

        run_until(clock.monotonic() + plan.warmup_minutes * 60)
        give_up = clock.monotonic() + plan.gate_extra_minutes * 60
        while True:
            take(("state", "locust"))
            g = gate(samples, watch.seen(), now=clock.now())
            if g["pass"] or g["G1"].get("final") or clock.monotonic() >= give_up:
                break
            run_until(clock.monotonic() + 60)
        record["gate"] = g
        if not g["pass"]:
            record["status"] = "aborted_unstable"
            record["reasons"].append("stability gate not met: " + "; ".join(
                f"{k} {g[k]['detail']}" for k in ("G1", "G2", "G3") if not g[k]["pass"]))
            return record

        record["clock_offset_seconds"].append(offset())
        times["normal_start"] = clock.now()
        run_until(clock.monotonic() + normal_minutes(plan) * 60)
        take(("state", "locust"))
        times["fault_on"], on_mono, on_ok = switch(injected_bytes, plan.variant, "on")
        if not on_ok:
            record["reasons"].append("flag_unconfirmed")
            write_atomic(flag_path, original)  # no fault period without a confirmed fault
        else:
            run_until(on_mono + plan.fault_minutes * 60)
            take(("state", "locust"))
            times["fault_off"], _, off_ok = switch(original, _serving(baseline, plan.flag), "off")
            if not off_ok:
                record["reasons"].append("flag_unconfirmed")
            run_until(clock.monotonic() + recovery_minutes(plan) * 60)
        take(("state", "locust"))
        times["end"] = clock.now()
        record["clock_offset_seconds"].append(offset())
        run_until(clock.monotonic() + plan.drain_minutes * 60)  # decision 008 §4
        events = watch.stop()  # before the collector stop: its exit is judged with the raw export
        raw = stack.finalize_raw(work_dir)
    except BaseException as e:  # decision 009 §4: a run that started always leaves a record, a crashed one too
        crashed = True
        record["status"] = "aborted_error"
        record["reasons"].append(f"harness error: {type(e).__name__}: {str(e)[:300]}")
        e.run_record = record  # the same dict: the teardown below still fills raw / events / down_exit_code
        raise
    finally:
        masked = _mask_signals()  # a second Ctrl-C / SIGTERM must not cut the teardown short
        teardown_errors: list[BaseException] = []

        def step(name: str, fn) -> None:
            """Each teardown step runs whatever the previous one did; a failure is recorded, not propagated here."""
            try:
                fn()
            except BaseException as e:  # noqa: BLE001 - every teardown step must run
                teardown_errors.append(e)
                record.setdefault("teardown_errors", []).append(f"{name}: {type(e).__name__}: {str(e)[:300]}")

        def restore_flag() -> None:
            if flag_path.read_bytes() != original:
                write_atomic(flag_path, original)

        def stop_watch() -> None:
            nonlocal events
            if watch is not None:
                stopped = watch.stop()
                events = events if events is not None else stopped

        def copy_raw() -> None:
            nonlocal raw
            if up_started and raw is None:
                raw = stack.finalize_raw(work_dir)  # whatever exists is kept for debugging (decision 009 §4)

        try:
            step("restore flag file", restore_flag)
            step("close samples", samples_file.close)
            step("stop event watch", stop_watch)
            step("copy raw", copy_raw)
            record["raw"], record["events"] = raw, events
        finally:
            try:
                if up_started:
                    record["down_exit_code"] = stack.compose(["down", "--volumes"])
            finally:
                _restore_signals(masked)
        if teardown_errors and not crashed:
            record["status"] = "aborted_error"
            record["reasons"].append(f"teardown error: {record['teardown_errors'][0]}")
            teardown_errors[0].run_record = record
            raise teardown_errors[0]

    try:
        _judge(record, samples, events, raw, times)
    except BaseException as e:
        record["status"] = "aborted_error"
        record["reasons"].append(f"harness error while judging: {type(e).__name__}: {str(e)[:300]}")
        e.run_record = record
        raise
    return record


def _judge(record: dict, samples: list[dict], events: list[dict] | None, raw: dict | None, times: dict) -> None:
    """Validity of a run group that ran to its end (decision 009 §4, 008 §6, 012)."""
    if {"fault_on", "fault_off"} <= times.keys():
        record["schedule"] = dict(times)
        record["normal_period"] = period_observations(samples, events or [], start=times["normal_start"],
                                                      end=times["fault_on"])
        record["fault_and_recovery"] = period_observations(samples, events or [], start=times["fault_on"],
                                                           end=times["end"])
        if not record["normal_period"]["clean"]:
            record["reasons"].append("normal_period_not_clean")
        if events is None:
            record["reasons"].append("event_stream_missing")
    if raw is not None and {"normal_start", "end"} <= times.keys():
        record["raw_accounting"] = account(raw.get("collector_snapshots") or [], raw.get("sdk_errors") or {},
                                           raw["files"], start_ns=_ns(times["normal_start"]), end_ns=_ns(times["end"]))
    if raw is None or raw_flags(raw["collector"], raw["files"]) or record.get("raw_accounting", {}).get("flags"):
        record["reasons"].append("raw_incomplete")
    if raw is not None and {"normal_start", "end"} <= times.keys():
        record["container_metric_gaps"] = container_metric_gaps(
            raw.get("container_minutes") or {}, services=load_policy().raw["sut_services"],
            start=times["normal_start"], end=times["end"])
        if record["container_metric_gaps"]:
            record["reasons"].append("container_metrics_missing")  # decision 012
    offsets = record["clock_offset_seconds"]
    if len(offsets) == 2 and abs(offsets[1] - offsets[0]) > MAX_CLOCK_DRIFT:
        record["reasons"].append("clock_drift")  # the window cannot be mapped onto the data clock reliably
    if errors := [s for s in samples if s["kind"] == "error"]:
        record["sampling_errors"] = errors[:20]  # all of them are kept for the label review
        # decision 009 §4: only the normal period decides validity, and only state / Locust samples judge it
        blind = [s for s in errors if s.get("sampler") in ("state", "locust")
                 and times.get("normal_start", "~") <= s["ts"] <= times.get("fault_on", "")]
        if blind:
            record["reasons"].append("sampling_errors")  # a normal period we could not observe cannot be vouched for
    record["status"] = "valid" if not record["reasons"] else "invalid"
    if record["status"] == "valid":
        record["incident_window"] = {"start": times["normal_start"], "end": times["end"]}  # decision 009 §1


# ---------------------------------------------------------------- storing a finished run group

def next_id(layout: DataLayout, prefix: str) -> str:
    """Next opaque id ("RG" / "INC") past every id already used on disk, on either side of the isolation line."""
    roots = {"RG": (layout.raw_root, layout.ground_truth_root / "run_groups", layout.root / "staging"),
             "INC": (layout.incidents_root, layout.ground_truth_root / "incidents")}[prefix]
    pattern = re.compile(rf"{prefix}-([0-9]{{3,}})")
    used = [int(m.group(1)) for root in roots if root.exists() for p in root.iterdir() if (m := pattern.fullmatch(p.name))]
    return f"{prefix}-{max(used, default=0) + 1:03d}"


def store_run_group(record: dict, work_dir: Path, layout: DataLayout, *, lock_sha256: str) -> dict:
    """Move a finished run group into place (decision 008 §5, 009 §6) and give a valid run its incident id.

    raw/<RG>/: the three raw files + raw_export.json. ground_truth/run_groups/<RG>/: run.json, the harness
    samples / events (their timings reveal the fault) and, for a valid run, injection.json. A valid run's
    incident id is reserved by creating ground_truth/incidents/<INC>/ (its label goes there).
    """
    rg = record["run_group_id"]
    truth, raw_dir = layout.run_group_truth_dir(rg), layout.raw_dir(rg)
    if truth.exists() or raw_dir.exists():
        raise FileExistsError(f"{rg} already stored ({truth} / {raw_dir})")
    incident_ids = [next_id(layout, "INC")] if record["status"] == "valid" else []

    export = None
    if (raw := record.get("raw")) is not None:  # checked before anything moves, so a refused store can be retried
        export = build_raw_export(rg, lock_sha256, raw["collector"], raw["files"], accounting=record.get("raw_accounting"))
        if problems := check_raw_export(export):
            raise ValueError(f"raw export record of {rg} is inconsistent: {problems}")
    raw_dir.mkdir(parents=True)
    for sig in SIGNALS:
        src = work_dir / "raw" / f"{sig}.jsonl"
        if src.exists():
            shutil.move(src, raw_dir / src.name)
    if export is not None:
        (raw_dir / "raw_export.json").write_text(json.dumps(export, indent=2) + "\n")

    truth.mkdir(parents=True)
    harness = truth / "harness"
    harness.mkdir()
    for name in ("samples.jsonl", "docker-events.jsonl", "otel-collector-shutdown.log"):
        if (work_dir / name).exists():
            shutil.move(work_dir / name, harness / name)
    if incident_ids:
        injection = {
            "injection_version": 1,
            "run_group_id": rg,
            "incident_ids": incident_ids,
            "seed": record["plan"]["seed"],
            "fault": {"mechanism": "flagd", "flag": record["plan"]["flag"], "variant": record["plan"]["variant"]},
            "schedule": record["schedule"],
            "controller": {"method": "flagd-file"},
            "flag_file": {"baseline_sha256": record["flag"]["baseline_sha256"],
                          "injected_sha256": record["flag"]["injected_sha256"]},
        }
        if problems := _schema_problems(injection, "fault_injection.schema.json"):
            raise ValueError(f"injection record of {rg} is invalid: {problems}")
        (truth / "injection.json").write_text(json.dumps(injection, indent=2) + "\n")
        for inc in incident_ids:
            layout.label_path(inc).parent.mkdir(parents=True)
    run = {k: v for k, v in record.items() if k != "raw"}
    run.update(incident_ids=incident_ids, raw_dir=raw_dir.relative_to(layout.root).as_posix(), env_lock_sha256=lock_sha256,
               raw_collector=(raw or {}).get("collector"))
    (truth / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    shutil.rmtree(work_dir)
    return {"incident_ids": incident_ids, "raw_dir": raw_dir, "truth_dir": truth}
