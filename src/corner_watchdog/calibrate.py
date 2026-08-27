"""The outcome loop: what the journal says about tier one's own bar.

`Calibration` has enforced its bounds and journaled every change since the first
week, and nothing ever called `adjust`. Disclosed-but-dead code is worse than
absent code, because the disclosure reads as a feature and the reviewer who
checks finds a mechanism that has never run. So it is wired here.

**The asymmetry is the whole design, and it is not a limitation to apologise
for.** Tier one's mistakes come in two kinds and only one of them is observable.
An escalation that tier two then declined is a false positive, and it is written
down: both tiers left a record on the same entry. A delta that tier one declined
and that actually mattered is a false negative, and there is no record of it
anywhere, because tier two never saw it and nothing else looked. Evidence
therefore only ever supports *raising* the bar. This module will never lower one,
and the reason is that lowering on the evidence available would be inferring a
number from data that by construction cannot contain it.

**The floor matters more than the rule.** Five escalations is not a measurement,
it is an anecdote, and an agent that retunes itself on five samples is the exact
confident wrongness this repository is written against. So there is a minimum,
the review refuses below it, and the refusal is journaled in the same shape an
adjustment is. A run that declines to retune has made a decision, not skipped a
step, which is the same claim this project makes about its declines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import Calibration

# Below this many escalations with a tier two outcome, no threshold moves. Set
# to twenty because the bar being tuned is a 311 swing, weekly variance is the
# noise it has to clear, and a handful of corners in one quiet fortnight cannot
# distinguish the two.
MIN_EVIDENCE = 20

# Only acted on when more than this share of escalations were declined by tier
# two. At exactly half the tiers disagree as often as they agree, which is not
# evidence that the bar is wrong so much as that the middle is genuinely
# ambiguous, which is what the middle is for.
MAX_FALSE_POSITIVE_RATE = 0.5

# One step, and a small one. A bar that can jump is a bar that can oscillate.
STEP = 5


@dataclass(frozen=True)
class CalibrationReview:
    """What the outcomes said, and what was done about it."""

    escalations: int
    declined_at_tier_two: int
    adjusted: bool
    reason: str
    key: str | None = None
    before: int | None = None
    after: int | None = None

    @property
    def false_positive_rate(self) -> float:
        return self.declined_at_tier_two / self.escalations if self.escalations else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalations": self.escalations,
            "declinedAtTierTwo": self.declined_at_tier_two,
            "adjusted": self.adjusted,
            "reason": self.reason,
            "key": self.key,
            "before": self.before,
            "after": self.after,
        }

    def summary(self) -> str:
        return self.reason


@dataclass
class Outcomes:
    """The two numbers the journal can actually support."""

    escalations: int = 0
    declined_at_tier_two: int = 0
    corners: set[str] = field(default_factory=set)


def outcomes_from(journal: list[dict[str, Any]]) -> Outcomes:
    """Escalations that reached tier two, and how many it then declined.

    Entries carrying an `error` are excluded. A deliberation that broke is not
    evidence that tier one was wrong to escalate, and letting a bug feed back
    into the thresholds would let the agent tune itself away from its own faults.
    """
    out = Outcomes()
    for entry in journal:
        if entry.get("error"):
            continue
        tier1 = entry.get("tier1") or {}
        if not tier1.get("significant"):
            continue
        # Only a delta that actually reached tier two carries an outcome. One
        # stopped by the budget was never judged, and counting it either way
        # would be inventing a verdict nobody reached.
        if not entry.get("tier2"):
            continue
        out.escalations += 1
        if entry.get("slug"):
            out.corners.add(entry["slug"])
        if not (entry.get("actions") or []):
            out.declined_at_tier_two += 1
    return out


def review(
    journal: list[dict[str, Any]],
    calibration: Calibration,
    *,
    min_evidence: int = MIN_EVIDENCE,
) -> CalibrationReview:
    """Read the outcomes, and move at most one threshold, upward, or refuse."""
    out = outcomes_from(journal)

    if out.escalations < min_evidence:
        return CalibrationReview(
            out.escalations,
            out.declined_at_tier_two,
            adjusted=False,
            reason=(
                f"{out.escalations} escalation(s) have reached tier two and this review "
                f"needs {min_evidence} before it will move a threshold. Nothing was "
                "adjusted. That is a decision about the evidence, not a step that was "
                "skipped: retuning on a handful of samples would move the bar on noise."
            ),
        )

    rate = out.declined_at_tier_two / out.escalations
    if rate <= MAX_FALSE_POSITIVE_RATE:
        return CalibrationReview(
            out.escalations,
            out.declined_at_tier_two,
            adjusted=False,
            reason=(
                f"tier two declined {out.declined_at_tier_two} of {out.escalations} "
                f"escalations, {rate:.0%}, at or under the {MAX_FALSE_POSITIVE_RATE:.0%} bar. "
                "Tier one's threshold is doing its job and nothing was adjusted."
            ),
        )

    key = "reports_311_jump"
    before = getattr(calibration, key)
    moved = calibration.adjust(
        key,
        before + STEP,
        evidence=(
            f"tier two declined {out.declined_at_tier_two} of {out.escalations} escalations "
            f"across {len(out.corners)} corner(s), {rate:.0%}, so tier one escalated more "
            "than the expensive tier found worth acting on."
        ),
    )
    after = getattr(calibration, key)
    if not moved:
        return CalibrationReview(
            out.escalations, out.declined_at_tier_two, adjusted=False,
            reason=(
                f"tier two declined {rate:.0%} of escalations, which calls for a higher bar, "
                f"but {key} is already at {before} and its ceiling refused the move."
            ),
            key=key, before=before, after=after,
        )

    return CalibrationReview(
        out.escalations, out.declined_at_tier_two, adjusted=True,
        reason=(
            f"tier two declined {out.declined_at_tier_two} of {out.escalations} escalations, "
            f"{rate:.0%}, so {key} was raised from {before} to {after}. Only raised, never "
            "lowered: a delta tier one declined that mattered leaves no record anywhere, so "
            "no evidence here can ever argue for a lower bar."
        ),
        key=key, before=before, after=after,
    )
