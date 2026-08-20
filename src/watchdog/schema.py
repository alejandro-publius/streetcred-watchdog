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


class MalformedSnapshot(ValueError):
    """A stored snapshot document that cannot be read as one.

    Raised rather than coerced. A corrupted count silently becoming zero is the
    same failure as a filter that matches nothing: the sweep continues, a number
    comes out, and the number is false. The caller is expected to quarantine the
    document and treat the corner as having no baseline, which refuses the
    comparison instead of inventing one.
    """


def _strict_int(value: Any, field: str) -> int:
    """Parse a stored count, or refuse. Absent and null are zero; junk is not."""
    if value is None or value == "":
        return 0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise MalformedSnapshot(f"{field} is not a number: {value!r}") from None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise MalformedSnapshot(f"{field} is not a finite number: {value!r}")
    return int(parsed)


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
    # The question these counts are the answer to: radius, windows, severity
    # vocabulary. Two snapshots taken under different questions cannot be
    # subtracted from each other. Empty on snapshots written before this field
    # existed, which is why an empty one never compares equal to a real one.
    query_fingerprint: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["counts"] = self.counts.to_dict()
        return _clean(d)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Snapshot":
        """Read a stored document, or raise MalformedSnapshot.

        Deliberately strict about numbers and deliberately forgiving about
        everything else. A missing name is cosmetic; a count that says "seventy"
        means this document cannot be subtracted from anything.
        """
        if not isinstance(d, dict):
            raise MalformedSnapshot(f"a snapshot document must be an object, got {type(d).__name__}")
        c = d.get("counts") or {}
        if not isinstance(c, dict):
            raise MalformedSnapshot(f"counts must be an object, got {type(c).__name__}")
        district = c.get("district")
        if district is not None:
            district = _strict_int(district, "district") or None
        return Snapshot(
            slug=d.get("slug", ""),
            name=d.get("name", ""),
            counts=Counts(
                collisions_5y=_strict_int(c.get("collisions_5y"), "collisions_5y"),
                fatal_5y=_strict_int(c.get("fatal_5y"), "fatal_5y"),
                severe_5y=_strict_int(c.get("severe_5y"), "severe_5y"),
                reports_311_3y=_strict_int(c.get("reports_311_3y"), "reports_311_3y"),
                district=district,
            ),
            grade=d.get("grade"),
            index=d.get("index"),
            fetched_at=d.get("fetched_at", ""),
            complete=bool(d.get("complete", True)),
            query_fingerprint=d.get("query_fingerprint", ""),
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


# What actually settled a tier-one verdict. Recorded per entry because "the
# agent declined" covers two completely different events: a rule observing that
# there was nothing to compare, and a tier weighing a real change and choosing
# not to act. A restraint rate that adds them together describes a quiet city
# and reads as a careful agent.
Basis = Literal[
    "first_sighting",   # no baseline yet, so there is nothing to compare
    "no_change",        # the record is identical to last time
    "unreliable",       # a snapshot on one side was incomplete
    "fetch_failed",     # the read did not come back at all
    "methodology",      # the query itself changed, so the arithmetic is meaningless
    "roster_drop",      # the corner left the watched set, so we stopped looking
    "corrupt_baseline", # the stored baseline was unreadable and was quarantined
    "rule_fatal",       # a new fatality, escalated before any tier is consulted
    "rule_severe",      # a new severe injury, same
    "triage",           # tier one weighed an ambiguous change
    "triage_defer",     # tier one weighed it and did not trust the evidence
    "budget_exhausted", # the token budget was spent, so no tier was consulted
]

# The bases that a rule settled without any judgment being exercised. Kept as a
# named set because the ledger's honesty depends on the distinction and a
# hand-maintained list at the render site would drift.
UNJUDGED_BASES = frozenset(
    {
        "first_sighting",
        "no_change",
        "unreliable",
        "fetch_failed",
        "methodology",
        "roster_drop",
        "corrupt_baseline",
        "budget_exhausted",
        # Journal entries written before this field existed. They belong here and
        # not on the other side: a missing field must never be able to inflate
        # the claim that something exercised judgment.
        "unrecorded",
    }
)


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
    # Which rule, or none of them. See Basis above.
    basis: Basis | None = None

    @property
    def involved_judgment(self) -> bool:
        """Whether anything actually weighed this, as opposed to observing it."""
        return self.basis not in UNJUDGED_BASES if self.basis else True

    def to_dict(self) -> dict[str, Any]:
        return _clean({
            "significant": self.significant,
            "reason": self.reason,
            "confidence": self.confidence,
            "byRule": self.by_rule,
            "basis": self.basis,
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
    # What consulting the tiers cost, or would have cost. Zero actual on every
    # entry this repo has written, because no model has ever been called.
    cost: dict[str, Any] | None = None
    # Which cycle wrote this. Lets the ledger group entries into cycles and say
    # how many of the watched corners a cycle actually reached, which is the
    # difference between a quiet morning and a run that died halfway.
    run_id: str | None = None

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
            "runId": self.run_id,
            "cost": self.cost,
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
