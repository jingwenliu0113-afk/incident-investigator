"""Raw export record of one run group (decision 008 §6): what was copied out of the collector and whether it is complete."""

from __future__ import annotations

from collect.records import _schema_problems

SIGNALS = ("traces", "metrics", "logs")
_FILE_KEYS = ("signal", "format", "bytes", "sha256", "lines", "empty_lines", "empty_messages", "parse_errors", "parse_error_lines",
              "last_line_truncated", "wrong_signal_lines", "items", "duplicates", "min_time", "max_time",
              "by_service", "minutes")


def raw_flags(collector: dict, scans: dict[str, dict | None]) -> list[str]:
    """Why a raw export is incomplete (decision 008 §6); empty when it is complete (before loss accounting)."""
    flags = []
    if collector.get("restarts"):
        flags.append("collector_restarted")  # append keeps data, but the restart edge may glue or cut a line
    if collector.get("stop_exit_code") == 137:
        flags.append("collector_sigkilled")  # killed before the final flush
    elif collector.get("stop_exit_code") != 0 and not collector.get("graceful_stop"):
        flags.append("collector_unclean_stop")  # exit 1 is graceful only with the shutdown-log verdict (decision 008 revision)
    if not collector.get("copied"):
        flags.append("copy_failed")
    for sig in SIGNALS:
        scan = scans.get(sig)
        if not scan or not scan["bytes"]:
            flags.append(f"missing_file:{sig}")
        elif scan["parse_errors"] or scan["wrong_signal_lines"]:
            flags.append(f"parse_errors:{sig}")
    return flags


def build_raw_export(run_group_id: str, lock_sha256: str, collector: dict, scans: dict[str, dict | None],
                     *, accounting: dict | None = None) -> dict:
    """`scans`: collect.rawfile.scan_raw_file() per signal (None when the file was not there)."""
    flags = raw_flags(collector, scans) + (accounting or {}).get("flags", [])
    files = [{"path": f"{sig}.jsonl", **{k: scans[sig][k] for k in _FILE_KEYS}}
             for sig in SIGNALS if scans.get(sig) and scans[sig]["bytes"]]
    record = {
        "raw_export_version": 1,
        "run_group_id": run_group_id,
        "env_lock_sha256": lock_sha256,
        "collector": {k: collector.get(k) for k in ("container_id", "restarts", "stop_exit_code", "graceful_stop",
                                                    "shutdown_reason", "stop_seconds", "cp_seconds", "copied")},
        "files": files,
        "flags": flags,
        "complete": not flags,
    }
    if accounting is not None:
        record["accounting"] = accounting
    return record


def check_raw_export(record: dict) -> list[str]:
    problems = _schema_problems(record, "raw_export.schema.json")
    if problems:
        return problems
    if record["complete"] != (not record["flags"]):
        problems.append(f"complete={record['complete']} contradicts flags {record['flags']}")
    signals = [f["signal"] for f in record["files"]]
    if len(signals) != len(set(signals)):
        problems.append(f"duplicate signals in files: {signals}")
    for sig in SIGNALS:
        if sig not in signals and f"missing_file:{sig}" not in record["flags"]:
            problems.append(f"no {sig} file and no missing_file:{sig} flag")
    return problems
