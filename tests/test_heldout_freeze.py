"""The held-out freeze record and its check (decision 023 §6): written once before the first held-out run group; after it,
deny by default: only NEXT.md, the slot list, the freeze record and new decision files may differ from the frozen commit."""

import copy
import json
import subprocess

import pytest

from collect import freeze
from collect.freeze import (ALLOWED_AFTER_FREEZE, PILOT_REVISABLE, check_freeze, commit_problems, freeze_problems,
                            freeze_record, is_ancestor, observe, pilot_revision_problems)
from collect.heldout import FREEZE_FILE, PLAN_FILE, SLOTS_FILE, doc_sha256, heldout_slots
from collect.pilot import PILOT
from heldout_fixtures import LOCK

S, F, P = SLOTS_FILE.as_posix(), FREEZE_FILE.as_posix(), PLAN_FILE.as_posix()
D013 = "docs/decisions/013-prediction-format-and-layered-scoring.md"
D011 = "docs/decisions/011-canonical-telemetry-schema.md"
REVISIONS = {n: {"status": "waived"} for n in PILOT_REVISABLE} | {"013": {"status": "used", "decision": D013}}
BASE, FREEZE_COMMIT, HEAD = "a" * 40, "b" * 40, "c" * 40
PLAN = {"entries": [dict(e) for e in PILOT[:3]]}
FAULTS = [[e["flag"], e["variant"]] for e in PLAN["entries"]]
LLM = {"status": "approved", "model": "m", "model_version": "m-2026-01-01", "temperature": 0, "config_sha256": "sha256:l"}
POLICY = {"version": 1, "sha256": "sha256:pol", "status": "frozen"}


def slots_doc(k=5, seed=20261009, slots=None):
    return {"slots_version": 1, "decision": "023 §4", "master_seed": seed, "k": k, "plan_sha256": "sha256:plan",
            "faults": FAULTS, "slots": slots if slots is not None else heldout_slots(FAULTS, k=k, seed=seed)}


def good(slots=None, policy=POLICY, llm=LLM, revisions=REVISIONS):
    """A consistent (record, observed) pair: the freeze commit on top of BASE, nothing else changed."""
    slots = slots or slots_doc()
    decisions = {D011: "1" * 40, D013: "3" * 40}
    observed = {"head": HEAD, "tree": "e" * 40, "dirty": False, "flagged": [], "ignored_code": [], "env_lock_sha256": LOCK,
                "policy": dict(policy), "llm": dict(llm), "plan": PLAN, "plan_sha256": "sha256:plan", "slots": slots,
                "slots_sha256": doc_sha256(slots), "decisions": dict(decisions),
                "blobs": {p: {"head": "9" * 40, "disk": "9" * 40} for p in (P, S, F)},
                "base": BASE, "base_tree": "d" * 40, "base_decisions": dict(decisions),
                "changes": [["A", S], ["A", F]], "ancestor": True,
                "log": {S: [[FREEZE_COMMIT, [BASE]]], F: [[FREEZE_COMMIT, [BASE]]]}}
    at_base = {**observed, "head": BASE, "tree": "d" * 40}
    record = freeze_record(at_base, slots_doc=slots, pilot_revisions=copy.deepcopy(revisions), now="2026-10-20T00:00:00Z")
    return record, observed


def test_no_record_is_one_problem_and_runs_no_git(tmp_path):
    def run(cmd):
        raise AssertionError(f"git ran: {cmd}")

    assert check_freeze(tmp_path, run=run) == (None, [freeze.NO_FREEZE])
    (tmp_path / FREEZE_FILE).parent.mkdir(parents=True)
    (tmp_path / FREEZE_FILE).write_text("{not json")
    record, problems = check_freeze(tmp_path, run=run)
    assert record is None and len(problems) == 1 and "unreadable" in problems[0]


