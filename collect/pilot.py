"""The pre-registered fault list of each set and the a priori (catalog) label of each fault (decisions 010, 016).

Written before any of these faults is collected: a run group of a set must be one of its entries, and its catalog label
is taken from here, never typed after seeing the data. Review against the frozen snapshot writes catalog+review
separately (decision 006 §7) and records every difference from these entries. Ground-truth content: not agent-readable
(methods read only the snapshot, decision 015 §6).
"""

from __future__ import annotations

import json

_EDGE = ["frontend", "frontend-proxy"]

# decision 016 table; the first entry is decision 010's incident
PILOT: tuple[dict, ...] = (
    {"flag": "paymentFailure", "variant": "100%", "origin": "payment",
     "affected": ["payment", "checkout", *_EDGE], "symptom_kinds": ["errors"],
     "description": "orders fail: failed to charge card", "notes": None},
    {"flag": "productCatalogFailure", "variant": "on", "origin": "product-catalog",
     "affected": ["product-catalog", "checkout", *_EDGE], "symptom_kinds": ["errors"],
     "description": "one product's page, recommendations that include it and orders containing it fail",
     "notes": "recommendation only lists products and is not affected (decision 010 rule 3)"},
    {"flag": "paymentUnreachable", "variant": "on", "origin": "checkout",
     "affected": ["checkout", *_EDGE], "symptom_kinds": ["errors"],
     "description": "every order fails: the payment dependency cannot be reached",
     "notes": "checkout dials a wrong payment address (decision 016 origin rule); payment is healthy and only "
              "stops receiving charges, so it is not affected; shipping, email, kafka consumers get less traffic"},
    {"flag": "cartFailure", "variant": "100%", "origin": "cart",
     "affected": ["cart", "checkout"], "symptom_kinds": ["none"],
     "description": "orders still succeed; carts are not emptied after an order",
     "notes": "cart's own second store points at a bad host; valkey-cart is healthy. The time a failed EmptyCart "
              "takes is not known a priori: if it is seconds or more, checkout and the edge slow down or time out, "
              "and review records it (decision 016)"},
    {"flag": "intlShippingSlowdown", "variant": "10sec", "origin": "shipping",
     "affected": ["shipping", "checkout", *_EDGE], "symptom_kinds": ["latency"],
     "description": "orders shipped outside the US take about 10 s longer",
     "notes": "only Locust orders to the one non-US address are slowed: about 3 in 10 minutes (decision 016 "
              "exercised rule)"},
    {"flag": "productCatalogLockContention", "variant": "on", "origin": "product-catalog",
     "affected": ["product-catalog", "recommendation", "checkout", *_EDGE], "symptom_kinds": ["latency", "errors"],
     "description": "product pages, recommendations and orders hang behind a table lock; some time out",
     "notes": "product-catalog's own code holds the lock; astronomy-db's connection and rollback counts change but "
              "it shows no errors or latency of its own (decision 016 rule 3 clarification)"},
    {"flag": "adHighCpu", "variant": "on", "origin": "ad",
     "affected": ["ad"], "symptom_kinds": ["none"],
     "description": "no visible change for users",
     "notes": "busy-loop threads in ad; with the machine's spare CPU the ads call is not expected to slow down"},
    {"flag": "adManualGc", "variant": "on", "origin": "ad",
     "affected": ["ad", *_EDGE], "symptom_kinds": ["latency"],
     "description": "the ads request is slow",
     "notes": "repeated full collections on every ads call; heap pressure may outlast the fault"},
    {"flag": "emailMemoryLeak", "variant": "1000x", "origin": "email",
     "affected": ["email", "checkout"], "symptom_kinds": ["none"],
     "description": "orders still succeed",
     "notes": "email memory grows about 2 MB per message to an OOM restart (about 6-8 minutes in); the confirmation "
              "send that hits the restart fails in checkout, which does not fail the order"},
    {"flag": "recommendationCacheFailure", "variant": "on", "origin": "recommendation",
     "affected": ["recommendation", *_EDGE], "symptom_kinds": ["latency", "errors"],
     "description": "recommendations slow down and fail while the service restarts",
     "notes": "the cache list grows on every miss until OOM restarts (a few in 10 minutes); memory is not freed "
              "when the fault ends"},
)

PLANS: dict[str, tuple[dict, ...]] = {"pilot": PILOT}


