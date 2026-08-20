"""The observer half: look, compare, triage, escalate or decline.

One sweep is one pass over the watched set. For each corner it reads the city's
current record, compares it against what it saw last time, lets the rule floor
decide anything a rule can decide, sends only the genuine ambiguity to tier one,
and either publishes an escalation or journals a decline right here.

The three behaviours worth reading closely:

  Where the observation comes from is injected. The sweep does not import
  DataSF; it is handed something that can produce snapshots. That is what lets
  the whole loop be exercised offline without a single line of "if testing"
  inside the decision path, which is the kind of branch that eventually ships.

  A corner whose fetch came back incomplete does not overwrite its stored
  snapshot. Storing a partial record as the new baseline means the next sweep
  compares a good fetch against a broken one and reports a fictional swing, so
  one bad minute at DataSF would poison a corner for as long as the agent runs.
  The old baseline stays and the comparison is journaled as unreliable.

  A decline is journaled the moment it is made, by the observer, without
  travelling to the actor. Declines are the common case, and routing them
  through the expensive tier to be told what is already known would make the
  restraint rate a function of the actor's uptime.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import httpx

from .datasf import DEFAULT_RADIUS_M, fetch_corner_records
from .delta import diff_snapshots, rule_verdict
from .ports import Bus, Store, Triage
from .schema import Basis, Delta, JournalEntry, Snapshot, Tier1Verdict, Trigger

# DataSF is a public service being used by an unauthenticated client. Five lanes
# per corner times twenty five corners is a lot of requests to open at once, and
# nothing here is urgent enough to justify it.
MAX_CONCURRENT_CORNERS = 5


class Fetcher(Protocol):
    """Where this sweep's observations come from."""

    def describe(self) -> str: ...

    async def fetch_all(self, corners: list[dict[str, Any]]) -> list[Snapshot | BaseException]: ...


class DataSFFetcher:
    """The real one. Reads San Francisco's open data portal, no credentials."""

    def __init__(self, concurrency: int = MAX_CONCURRENT_CORNERS):
        self.concurrency = concurrency

    def describe(self) -> str:
        return f"DataSFFetcher, live reads from data.sfgov.org, {self.concurrency} corners at a time"

    async def fetch_all(self, corners: list[dict[str, Any]]) -> list[Snapshot | BaseException]:
        sem = asyncio.Semaphore(self.concurrency)

        async def one(corner: dict[str, Any], client: httpx.AsyncClient) -> Snapshot:
            async with sem:
                return await fetch_corner_records(
                    corner["slug"],
                    corner.get("name", corner["slug"]),
                    float(corner["lat"]),
                    float(corner["lon"]),
                    radius_m=int(corner.get("radiusMeters") or DEFAULT_RADIUS_M),
                    configured_district=corner.get("district"),
                    client=client,
                )

        async with httpx.AsyncClient() as client:
            return list(await asyncio.gather(*(one(c, client) for c in corners), return_exceptions=True))


@dataclass
class SweepResult:
    looked_at: int = 0
    escalated: int = 0
    declined: int = 0
    unreliable: int = 0
    incomplete_fetches: list[str] = field(default_factory=list)
    first_sightings: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "looked_at": self.looked_at,
            "escalated": self.escalated,
            "declined": self.declined,
            "unreliable": self.unreliable,
            "incomplete_fetches": self.incomplete_fetches,
            "first_sightings": self.first_sightings,
        }


