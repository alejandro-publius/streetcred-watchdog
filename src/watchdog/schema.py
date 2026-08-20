"""Firestore's shape, written down.

Three collections and nothing else:

    snapshots/{slug}      what the city's records said about a corner last time
                          we looked. One document per watched corner, overwritten
                          each sweep.
    journal/{entry_id}    every evaluation, including and especially the ones
                          that ended in no action. Append only. Never edited,
                          never deleted, because a decision journal you can
                          rewrite is not a decision journal.
    calibration/state     one document. The thresholds the reflex tier consults,
                          plus the bounded history of how they got there.

These dataclasses are the schema documentation. If a field is not here it does
not go to Firestore, which is what stops an agent from quietly inventing a
field that later reads as a fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

SCHEMA_VERSION = "v1"

Action = Literal["rescore", "reaudit_imagery", "regenerate_letter", "flag"]
# "rehearsal" marks an entry whose baseline was constructed rather than
# observed. It exists so that exercising the action path can never be mistaken
# for the agent having seen something. Rehearsal entries are written to their
# own state directory, kept out of the real journal, and excluded from the
# restraint rate.
Trigger = Literal["cron", "hourly", "manual", "backfill", "rehearsal"]


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drop Nones so Firestore documents stay readable in the console."""
    return {k: v for k, v in d.items() if v is not None}


@dataclass(frozen=True)
class Counts:
    """The bounded record for one corner at one moment.

    Bounded is the operative word. StreetCred counts collisions over five years
    and filtered 311 over three, inside 150 metres. An unbounded count describes
    two decades of a corner that has since been rebuilt, and the two systems
    would then disagree about the same intersection while both being "right".
    """

    collisions_5y: int = 0
    fatal_5y: int = 0
    severe_5y: int = 0
    reports_311_3y: int = 0
    district: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


@dataclass(frozen=True)
class Snapshot:
    slug: str
    name: str
    counts: Counts
    grade: str | None = None
    index: int | None = None
    fetched_at: str = ""
    # False when a lane failed and the counts are partial. A snapshot that does
    # not know it is incomplete will produce a phantom delta on the next sweep,
    # which is the most expensive kind of wrong this system can be.
    complete: bool = True
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["counts"] = self.counts.to_dict()
        return _clean(d)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Snapshot":
        c = d.get("counts") or {}
        return Snapshot(
            slug=d.get("slug", ""),
            name=d.get("name", ""),
            counts=Counts(
                collisions_5y=int(c.get("collisions_5y") or 0),
                fatal_5y=int(c.get("fatal_5y") or 0),
                severe_5y=int(c.get("severe_5y") or 0),
                reports_311_3y=int(c.get("reports_311_3y") or 0),
                district=c.get("district"),
            ),
            grade=d.get("grade"),
            index=d.get("index"),
            fetched_at=d.get("fetched_at", ""),
            complete=bool(d.get("complete", True)),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class Delta:
    """What changed between two snapshots. Produced by arithmetic, never a model."""

    slug: str
    name: str
    new_collisions: int = 0
    new_fatal: int = 0
    new_severe: int = 0
    reports_311_change: int = 0
    district_changed: bool = False
    # True when there is nothing to evaluate. Still journaled, because "we looked
    # and nothing had changed" is the most common honest outcome and a journal
    # that omits it overstates how busy the agent was.
    empty: bool = True
    # Set when either side of the comparison was incomplete. Triage must not
    # treat a failed fetch as a drop to zero.
    unreliable: bool = False
    note: str = ""

    def summary(self) -> str:
        """One plain sentence, the way the diary will print it."""
        if self.unreliable:
            return f"Comparison unreliable at {self.name}: {self.note}"
        if self.empty:
            return f"No change at {self.name}."
        bits: list[str] = []
        if self.new_fatal:
            bits.append(f"{self.new_fatal} new fatal collision" + ("s" if self.new_fatal != 1 else ""))
        if self.new_severe:
            bits.append(f"{self.new_severe} new severe injury collision" + ("s" if self.new_severe != 1 else ""))
        plain = self.new_collisions - self.new_fatal - self.new_severe
        if plain > 0:
            bits.append(f"{plain} new injury collision" + ("s" if plain != 1 else ""))
        if self.reports_311_change:
            direction = "rose" if self.reports_311_change > 0 else "fell"
            bits.append(f"311 street-condition reports {direction} by {abs(self.reports_311_change)}")
        if self.district_changed:
            bits.append("the majority supervisor district changed")
        return f"{self.name}: " + ", ".join(bits) + "."

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


@dataclass(frozen=True)
class Tier1Verdict:
    """The reflex tier's answer. Cheap, runs on everything."""

    significant: bool
    reason: str
    confidence: float | None = None
    # True when a rule decided this before the model was consulted at all. The
    # diary prints "Rule" instead of "Triage" for these, because crediting a
    # model for a deterministic floor overstates what was decided.
    by_rule: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _clean({
            "significant": self.significant,
            "reason": self.reason,
            "confidence": self.confidence,
            "byRule": self.by_rule,
        })


@dataclass(frozen=True)
class Tier2Decision:
    """The judgment tier's answer. Expensive, runs only on escalations."""

    reasoning: str
    actions: list[Action] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"reasoning": self.reasoning, "actions": list(self.actions)}