def test_a_consistent_record_has_no_problem_and_names_the_commit_before_it():
    record, observed = good()
    assert freeze_problems(record, observed) == []
    assert record["frozen_from_commit"] == BASE and record["k"] == 5 and record["master_seed"] == 20261009
    assert record["slots"] == {"path": S, "sha256": doc_sha256(slots_doc()), "count": 15}
    assert record["plan"] == {"path": P, "sha256": "sha256:plan", "faults": 3}
    assert list(record) == ["freeze_version", "decision", "frozen_at", "frozen_from_commit", "frozen_tree", "decisions",
                            "env_lock_sha256", "policy", "llm", "pilot_revisions", "plan", "k", "master_seed", "slots"]


def edit(change):
    def apply():
        record, observed = good()
        change(record, observed)
        return record, observed
    return apply


def rebuilt(**kw):
    def apply():
        slots = kw.pop("slots", None)
        return good(slots=slots, **kw)
    return apply


SWAPPED = slots_doc()
SWAPPED["slots"][0], SWAPPED["slots"][1] = ({**SWAPPED["slots"][1], "slot": "H01"}, {**SWAPPED["slots"][0], "slot": "H02"})


@pytest.mark.parametrize("make, needle", [
    (edit(lambda r, o: o.update(dirty=True)), "clean"),
    (edit(lambda r, o: o.update(flagged=["collect/heldout.py"])), "collect/heldout.py"),
    (edit(lambda r, o: o.update(ignored_code=["eval/extra.py"])), "eval/extra.py"),
    (edit(lambda r, o: o.update(ancestor=False)), "ancestor"),
    (edit(lambda r, o: o["changes"].append(["M", "collect/x.py"])), "collect/x.py"),
    (edit(lambda r, o: o["changes"].append(["M", D013])), D013),
    (edit(lambda r, o: o["changes"].append(["M", "README.md"])), "README.md"),
    (edit(lambda r, o: o["changes"].append(["D", "docs/decisions/099-x.md"])), "099-x"),
    (edit(lambda r, o: o["log"][F].append(["f" * 40, [FREEZE_COMMIT]])), "2 commits"),
    (edit(lambda r, o: o["log"].update({S: [["f" * 40, ["0" * 40]]], F: [["f" * 40, ["0" * 40]]]})), "first parent"),
    (edit(lambda r, o: o["blobs"][S].update(head=None)), "not committed"),
    (edit(lambda r, o: o["blobs"][P].update(disk="8" * 40)), P),
    (edit(lambda r, o: o.update(plan_sha256="sha256:other")), "plan"),
    (edit(lambda r, o: o["base_decisions"].update({D013: "4" * 40})), "decision"),
    (edit(lambda r, o: o.update(env_lock_sha256="sha256:other")), "env lock"),
    (rebuilt(slots=SWAPPED), "regenerated"),
    (rebuilt(slots=slots_doc(k=4)), "K"),
    (rebuilt(slots=slots_doc(seed=1)), "seed"),
    (rebuilt(revisions=REVISIONS | {"013": {"status": "waived"}}), "013"),
    (rebuilt(policy={**POLICY, "version": 2}), "011"),
    (rebuilt(revisions=REVISIONS | {"019": {"status": "used", "decision": "docs/decisions/099-missing.md"}}), "019"),
    (rebuilt(llm={**LLM, "model_version": None}), "model_version"),
    (rebuilt(llm={**LLM, "status": "proposed"}), "approved"),
    (edit(lambda r, o: o["log"].update({F: [["f" * 40, [FREEZE_COMMIT]]]})), "one commit"),  # slots and freeze apart
    (edit(lambda r, o: o["policy"].update(sha256="sha256:other")), "policy"),
    (edit(lambda r, o: o["llm"].update(config_sha256="sha256:other")), "llm_methods.json"),
    (edit(lambda r, o: o.update(slots_sha256="sha256:other")), "slot list the record names"),
    (edit(lambda r, o: o.update(base_tree="0" * 40)), "frozen_tree"),
], ids=["dirty", "flagged", "ignored", "ancestor", "code", "decision", "readme", "deleted", "two-commits", "parent",
        "uncommitted", "plan-blob", "plan-sha", "decision-blob", "env-lock", "order", "k", "seed", "013", "011", "019",
        "model-version", "llm", "slots-and-freeze-apart", "policy-sha", "llm-drift", "slots-sha", "frozen-tree"])
