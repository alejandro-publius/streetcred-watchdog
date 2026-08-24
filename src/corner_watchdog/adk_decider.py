"""Tier two as an ADK agent, where restraint is a tool rather than an absence.

This is the design claim of the whole project written as code, so it is worth
stating before the imports.

The agent has a tool for every action it can take. It also has `decline`, which
takes structured reasoning and does nothing. The agent must call exactly one of
them. There is no path through this module where a deliberation ends in silence:
a decision to leave a corner alone is made the same way as a decision to redraft
its letter, by naming it, justifying it in the terms the contract demands, and
signing it with a tool call that lands in the journal in the same shape.

That matters because of what the alternative looks like. An agent asked to
"return actions" and returning an empty list has not decided anything; it has
failed to produce output, and the two are indistinguishable downstream. The
restraint rate on the public ledger is the headline number of this repository,
and a number assembled from absences is not evidence of judgment. So the absence
is removed from the design: doing nothing is a signed decision here.

Two seams are kept deliberately narrow.

`AdkDecider` satisfies the same `Decider` protocol `RuleDecider` does and returns
the same `Tier2Decision`. The actor cannot tell which one it has, which is what
makes `DECIDER=rule` a real comparison rather than a different program.

The tool arguments are the fields `contract.py` already validates, and the
decision is assembled into a dict and pushed through `parse_deliberation` before
it becomes a `Tier2Decision`. A tool call is not trusted more than a JSON blob
was. It goes through the same gate, so an entry written by this path is
indistinguishable in shape from one written by the old one, and every rule the
contract enforces (name the claim, do not repeat actions, do not attach actions
to a decline) applies here without being restated.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool
from google.genai import types

from .budget import ActionBudget
from .config import deliberation_model
from .contract import ContractViolation, parse_deliberation
from .guardrails import budget_note, screen_all
from .ports import DeliberationError, DeliberationRequest
from .prompts import (
    DELIBERATION_TOOL_INSTRUCTION,
    DELIBERATION_TOOL_VERSION,
    deliberation_case,
)
from .schema import Counts, Delta, JournalEntry, Tier2Decision

APP_NAME = "corner-watchdog"

# Where the signed decision is parked on the session so that callbacks, the
# `adk web` state view and this module all read one record rather than three.
DECISION_KEY = "deliberation"

# The tool the model calls, and the action the journal stores. They differ in
# one place only: the journal has said `reaudit_imagery` since the first commit
# and renaming a value that is already written into an append-only file would
# make the history unreadable, so the tool is `re_audit` and the mapping is here
# rather than in a rename.
TOOL_TO_ACTION = {
    "rescore": "rescore",
    "regenerate_letter": "regenerate_letter",
    "re_audit": "reaudit_imagery",
    "flag": "flag",
}
ACTION_TO_TOOL = {action: tool for tool, action in TOOL_TO_ACTION.items()}

ACTION_TOOLS = tuple(TOOL_TO_ACTION)
DECLINE_TOOL = "decline"
ALL_TOOLS = (*ACTION_TOOLS, DECLINE_TOOL)


__all__ = [
    "ACTION_TOOLS",
    "ALL_TOOLS",
    "TOOL_TO_ACTION",
    "AdkDecider",
    "DeliberationError",
    "DeliberationOutcome",
    "DeliberationRequest",
    "Guardrails",
    "build_decider_agent",
]

# Set by the before-model gates when they stop a deliberation reaching the model.
SHORT_CIRCUIT_KEY = "short_circuit"


@dataclass
class DeliberationOutcome:
    """What actually happened, for the actor to finish and for tests to read."""

    decision: Tier2Decision | None = None
    taken: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    journaled: bool = False
    model_reached: bool = False
    short_circuit: str | None = None


@dataclass
class Guardrails:
    """The gates the callbacks enforce, and where the journal entry lands.

    Optional as a whole. Without it the decider is a plain `Decider` that decides
    and returns, which is what the eval harness and most of the tests want. With
    it, the daily action budget, the injection screen and the journal write all
    move inside the ADK invocation, which is what production runs on.
    """

    action_budget: ActionBudget | None = None
    journal: Callable[[JournalEntry], None] | None = None


def _resolve_actions(primary: str, also: list[str] | None) -> list[str]:
    """The full ordered action list this one tool call commits to.

    `also` is named in the model's vocabulary, which is tool names, and comes
    back in the journal's vocabulary, which is action names. Unknown entries are
    left as they are so `parse_deliberation` rejects them by name rather than
    this function silently dropping something the model asked for.
    """
    ordered = [TOOL_TO_ACTION[primary]]
    for name in also or []:
        cleaned = str(name).strip()
        ordered.append(TOOL_TO_ACTION.get(cleaned, cleaned))
    # De-duplicate while holding the order the reasoning explains them in.
    return list(dict.fromkeys(ordered))


def _sign(
    tool_context: ToolContext,
    *,
    tool: str,
    reasoning: str,
    published_claim_now_wrong: str | None = None,
    still_accurate: str | None = None,
    also: list[str] | None = None,
) -> dict[str, Any]:
    """Record one signed decision on the session, and hand it back to the model.

    Every tool in this module ends here, so the record has one shape whether the
    agent acted or declined. `signatures` counts rather than overwrites: the
    enforcement of "exactly one" reads this, and a second call has to be visible
    to be refused.
    """
    if tool == DECLINE_TOOL:
        record = {
            "verdict": "decline",
            "reasoning": reasoning,
            "actions": [],
            "still_accurate": still_accurate,
        }
    else:
        record = {
            "verdict": "act",
            "reasoning": reasoning,
            "actions": _resolve_actions(tool, also),
            "published_claim_now_wrong": published_claim_now_wrong,
        }

    signed = list(tool_context.state.get("signatures") or [])
    signed.append(tool)
    tool_context.state["signatures"] = signed
    tool_context.state[DECISION_KEY] = record
    return {"recorded": tool, "actions": record["actions"]}


# ------------------------------------------------------------------- the tools
#
# One per action, plus decline. The docstrings are the tool descriptions the
# model reads, and the annotations are the schema, so both are written for the
# reader who is a model rather than for the one who is a maintainer.


def rescore(
    reasoning: str,
    published_claim_now_wrong: str,
    also: list[str],
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Recompute the corner's Danger Index because its published score is now wrong.

    Args:
      reasoning: Two to four plain sentences, published verbatim on a public page.
      published_claim_now_wrong: The published figure or sentence this change has
        made inaccurate. Required. You may not name an action before you have
        named the claim it corrects.
      also: Every other tool this same decision commits to, by name, or an empty
        list when this is the only one.
    """
    return _sign(
        tool_context, tool="rescore", reasoning=reasoning,
        published_claim_now_wrong=published_claim_now_wrong, also=also,
    )


