"""Evidence existence (SPEC Core §9): the share of cited ids that name a record of the frozen snapshot.

Relevance is a separate layer (candidate pool, weak labels, gold subset) and is never mixed into this number.
"""

from __future__ import annotations


def existence(cited: list[dict], snapshot) -> dict:
    """`cited`: a prediction's evidence entries ({id, t0?, t1?}); `snapshot`: collect.snapshot.Snapshot."""
    unresolved = [e["id"] for e in cited if snapshot.resolve(e["id"], e.get("t0"), e.get("t1")) is None]
    resolved = len(cited) - len(unresolved)
    return {"cited": len(cited), "resolved": resolved, "rate": resolved / len(cited) if cited else None,
            "unresolved": unresolved}
