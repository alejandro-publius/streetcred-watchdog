"""Exercising the action path without pretending anything was observed.

The problem this solves is real and worth stating plainly. Two cycles run
minutes apart against a five year rolling window produce no change at all, which
is the honest result and also means the deliberation tier, the budget and the
letter renderer never run. Shipping a loop whose expensive half has never
executed is how a demo becomes a surprise.

So the rehearsal constructs a baseline and observes nothing. The current
observation is the real snapshot already on disk, fetched from DataSF by a real
cycle. What is fabricated is only the *previous* reading, chosen so the
difference between then and now is a known quantity. That inversion matters: no
number in the rehearsal's current record was made up, and the made-up number is
the one being subtracted from, which is the one nothing is published from.

Four containments keep it from ever being mistaken for an observation:

  1. It writes to its own state directory. The real journal is never touched.
  2. Every entry carries trigger "rehearsal".
  3. Every entry's degraded line says the baseline was constructed.
  4. The ledger renders it in a separate section and leaves it out of the
     restraint rate.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .observer import Fetcher
from .runner import run_cycle
from .schema import Counts, Snapshot
from .store import LocalJsonStore

BASELINE_NOTE = (
    "The previous reading in this comparison was constructed, not observed. The current reading is "
    "a real DataSF snapshot from an earlier cycle. Nothing here is evidence that anything happened "
    "at this corner."
)

# What each rehearsed corner is for. Read as: subtract this from the real
# current record to get the baseline, and the delta is what the loop then sees.
SCENARIOS = [
    ("a new fatality, which the rule floor escalates before any model is consulted", {"fatal_5y": 1, "collisions_5y": 1}),
    ("a new severe injury, also settled by rule", {"severe_5y": 1, "collisions_5y": 1}),
    ("two new injury collisions, escalated by tier one against its threshold", {"collisions_5y": 2}),
    ("a large street-condition swing with no new collisions", {"reports_311_3y": 22}),
    ("a small street-condition swing, which tier one should decline", {"reports_311_3y": 3}),
    ("nothing at all, which the rule floor declines without spending anything", {}),
]


class ReplayFetcher:
    """Returns snapshots already on disk. Opens no sockets."""

    def __init__(self, snapshots: dict[str, Snapshot]):
        self.snapshots = snapshots

    def describe(self) -> str:
        return "ReplayFetcher, real snapshots replayed from disk, no network"

    async def fetch_all(self, corners: list[dict[str, Any]]) -> list[Snapshot | BaseException]:
        out: list[Snapshot | BaseException] = []
        for c in corners:
            snap = self.snapshots.get(c["slug"])
            out.append(snap if snap is not None else KeyError(c["slug"]))
        return out


def _lower(snapshot: Snapshot, by: dict[str, int]) -> Snapshot:
    """The constructed baseline: the real record minus a known amount."""
    c = snapshot.counts
    counts = Counts(
        collisions_5y=max(0, c.collisions_5y - by.get("collisions_5y", 0)),
        fatal_5y=max(0, c.fatal_5y - by.get("fatal_5y", 0)),
        severe_5y=max(0, c.severe_5y - by.get("severe_5y", 0)),
        reports_311_3y=max(0, c.reports_311_3y - by.get("reports_311_3y", 0)),
        district=c.district,
    )
    return replace(snapshot, counts=counts, fetched_at="constructed baseline, not observed")


async def rehearse(
    *,
    state_dir: str | Path = "state",
    rehearsal_dir: str | Path = "state-rehearsal",
    outbox_dir: str | Path = "outbox",
    watched_path: str | Path = "data/watched.json",
    printer: Callable[[str], None] = print,
) -> int:
    real = LocalJsonStore(state_dir)
    snapshots = {s.slug: s for s in real.all_snapshots()}
    if not snapshots:
        printer("No snapshots on disk yet. Run a real cycle first, so the rehearsal has real")
        printer("current readings to work from rather than inventing both sides of a comparison.")
        return 1

    watched_doc = json.loads(Path(watched_path).read_text())
    by_slug = {c["slug"]: c for c in watched_doc.get("corners", [])}

    usable = [slug for slug in by_slug if slug in snapshots]
    if len(usable) < len(SCENARIOS):
        printer(f"Only {len(usable)} watched corners have snapshots; need {len(SCENARIOS)}.")
        return 1

    rehearsal_store = LocalJsonStore(rehearsal_dir)
    corners: list[dict[str, Any]] = []
    printer("Rehearsal. Baselines are constructed; current readings are real snapshots on disk.")
    printer("")
    for slug, (description, lower_by) in zip(usable, SCENARIOS):
        now = snapshots[slug]
        rehearsal_store.put_snapshot(_lower(now, lower_by))
        corners.append(by_slug[slug])
        printer(f"  {now.name}: {description}")

    (Path(rehearsal_dir) / "README.txt").write_text(
        "Rehearsal state. " + BASELINE_NOTE + "\nThis directory is not the agent's journal.\n"
    )

    printer("")
    report = await run_cycle(
        corners,
        outbox_dir=Path(outbox_dir) / "rehearsal",
        run_id="rehearsal",
        trigger="rehearsal",
        store=rehearsal_store,
        fetcher=ReplayFetcher(snapshots),
        extra_degradation=BASELINE_NOTE,
    )

    s, a = report.sweep, report.actor
    printer(f"  looked at {s.looked_at}, escalated {s.escalated}, declined at triage {s.declined}")
    printer(f"  deliberated on {a.deliberated}, acted on {a.acted}, declined after deliberation {a.declined}")
    if a.actions_taken:
        printer(f"  actions: {', '.join(a.actions_taken)}")
    for artefact in a.artefacts:
        printer(f"  wrote {artefact}")
    return 0