def regenerate_letter(
    reasoning: str,
    published_claim_now_wrong: str,
    also: list[str],
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Redraft the corner's public letter because it states a figure that has moved.

    Args:
      reasoning: Two to four plain sentences, published verbatim on a public page.
      published_claim_now_wrong: The sentence in the letter that is now inaccurate.
        Required.
      also: Every other tool this same decision commits to, by name, or an empty
        list when this is the only one.
    """
    return _sign(
        tool_context, tool="regenerate_letter", reasoning=reasoning,
        published_claim_now_wrong=published_claim_now_wrong, also=also,
    )


def re_audit(
    reasoning: str,
    published_claim_now_wrong: str,
    also: list[str],
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Re-audit the corner's imagery because the change implicates something visible there.

    Args:
      reasoning: Two to four plain sentences, published verbatim on a public page.
      published_claim_now_wrong: The published claim about this corner that the
        imagery would settle. Required.
      also: Every other tool this same decision commits to, by name, or an empty
        list when this is the only one.
    """
    return _sign(
        tool_context, tool="re_audit", reasoning=reasoning,
        published_claim_now_wrong=published_claim_now_wrong, also=also,
    )


def flag(
    reasoning: str,
    published_claim_now_wrong: str,
    also: list[str],
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Put this corner in front of a human. Mandatory alongside any redraft on a new fatality.

    Args:
      reasoning: Two to four plain sentences, published verbatim on a public page.
      published_claim_now_wrong: What a human needs to look at and why. Required.
      also: Every other tool this same decision commits to, by name, or an empty
        list when this is the only one.
    """
    return _sign(
        tool_context, tool="flag", reasoning=reasoning,
        published_claim_now_wrong=published_claim_now_wrong, also=also,
    )


def decline(
    reasoning: str,
    still_accurate: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Decide that nothing published about this corner is wrong, so nothing should change.

    This is a first-class decision and the most common correct outcome. It is not
    a fallback and it is not a failure. It is journaled and published at exactly
    the same weight as the four action tools, with your reasoning attached.

    Args:
      reasoning: Two to four plain sentences, published verbatim on a public page,
        saying what you weighed and why it did not clear the bar.
      still_accurate: The published claim about this corner that remains true after
        this change. Required. A decline has to name what it is leaving alone.
    """
    return _sign(
        tool_context, tool=DECLINE_TOOL, reasoning=reasoning, still_accurate=still_accurate,
    )


def build_decider_agent(*, model: str | Any | None = None, name: str = "corner_watchdog_decider") -> LlmAgent:
    """The judgment agent, with its five tools and nothing else.

    `model` accepts a `BaseLlm` instance as well as a string, which is how the
    tests drive the real graph against a scripted model without a network.
    """
    return LlmAgent(
        name=name,
        model=model if model is not None else deliberation_model(),
        description=(
            "Decides what a street-safety monitor should do about a change in San Francisco's "
            "public records, including deciding to do nothing."
        ),
        instruction=DELIBERATION_TOOL_INSTRUCTION,
        tools=[rescore, regenerate_letter, re_audit, flag, decline],
    )


class AdkDecider:
    """Tier two, run as an ADK agent. Satisfies the same protocol as RuleDecider."""

    def __init__(
        self,
        *,
        model: str | Any | None = None,
        why_degraded: str | None = None,
        guardrails: Guardrails | None = None,
    ) -> None:
        self._model_name = (
            model if isinstance(model, str) or model is None
            else getattr(model, "model", str(model))
        )
        self._why = why_degraded
        self.guardrails = guardrails or Guardrails()
        # What the actor handed over for the deliberation now in flight, and what
        # came out of it. Deciding is sequential by construction, see the comment
        # in observer.sweep: fetching is concurrent, deciding is not, because
        # journal order and budget spending have to be reproducible.
        self.request: DeliberationRequest | None = None
        self.outcome = DeliberationOutcome()
        self.last_signatures: list[str] = []

        self.agent = build_decider_agent(model=model)
        self.agent.before_model_callback = [self._gate_budget, self._gate_injection]
        self.agent.after_tool_callback = self._write_journal
        self._runner = InMemoryRunner(agent=self.agent, app_name=APP_NAME)

    # ------------------------------------------------------------- the handshake

    def begin(self, request: DeliberationRequest) -> None:
        """Accept the journal context for the deliberation about to run."""
        self.request = request
        self.outcome = DeliberationOutcome()

    # -------------------------------------------------------- before the model

    def _gate_budget(
        self, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        """The daily action budget, checked before a token is spent thinking.

        Returning a response here means the model is never called. That is the
        property worth having: an exhausted budget produces an entry saying
        nothing looked at this corner, rather than a deliberation whose
        conclusions are then thrown away, which costs money to reach a foregone
        conclusion and reads in the journal as though a decision was made.
        """
        budget = self.guardrails.action_budget
        if budget is None or budget.remaining > 0:
            return None

        note = budget_note(budget.spent, budget.limit)
        callback_context.state[SHORT_CIRCUIT_KEY] = {"kind": "budget", "note": note}
        self._journal_short_circuit(intents=[note])
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="Not deliberated: the daily action budget is spent.")],
            )
        )

    def _gate_injection(
        self, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        """The prompt-injection screen, on text that arrived from a public API.

        Runs against the request the model is actually about to receive rather
        than against the delta the actor was handed, because those are only the
        same thing while nothing in between edits it, and a screen that checks a
        different string than the one that gets sent is not a screen.
        """
        finding = screen_all(_request_text(llm_request))
        if not finding:
            return None

        callback_context.state[SHORT_CIRCUIT_KEY] = {"kind": "screened", "note": str(finding)}
        self._journal_short_circuit(intents=[str(finding)])
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="Not deliberated: the input was screened.")],
            )
        )

    # ---------------------------------------------------------- after the tool

    def _write_journal(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        """The journal entry, written where the decision was signed.

        The action budget is spent here too, one unit per action, so that the
        entry records what was actually carried out and what the budget refused.
        The actor then runs the actuator verbs for the actions this allowed. That
        ordering is the same one the actor used to run itself; what changed is
        that the record is now written at the moment of the signature rather than
        after a round trip.
        """
        record = tool_context.state.get(DECISION_KEY)
        if not record:
            return None

        try:
            decision = parse_deliberation(dict(record))
        except ContractViolation:
            # Left for decide() to raise on. Journaling a decision the contract
            # rejects would put an unvalidated record in an append-only file.
            return None

        # The outcome is recorded whether or not anybody asked for a journal
        # entry, because it is this decider's own account of what it just did.
        # Only the write below is conditional, and `journaled` says which
        # happened, so the actor knows whether it still owes an entry.
        taken, intents = self._spend(list(decision.actions))
        tier2 = decision.to_tier2_decision()
        self.outcome.decision = tier2
        self.outcome.taken = taken
        self.outcome.intents = intents

        if self.guardrails.journal is None or self.request is None:
            return None
        self.outcome.journaled = True

        r = self.request
        self.guardrails.journal(
            JournalEntry(
                ts=_now(),
                slug=r.slug,
                name=r.name,
                delta=r.delta_summary,
                trigger=r.trigger,  # type: ignore[arg-type]
                tier1=r.tier1,
                tier2=tier2,
                actions=taken,  # type: ignore[arg-type]
                intents=intents,
                degraded=r.degraded,
                run_id=r.run_id,
                cost=r.cost,
            )
        )
        return None

    def _spend(self, actions: list[str]) -> tuple[list[str], list[str]]:
        budget = self.guardrails.action_budget
        if budget is None:
            return actions, []
        taken: list[str] = []
        intents: list[str] = []
        for action in actions:
            if budget.take(action):
                taken.append(action)
            else:
                intents.append(ActionBudget.intent_for(action))
        return taken, intents

    def _journal_short_circuit(self, *, intents: list[str]) -> None:
        """An entry for a deliberation that never happened. Never a decline.

        No tier two, so the ledger sees an entry with intents and no actions,
        which `_wanted_to_act` already keeps out of the restraint rate.
        """
        self.outcome.intents = list(intents)
        self.outcome.short_circuit = intents[0] if intents else None
        if self.guardrails.journal is None or self.request is None:
            return
        r = self.request
        self.guardrails.journal(
            JournalEntry(
                ts=_now(),
                slug=r.slug,
                name=r.name,
                delta=r.delta_summary,
                trigger=r.trigger,  # type: ignore[arg-type]
                tier1=r.tier1,
                intents=list(intents),
                degraded=r.degraded,
                run_id=r.run_id,
                cost=r.cost,
            )
        )
        self.outcome.journaled = True

    def describe(self) -> str:
        return (
            f"AdkDecider, google.adk LlmAgent with {len(ALL_TOOLS)} tools "
            f"({', '.join(ALL_TOOLS)}), model {self._model_name or 'unset'}, "
            f"{DELIBERATION_TOOL_VERSION}"
        )

    @property
    def degraded(self) -> str | None:
        """None when the model genuinely ran.

        Unlike the stand-ins, this returns None on the happy path, because on the
        happy path a model did run. It carries a sentence only when the caller
        had a reason to say otherwise.
        """
        return self._why

    async def decide(
        self, delta: Delta, corner: dict[str, Any], counts: Counts, escalation_reason: str
    ) -> Tier2Decision:
        case = deliberation_case(
            name=delta.name,
            grade=corner.get("grade"),
            index=corner.get("index"),
            delta=delta.summary(),
            escalation_reason=escalation_reason,
            counts=counts,
        )
        record, signatures = await self._run(case)
        self.last_signatures = signatures

        if record is None:
            # A gate stopped this before the model. Already journaled as an
            # intent by the callback that stopped it, and not a decision, so
            # there is nothing here for the contract to validate.
            return Tier2Decision(reasoning=self.outcome.short_circuit or "", actions=[])

        try:
            decision = parse_deliberation(record)
        except ContractViolation as e:
            raise DeliberationError(
                f"the agent signed {signatures} but the result does not satisfy the decision "
                f"contract: {e}"
            ) from e
        decided = decision.to_tier2_decision()
        self.outcome.decision = self.outcome.decision or decided
        return decided

    async def _run(self, case: str) -> tuple[dict[str, Any] | None, list[str]]:
        """One deliberation. Returns the signed record, or None if a gate stopped it."""
        session = await self._runner.session_service.create_session(
            app_name=APP_NAME, user_id="watchdog", session_id=uuid.uuid4().hex,
        )
        message = types.Content(role="user", parts=[types.Part(text=case)])

        async for _event in self._runner.run_async(
            user_id="watchdog", session_id=session.id, new_message=message,
        ):
            pass

        finished = await self._runner.session_service.get_session(
            app_name=APP_NAME, user_id="watchdog", session_id=session.id,
        )
        state = dict(finished.state) if finished else {}
        signatures = list(state.get("signatures") or [])
        record = state.get(DECISION_KEY)

        stopped = state.get(SHORT_CIRCUIT_KEY)
        if stopped:
            # A gate refused this before the model. Not an error and not a
            # decline: nothing was asked and nothing answered.
            self.outcome.model_reached = False
            return None, signatures
        self.outcome.model_reached = True

        # Exactly one. Both directions are errors and neither is a decline.
        if not signatures or not record:
            raise DeliberationError(
                "the deliberation ended without a tool call. Prose is not a decision here: "
                "nothing was signed, so there is nothing to journal and nothing to act on. "
                "Recording this as a decline would put a failure of the agent into the "
                "numerator of the restraint rate."
            )
        if len(signatures) > 1:
            # The state holds whichever ran last, so acting on it would be acting
            # on an arbitrary one of several conflicting decisions.
            raise DeliberationError(
                f"the deliberation signed {len(signatures)} tools ({', '.join(signatures)}) "
                "and exactly one is allowed. A decision that names itself more than once is "
                "not a decision, and the last one to run is not the right one by virtue of "
                "having run last."
            )
        return dict(record), signatures

    async def aclose(self) -> None:
        await self._runner.close()


def _request_text(llm_request: LlmRequest) -> dict[str, str]:
    """The text of a model request, by where it came from.

    The system instruction is this repository's own prose and is screened anyway.
    A screen that trusts one field because of who is believed to have written it
    is a screen with a hole in it shaped like whoever gets to write that field.
    """
    fields: dict[str, str] = {}
    config = getattr(llm_request, "config", None)
    instruction = getattr(config, "system_instruction", None)
    if isinstance(instruction, str):
        fields["the agent instruction"] = instruction

    parts: list[str] = []
    for content in llm_request.contents or []:
        for part in content.parts or []:
            if part.text:
                parts.append(part.text)
    if parts:
        fields["the delta text"] = "\n".join(parts)
    return fields


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
