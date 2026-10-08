"""The pre-registered fault list of each set and the a priori (catalog) label of each fault (decisions 010, 016).

Written before any of these faults is collected: a run group of a set must be one of its entries, and its catalog label
is taken from here, never typed after seeing the data. Review against the frozen snapshot writes catalog+review
separately (decision 006 §7) and records every difference from these entries. Ground-truth content: not agent-readable
(methods read only the snapshot, decision 015 §6).
"""

from __future__ import annotations

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


def planned(split: str, flag: str, variant: str) -> dict | None:
    """The registered entry of `split` for this flag and variant, or None when it is not on the plan."""
    if split not in PLANS:
        raise LookupError(f"no fault plan for the {split!r} set yet (it needs its own protocol decision)")
    return next((e for e in PLANS[split] if e["flag"] == flag and e["variant"] == variant), None)