def test_each_departure_from_the_frozen_state_is_one_named_problem(make, needle):
    record, observed = make()
    problems = freeze_problems(record, observed)
    assert len(problems) == 1 and needle in problems[0], problems


@pytest.mark.parametrize("change", [["M", "NEXT.md"], ["A", "docs/decisions/027-heldout-collection-notes.md"]])
def test_next_and_new_decision_files_may_change_after_the_freeze(change):
    record, observed = good()
    observed["changes"].append(change)
    assert freeze_problems(record, observed) == []
    assert ("M", "NEXT.md") in ALLOWED_AFTER_FREEZE


def test_pilot_revision_declarations():
    paths = {D011, D013}
    assert pilot_revision_problems(REVISIONS, paths, 1) == []
    assert pilot_revision_problems(REVISIONS | {"011": {"status": "used", "decision": D011}}, paths, 2) == []
    assert any("011" in p for p in pilot_revision_problems(REVISIONS, paths, 2))  # v2 is 011's one revision
    assert any("011" in p for p in pilot_revision_problems(REVISIONS | {"011": {"status": "used", "decision": D011}}, paths, 1))
    assert any("017" in p for p in pilot_revision_problems({k: v for k, v in REVISIONS.items() if k != "017"}, paths, 1))
    assert any("024" in p for p in pilot_revision_problems(REVISIONS | {"024": {"status": "waived"}}, paths, 1))
    assert any("015" in p for p in pilot_revision_problems(REVISIONS | {"015": {"status": "maybe"}}, paths, 1))
    # user decision 2026-10-10 (decision 014 addendum): the statistical baseline's one Pilot revision is waived, v2 is final
    d014 = "docs/decisions/014-time-framing-and-statistical-baseline.md"
    used_014 = REVISIONS | {"014": {"status": "used", "decision": d014}}
    assert [p for p in pilot_revision_problems(used_014, paths | {d014}, 1) if "014" in p] == [
        "014 must be declared waived: the user waived the statistical baseline's one Pilot revision on 2026-10-10 "
        "(decision 014 addendum; stat-anomaly v2 is final)"]


class Fail:
    def __init__(self, code):
        self.code, self.calls = code, []

    def __call__(self, cmd):
        self.calls.append(cmd)
        raise subprocess.CalledProcessError(self.code, cmd)


def test_is_ancestor_reads_exit_1_as_no_and_anything_else_as_a_git_failure(tmp_path):
    assert is_ancestor(tmp_path, BASE, HEAD, run=Fail(1)) is False
    with pytest.raises(subprocess.CalledProcessError):
        is_ancestor(tmp_path, BASE, HEAD, run=Fail(128))
    assert is_ancestor(tmp_path, BASE, HEAD, run=lambda cmd: "") is True


# ---------------------------------------------------------------- one real repository

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout.strip()