def planned(split: str, flag: str, variant: str, *, project_dir=None) -> dict | None:
    """The registered entry of `split` for this flag and variant, or None when it is not on the plan. The held-out plan
    is docs/heldout/plan.json, read only from an explicit project directory (decision 023 §1)."""
    if split == "heldout":
        if project_dir is None:
            raise LookupError("no fault plan for the 'heldout' set without a project directory (decision 023 §1)")
        from collect.heldout import plan_entries

        entries = plan_entries(project_dir)
    elif split in PLANS:
        entries = PLANS[split]
    else:
        raise LookupError(f"no fault plan for the {split!r} set yet (it needs its own protocol decision)")
    return next((e for e in entries if e["flag"] == flag and e["variant"] == variant), None)

# decision 016 §5: what the review must look at for each fault, beyond the general checks (decision 018 §5)
REVIEW_CHECKS: dict[str, list[str]] = {
    "cartFailure": ["how long a failed EmptyCart takes; if checkout or the edge slow down or time out, update affected and "
                    "symptom (decision 016 §2, §3)"],
    "intlShippingSlowdown": ["at least one order to a non-US address reached shipping in the fault period (else "
                             "fault_exercised = false)"],
    "productCatalogLockContention": ["whether astronomy-db was OOM-killed or restarted (counts as its error, decision 016 §2)",
                                     "gaps in astronomy-db metrics"],
    "adHighCpu": ["whether ad or the edge show any latency at all"],
    "adManualGc": ["size of the ads latency; whether ad was OOM-killed",
                   "stack-trace class names or a GC cause that names the fault (leakage: record it for policy v2)"],
    "emailMemoryLeak": ["number and time of OOM restarts; whether checkout really shows failed confirmation sends"],
    "recommendationCacheFailure": ["number of OOM restarts of recommendation"],
}
GENERAL_CHECKS = [
    "fault_exercised: did any request reach the faulty code path in the fault period? (decision 016 §5)",
    "affected_services: services whose own spans / logs / metrics show fault-caused errors or latency; OOM or restart "
    "counts as an error; less traffic does not (decisions 010 rule 3, 016 §2)",
    "user_symptom: at frontend-proxy, requests of the traffic generator fail (errors) or slow down (latency) (decision 016 §3)",
    "telemetry_coverage per signal: origin (the origin shows the fault), symptom_only (only downstream), none (decision 006 §7)",
    "every field that differs from the a priori label needs a reason in review.reasons (decision 018 §3)",
]

MAX_INVALID_ATTEMPTS = 3  # run groups of one fault that ended without an incident before a person must look


WITHDRAWAL = "withdrawn.json"  # ground-truth side, next to run.json (decision 025 revision 3)


HELDOUT_NEVER_WITHDRAWN = ("a held-out run group is never withdrawn (decision 026 #30: 023 has no withdrawal, decision 025 "
                           "revision 3 withdrew one Pilot run group); a person decides in a new decision")


def withdraw(layout, run_group_id: str, *, reason: str, decided_by: str, now: str) -> dict:
    """Withdraw a valid Pilot run group by a person's decision (decision 025 revision 3): everything stays on disk, its
    incidents count for no set. A held-out run group is never withdrawn (decision 026 #30)."""
    path = layout.run_group_truth_dir(run_group_id) / "run.json"
    if not path.exists():
        raise ValueError(f"{run_group_id}: no run record")
    run = json.loads(path.read_text())
    injection = layout.injection_path(run_group_id)
    if (run.get("plan") or {}).get("split") == "heldout" or (
            injection.exists() and json.loads(injection.read_text()).get("split") == "heldout"):
        raise ValueError(f"{run_group_id}: {HELDOUT_NEVER_WITHDRAWN}")
    if run.get("status") != "valid":
        raise ValueError(f"{run_group_id} is {run.get('status')}: only a valid run group has an incident to withdraw")
    target = path.with_name(WITHDRAWAL)
    if target.exists():
        raise ValueError(f"{run_group_id} is already withdrawn")
    record = {"run_group_id": run_group_id, "incident_ids": run.get("incident_ids") or [], "reason": reason,
              "decided_by": decided_by, "withdrawn_at": now}
    target.write_text(json.dumps(record, indent=2) + "\n")
    return record


def withdrawals(layout) -> dict[str, dict]:
    """run group id (its directory) -> its withdrawal record, for every withdrawn run group of any set."""
    return {path.parent.name: json.loads(path.read_text())
            for path in sorted((layout.ground_truth_root / "run_groups").glob(f"RG-*/{WITHDRAWAL}"))}


