"""Pinning the watched set, and noticing when it moves.

The watched set is a claim about which corners this agent is responsible for.
It is read from page one of a scoreboard ordered by points that change on every
sweep, so it is not a fixed list, it is a snapshot of a ranking. Two things
follow, and neither is handled by simply refetching it:

  A corner can fall off the roster. The sweep only journals corners it was
  handed, so a corner that drops out produces no entry at all. The agent stops
  watching and the journal looks exactly the same as a morning where that corner
  was fine. Absence is the one thing a decision journal is worst at recording,
  and this whole project is an argument that absence should be legible.

  The file can change under the operator. A roster refetched silently between
  runs means yesterday's baselines belong to a different set of corners than
  today's, and nothing says so.

So the roster carries a hash of its own contents, refetching reports what moved
rather than overwriting quietly, and a corner that leaves the roster gets a
journal entry saying the agent stopped looking at it.
"""

from __future__ import annotations

import hashlib
from typing import Any


def roster_hash(slugs: list[str]) -> str:
    """A stable fingerprint of the membership, insensitive to ordering.

    Order is deliberately excluded. The scoreboard reorders constantly as points
    move, and a hash that changed every morning would train whoever reads it to
    ignore the one signal it exists to send.
    """
    joined = "\n".join(sorted(slugs))
    return hashlib.sha256(joined.encode()).hexdigest()[:12]


def drift(old: list[str], new: list[str]) -> dict[str, Any]:
    """What changed between two rosters."""
    old_set, new_set = set(old), set(new)
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    return {
        "added": added,
        "removed": removed,
        "unchanged": len(old_set & new_set),
        "membership_changed": bool(added or removed),
        # Reordering alone is not drift worth blocking on, but it is worth
        # reporting, because a corner sliding from rank 3 to rank 24 is real.
        "reordered": old_set == new_set and old != new,
    }


def describe(d: dict[str, Any]) -> list[str]:
    """Plain lines for a terminal, one per thing that happened."""
    lines: list[str] = []
    for slug in d["added"]:
        lines.append(f"  joined the watched set: {slug}")
    for slug in d["removed"]:
        lines.append(f"  left the watched set:   {slug}")
    if not d["membership_changed"]:
        lines.append(
            "  membership unchanged"
            + (", but the ranking moved" if d["reordered"] else "")
        )
    return lines