def write(repo, rel, text):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def frozen_repo(tmp_path):
    """A tiny project: code, decisions, lock, policy, approved llm config and plan.json committed; then the freeze commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo, "NEXT.md", "# NEXT\n")
    write(repo, "collect/x.py", "X = 1\n")
    write(repo, D011, "011\n")
    write(repo, D013, "013\n")
    write(repo, "docs/decisions/README.md", "index\n")
    write(repo, "env/otel-demo.lock.json", json.dumps({"lock_version": 1}, indent=2) + "\n")
    write(repo, "collect/canonical_policy.v1.json", json.dumps({"version": 1, "status": "frozen"}))
    write(repo, "eval/llm_methods.json", json.dumps({k: LLM[k] for k in ("status", "model", "model_version", "temperature")}))
    write(repo, P, json.dumps(PLAN, indent=2) + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "plan")
    base = git(repo, "rev-parse", "HEAD")
    observed = observe(repo)
    assert observed["head"] == base and observed["dirty"] is False and set(observed["decisions"]) == {D011, D013}
    slots = {**slots_doc(), "plan_sha256": observed["plan_sha256"]}
    record = freeze_record(observed, slots_doc=slots, pilot_revisions=REVISIONS, now="2026-10-20T00:00:00Z")
    write(repo, S, json.dumps(slots, indent=2) + "\n")
    write(repo, F, json.dumps(record, indent=2) + "\n")
    git(repo, "add", S, F)
    git(repo, "commit", "-q", "-m", "freeze")
    return repo, base


def test_a_real_freeze_commit_passes_and_only_allowed_changes_keep_it_passing(tmp_path):
    repo, base = frozen_repo(tmp_path)
    record, problems = check_freeze(repo)
    assert problems == []
    head = git(repo, "rev-parse", "HEAD")
    assert record["frozen_from_commit"] == base == git(repo, "rev-parse", "HEAD^") and head not in json.dumps(record)
    assert commit_problems(repo, record, head) == []
    assert commit_problems(repo, record, base) != []  # before the freeze record existed
    orphan = git(repo, "commit-tree", "HEAD^{tree}", "-m", "the same files without the frozen history")
    assert commit_problems(repo, record, orphan) == [f"commit {orphan[:12]} does not descend from the frozen commit"]

    write(repo, "NEXT.md", "# NEXT\n- held-out: H01 filled\n")
    git(repo, "commit", "-q", "-am", "next")
    assert check_freeze(repo)[1] == []
    assert commit_problems(repo, record, git(repo, "rev-parse", "HEAD")) == []

    write(repo, "notes.txt", "scratch\n")  # untracked
    assert any("clean" in p for p in check_freeze(repo)[1])
    (repo / "notes.txt").unlink()

    write(repo, "collect/x.py", "X = 2\n")
    git(repo, "commit", "-q", "-am", "code after the freeze")
    problems = check_freeze(repo)[1]
    assert problems and all("collect/x.py" in p for p in problems)
    assert any("collect/x.py" in p for p in commit_problems(repo, record, git(repo, "rev-parse", "HEAD")))


def hide_an_edit(repo, flag):
    git(repo, "update-index", flag, "collect/x.py")
    write(repo, "collect/x.py", "X = 2\n")


def ignored_code(repo):
    with (repo / ".git/info/exclude").open("a") as f:
        f.write("extra.py\n")
    write(repo, "eval/extra.py", "Y = 1\n")


@pytest.mark.parametrize("hide, needle", [
    (lambda repo: hide_an_edit(repo, "--assume-unchanged"), "collect/x.py"),
    (lambda repo: hide_an_edit(repo, "--skip-worktree"), "collect/x.py"),
    (ignored_code, "eval/extra.py"),
], ids=["assume-unchanged", "skip-worktree", "ignored"])
def test_code_that_git_status_does_not_show_still_fails_the_check_of_a_real_checkout(tmp_path, hide, needle):
    repo, _ = frozen_repo(tmp_path)
    hide(repo)
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""  # git itself shows nothing
    problems = check_freeze(repo)[1]
    assert len(problems) == 1 and needle in problems[0], problems


# ---------------------------------------------------------------- the two writers (after the Pilot and its LLM runs)

METHODS = ["agent", "stat-anomaly"]
NOW = "2026-10-20T00:00:00Z"
PROJECT_LOCK = {"lock_version": 1}
SOAK = "soak/20261010T053643Z/report.json"


def pilot_run_config(config, method):
    """The run_config.json `eval run --method <m> --set pilot` writes with `config` (decision 024 / 029)."""
    from agent.ollama import pinned_record
    from eval.runner import SCOPES, method_budgets

    return {"method": method, "split": "pilot", "model": config["model"], "budgets": method_budgets(method, config),
            "scope": SCOPES[method], "llm": pinned_record(config)}


def pilot_llm_results(layout, method, config, incidents=("INC-002",)):
    """What `eval run --method <m> --set pilot` run to the end and `eval score` leave: run_config.json, one power.jsonl
    line per incident naming that run_config.json (review 2026-10-10, decision 026 #32) and scores.json from that run."""
    from env.lock import sha256_path

    run_config = pilot_run_config(config, method)
    write(layout.root, f"results/pilot/{method}/run_config.json", json.dumps(run_config, indent=2) + "\n")
    sha = sha256_path(layout.root / f"results/pilot/{method}/run_config.json")
    write(layout.root, f"results/pilot/{method}/power.jsonl", "".join(
        json.dumps({"incident_id": inc, "attempt": None, "run_config_sha256": sha, "formal": True}) + "\n" for inc in incidents))
    write(layout.root, f"results/pilot/{method}/scores.json",
          json.dumps({"run_config": run_config, "incidents": [{"incident_id": inc} for inc in incidents]}))
    return run_config


def soak_report(layout, *, lock=None, passed=True, verify=(), rel=SOAK):
    from env.lock import lock_sha256

    write(layout.root, rel, json.dumps({"pass": passed, "env_lock_sha256": lock or lock_sha256(PROJECT_LOCK),
                                        "teardown": {"verify": list(verify)}}))


def project(tmp_path, llm=None):
    """A committed tiny project with the approved local model (decision 029) whose data/external (gitignored) holds a
    complete, reviewed, audited Pilot, Pilot scores of every method, the agent's Pilot run with exactly that model and
    a passing soak of the project's lock (decision 026 #31, #32)."""
    from collect.layout import DataLayout
    from heldout_fixtures import complete_pilot
    from ollama_fixtures import approved_config

    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    write(repo, ".gitignore", "data/external/\n")
    write(repo, "NEXT.md", "# NEXT\n")
    write(repo, D011, "011\n")
    write(repo, D013, "013\n")
    write(repo, "env/otel-demo.lock.json", json.dumps(PROJECT_LOCK, indent=2) + "\n")
    write(repo, "collect/canonical_policy.v1.json", json.dumps({"version": 1, "status": "frozen"}))
    config = llm if llm is not None else approved_config()
    write(repo, "eval/llm_methods.json", json.dumps(config))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "project")
    layout = DataLayout(repo / "data/external")
    complete_pilot(layout)
    for m in METHODS:
        write(layout.root, f"results/pilot/{m}/scores.json", "{}")
    pilot_llm_results(layout, "agent", approved_config())
    soak_report(layout)
    return repo, layout


