"""The two tiers, and what stands in for them when there is no Vertex project.

`RuleTriage` and `RuleDecider` are not simulations of Gemma and Gemini. They do
not pretend to reason and they never emit a sentence claiming a model wrote it.
They are the deterministic policy the models were going to be asked to apply,
written out longhand, so the loop around them can be run and criticised tonight.

Two things follow from that, and both matter more than the rules themselves:

  1. The degradation is journaled. Every entry produced while a stand-in was
     wired carries a `degraded` line naming which tier was not a model. An agent
     that quietly falls back produces output indistinguishable from the real
     thing, which is the failure mode this whole repo is written against.
  2. The seam is the real one. `judge` and `decide` take exactly what the
     versioned prompts in prompts.py take, so the model implementations fill the
     same signature rather than a convenient new one.

The prompts are still formatted for every call even though no model reads them
here. That is deliberate: it keeps prompts.py honest, and a prompt that has
never once been rendered against real data is a prompt that will fail the first
time it is.
"""

from __future__ import annotations

import os
from typing import Any

from .config import decider_name, deliberation_model
from .prompts import DELIBERATION_PROMPT_VERSION, TRIAGE_PROMPT_VERSION, deliberation_prompt, triage_prompt
from .schema import Calibration, Counts, Delta, Tier1Verdict, Tier2Decision


