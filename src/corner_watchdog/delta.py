"""Comparing two snapshots. Deterministic, no model, no network.

This is the piece the whole agent rests on, so it is the piece with no
cleverness in it at all. Everything here can be checked by reading it, and the
tests hold the cases that are easy to get wrong: a failed fetch that looks like
a drop to zero, a first sighting that looks like a hundred new collisions, and
a count that went down, which the city's data does sometimes do when a record
is reclassified.
"""

from __future__ import annotations

from .schema import Counts, Delta, Snapshot


def diff_snapshots(old: Snapshot | None, new: Snapshot) -> Delta:
    """What changed between two looks at one corner.

    Returns a Delta that is always safe to journal. The three guards below are
    the ones that matter, and each of them exists because the naive version
    produces a confident lie rather than an error.
    """
    name = new.name or new.slug

    # Guard 1: a corner we have never seen has not changed. Without this, the
    # first sweep reports every corner as having gained its entire five year
    # collision history overnight, and the agent burns its whole budget acting
    # on a baseline.
    if old is None:
        return Delta(
            slug=new.slug,
            name=name,
            empty=True,
            note="first snapshot, nothing to compare against",
        )

    # Guard 2: if either side is incomplete, the arithmetic is meaningless. A
    # DataSF timeout that returns zero rows is indistinguishable from a corner
    # with no collisions unless somebody records which one happened.
    if not old.complete or not new.complete:
        return Delta(
            slug=new.slug,
            name=name,
            empty=True,
            unreliable=True,
            note="a snapshot on one side of the comparison was incomplete",
        )

    o: Counts = old.counts
    n: Counts = new.counts

    # Guard 2b: the two snapshots must be answers to the same question. A change
    # in radius, window or category vocabulary moves every count at every corner
    # at once, and subtracting across that change produces a delta that is news
    # about this repo wearing the clothes of news about a street. The radius
    # moved from 150 metres to 80 on 2026-08-19; without this guard that would
    # have arrived as a forty percent collapse in collisions at all twenty five
    # corners on the same morning, with confident reasoning attached.
    if old.query_fingerprint != new.query_fingerprint:
        return Delta(
            slug=new.slug,
            name=name,
            empty=True,
            unreliable=True,
            note=(
                "the query changed between these two looks, so the arithmetic is meaningless: "
                f"{old.query_fingerprint or 'not recorded'} then {new.query_fingerprint or 'not recorded'}"
            ),
        )

    # Guard 3: counts can legitimately fall when the city reclassifies or
    # withdraws a record. A negative "new collisions" is not a thing, so it is
    # floored at zero and the drop is carried in the note instead of silently
    # cancelling out a real increase elsewhere.
    new_collisions = max(0, n.collisions_5y - o.collisions_5y)
    new_fatal = max(0, n.fatal_5y - o.fatal_5y)
    new_severe = max(0, n.severe_5y - o.severe_5y)
    reports_change = n.reports_311_3y - o.reports_311_3y

    notes: list[str] = []
    if n.collisions_5y < o.collisions_5y:
        notes.append(
            f"collision count fell from {o.collisions_5y} to {n.collisions_5y}, "
            "likely a reclassified or withdrawn record"
        )
    if n.fatal_5y < o.fatal_5y:
        notes.append(f"fatal count fell from {o.fatal_5y} to {n.fatal_5y}")

    district_changed = (
        o.district is not None and n.district is not None and o.district != n.district
    )

    empty = not (new_collisions or new_severe or new_fatal or reports_change or district_changed)

    return Delta(
        slug=new.slug,
        name=name,
        new_collisions=new_collisions,
        new_fatal=new_fatal,
        new_severe=new_severe,
        reports_311_change=reports_change,
        district_changed=district_changed,
        empty=empty,
        unreliable=False,
        note="; ".join(notes),
    )


# --------------------------------------------------------------- the floor

def rule_verdict(delta: Delta, calibration) -> tuple[bool, str] | None:
    """Rules that decide before any model is consulted.

    Returns (significant, reason) when a rule fires, otherwise None and the
    ambiguous middle goes to the reflex model. Keeping this separate from the
    model is the whole architecture in one function: a deterministic floor that
    cannot be talked out of escalating a death, and a model that only ever
    adjudicates the cases where reasonable people would differ.
    """
    if delta.unreliable:
        return (False, "The comparison was unreliable, so there is nothing to judge yet.")

    if delta.new_fatal > 0:
        return (
            True,
            f"{delta.new_fatal} new fatal collision"
            + ("s" if delta.new_fatal != 1 else "")
            + " recorded. Any new fatality is significant by rule, before any model is consulted.",
        )

    if delta.new_severe > 0:
        return (
            True,
            f"{delta.new_severe} new severe injury collision"
            + ("s" if delta.new_severe != 1 else "")
            + " recorded. Severe injuries are significant by rule.",
        )

    if delta.empty:
        return (False, "Nothing changed at this corner since the last look.")

    return None