def plan_it(repo, layout, amendments=None):
    return freeze.write_heldout_plan(repo, layout, amendments or {"amend": [], "remove": []}, methods=METHODS,
                                     results_root=layout.root / "results")


def freeze_it(repo, layout, revisions=REVISIONS):
    return freeze.write_freeze(repo, layout, revisions, methods=METHODS, results_root=layout.root / "results", now=NOW)


def test_plan_then_freeze_then_one_commit_passes_the_check_and_each_is_written_once(tmp_path):
    repo, layout = project(tmp_path)
    out = plan_it(repo, layout)
    assert out["faults"] == 10 and json.loads((repo / P).read_text())["entries"] == [dict(e) for e in PILOT]
    with pytest.raises(FileExistsError):
        plan_it(repo, layout)
    git(repo, "add", P)
    git(repo, "commit", "-q", "-m", "held-out plan")
    out = freeze_it(repo, layout)
    assert out["slots"]["count"] == 50 and "one commit" in out["next"]
    with pytest.raises(FileExistsError):
        freeze_it(repo, layout)
    git(repo, "add", S, F)
    git(repo, "commit", "-q", "-m", "held-out freeze")
    record, problems = check_freeze(repo)
    from ollama_fixtures import DIGEST

    assert problems == [] and record["llm"]["model_version"] == DIGEST
    assert freeze.freeze_sha256(repo) == out["freeze"]["sha256"]
    assert list(record) == list(freeze.RECORD_KEYS)  # the record keeps its shape: the two checks are refusals (026 #31, #32)
    from env.lock import sha256_path

    assert out["checked"] == {  # printed by `collect heldout-freeze`, for the freeze commit's message or NEXT
        "soak_report": {"path": SOAK, "sha256": sha256_path(layout.root / SOAK)},
        "pilot_run_config_sha256": {"agent": sha256_path(layout.root / "results/pilot/agent/run_config.json")}}


