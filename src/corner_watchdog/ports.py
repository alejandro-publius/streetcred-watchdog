"""The seams where the cloud goes.

Every dependency this agent has on somebody else's server is named here as a
Protocol, and every one of them has a local implementation that runs with no
account, no key and no network beyond the two public read-only APIs the agent
genuinely observes.

The point is not that the local versions are good enough to ship. The point is
that the loop can be run, watched and argued with tonight, and that swapping in
Firestore, Pub/Sub, Gemma and Gemini later is a constructor change at one wiring
site rather than a rewrite. A seam you cannot run without a credential is a seam
you have never actually tested.

    Store      LocalJsonStore   ->  Firestore
    Bus        DirectBus        ->  Pub/Sub
    Triage     RuleTriage       ->  Gemma on Vertex
    Decider    RuleDecider      ->  Gemini on Vertex
    Actuator   DryRunActuator   ->  LiveActuator, which refuses until it is real

Each protocol carries a `describe()` so the journal can record which side of the
seam actually ran. An agent that degrades quietly is worse than one that fails,
because the output looks identical either way.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .schema import Calibration, Counts, Delta, JournalEntry, Snapshot, Tier1Verdict, Tier2Decision


@runtime_checkable
class Store(Protocol):
    """Snapshots, the journal and calibration state."""

    def describe(self) -> str: ...

    def get_snapshot(self, slug: str) -> Snapshot | None: ...

    def put_snapshot(self, snapshot: Snapshot) -> None: ...

    def append_journal(self, entry: JournalEntry) -> None: ...

    def read_journal(self) -> list[dict[str, Any]]: ...

    def get_calibration(self) -> Calibration: ...

    def put_calibration(self, calibration: Calibration) -> None: ...


@runtime_checkable
class Bus(Protocol):
    """The observer-to-actor hop.

    Kept as a real seam even locally. The observer must not be able to reach
    into the actor and read its state, because on Cloud Run it cannot.
    """

    def describe(self) -> str: ...

    async def publish(self, envelope: dict[str, Any]) -> None: ...


@runtime_checkable
class Triage(Protocol):
    """Tier one. Cheap, runs on every delta including the empty ones."""

    def describe(self) -> str: ...

    @property
    def degraded(self) -> str | None:
        """None when the real model ran, a plain sentence when it did not."""
        ...

    async def judge(self, delta: Delta, corner: dict[str, Any], calibration: Calibration) -> Tier1Verdict: ...


class DeliberationError(RuntimeError):
    """A Decider did not produce a decision this system can act on.

    Lives here rather than beside the ADK implementation because it belongs to
    the protocol: any tier two that cannot answer has to fail this way, and the
    actor has to be able to catch it without importing a framework.

    Raised rather than converted into a decline. A deliberation that returned
    prose, or signed itself twice, has not declined. Nothing weighed the change
    and nothing signed anything, and recording it as restraint would put a
    failure of the agent into the numerator of the number this project asks to
    be judged on.
    """


@runtime_checkable
class Decider(Protocol):
    """Tier two. Expensive, only ever sees what tier one escalated."""

    def describe(self) -> str: ...

    @property
    def degraded(self) -> str | None: ...

    async def decide(
        self, delta: Delta, corner: dict[str, Any], counts: Counts, escalation_reason: str
    ) -> Tier2Decision: ...


@runtime_checkable
class Actuator(Protocol):
    """Where an action lands. Locally a file; in production StreetCred."""

    def describe(self) -> str: ...

    @property
    def is_live(self) -> bool: ...

    async def rescore(self, corner: dict[str, Any], counts: Counts, reasoning: str) -> str: ...

    async def regenerate_letter(
        self, corner: dict[str, Any], counts: Counts, delta: Delta, reasoning: str
    ) -> str: ...

    async def reaudit_imagery(
        self, corner: dict[str, Any], counts: Counts, delta: Delta, reasoning: str
    ) -> str: ...

    async def flag(self, corner: dict[str, Any], reason: str) -> str: ...