def vertex_is_configured() -> tuple[bool, str]:
    """Whether a real Vertex call could even be attempted.

    Checks configuration only. It deliberately does not try a call and time out,
    because a run that hangs for ninety seconds before falling back teaches the
    operator nothing that this cannot tell them immediately.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    adc = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
    if not project:
        return False, "GOOGLE_CLOUD_PROJECT is not set"
    if not creds and not os.path.exists(adc):
        return False, "no Google application default credentials on this machine"
    return True, "configured"


# ------------------------------------------------------------------- tier one

class RuleTriage:
    """The Gemma stand-in.

    It only ever sees the ambiguous middle. Anything involving a death, a severe
    injury, an unreliable comparison or an empty delta was already settled by
    `rule_verdict` in delta.py before this is consulted, which is the same
    contract the real model runs under.
    """

    def __init__(self, why_degraded: str) -> None:
        self._why = why_degraded

    def describe(self) -> str:
        return f"RuleTriage, deterministic thresholds (stands in for Gemma, {TRIAGE_PROMPT_VERSION})"

    @property
    def degraded(self) -> str | None:
        return f"Tier one ran as deterministic rules, not Gemma: {self._why}."

    async def judge(self, delta: Delta, corner: dict[str, Any], calibration: Calibration) -> Tier1Verdict:
        # Rendered and discarded. See the module docstring.
        triage_prompt(
            name=delta.name,
            grade=corner.get("grade"),
            index=corner.get("index"),
            delta=delta.summary(),
            calibration=calibration,
        )

        if delta.new_collisions >= calibration.min_new_collisions:
            n = delta.new_collisions
            return Tier1Verdict(
                significant=True,
                reason=(
                    f"{n} new injury collision{'s' if n != 1 else ''} on the city's record here since "
                    f"the last look, at or above the current bar of {calibration.min_new_collisions}. "
                    "That is worth a closer look at what this corner's page says."
                ),
                confidence=None,
                by_rule=False,
            )

        if delta.district_changed:
            return Tier1Verdict(
                significant=True,
                reason=(
                    "The supervisor district this corner falls in changed, so the published page is "
                    "pointing residents at the wrong office. Worth a closer look."
                ),
                confidence=None,
                by_rule=False,
            )

        swing = abs(delta.reports_311_change)
        if swing >= calibration.reports_311_jump:
            direction = "rose" if delta.reports_311_change > 0 else "fell"
            return Tier1Verdict(
                significant=True,
                reason=(
                    f"Street-condition reports here {direction} by {swing} since the last look, past the "
                    f"current bar of {calibration.reports_311_jump}. A swing that size usually means "
                    "something at the corner actually changed."
                ),
                confidence=None,
                by_rule=False,
            )

        if delta.reports_311_change:
            direction = "rose" if delta.reports_311_change > 0 else "fell"
            return Tier1Verdict(
                significant=False,
                reason=(
                    f"Street-condition reports {direction} by {swing}, which is ordinary week-to-week "
                    "variance at a corner this busy. The bar for a closer look is "
                    f"{calibration.reports_311_jump}. "
                    "Nothing here changes what the record says about this crossing."
                ),
                confidence=None,
                by_rule=False,
            )

        return Tier1Verdict(
            significant=False,
            reason=(
                "What moved here does not change what the public record says about how dangerous this "
                "corner is, so it does not warrant the expensive look."
            ),
            confidence=None,
            by_rule=False,
        )


# ------------------------------------------------------------------- tier two

class RuleDecider:
    """The Gemini stand-in. Runs only on escalations, sees the full record."""

    def __init__(self, why_degraded: str) -> None:
        self._why = why_degraded

    def describe(self) -> str:
        return f"RuleDecider, deterministic policy (stands in for Gemini, {DELIBERATION_PROMPT_VERSION})"

    @property
    def degraded(self) -> str | None:
        return f"Tier two ran as deterministic policy, not Gemini: {self._why}."

    async def decide(
        self, delta: Delta, corner: dict[str, Any], counts: Counts, escalation_reason: str
    ) -> Tier2Decision:
        deliberation_prompt(
            name=delta.name,
            grade=corner.get("grade"),
            index=corner.get("index"),
            delta=delta.summary(),
            escalation_reason=escalation_reason,
            counts=counts,
        )

        actions: list[str] = []
        because: list[str] = []

        # The letter cites collision figures in so many words, so any movement in
        # them makes a sentence in the published letter untrue.
        if delta.new_fatal or delta.new_severe or delta.new_collisions:
            actions.append("rescore")
            actions.append("regenerate_letter")
            because.append(
                "The letter on this corner's page states its collision figures outright, and those "
                "figures moved, so both the score inputs and the letter's own sentences are now behind "
                "the city's record."
            )

        if delta.new_fatal:
            actions.append("flag")
            because.append(
                "A new fatality is not something to leave to an automated redraft alone, so a human is "
                "flagged as well."
            )

        if delta.district_changed:
            actions.append("regenerate_letter")
            because.append(
                "The letter is addressed to a supervisor, and the district under this corner changed, so "
                "the address line is wrong."
            )

        if abs(delta.reports_311_change) >= 15 and not delta.new_collisions:
            actions.append("reaudit_imagery")
            because.append(
                "A street-condition swing this size with no new collisions points at something visible "
                "at the corner rather than at the crash record, so the imagery is what to look at."
            )

        # De-duplicate while holding the order the reasoning explains them in.
        ordered = list(dict.fromkeys(actions))

        if not ordered:
            return Tier2Decision(
                reasoning=(
                    "Tier one was right to send this up, and having looked at the corner's full record "
                    "there is still nothing here that makes a published figure wrong. The score inputs "
                    "did not move and the letter's stated numbers are all still accurate. Acting anyway "
                    "would churn the page without correcting anything, so this is a decline."
                ),
                actions=[],
            )

        return Tier2Decision(reasoning=" ".join(because), actions=ordered)  # type: ignore[arg-type]


def select_brains() -> tuple[RuleTriage, Any, str | None]:
    """Wire the tiers, and say plainly which ones are real.

    Returns the two tiers plus a single degradation line for the journal, or
    None when both tiers were genuinely models.

    `DECIDER` chooses tier two. The default is the ADK judgment agent; `rule`
    keeps the deterministic stand-in selectable so the two can be compared on
    the same journal. An unrecognised value raises rather than falling back,
    which is `config.py`'s rule and the reason it exists.

    There is one fallback here and it is loud. `DECIDER=adk` on a machine with no
    Vertex project cannot call a model, so it runs the stand-in and says so on
    every entry it writes. That is the same admission this module has always
    made; what it must never become is silence, because an agent that quietly
    degrades produces output indistinguishable from the real thing.
    """
    wanted = decider_name()
    ok, why = vertex_is_configured()
    triage = RuleTriage(why)

    if wanted == "rule":
        decider = RuleDecider(why)
        note = (
            f"{triage.degraded} Tier two ran as deterministic policy because DECIDER=rule was "
            "selected, not because a model was unavailable."
        )
        return triage, decider, note

    if not ok:
        decider = RuleDecider(why)
        note = (
            f"{triage.degraded} DECIDER=adk was requested but no model could be called: {why}. "
            "Tier two ran as deterministic policy instead. Nothing on this entry was decided by "
            "a model."
        )
        return triage, decider, note

    from .adk_decider import AdkDecider

    decider = AdkDecider(model=deliberation_model())
    # Tier one is still not a model. Tier two now is, so the note names only the
    # tier that is actually standing in.
    return triage, decider, triage.degraded
