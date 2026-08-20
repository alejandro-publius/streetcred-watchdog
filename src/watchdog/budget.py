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