@dataclass(frozen=True)
class JournalEntry:
    ts: str
    slug: str | None
    name: str | None
    delta: str
    trigger: Trigger
    tier1: Tier1Verdict
    tier2: Tier2Decision | None = None
    actions: list[Action] = field(default_factory=list)
    # Actions the budget refused. Journaled rather than dropped, so a quiet night
    # caused by an exhausted budget cannot be mistaken for a quiet night caused
    # by a calm city.
    intents: list[str] = field(default_factory=list)
    degraded: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean({
            "ts": self.ts,
            "slug": self.slug,
            "name": self.name,
            "delta": self.delta,
            "trigger": self.trigger,
            "tier1": self.tier1.to_dict(),
            "tier2": self.tier2.to_dict() if self.tier2 else None,
            "actions": list(self.actions),
            "intents": list(self.intents),
            "degraded": self.degraded,
        })

    def to_ingest_payload(self) -> dict[str, Any]:
        """The wire shape StreetCred's /api/agent/report validates."""
        return {"kind": "journal_entry", **self.to_dict()}


@dataclass
class Calibration:
    """Thresholds the reflex tier consults, and how they got there.

    Bounded on purpose. A week of unusual data must not be able to swing the
    agent into ignoring everything or escalating everything, so every threshold
    has a floor and a ceiling and every adjustment is journaled with its before
    and after values.
    """

    reports_311_jump: int = 15
    min_new_collisions: int = 1
    # Never below this, never above it, whatever the outcome checks say.
    bounds: dict[str, tuple[int, int]] = field(
        default_factory=lambda: {"reports_311_jump": (5, 40), "min_new_collisions": (1, 3)}
    )
    history: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def adjust(self, key: str, new_value: int, evidence: str) -> bool:
        """Move one threshold inside its bounds. Returns False if refused."""
        if key not in self.bounds:
            return False
        low, high = self.bounds[key]
        clamped = max(low, min(high, new_value))
        old = getattr(self, key)
        if clamped == old:
            return False
        setattr(self, key, clamped)
        self.history.append(
            {"key": key, "from": old, "to": clamped, "requested": new_value, "evidence": evidence}
        )
        # A season of adjustments is plenty of provenance for a demo, and it
        # keeps one Firestore document from growing without limit.
        self.history = self.history[-60:]
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "reports_311_jump": self.reports_311_jump,
            "min_new_collisions": self.min_new_collisions,
            "bounds": {k: list(v) for k, v in self.bounds.items()},
            "history": self.history,
            "schema_version": self.schema_version,
        }
