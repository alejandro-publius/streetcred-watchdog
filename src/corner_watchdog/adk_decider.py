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

import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.genai import types

from .config import deliberation_model
from .contract import ContractViolation, parse_deliberation
from .prompts import (
    DELIBERATION_TOOL_INSTRUCTION,
    DELIBERATION_TOOL_VERSION,
    deliberation_case,
)
from .schema import Counts, Delta, Tier2Decision

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


class DeliberationError(RuntimeError):
    """The agent did not produce a decision this system can act on.

    Raised rather than converted into a decline. A run that returned prose has
    not declined; nothing weighed the change and nothing signed anything, and
    recording it as restraint would put a failure of the agent into the numerator
    of the number this project asks to be judged on.
    """


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

    def __init__(self, *, model: str | Any | None = None, why_degraded: str | None = None) -> None:
        self._model_name = (
            model if isinstance(model, str) or model is None
            else getattr(model, "model", str(model))
        )
        self._why = why_degraded
        self.agent = build_decider_agent(model=model)
        self._runner = InMemoryRunner(agent=self.agent, app_name=APP_NAME)
        # What the last deliberation actually did, for the actor and the tests.
        # Deciding is sequential by construction, see observer.sweep.
        self.last_signatures: list[str] = []

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

        try:
            decision = parse_deliberation(record)
        except ContractViolation as e:
            raise DeliberationError(
                f"the agent signed {signatures} but the result does not satisfy the decision "
                f"contract: {e}"
            ) from e
        return decision.to_tier2_decision()

    async def _run(self, case: str) -> tuple[dict[str, Any], list[str]]:
        """One deliberation. Returns the signed record and which tools signed it."""
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

        if not record:
            raise DeliberationError(
                "the deliberation ended without a tool call. Prose is not a decision here: "
                "nothing was signed, so there is nothing to journal and nothing to act on."
            )
        return dict(record), signatures

    async def aclose(self) -> None:
        await self._runner.close()