def no_scores(repo, layout):
    (layout.root / "results/pilot/agent/scores.json").unlink()


def unreviewed(repo, layout):
    layout.label_path("INC-003").with_name("label_review.json").unlink()


def unaudited(repo, layout):
    layout.label_path("INC-004").with_name("leakage_audit.json").unlink()


def heldout_run(repo, layout):
    from heldout_fixtures import FREEZE_SHA, write_run

    write_run(layout, "RG-050", "paymentFailure", "100%", "invalid", split="heldout", slot="H01", freeze_sha=FREEZE_SHA)


def staging(repo, layout):
    (layout.root / "staging" / "RG-051").mkdir(parents=True)


def llm_proposed(repo, layout):
    write(repo, "eval/llm_methods.json", json.dumps({"status": "proposed", "model": None}))
    git(repo, "commit", "-q", "-am", "llm")


def llm_no_version(repo, layout):
    write(repo, "eval/llm_methods.json", json.dumps({**{k: LLM[k] for k in LLM_FIELDS_}, "model_version": None}))
    git(repo, "commit", "-q", "-am", "llm")


LLM_FIELDS_ = ("status", "model", "model_version", "temperature")


@pytest.mark.parametrize("breaks, needle", [
    (no_scores, "agent"), (unreviewed, "INC-003"), (unaudited, "INC-004"), (heldout_run, "held-out run groups"),
    (staging, "staging"), (llm_proposed, "approved"), (llm_no_version, "approved")],
    ids=["no-scores", "unreviewed", "unaudited", "heldout-run", "staging", "llm-proposed", "llm-no-version"])
def test_both_writers_wait_for_the_whole_pilot_and_the_llm_trial_runs(tmp_path, breaks, needle):
    # 023 line 6: "Pilot 後定稿" waits for Pilot collection, review, leakage audit and the LLM trial runs (NEXT A1)
    repo, layout = project(tmp_path)
    breaks(repo, layout)
    with pytest.raises(ValueError, match=needle):
        plan_it(repo, layout)
    assert not (repo / P).exists()

    repo, layout = project(tmp_path / "f")
    plan_it(repo, layout)
    git(repo, "add", P)
    git(repo, "commit", "-q", "-m", "held-out plan")
    breaks(repo, layout)
    with pytest.raises(ValueError, match=needle):
        freeze_it(repo, layout)
    assert not (repo / S).exists() and not (repo / F).exists()


def test_the_freeze_needs_declared_revisions_a_committed_plan_and_one_that_still_rebuilds(tmp_path):
    repo, layout = project(tmp_path)
    plan_it(repo, layout)
    with pytest.raises(ValueError, match="committed"):
        freeze_it(repo, layout)  # plan.json is not committed yet
    git(repo, "add", P)
    git(repo, "commit", "-q", "-m", "held-out plan")
    with pytest.raises(ValueError, match="013"):
        freeze_it(repo, layout, {k: v for k, v in REVISIONS.items() if k != "013"})
    doc = json.loads((repo / P).read_text())
    doc["entries"][0]["affected"] = ["payment"]  # hand-edited after it was written
    write(repo, P, json.dumps(doc, indent=2) + "\n")
    git(repo, "commit", "-q", "-am", "edit")
    with pytest.raises(ValueError, match="rebuil"):
        freeze_it(repo, layout)
    assert not (repo / S).exists() and not (repo / F).exists()


def untracked(repo):
    write(repo, "notes.txt", "scratch\n")


def assume_unchanged(repo):
    git(repo, "update-index", "--assume-unchanged", "NEXT.md")
    write(repo, "NEXT.md", "# NEXT\nedited, hidden from git status\n")


