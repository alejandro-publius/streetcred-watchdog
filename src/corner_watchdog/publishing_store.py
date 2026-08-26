"""A Store that also publishes what it journals.

The actor writes journal entries at three sites and the ADK decider's after-tool
callback writes a fourth. Adding a publish call to each would be four places to
forget, and the one that got forgotten would be a decision that never reached
the diary with nothing saying so.

So the publish hangs off the write. Anything journaled through this store is
queued for publication, which makes "every journaled decision reaches the diary"
a property of the wiring rather than a rule four call sites have to remember.

It decorates a Store rather than subclassing one, because there are two real
stores now and the deployed services use `FirestoreStore`. Wrapping keeps this
working for both and keeps the publish out of the store implementations, neither
of which should know that StreetCred exists.

Queue then flush, rather than post inside the write. `append_journal` is
synchronous by the Store protocol and posting is not, and making the protocol
async to suit this would push the change into every caller and both stores. The
actor flushes after each envelope and the observer after its sweep, so nothing
waits longer than one decision to be published.

The entry is always journaled first. A publish that fails must not be able to
cost the decision itself, which is the only thing here that cannot be recreated.
"""

from __future__ import annotations

from typing import Any

from .publisher import DecisionPublisher, PublishResult
from .schema import JournalEntry


class PublishingStore:
    """Wraps a Store. Journals through it, queues the entry, flushes on demand."""

    def __init__(self, inner: Any, publisher: DecisionPublisher) -> None:
        self.inner = inner
        self.publisher = publisher
        self._pending: list[JournalEntry] = []

    def describe(self) -> str:
        return f"{self.inner.describe()}, publishing decisions to StreetCred"

    @property
    def result(self) -> PublishResult:
        return self.publisher.result

    # ---------------------------------------------------------------- the hook

    def append_journal(self, entry: JournalEntry) -> None:
        self.inner.append_journal(entry)
        # A failed-publish entry is a record about publishing, not a decision.
        # Posting it would be an infinite regress: its own publish could fail,
        # journaling another one, forever.
        if entry.error and entry.error.startswith("publish "):
            return
        self._pending.append(entry)

    async def flush(self) -> PublishResult:
        """Post everything journaled since the last flush."""
        pending, self._pending = list(self._pending), []
        for entry in pending:
            await self.publisher.publish(entry)
        return self.publisher.result

    # --------------------------------------------------- everything else, as is

    def get_snapshot(self, slug: str):
        return self.inner.get_snapshot(slug)

    def put_snapshot(self, snapshot) -> None:
        self.inner.put_snapshot(snapshot)

    def all_snapshots(self):
        return self.inner.all_snapshots()

    def read_journal(self, *a, **k):
        return self.inner.read_journal(*a, **k)

    def get_calibration(self):
        return self.inner.get_calibration()

    def put_calibration(self, calibration) -> None:
        self.inner.put_calibration(calibration)

    @property
    def quarantined(self) -> dict[str, str]:
        return getattr(self.inner, "quarantined", {})
