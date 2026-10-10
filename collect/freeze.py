"""The held-out freeze record and its fail-closed check (decision 023 §6; implementation decision 026). The only held-out
module that runs git, and only read-only git commands (rev-parse, status, ls-files, diff, merge-base, log, ls-tree,
hash-object without -w).

The record cannot name its own commit, so it names the commit it was written on (frozen_from_commit, the parent of the
freeze commit). Deny by default: from there to HEAD only ALLOWED_AFTER_FREEZE may change; everything else (code, tests,
SPEC, README, docs, every existing decision) must be byte-identical.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from collect.heldout import (FREEZE_FILE, HELDOUT_K, HELDOUT_MASTER_SEED, PLAN_FILE, SLOTS_FILE, doc_sha256,
                             heldout_slots)

Run = Callable[[Sequence[str]], str]

NO_FREEZE = "no held-out freeze record (decision 023 §6): held-out collection and method runs are refused"
DECISIONS_DIR = "docs/decisions"
NEW_DECISION = re.compile(r"docs/decisions/[0-9]{3}-[^/]+\.md")
ALLOWED_AFTER_FREEZE = (("M", "NEXT.md"), ("A", SLOTS_FILE.as_posix()), ("A", FREEZE_FILE.as_posix()),
                        ("A", "docs/decisions/NNN-*.md"))
PILOT_REVISABLE = ("011", "013", "014", "015", "017", "019", "020", "021", "022")  # "Pilot 上修訂一次" (023 §6)
CODE_DIRS = ("agent", "baselines", "collect", "env", "eval", "schemas", "tools")
COMMIT = re.compile(r"[0-9a-f]{40}")
RECORD_KEYS = ("freeze_version", "decision", "frozen_at", "frozen_from_commit", "frozen_tree", "decisions",
               "env_lock_sha256", "policy", "llm", "pilot_revisions", "plan", "k", "master_seed", "slots")
LLM_FIELDS = ("status", "model", "model_version", "temperature")


def _run(cmd: Sequence[str]) -> str:
    return subprocess.run(list(cmd), check=True, capture_output=True, text=True).stdout


def _git(run: Run, project_dir: Path, *args: str) -> str:
    return run(["git", "-C", str(project_dir), *args])


def _blob(run: Run, project_dir: Path, rev: str, path: str) -> str | None:
    try:
        return _git(run, project_dir, "rev-parse", f"{rev}:{path}").strip() or None
    except subprocess.CalledProcessError:
        return None


def is_ancestor(project_dir: Path, a: str, b: str, *, run: Run | None = None) -> bool:
    """`git merge-base --is-ancestor`: exit 1 means no; any other failure is re-raised (the caller says git failed)."""
    try:
        _git(run or _run, project_dir, "merge-base", "--is-ancestor", a, b)
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return False
        raise
    return True


def _changes(run: Run, project_dir: Path, a: str, b: str) -> list[list[str]]:
    out = _git(run, project_dir, "diff", "--name-status", "--no-renames", a, b, "--")
    return [line.split("\t", 1) for line in out.splitlines() if line.strip()]


def _tree_files(run: Run, project_dir: Path, rev: str, directory: str) -> dict[str, str]:
    """{path: blob} of the files directly in `directory` at `rev` (README.md excluded: it is the index, not a decision)."""
    out = {}
    for line in _git(run, project_dir, "ls-tree", rev, directory.rstrip("/") + "/").splitlines():
        meta, path = line.split("\t", 1)
        if meta.split()[1] == "blob" and Path(path).name != "README.md":
            out[path] = meta.split()[2]
    return out


def _sha(path: Path) -> str | None:
    from env.lock import sha256_path

    return sha256_path(path) if path.exists() else None


def _read(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def observe(project_dir: Path, *, base: str | None = None, run: Run | None = None) -> dict:
    """What the freeze record and its check look at, read from `project_dir` and its git (read only)."""
    from collect.policy import POLICY_PATH
    from env.lock import LOCK_PATH, PROJECT_DIR, lock_sha256

    run, project_dir = run or _run, Path(project_dir)
    head = _git(run, project_dir, "rev-parse", "HEAD").strip()
    flagged = [line[2:] for line in _git(run, project_dir, "ls-files", "-v").splitlines()
               if line and (line[0].islower() or line[0] == "S")]
    ignored = _git(run, project_dir, "ls-files", "--others", "--ignored", "--exclude-standard", "--", *CODE_DIRS,
                   ":(exclude)env/upstream").splitlines()
    lock = _read(project_dir / LOCK_PATH)
    policy_path = project_dir / POLICY_PATH.relative_to(PROJECT_DIR)
    policy = _read(policy_path)
    llm_path = project_dir / "eval" / "llm_methods.json"
    llm = _read(llm_path)
    plan, slots = _read(project_dir / PLAN_FILE), _read(project_dir / SLOTS_FILE)
    blobs = {}
    for rel in (PLAN_FILE, SLOTS_FILE, FREEZE_FILE):
        disk = _git(run, project_dir, "hash-object", "--", rel.as_posix()).strip() if (project_dir / rel).exists() else None
        blobs[rel.as_posix()] = {"head": _blob(run, project_dir, "HEAD", rel.as_posix()), "disk": disk}
    observed = {
        "head": head, "tree": _git(run, project_dir, "rev-parse", "HEAD^{tree}").strip(),
        "dirty": bool(_git(run, project_dir, "status", "--porcelain", "--untracked-files=all").strip()),
        "flagged": flagged, "ignored_code": [p for p in ignored if p.endswith(".py")],
        "env_lock_sha256": None if lock is None else lock_sha256(lock),
        "policy": None if policy is None else {"version": policy.get("version"), "sha256": _sha(policy_path),
                                               "status": policy.get("status")},
        "llm": None if llm is None else {**{k: llm.get(k) for k in LLM_FIELDS}, "config_sha256": _sha(llm_path)},
        "plan": plan, "plan_sha256": _sha(project_dir / PLAN_FILE),
        "slots": slots, "slots_sha256": _sha(project_dir / SLOTS_FILE),
        "decisions": _tree_files(run, project_dir, "HEAD", DECISIONS_DIR), "blobs": blobs,
    }
    if base is not None:
        observed.update(
            base=base, base_tree=_git(run, project_dir, "rev-parse", f"{base}^{{tree}}").strip(),
            base_decisions=_tree_files(run, project_dir, base, DECISIONS_DIR),
            changes=_changes(run, project_dir, base, "HEAD"), ancestor=is_ancestor(project_dir, base, "HEAD", run=run),
            log={rel.as_posix(): [[line.split()[0], line.split()[1:]] for line in _git(
                run, project_dir, "log", "--format=%H %P", "--", rel.as_posix()).splitlines() if line.strip()]
                 for rel in (SLOTS_FILE, FREEZE_FILE)})
    return observed


def _change_problems(changes: list) -> list[str]:
    out = []
    for status, path in changes:
        if ((status, path) in ALLOWED_AFTER_FREEZE[:3]) or (status == "A" and NEW_DECISION.fullmatch(path)):
            continue
        out.append(f"{path} ({status}) differs from the frozen commit: after the freeze only NEXT.md, the slot list, the "
                   "freeze record and new decision files may change (decision 023 §6, deny by default)")
    return out


def pilot_revision_problems(revisions, decision_paths, policy_version) -> list[str]:
    """023 §6: each decision's one Pilot revision is used (naming a decision file of the frozen commit: the person's
    attestation) or waived; 013's is used by 023 §7; 011's is used exactly when the policy is v2; 014's is waived (user
    decision 2026-10-10, decision 014 addendum)."""
    if not isinstance(revisions, dict):
        return ["pilot_revisions must map each of " + ", ".join(PILOT_REVISABLE) + " to used or waived"]
    problems = [f"pilot_revisions has no declaration for {n}" for n in PILOT_REVISABLE if n not in revisions]
    problems += [f"pilot_revisions names {n}, which has no Pilot revision (only {', '.join(PILOT_REVISABLE)})"
                 for n in sorted(set(revisions) - set(PILOT_REVISABLE))]
    for n in PILOT_REVISABLE:
        r = revisions.get(n)
        if r is None:
            continue
        if not isinstance(r, dict) or r.get("status") not in ("used", "waived") or set(r) - {"status", "decision"}:
            problems.append(f"{n}: declare {{\"status\": \"used\", \"decision\": <file>}} or {{\"status\": \"waived\"}}")
        elif r["status"] == "used" and r.get("decision") not in decision_paths:
            problems.append(f"{n}: used, but {r.get('decision')!r} is not a decision file in the frozen commit")
        elif r["status"] == "waived" and r.get("decision") is not None:
            problems.append(f"{n}: a waived revision names no decision")
    if (revisions.get("013") or {}).get("status") != "used":
        problems.append("013 must be declared used: 023 §7 is 013's one revision")
    if (revisions.get("014") or {}).get("status") != "waived":
        problems.append("014 must be declared waived: the user waived the statistical baseline's one Pilot revision on "
                        "2026-10-10 (decision 014 addendum; stat-anomaly v2 is final)")
    status_011 = (revisions.get("011") or {}).get("status")
    if policy_version not in (1, 2) or status_011 != {1: "waived", 2: "used"}.get(policy_version):
        problems.append(f"011 is {status_011!r} with policy version {policy_version!r}: policy v1 means 011 waived, "
                        "v2 means 011 used (023 §6)")
    return problems


def freeze_record(observed: dict, *, slots_doc: dict, pilot_revisions: dict, now: str) -> dict:
    """The record 023 §6 lists, from what observe() saw at the commit it is written on."""
    return {"freeze_version": 1, "decision": "023 §6", "frozen_at": now,
            "frozen_from_commit": observed["head"], "frozen_tree": observed["tree"],
            "decisions": dict(observed["decisions"]), "env_lock_sha256": observed["env_lock_sha256"],
            "policy": {"version": observed["policy"]["version"], "sha256": observed["policy"]["sha256"]},
            "llm": dict(observed["llm"]), "pilot_revisions": pilot_revisions,
            "plan": {"path": PLAN_FILE.as_posix(), "sha256": observed["plan_sha256"],
                     "faults": len(observed["plan"]["entries"])},
            "k": slots_doc["k"], "master_seed": slots_doc["master_seed"],
            "slots": {"path": SLOTS_FILE.as_posix(), "sha256": doc_sha256(slots_doc), "count": len(slots_doc["slots"])}}


def freeze_problems(record: dict, observed: dict) -> list[str]:
    """Every way HEAD and the checkout depart from the freeze record (pure; observed with base = frozen_from_commit)."""
    problems = []
    if observed["dirty"]:
        problems.append("the checkout is not clean (untracked or modified files): held-out work needs a clean checkout")
    if observed["flagged"]:
        problems.append(f"files marked assume-unchanged or skip-worktree hide changes: {observed['flagged']}")
    if observed["ignored_code"]:
        problems.append(f"ignored code files under the code directories: {observed['ignored_code']}")
    if not isinstance(record, dict) or record.get("freeze_version") != 1 or list(record) != list(RECORD_KEYS):
        return problems + [f"the freeze record is not a version-1 record with exactly the keys {RECORD_KEYS}"]
    try:
        if not observed["ancestor"]:
            problems.append(f"frozen_from_commit {record['frozen_from_commit']} is not an ancestor of HEAD")
        problems += _change_problems(observed["changes"])
        logs = observed["log"]
        for rel in (SLOTS_FILE.as_posix(), FREEZE_FILE.as_posix()):
            if len(logs[rel]) != 1:
                problems.append(f"{rel} is touched by {len(logs[rel])} commits: it is written once, in one commit")
        if all(len(logs[rel]) == 1 for rel in logs):
            (s_commit, parents), (f_commit, _) = logs[SLOTS_FILE.as_posix()][0], logs[FREEZE_FILE.as_posix()][0]
            if s_commit != f_commit or (parents or [None])[0] != record["frozen_from_commit"]:
                problems.append("the slot list and the freeze record are not added by one commit whose first parent is "
                                "frozen_from_commit")
        for rel, b in observed["blobs"].items():
            if b["head"] is None:
                problems.append(f"{rel} is not committed at HEAD")
            elif b["head"] != b["disk"]:
                problems.append(f"{rel} on disk differs from HEAD")
        if observed.get("base_tree") != record["frozen_tree"]:
            problems.append("frozen_tree is not the tree of frozen_from_commit")
        if observed.get("base_decisions") != record["decisions"]:
            problems.append("the decision blobs of the record are not those of frozen_from_commit")
        if observed["env_lock_sha256"] != record["env_lock_sha256"]:
            problems.append("the env lock differs from the freeze record (decision 023 §6 / user decision 6: stop)")
        if observed["policy"] is None or [observed["policy"][k] for k in ("version", "sha256")] != [
                record["policy"].get("version"), record["policy"].get("sha256")]:
            problems.append("the normalize policy differs from the freeze record (decision 011 §4)")
        if observed["llm"] != record["llm"]:
            problems.append("eval/llm_methods.json differs from the freeze record")
        if observed["plan_sha256"] != record["plan"]["sha256"]:
            problems.append("docs/heldout/plan.json is not the plan the record names")
        if observed["slots_sha256"] != record["slots"]["sha256"]:
            problems.append("docs/heldout/slots.json is not the slot list the record names")
        plan, slots = observed["plan"], observed["slots"]
        if plan is not None and slots is not None:
            faults = [[e["flag"], e["variant"]] for e in plan["entries"]]
            if record["k"] != HELDOUT_K:
                problems.append(f"K is {record['k']}, not {HELDOUT_K} (user decision 2026-10-09)")
            elif record["master_seed"] != HELDOUT_MASTER_SEED:
                problems.append(f"the master seed is {record['master_seed']}, not {HELDOUT_MASTER_SEED} (decision 023 §4)")
            elif (slots.get("faults") != faults or slots.get("k") != record["k"]
                  or slots.get("master_seed") != record["master_seed"] or slots.get("plan_sha256") != record["plan"]["sha256"]
                  or record["plan"].get("faults") != len(faults) or record["slots"].get("count") != len(slots.get("slots") or [])
                  or slots.get("slots") != heldout_slots(faults, k=record["k"], seed=record["master_seed"])):
                problems.append("slots.json is not the list regenerated from plan.json, K and the master seed (decision 023 §4)")
        problems += pilot_revision_problems(record["pilot_revisions"], set(record["decisions"]),
                                            record["policy"].get("version"))
        llm = record["llm"]
        if llm.get("status") != "approved" or any(llm.get(k) is None for k in ("model", "model_version", "temperature")):
            problems.append(f"the LLM methods must be approved with model, model_version and temperature (got {llm})")
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        problems.append(f"the freeze record or its files are malformed: {type(e).__name__}: {e}")
    return problems


def check_freeze(project_dir: Path, run: Run | None = None) -> tuple[dict | None, list[str]]:
    """(record, problems). No record: one problem and no git at all. Callers use this module attribute (tests patch it)."""
    path = Path(project_dir) / FREEZE_FILE
    if not path.exists():
        return None, [NO_FREEZE]
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return None, [f"the freeze record is unreadable: {e}"]
    base = record.get("frozen_from_commit") if isinstance(record, dict) else None
    if not isinstance(base, str) or not COMMIT.fullmatch(base):
        return record, ["the freeze record names no frozen_from_commit"]
    try:
        observed = observe(project_dir, base=base, run=run or _run)
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        return record, [f"git failed while checking the freeze record: {e}"]
    return record, freeze_problems(record, observed)


def freeze_sha256(project_dir: Path) -> str:
    from env.lock import sha256_path

    return sha256_path(Path(project_dir) / FREEZE_FILE)


@functools.lru_cache(maxsize=1024)
def _commit_problems(project_dir: str, base: str, commit: str, head_blob: str | None, run: Run) -> tuple[str, ...]:
    short = commit[:12]
    try:
        if not is_ancestor(Path(project_dir), base, commit, run=run):
            return (f"commit {short} does not descend from the frozen commit",)
        problems = [f"commit {short}: {p}" for p in _change_problems(_changes(run, Path(project_dir), base, commit))]
        blob = _blob(run, Path(project_dir), commit, FREEZE_FILE.as_posix())
        if blob is None or blob != head_blob:
            problems.append(f"commit {short} does not contain this freeze record")
        return tuple(problems)
    except subprocess.CalledProcessError as e:
        return (f"git failed on commit {short}: {e}",)


def commit_problems(project_dir: Path, record: dict, commit: str | None, *, run: Run | None = None) -> list[str]:
    """Why held-out data made at `commit` (a run's or a normalize's checkout) is not from the frozen code: it must descend
    from frozen_from_commit, differ from it only in allowed paths and contain this freeze record. Cached per commit."""
    run = run or _run
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        return [f"no recorded commit ({commit!r})"]
    head_blob = _blob(run, Path(project_dir), "HEAD", FREEZE_FILE.as_posix())
    return list(_commit_problems(str(project_dir), record["frozen_from_commit"], commit, head_blob, run))


# ---------------------------------------------------------------- the two writers ("Pilot 後定稿", decision 023 line 6)

def post_pilot_problems(project_dir: Path, layout, removed: set, *, methods, results_root: Path) -> list[str]:
    """Why plan and freeze cannot be written yet: 023 line 6 waits for Pilot collection, review, leakage audit and the
    LLM trial runs; §6 wants the freeze before the first held-out run group. Shared by both writers (read only)."""
    from collect.heldout import _run_groups, heldout_runs, pilot_problems, run_split
    from collect.pilot import withdrawn

    problems, gone = [], withdrawn(layout)  # a withdrawn Pilot incident is never audited (decision 025 revision 3)
    staging = layout.root / "staging"
    if staging.exists() and any(staging.iterdir()):
        problems.append(f"{staging} is not empty: a run or normalize is in progress or was left behind")
    try:
        if heldout_runs(layout):
            problems.append("held-out run groups already exist: the freeze comes before the first one (decision 023 §6)")
        problems += pilot_problems(layout, removed)
        for run, _ in _run_groups(layout):
            if run_split(run) == "pilot" and run.get("status") == "valid":
                problems += [f"Pilot incident {inc} has no leakage audit (decision 015)" for inc in run.get("incident_ids") or []
                             if inc not in gone and not layout.label_path(inc).with_name("leakage_audit.json").exists()]
    except ValueError as e:
        problems.append(str(e))
    problems += [f"{m} has no Pilot scores (results/pilot/{m}/scores.json): every method runs on the Pilot first "
                 "(decision 023 前置條件)" for m in methods if not (Path(results_root) / "pilot" / m / "scores.json").exists()]
    llm = _read(Path(project_dir) / "eval" / "llm_methods.json") or {}
    if llm.get("status") != "approved" or any(llm.get(k) is None for k in ("model", "model_version", "temperature")):
        problems.append("eval/llm_methods.json is not approved with model, model_version and temperature (NEXT A1: paid "
                        "LLM methods are deferred)")
    return problems


def write_heldout_plan(project_dir: Path, layout, amendments: dict, *, methods, results_root: Path,
                       run: Run | None = None) -> dict:
    """docs/heldout/plan.json (decision 023 §1), written once from the Pilot evidence and a person's amendments."""
    from collect.heldout import amendment_lists, build_heldout_plan, pilot_evidence, write_once

    project_dir, run = Path(project_dir), run or _run
    if (project_dir / PLAN_FILE).exists():
        raise FileExistsError(f"{PLAN_FILE} exists: the held-out plan is written once (decision 023 §1)")
    removed = {(r["flag"], r["variant"]) for r in amendment_lists(amendments)[1]}
    if problems := post_pilot_problems(project_dir, layout, removed, methods=methods, results_root=results_root):
        raise ValueError("held-out plan refused: " + "; ".join(problems))
    with_results = [m for m in methods if (Path(results_root) / "pilot" / m / "scores.json").exists()]
    plan = build_heldout_plan(pilot_evidence(layout), amendments,
                              decision_files=set(_tree_files(run, project_dir, "HEAD", DECISIONS_DIR)),
                              methods_with_results=with_results)
    sha = write_once(project_dir / PLAN_FILE, plan)
    return {"plan": PLAN_FILE.as_posix(), "sha256": sha, "faults": len(plan["entries"]), "amended": len(plan["amended"]),
            "removed": len(plan["removed"]), "next": "review and commit docs/heldout/plan.json, then `collect heldout-freeze`"}