class Observer:
    def __init__(
        self,
        store: Store,
        bus: Bus,
        triage: Triage,
        *,
        fetcher: Fetcher | None = None,
        degraded: str | None = None,
        provenance: str | None = None,
    ):
        self.store = store
        self.bus = bus
        self.triage = triage
        self.fetcher: Fetcher = fetcher or DataSFFetcher()
        # Two different admissions, kept apart on purpose. `degraded` says a
        # model did not run, and belongs only on entries where one would have.
        # `provenance` says something about the inputs themselves and belongs on
        # every entry regardless of who decided it.
        self.degraded = degraded
        self.provenance = provenance

    def _caveat(self, by_rule: bool) -> str | None:
        parts = [self.provenance, None if by_rule else self.degraded]
        joined = " ".join(p for p in parts if p)
        return joined or None

    @staticmethod
    def _basis(old: Snapshot | None, delta: Delta, by_rule: bool) -> Basis:
        """Which rule settled this, or that a tier actually weighed it.

        Derived from the delta rather than threaded back out of rule_verdict, so
        delta.py keeps the signature its tests were written against.
        """
        if not by_rule:
            return "triage"
        if delta.unreliable:
            return "methodology" if delta.note.startswith("the query") else "unreliable"
        if old is None:
            return "first_sighting"
        if delta.new_fatal > 0:
            return "rule_fatal"
        if delta.new_severe > 0:
            return "rule_severe"
        return "no_change"

    async def sweep(self, corners: list[dict[str, Any]], *, trigger: Trigger = "manual") -> SweepResult:
        result = SweepResult()
        fresh = await self.fetcher.fetch_all(corners)

        # Fetching is concurrent; deciding is not. Journal order, budget spending
        # and escalation order all need to be reproducible from the same inputs.
        for corner, snapshot in zip(corners, fresh):
            if isinstance(snapshot, BaseException):
                # Not a partial failure but a total one. Record it as a corner we
                # could not look at, which is different from a corner where
                # nothing happened, and move on without touching its baseline.
                result.looked_at += 1
                result.unreliable += 1
                result.incomplete_fetches.append(corner.get("slug", "unknown"))
                self.store.append_journal(
                    JournalEntry(
                        ts=_now(),
                        slug=corner.get("slug"),
                        name=corner.get("name"),
                        delta=f"Could not read the city's record for {corner.get('name', 'this corner')}.",
                        trigger=trigger,
                        tier1=Tier1Verdict(
                            significant=False,
                            reason=(
                                "The fetch failed outright, so there is nothing to compare and nothing "
                                "to judge. The previous baseline is kept untouched."
                            ),
                            by_rule=True,
                            basis="fetch_failed",
                        ),
                        degraded=" ".join(
                            p for p in (self.provenance, f"Read failed: {type(snapshot).__name__}.") if p
                        ),
                    )
                )
                continue

            result.looked_at += 1
            old = self.store.get_snapshot(snapshot.slug)
            delta = diff_snapshots(old, snapshot)

            if snapshot.complete:
                self.store.put_snapshot(snapshot)
            else:
                # Keep the last good baseline. See the module docstring.
                result.incomplete_fetches.append(snapshot.slug)

            if delta.unreliable:
                result.unreliable += 1
            if old is None:
                result.first_sightings += 1

            calibration = self.store.get_calibration()
            ruled = rule_verdict(delta, calibration)
            if ruled is not None:
                significant, reason = ruled
                verdict = Tier1Verdict(
                    significant=significant,
                    reason=reason,
                    by_rule=True,
                    basis=self._basis(old, delta, by_rule=True),
                )
            else:
                judged = await self.triage.judge(delta, corner, calibration)
                verdict = replace(judged, basis=judged.basis or "triage")

            if not verdict.significant:
                result.declined += 1
                self.store.append_journal(
                    JournalEntry(
                        ts=_now(),
                        slug=snapshot.slug,
                        name=snapshot.name,
                        delta=delta.summary(),
                        trigger=trigger,
                        tier1=verdict,
                        degraded=self._caveat(verdict.by_rule),
                    )
                )
                continue

            result.escalated += 1
            await self.bus.publish(
                {
                    "ts": _now(),
                    "trigger": trigger,
                    "corner": corner,
                    "delta": delta.to_dict(),
                    "delta_summary": delta.summary(),
                    "counts": snapshot.counts.to_dict(),
                    "tier1": verdict.to_dict(),
                }
            )

        return result


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