def ignored(repo):
    with (repo / ".git/info/exclude").open("a") as f:
        f.write("extra.py\n")
    write(repo, "eval/extra.py", "Y = 1\n")


@pytest.mark.parametrize("dirt", [untracked, assume_unchanged, ignored], ids=["untracked", "assume-unchanged", "ignored"])
def test_the_freeze_is_written_only_from_a_clean_checkout(tmp_path, dirt):
    repo, layout = project(tmp_path)
    plan_it(repo, layout)
    git(repo, "add", P)
    git(repo, "commit", "-q", "-m", "held-out plan")
    dirt(repo)
    with pytest.raises(ValueError) as e:
        freeze_it(repo, layout)
    assert str(e.value) == ("held-out freeze refused: the checkout is not clean (status, assume-unchanged / skip-worktree "
                            "flags, ignored code)")
    assert not (repo / S).exists() and not (repo / F).exists()


def test_a_withdrawn_pilot_run_group_needs_no_review_or_audit_before_the_plan(tmp_path):
    # decision 025 revision 3: a withdrawn Pilot incident is never audited (incidents_in skips it) nor reviewed
    from collect.pilot import withdraw
    from heldout_fixtures import write_run

    repo, layout = project(tmp_path)
    write_run(layout, "RG-020", "paymentFailure", "100%", inc="INC-020")
    with pytest.raises(ValueError, match="INC-020"):
        plan_it(repo, layout)
    withdraw(layout, "RG-020", reason="collected in the automatic power mode", decided_by="user", now=NOW)
    assert plan_it(repo, layout)["faults"] == 10


# ---------------------------------------------------------------- user decision 2026-10-10 「照建議」 item 7 (026 revision 3)

def no_soak(layout):
    import shutil

    shutil.rmtree(layout.root / "soak")


def run_config_edit(change):
    def apply(layout):
        path = layout.root / "results/pilot/agent/run_config.json"
        doc = json.loads(path.read_text())
        change(doc)
        path.write_text(json.dumps(doc, indent=2) + "\n")
        scores = layout.root / "results/pilot/agent/scores.json"
        scores.write_text(json.dumps({**json.loads(scores.read_text()), "run_config": doc}))  # only the settings differ
    return apply


@pytest.mark.parametrize("breaks", [
    no_soak,
    lambda layout: soak_report(layout, lock="sha256:" + "0" * 64),  # the soak of the lock before (e.g. soak #5)
    lambda layout: soak_report(layout, passed=False),
    lambda layout: soak_report(layout, verify=["ii-otel-demo containers left"]),
], ids=["no-soak", "other-lock", "failed", "teardown"])
def test_the_freeze_needs_a_passing_soak_of_the_lock_it_freezes(tmp_path, breaks):
    # decision 026 #31 (user decision 2026-10-10, item 7a; decision 028 「必須在 held-out freeze 之前」): the rule of the
    # collection preflight, collect.live.passing_soak with the current lock
    repo, layout = project(tmp_path)
    if breaks is not no_soak:
        no_soak(layout)
    breaks(layout)
    plan_it(repo, layout)  # the plan does not need it
    git(repo, "add", P)
    git(repo, "commit", "-q", "-m", "held-out plan")
    with pytest.raises(ValueError, match="no passing soak of the env lock sha256:[0-9a-f]{64}.*026 #31"):
        freeze_it(repo, layout)
    assert not (repo / S).exists() and not (repo / F).exists()


def llm_config_changed(repo, layout):
    from ollama_fixtures import approved_config

    write(repo, "eval/llm_methods.json", json.dumps(approved_config(num_ctx=262_144)))  # after the Pilot ran
    git(repo, "commit", "-q", "-am", "llm")


def stale_scores(repo, layout):
    path = layout.root / "results/pilot/agent/scores.json"
    doc = json.loads(path.read_text())
    path.write_text(json.dumps({**doc, "run_config": {**doc["run_config"], "model": "earlier"}}))