def write_freeze(project_dir: Path, layout, pilot_revisions: dict, *, methods, results_root: Path, now: str,
                 run: Run | None = None) -> dict:
    """docs/heldout/slots.json and freeze.json (decision 023 §4, §6), written once on a clean checkout whose HEAD has the
    committed plan; frozen_from_commit = HEAD, so the next commit must add exactly these two files. Also refused without a
    passing soak of the lock being frozen and unless every LLM method's Pilot run used exactly the LLM settings being
    frozen (user decision 2026-10-10, decision 026 #31, #32); what was found is returned under "checked"."""
    from collect.heldout import build_heldout_plan, pilot_evidence, write_once

    project_dir = Path(project_dir)
    for rel in (SLOTS_FILE, FREEZE_FILE):
        if (project_dir / rel).exists():
            raise FileExistsError(f"{rel} exists: the slot list and the freeze record are written once (decision 023 §6)")
    observed = observe(project_dir, run=run or _run)
    problems = []
    if observed["dirty"] or observed["flagged"] or observed["ignored_code"]:
        problems.append("the checkout is not clean (status, assume-unchanged / skip-worktree flags, ignored code)")
    blob = observed["blobs"][PLAN_FILE.as_posix()]
    plan = observed["plan"]
    if plan is None or blob["head"] is None or blob["head"] != blob["disk"]:
        problems.append(f"{PLAN_FILE} must exist and be committed at HEAD before the freeze")
    if plan is None:
        raise ValueError("held-out freeze refused: " + "; ".join(problems))
    removed = {(r["flag"], r["variant"]) for r in plan.get("removed") or []}
    problems += post_pilot_problems(project_dir, layout, removed, methods=methods, results_root=results_root)
    again = {"amend": [{"flag": a["flag"], "variant": a["variant"], "field": a["field"], "value": a["heldout"],
                        "reason": a["reason"]} for a in plan.get("amended") or []],
             "remove": [{k: r[k] for k in ("flag", "variant", "basis", "reason", "decision")
                         if k != "decision" or r.get("decision") is not None} for r in plan.get("removed") or []]}
    try:
        rebuilt = build_heldout_plan(pilot_evidence(layout), again, decision_files=set(observed["decisions"]),
                                     methods_with_results=plan.get("methods_with_pilot_results") or [])
    except (ValueError, KeyError, TypeError) as e:
        problems.append(f"plan.json no longer rebuilds from the Pilot evidence: {e}")
    else:
        if rebuilt != plan:
            problems.append("plan.json is not the plan rebuilt from the Pilot evidence and its own amendments and removals")
    if observed["env_lock_sha256"] is None:
        problems.append("no env lock to freeze")
    policy = observed["policy"]
    if policy is None or policy.get("status") != "frozen":
        problems.append("the normalize policy is not frozen (decision 011 §4)")
    problems += pilot_revision_problems(pilot_revisions, set(observed["decisions"]), (policy or {}).get("version"))
    soak_problems, soak = _soak_evidence(layout, observed["env_lock_sha256"])
    llm_problems, run_shas = _pilot_llm_evidence(project_dir, results_root, methods)
    problems += soak_problems + llm_problems
    if problems:
        raise ValueError("held-out freeze refused: " + "; ".join(problems))
    faults = [[e["flag"], e["variant"]] for e in plan["entries"]]
    slots_doc = {"slots_version": 1, "decision": "023 §4", "master_seed": HELDOUT_MASTER_SEED, "k": HELDOUT_K,
                 "plan_sha256": observed["plan_sha256"], "faults": faults, "slots": heldout_slots(faults)}
    record = freeze_record(observed, slots_doc=slots_doc, pilot_revisions=pilot_revisions, now=now)
    slots_sha = write_once(project_dir / SLOTS_FILE, slots_doc)
    freeze_sha = write_once(project_dir / FREEZE_FILE, record)
    return {"slots": {"path": SLOTS_FILE.as_posix(), "sha256": slots_sha, "count": len(slots_doc["slots"])},
            "freeze": {"path": FREEZE_FILE.as_posix(), "sha256": freeze_sha, "frozen_from_commit": observed["head"]},
            "checked": {"soak_report": soak, "pilot_run_config_sha256": run_shas},
            "next": f"commit exactly these two files in one commit (git add {SLOTS_FILE} {FREEZE_FILE} && git commit), "
                    "then `collect status --set heldout`"}


