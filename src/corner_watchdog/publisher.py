"""Every journaled decision reaches the public diary, or says why it did not.

This is the half of the loop that was missing. The agent decided, journaled and
declined, and none of it left the building: a reader had to be told where to
look, which makes the whole thing a description of an agent rather than an agent.

Three properties, and the third is the one that took the thinking.

**A failed publish is a journal entry, not a log line.** The decision is already
in Firestore by the time this runs. If the post then fails and nothing records
that, the journal and the diary disagree and nothing in either says so. So a
failure is written back into the journal with an `error`, which is the field the
ledger already uses to keep a broken run out of the restraint rate.

**Publishing is journaled separately from deciding.** Receipts go to their own
log rather than into the journal as ordinary entries. That is not tidiness: the
ledger counts an entry with no actions as restraint, so a successful publish
receipt sitting in the journal would raise the one number this project asks to
be judged on, once per decision, forever. The publish log is what makes the two
sides reconcilable; the journal stays a record of decisions only.

**A rejection is not a retry.** StreetCred validates on content, so a 400 means
the payload is wrong and will be wrong on the tenth attempt too. Retrying it
burns the backoff window and delays every decision behind it, and on the Pub/Sub
path it is how one poison record blocks a subscription until its retention
expires. Only a transport fault or a 5xx is retried. A 400 is dead on arrival,
recorded as permanently failed, and never tried again.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .schema import JournalEntry, Tier1Verdict

# Four attempts over roughly fourteen seconds. The far side is a Worker with no
# cold start worth speaking of, so a fault that survives this is a fault that
# needs a person, not a longer wait.
MAX_ATTEMPTS = 4
BASE_DELAY_S = 2.0

# Statuses that mean "try again". Everything else is the far side telling us
# something about the payload, and the payload does not change between attempts.
RETRYABLE = frozenset({0, 408, 429, 500, 502, 503, 504})

PUBLISHED = "published"
DUPLICATE = "duplicate"
FAILED = "failed"
DEAD = "permanently_failed"


@dataclass(frozen=True)
class PublishReceipt:
    """What happened to one decision on its way to the diary."""

    decision_id: str
    slug: str | None
    status: str
    attempts: int
    status_code: int
    why: str = ""
    at: str = ""

    @property
    def ok(self) -> bool:
        # A duplicate is a success. The actor retries, the site is idempotent,
        # and a second landing means the first one worked.
        return self.status in (PUBLISHED, DUPLICATE)

    @property
    def dead(self) -> bool:
        return self.status == DEAD

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PublishResult:
    """A run's worth of receipts, for the cycle report and for doctor."""

    published: int = 0
    duplicates: int = 0
    failed: int = 0
    dead: int = 0
    receipts: list[PublishReceipt] = field(default_factory=list)

    def record(self, r: PublishReceipt) -> None:
        self.receipts.append(r)
        if r.status == PUBLISHED:
            self.published += 1
        elif r.status == DUPLICATE:
            self.duplicates += 1
        elif r.status == DEAD:
            self.dead += 1
        else:
            self.failed += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "published": self.published,
            "duplicates": self.duplicates,
            "failed": self.failed,
            "dead": self.dead,
            "receipts": [r.to_dict() for r in self.receipts],
        }


def decision_id_for(entry: JournalEntry) -> str:
    """The agent's own id for a decision, stable across retries.

    Built from the run, the corner and the timestamp rather than randomly,
    because the point of it is that a repost of the same decision carries the
    same id and the far side can refuse the second one.
    """
    return f"{entry.run_id or 'norun'}:{entry.slug or 'noslug'}:{entry.ts}"


class DecisionPublisher:
    """Posts journaled decisions to StreetCred and records what happened."""

    def __init__(
        self,
        client: Any,
        *,
        append_journal: Callable[[JournalEntry], None] | None = None,
        append_publish_log: Callable[[dict[str, Any]], None] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        base_delay_s: float = BASE_DELAY_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.append_journal = append_journal
        self.append_publish_log = append_publish_log
        self.max_attempts = max_attempts
        self.base_delay_s = base_delay_s
        self.sleep = sleep
        self.result = PublishResult()

    async def publish(self, entry: JournalEntry) -> PublishReceipt:
        """One decision, up to max_attempts, then a receipt either way."""
        decision_id = decision_id_for(entry)
        payload = {**entry.to_ingest_payload(), "decisionId": decision_id}

        last_status = 0
        last_why = ""
        for attempt in range(1, self.max_attempts + 1):
            out = await self.client.post_journal(payload)
            last_status = getattr(out, "status", 0) or 0
            body = getattr(out, "body", {}) or {}

            if getattr(out, "ok", False):
                status = DUPLICATE if body.get("duplicate") else PUBLISHED
                return self._finish(
                    PublishReceipt(decision_id, entry.slug, status, attempt, last_status)
                )

            last_why = str(body.get("why") or body.get("error") or "no reason given")[:200]

            # The far side judged the payload. It will judge it the same way
            # next time, and on the Pub/Sub path retrying it is how one poison
            # record holds a subscription open until its retention expires.
            if last_status not in RETRYABLE:
                return self._finish(
                    PublishReceipt(decision_id, entry.slug, DEAD, attempt, last_status, last_why),
                    dead_reason=last_why,
                )

            if attempt < self.max_attempts:
                await self.sleep(self.base_delay_s * (2 ** (attempt - 1)))

        # Out of attempts on a fault that could have cleared. Still dead: this
        # decision does not get retried forever, and a person is told instead.
        return self._finish(
            PublishReceipt(decision_id, entry.slug, DEAD, self.max_attempts, last_status, last_why),
            dead_reason=f"{last_why} after {self.max_attempts} attempts",
        )

    def _finish(self, receipt: PublishReceipt, *, dead_reason: str = "") -> PublishReceipt:
        receipt = PublishReceipt(
            receipt.decision_id,
            receipt.slug,
            receipt.status,
            receipt.attempts,
            receipt.status_code,
            # The reason a run of attempts ended is more informative than the
            # last body, and it is what a person reading doctor output needs.
            dead_reason or receipt.why,
            _now(),
        )
        self.result.record(receipt)

        # The reconciliation record. Its own log, never the journal: the ledger
        # counts a journal entry with no actions as restraint, so a receipt per
        # decision would raise the restraint rate once per decision forever.
        if self.append_publish_log:
            self.append_publish_log(receipt.to_dict())

        # A decision that never reached the diary is a hole between the two
        # sides, and a hole nobody wrote down is one nobody finds.
        if receipt.dead and self.append_journal:
            self.append_journal(
                JournalEntry(
                    ts=_now(),
                    slug=receipt.slug,
                    name=receipt.slug,
                    delta=f"A decision about {receipt.slug or 'a corner'} was not published.",
                    trigger="manual",
                    tier1=Tier1Verdict(
                        significant=False,
                        reason=(
                            "The decision itself is already journaled above. This entry records "
                            "that publishing it to the public diary failed and will not be "
                            "retried, so the journal and the diary can be reconciled without "
                            "either side being read as complete."
                        ),
                        by_rule=True,
                        basis="unreliable",
                    ),
                    error=(
                        f"publish {receipt.status} after {receipt.attempts} attempt(s), "
                        f"status {receipt.status_code}: {dead_reason or receipt.why}"
                    ),
                )
            )
        return receipt


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