def withdrawn(layout) -> dict[str, str]:
    """incident id -> reason, for every withdrawn run group."""
    out = {}
    for w in withdrawals(layout).values():
        out.update({inc: w["reason"] for inc in w["incident_ids"]})
    return out


ACKS = "failure_acks.jsonl"  # ground-truth side: a person looked at a fault's failed run groups (decision 016 §5)


def _acknowledged(layout) -> set[str]:
    path = layout.ground_truth_root / ACKS
    return {rg for line in path.read_text().splitlines() if line.strip() for rg in json.loads(line)["run_groups"]} \
        if path.exists() else set()


def acknowledge_failures(layout, split: str, flag: str, variant: str, *, reason: str, decided_by: str, now: str) -> dict:
    """Record that a person looked at the failed run groups of one fault (decision 016 §5 / 009 §4): the fault is
    collected again and its invalid attempts count anew. Nothing is changed or deleted."""
    entry = next((s for s in plan_status(layout, split) if (s["flag"], s["variant"]) == (flag, variant)), None)
    if entry is None:
        raise ValueError(f"{flag} {variant} is not on the {split} plan")
    failed = [rg for rg, status in entry["run_groups"] if status != "valid" and rg not in entry["acknowledged"]]
    if not failed:
        raise ValueError(f"{flag} {variant}: no failed run group left to acknowledge")
    record = {"split": split, "flag": flag, "variant": variant, "run_groups": failed, "reason": reason,
              "decided_by": decided_by, "acknowledged_at": now}
    path = layout.ground_truth_root / ACKS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return record


def plan_status(layout, split: str) -> list[dict]:
    """Per planned fault, in plan order: its run groups (id, status), its usable incident, its excluded incidents and the
    power settings each valid run group was collected under (decision 025).

    A run group recorded before `--set` existed (no split in its plan) was a Pilot run (decision 010)."""
    runs = []
    for path in sorted((layout.ground_truth_root / "run_groups").glob("RG-*/run.json")):
        r = json.loads(path.read_text())
        plan = r.get("plan") or {}
        if plan.get("split", "pilot") == split:
            power = ((r.get("provenance") or {}).get("machine") or {}).get("power")  # decision 025; None: not recorded
            runs.append((r["run_group_id"], r.get("status"), plan.get("flag"), plan.get("variant"), r.get("incident_ids") or [],
                         power))
    out, withdrawals, acked = [], withdrawn(layout), _acknowledged(layout)
    for e in PLANS[split]:
        mine = [r for r in runs if (r[2], r[3]) == (e["flag"], e["variant"])]
        usable, excluded, gone = None, [], []
        for _, status, _, _, incs, _ in mine:
            for inc in incs if status == "valid" else []:
                review = layout.label_path(inc).with_name("label_review.json")
                if inc in withdrawals:
                    gone.append(inc)
                elif review.exists() and json.loads(review.read_text()).get("fault_exercised") is False:
                    excluded.append(inc)
                elif usable is None:
                    usable = inc
        out.append({"flag": e["flag"], "variant": e["variant"], "run_groups": [(r[0], r[1]) for r in mine],
                    "incident": usable, "excluded": excluded, "withdrawn": gone,
                    "acknowledged": [r[0] for r in mine if r[0] in acked],
                    "power": {r[0]: r[5] for r in mine if r[1] == "valid"}})
    return out


def next_planned(layout, split: str) -> dict | None:
    """The first planned fault without a usable incident, or None when the set is complete. Raises when a fault needs a
    person: its fault was not exercised twice (decision 016 §5 allows one recollection) or MAX_INVALID_ATTEMPTS run
    groups ended without an incident."""
    for s in plan_status(layout, split):
        if s["incident"] is not None:
            continue
        failed = [rg for rg, status in s["run_groups"] if status != "valid" and rg not in s["acknowledged"]]
        if len(s["excluded"]) >= 2:
            raise RuntimeError(f"{s['flag']} {s['variant']}: the fault was not exercised in {s['excluded']}; "
                               "decision 016 §5 allows one recollection, a person decides what next")
        if len(failed) >= MAX_INVALID_ATTEMPTS:
            raise RuntimeError(f"{s['flag']} {s['variant']}: {len(failed)} run groups ended invalid or aborted ({failed}); "
                               "a person looks at the run records before collecting it again")
        return planned(split, s["flag"], s["variant"])
    return None