def earlier_run_line(repo, layout):
    """A scored prediction whose latest power.jsonl line names another run_config.json: a run with these settings stopped
    before this incident and left the prediction of an earlier run (review 2026-10-10)."""
    path = layout.root / "results/pilot/agent/power.jsonl"
    line = json.loads(path.read_text())
    path.write_text(json.dumps({**line, "run_config_sha256": "sha256:" + "0" * 64}) + "\n")


def scores_without_incidents(repo, layout):
    path = layout.root / "results/pilot/agent/scores.json"
    path.write_text(json.dumps({"run_config": json.loads(path.read_text())["run_config"]}))


@pytest.mark.parametrize("breaks, needle", [
    (lambda repo, layout: (layout.root / "results/pilot/agent/run_config.json").unlink(), "agent has no Pilot run_config"),
    (lambda repo, layout: run_config_edit(lambda d: d["llm"].update(num_ctx=262_144))(layout), "agent.*llm"),
    (lambda repo, layout: run_config_edit(lambda d: d["llm"].update(model_version="sha256:" + "cd" * 32))(layout), "llm"),
    (lambda repo, layout: run_config_edit(lambda d: d["llm"].update(ollama_version="0.34.0"))(layout), "llm"),
    (lambda repo, layout: run_config_edit(lambda d: d["llm"].update(think=True))(layout), "llm"),
    (lambda repo, layout: run_config_edit(lambda d: d["llm"].update(num_predict=4096))(layout), "llm"),
    (lambda repo, layout: run_config_edit(lambda d: d["llm"].update(seed=7))(layout), "llm"),
    (lambda repo, layout: run_config_edit(lambda d: d["llm"].update(temperature=0.6))(layout), "llm"),
    (lambda repo, layout: run_config_edit(lambda d: d.pop("llm"))(layout), "llm"),
    (lambda repo, layout: run_config_edit(lambda d: d["budgets"].update(turns=20))(layout), "budgets"),
    (lambda repo, layout: run_config_edit(lambda d: d.update(model="other:1b"))(layout), "model"),
    (lambda repo, layout: run_config_edit(lambda d: d.update(split="heldout"))(layout), "split"),
    (llm_config_changed, "agent.*llm"),
    (stale_scores, "scores.json"),
    (earlier_run_line, "agent: its Pilot scores include predictions .*INC-002.*to the end"),
    (lambda repo, layout: (layout.root / "results/pilot/agent/power.jsonl").unlink(), "agent: .*INC-002.*to the end"),
    (scores_without_incidents, "agent: .*cannot be compared"),
], ids=["no-run-config", "num-ctx", "digest", "ollama-version", "think", "num-predict", "seed", "temperature", "no-llm",
        "budgets", "model", "split", "config-changed-after-the-pilot", "stale-scores", "earlier-run-prediction",
        "no-power-line", "scores-without-incidents"])
def test_the_freeze_needs_pilot_llm_runs_with_exactly_the_settings_it_freezes(tmp_path, breaks, needle):
    # decision 026 #32 (user decision 2026-10-10, item 7b): every LLM method's Pilot run_config.json records the model,
    # runtime (provider, model, digest, Ollama version, num_ctx, num_predict, temperature, seed, think) and budgets of the
    # llm_methods.json being frozen, and its Pilot scores were computed from that run
    repo, layout = project(tmp_path)
    plan_it(repo, layout)
    git(repo, "add", P)
    git(repo, "commit", "-q", "-m", "held-out plan")
    breaks(repo, layout)
    with pytest.raises(ValueError, match=needle) as e:
        freeze_it(repo, layout)
    assert "026 #32" in str(e.value)
    assert not (repo / S).exists() and not (repo / F).exists()


def test_only_llm_methods_need_a_pilot_run_config(tmp_path):
    repo, layout = project(tmp_path)
    assert not (layout.root / "results/pilot/stat-anomaly/run_config.json").exists()  # a result from before decision 024
    plan_it(repo, layout)
    git(repo, "add", P)
    git(repo, "commit", "-q", "-m", "held-out plan")
    assert freeze_it(repo, layout)["checked"]["pilot_run_config_sha256"].keys() == {"agent"}
