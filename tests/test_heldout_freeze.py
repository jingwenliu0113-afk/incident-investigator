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
], ids=["dirty", "flagged", "ignored", "ancestor", "code", "decision", "readme", "deleted", "two-commits", "parent",
        "uncommitted", "plan-blob", "plan-sha", "decision-blob", "env-lock", "order", "k", "seed", "013", "011", "019",
        "model-version", "llm"])
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


# ---------------------------------------------------------------- the two writers (after the Pilot, blocked by A1 today)

METHODS = ["agent", "stat-anomaly"]
NOW = "2026-10-20T00:00:00Z"


def project(tmp_path, llm=None):
    """A committed tiny project whose data/external (gitignored) holds a complete, reviewed, audited Pilot and Pilot
    scores of every method."""
    from collect.layout import DataLayout
    from heldout_fixtures import complete_pilot

    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    write(repo, ".gitignore", "data/external/\n")
    write(repo, "NEXT.md", "# NEXT\n")
    write(repo, D011, "011\n")
    write(repo, D013, "013\n")
    write(repo, "env/otel-demo.lock.json", json.dumps({"lock_version": 1}, indent=2) + "\n")
    write(repo, "collect/canonical_policy.v1.json", json.dumps({"version": 1, "status": "frozen"}))
    write(repo, "eval/llm_methods.json", json.dumps(llm if llm is not None else
                                                     {k: LLM[k] for k in ("status", "model", "model_version", "temperature")}))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "project")
    layout = DataLayout(repo / "data/external")
    complete_pilot(layout)
    for m in METHODS:
        write(layout.root, f"results/pilot/{m}/scores.json", "{}")
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
    assert problems == [] and record["llm"]["model_version"] == LLM["model_version"]
    assert freeze.freeze_sha256(repo) == out["freeze"]["sha256"]


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
