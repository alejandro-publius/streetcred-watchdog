"""The actor half: deliberate on what was escalated, then act or decline.

It receives an envelope off the bus and nothing else. No store reads for extra
context, no reaching back into the observer, because on Cloud Run it is a
separate service behind a push subscription and anything not in the envelope is
not available to it. Keeping that discipline locally is the only way the local
run says anything true about the deployed one.

Declines land in the journal in exactly the same shape as actions, with the same
fields and the same prominence. That is not a stylistic choice. If a decline
were journaled more thinly than an action, the diary would quietly become a
highlight reel again by way of the schema.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from .budget import ActionBudget, Cost, TokenBudget
from .ports import Actuator, Decider, Store
from .schema import Counts, Delta, JournalEntry, Tier1Verdict, Tier2Decision


@dataclass
class ActorResult:
    deliberated: int = 0
    acted: int = 0
    declined: int = 0
    actions_taken: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    artefacts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "deliberated": self.deliberated,
            "acted": self.acted,
            "declined": self.declined,
            "actions_taken": self.actions_taken,
            "intents": self.intents,
            "artefacts": self.artefacts,
        }


def _delta_from_wire(d: dict[str, Any]) -> Delta:
    return Delta(
        slug=d.get("slug", ""),
        name=d.get("name", ""),
        new_collisions=int(d.get("new_collisions") or 0),
        new_fatal=int(d.get("new_fatal") or 0),
        new_severe=int(d.get("new_severe") or 0),
        reports_311_change=int(d.get("reports_311_change") or 0),
        district_changed=bool(d.get("district_changed")),
        empty=bool(d.get("empty", True)),
        unreliable=bool(d.get("unreliable", False)),
        note=d.get("note", ""),
    )


def _counts_from_wire(d: dict[str, Any]) -> Counts:
    return Counts(
        collisions_5y=int(d.get("collisions_5y") or 0),
        fatal_5y=int(d.get("fatal_5y") or 0),
        severe_5y=int(d.get("severe_5y") or 0),
        reports_311_3y=int(d.get("reports_311_3y") or 0),
        district=d.get("district"),
    )


class Actor:
    def __init__(
        self,
        store: Store,
        decider: Decider,
        actuator: Actuator,
        budget: ActionBudget,
        *,
        degraded: str | None = None,
        run_id: str | None = None,
        tokens: TokenBudget | None = None,
    ):
        self.tokens = tokens or TokenBudget()
        self.run_id = run_id
        self.store = store
        self.decider = decider
        self.actuator = actuator
        self.budget = budget
        self.degraded = degraded
        self.result = ActorResult()

    async def handle(self, envelope: dict[str, Any]) -> None:
        corner = envelope.get("corner") or {}
        delta = _delta_from_wire(envelope.get("delta") or {})
        counts = _counts_from_wire(envelope.get("counts") or {})
        t1 = envelope.get("tier1") or {}
        tier1 = Tier1Verdict(
            significant=bool(t1.get("significant")),
            reason=t1.get("reason", ""),
            confidence=t1.get("confidence"),
            by_rule=bool(t1.get("byRule")),
            basis=t1.get("basis"),
        )

        projected = Cost.for_tiers("tier2")
        if not self.tokens.take(projected):
            # Not deliberated, not declined. Nothing looked at it, and the entry
            # has to say that rather than let an unspent thought read as restraint.
            note = self.tokens.exhausted_note("deliberation")
            self.result.intents.append(note)
            self.store.append_journal(
                JournalEntry(
                    ts=_now(), slug=corner.get("slug"), name=corner.get("name"),
                    delta=envelope.get("delta_summary") or delta.summary(),
                    trigger=envelope.get("trigger", "manual"), tier1=tier1,
                    intents=[note], degraded=self.degraded,
                    run_id=envelope.get("runId") or self.run_id,
                    cost=Cost().to_dict(),
                )
            )
            return

        self.result.deliberated += 1
        decision: Tier2Decision = await self.decider.decide(delta, corner, counts, tier1.reason)

        taken: list[str] = []
        intents: list[str] = []
        for action in decision.actions:
            if not self.budget.take(action):
                intents.append(ActionBudget.intent_for(action))
                continue
            artefact = await self._run(action, corner, counts, delta, decision.reasoning)
            taken.append(action)
            if artefact:
                self.result.artefacts.append(artefact)

        if taken:
            self.result.acted += 1
        else:
            self.result.declined += 1
        self.result.actions_taken.extend(taken)
        self.result.intents.extend(intents)

        self.store.append_journal(
            JournalEntry(
                ts=_now(),
                slug=corner.get("slug"),
                name=corner.get("name"),
                delta=envelope.get("delta_summary") or delta.summary(),
                trigger=envelope.get("trigger", "manual"),
                tier1=tier1,
                tier2=decision,
                actions=taken,  # type: ignore[arg-type]
                intents=intents,
                degraded=self.degraded,
                run_id=envelope.get("runId") or self.run_id,
                cost=_merge_cost(envelope.get("cost"), projected),
            )
        )

    async def _run(
        self, action: str, corner: dict[str, Any], counts: Counts, delta: Delta, reasoning: str
    ) -> str | None:
        if action == "rescore":
            return await self.actuator.rescore(corner, counts, reasoning)
        if action == "regenerate_letter":
            return await self.actuator.regenerate_letter(corner, counts, delta, reasoning)
        if action == "reaudit_imagery":
            return await self.actuator.reaudit_imagery(corner, counts, delta, reasoning)
        if action == "flag":
            return await self.actuator.flag(corner, reasoning)
        # An action the actuator does not implement is a bug in the decider, and
        # silently ignoring it would hide that bug behind a clean-looking run.
        raise ValueError(f"decider returned an action with no actuator verb: {action!r}")


def _merge_cost(tier1_cost: dict[str, Any] | None, tier2: Cost) -> dict[str, Any]:
    """Tier one's projection travels on the envelope; tier two's is added here."""
    if not tier1_cost:
        return tier2.to_dict()
    merged = dict(tier1_cost)
    merged["projectedPromptTokens"] = merged.get("projectedPromptTokens", 0) + tier2.projected_prompt_tokens
    merged["projectedOutputTokens"] = merged.get("projectedOutputTokens", 0) + tier2.projected_output_tokens
    merged["tiersConsulted"] = list(merged.get("tiersConsulted", [])) + list(tier2.tiers_consulted)
    merged["projectionOnly"] = merged.get("actualTokens", 0) == 0
    return merged


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
