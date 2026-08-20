"""The agent's daily action budget.

An exhausted budget converts an action into a journaled intent rather than a
silent skip. This is the whole module and it is the reason it exists: a quiet
night caused by a spent budget and a quiet night caused by a calm city produce
identical output unless somebody insists on writing down which one happened.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Phrased the way the diary prints them, in the past conditional, because that
# is what they are: the action the agent would have taken.
_INTENT_PHRASING = {
    "rescore": "would have rescored the corner",
    "regenerate_letter": "would have redrafted the letter",
    "reaudit_imagery": "would have re-audited the imagery",
    "flag": "would have flagged this for a human",
}


# Measured on 2026-08-20 by rendering the real prompts in prompts.py against a
# real corner, 6th and Mission, and counting characters over four. Two estimators
# agreed within 12 percent. See docs/GEMINI_WIRING.md.
#
# These are projections, not observations. No model has ever been called by this
# repository, so the actual spend is zero and every cost record says so. A
# projected number presented as a measured one is the same lie as a filter that
# matches nothing, and it would be a particularly cheap one to tell in a section
# titled "unit economics".
TIER1_PROMPT_TOKENS = 265
TIER1_OUTPUT_TOKENS = 77
TIER2_PROMPT_TOKENS = 402
TIER2_OUTPUT_TOKENS = 184


@dataclass(frozen=True)
class Cost:
    """What a model call would have cost, and what it actually cost.

    `actual_tokens` is zero on every entry this repository has ever written,
    because no model has ever been called. The field exists so that the day one
    is, the page does not have to change shape to start telling the truth.
    """

    projected_prompt_tokens: int = 0
    projected_output_tokens: int = 0
    actual_tokens: int = 0
    tiers_consulted: tuple[str, ...] = ()

    @property
    def projected_total(self) -> int:
        return self.projected_prompt_tokens + self.projected_output_tokens

    def to_dict(self) -> dict[str, int | list[str] | bool]:
        return {
            "projectedPromptTokens": self.projected_prompt_tokens,
            "projectedOutputTokens": self.projected_output_tokens,
            "actualTokens": self.actual_tokens,
            "tiersConsulted": list(self.tiers_consulted),
            # Stated on every single record rather than once in a footnote.
            "projectionOnly": self.actual_tokens == 0,
        }

    @staticmethod
    def for_tiers(*tiers: str) -> "Cost":
        prompt = out = 0
        for tier in tiers:
            if tier == "tier1":
                prompt += TIER1_PROMPT_TOKENS
                out += TIER1_OUTPUT_TOKENS
            elif tier == "tier2":
                prompt += TIER2_PROMPT_TOKENS
                out += TIER2_OUTPUT_TOKENS
        return Cost(
            projected_prompt_tokens=prompt,
            projected_output_tokens=out,
            actual_tokens=0,
            tiers_consulted=tuple(tiers),
        )


@dataclass
class TokenBudget:
    """A ceiling on model spend, separate from the ceiling on actions.

    The two limit different things and conflating them would be a bug. The action
    budget stops the agent doing too much to the world. This stops it spending too
    much thinking about it. An agent can exhaust either without touching the other.

    Enforced against projected tokens, which is the only kind this build has. When
    it runs out, the tier is not consulted and the entry says so, rather than the
    tier being consulted anyway and the number quietly going over.
    """

    limit: int = 0  # 0 means no ceiling
    spent: int = 0
    refused: int = 0

    @staticmethod
    def from_env() -> "TokenBudget":
        raw = os.environ.get("DAILY_TOKEN_BUDGET", "0")
        try:
            limit = int(raw)
        except ValueError:
            limit = 0
        return TokenBudget(limit=max(0, limit))

    @property
    def capped(self) -> bool:
        return self.limit > 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent) if self.capped else 0

    def take(self, cost: Cost) -> bool:
        """Reserve a projected call, or refuse it."""
        if not self.capped:
            self.spent += cost.projected_total
            return True
        if self.spent + cost.projected_total > self.limit:
            self.refused += 1
            return False
        self.spent += cost.projected_total
        return True

    def exhausted_note(self, tier: str) -> str:
        return (
            f"would have consulted {tier}, projected token budget of {self.limit} reached "
            f"after {self.spent}"
        )


@dataclass
class ActionBudget:
    limit: int = 40
    spent: int = 0
    refused: list[str] = field(default_factory=list)

    @staticmethod
    def from_env() -> "ActionBudget":
        raw = os.environ.get("DAILY_ACTION_BUDGET", "40")
        try:
            limit = int(raw)
        except ValueError:
            limit = 40
        return ActionBudget(limit=max(0, limit))

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def take(self, action: str) -> bool:
        """Spend one unit. False means the caller must journal an intent."""
        if self.spent >= self.limit:
            self.refused.append(action)
            return False
        self.spent += 1
        return True

    @staticmethod
    def intent_for(action: str) -> str:
        return f"{_INTENT_PHRASING.get(action, f'would have run {action}')}, budget reached"