def _soak_evidence(layout, lock_sha: str | None) -> tuple[list[str], dict | None]:
    """decision 026 #31 (user decision 2026-10-10, 「照建議」 item 7a; decision 028 「必須在 held-out freeze 之前」): a
    soak report that passed, tore down cleanly and ran on exactly the lock being frozen, by the collection preflight's
    own rule (collect.live.passing_soak). Not written into the record (its keys are fixed): the record pins the lock,
    so the soak found here stays the one of the frozen lock. Returns (problems, {path, sha256} of the report)."""
    if lock_sha is None:
        return [], None  # "no env lock to freeze" already
    from collect.live import passing_soak
    from env.lock import sha256_path

    found = passing_soak(Path(layout.root), lock_sha)
    if found is None:
        return [f"no passing soak of the env lock {lock_sha} under {Path(layout.root) / 'soak'} (a report with pass true, "
                "teardown.verify [] and this env_lock_sha256, the rule of the collection preflight): run "
                "`./tools/with-mac-lock uv run python -m env soak --minutes 30 --warmup-minutes 5` first "
                "(decision 028; 026 #31)"], None
    report = found / "report.json"
    return [], {"path": report.relative_to(layout.root).as_posix(), "sha256": sha256_path(report)}


def _pilot_llm_evidence(project_dir: Path, results_root: Path, methods) -> tuple[list[str], dict]:
    """decision 026 #32 (user decision 2026-10-10, item 7b): eval.runner.pilot_llm_problems with the llm_methods.json
    of the checkout being frozen (the file the record pins)."""
    from eval.runner import pilot_llm_problems

    return pilot_llm_problems(results_root, _read(Path(project_dir) / "eval" / "llm_methods.json"), methods)
