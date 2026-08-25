"""The two-agent graph: the cheap tier, then the expensive one, and not always.

    SequentialAgent
      |
      +-- GemmaTriageAgent      runs on every delta, including the empty ones
      |     |
      |     +-- declines -----> the invocation ends here, and the entry is
      |                         journaled by the observer. Tier two is not built,
      |                         not called, and not billed.
      |
      +-- corner_watchdog_decider   only ever sees what tier one escalated

The conditional edge is the architecture, so it is worth saying what would be
lost without it. A `SequentialAgent` runs its sub-agents in order,
unconditionally, and the obvious way to build this graph is to let both run and
have the second one return early on a declined delta. That version produces the
same journal and costs money on every corner every morning, because the
expensive tier has already been invoked by the time it discovers it had nothing
to do. Across the 175 evaluations in this repository's real journal, the number
that would have reached tier two is four. The gate is what keeps the other 171
free.

The gate is a `before_agent_callback` on tier two rather than `end_invocation`
on tier one, and the difference is not stylistic. Every sub-agent runs against
its own copy of the invocation context, so a triage agent setting
`ctx.end_invocation` ends its own invocation and the sequence carries on to tier
two regardless. That version looks correct, passes any test that only reads the
journal, and bills a model on every quiet corner. A callback that returns
content is checked by `BaseAgent.run_async` before `_run_async_impl` is entered
at all, so tier two is skipped rather than entered and excused.

`GemmaTriageAgent` wraps the triage path rather than reimplementing it. It calls
`rule_verdict` from delta.py and then the same `Triage` implementation the
observer holds, in that order, which is the order the observer has always used:
the deterministic floor answers anything involving a death, a severe injury, an
unreliable comparison or an empty delta before a model is consulted at all, and
only the ambiguous middle reaches the reflex tier. Behaviour is identical
because it is the same two calls, not because it was carefully matched.

The graph takes a JSON envelope as its input message: the same envelope the bus
carries between the observer and the actor. That is what makes `adk web` show a
real escalation rather than a demo of itself. A message that is not that
envelope is refused by name rather than guessed at, because a graph that invents
a delta when it cannot read one is the failure this repository is about.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from .brains import RuleTriage
from .delta import rule_verdict
from .ports import Triage
from .prompts import deliberation_case
from .schema import Calibration, Counts, Delta, Tier1Verdict

TRIAGE_AGENT_NAME = "gemma_triage"
GRAPH_NAME = "corner_watchdog"

# Where tier one leaves its verdict for tier two and for the trace.
VERDICT_KEY = "tier1"
ENVELOPE_KEY = "envelope"


class MalformedEnvelope(ValueError):
    """The message this graph was given is not a delta envelope."""


def parse_envelope(text: str) -> dict[str, Any]:
    """Read the bus envelope out of the incoming message, or refuse.

    Refuses rather than falling back to a blank delta. An empty delta is a
    perfectly valid input to this graph and it means "nothing changed at this
    corner", so silently producing one from an unreadable message would turn a
    malformed input into a confident statement about a street.
    """
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as e:
        raise MalformedEnvelope(
            "this graph takes the JSON envelope the bus carries between the observer and "
            f"the actor, and the message it was given is not JSON: {e}. Nothing was decided. "
            "Run `corner_watchdog rehearse` or read state/journal.jsonl for a real one."
        ) from None
    if not isinstance(loaded, dict) or "delta" not in loaded:
        raise MalformedEnvelope(
            "the message parsed as JSON but carries no `delta`, so there is nothing to "
            "triage. Nothing was decided."
        )
    return loaded


def delta_from_envelope(d: dict[str, Any]) -> Delta:
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


def counts_from_envelope(d: dict[str, Any]) -> Counts:
    return Counts(
        collisions_5y=int(d.get("collisions_5y") or 0),
        fatal_5y=int(d.get("fatal_5y") or 0),
        severe_5y=int(d.get("severe_5y") or 0),
        reports_311_3y=int(d.get("reports_311_3y") or 0),
        district=d.get("district"),
    )


class GemmaTriageAgent(BaseAgent):
    """Tier one as a node in the graph. Cheap, runs on everything, ends most of them."""

    triage: Triage = None  # type: ignore[assignment]
    calibration: Calibration = None  # type: ignore[assignment]

    def __init__(
        self,
        *,
        triage: Triage | None = None,
        calibration: Calibration | None = None,
        name: str = TRIAGE_AGENT_NAME,
    ) -> None:
        super().__init__(
            name=name,
            description=(
                "Decides whether a change in a corner's public record is worth spending "
                "expensive deliberation on. Most changes are not."
            ),
            triage=triage or RuleTriage("no Gemma client is wired in this build"),
            calibration=calibration or Calibration(),
        )

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        text = _incoming_text(ctx)
        try:
            envelope = parse_envelope(text)
        except MalformedEnvelope as e:
            # A verdict is still written, and it is a refusal. Leaving the session
            # blank would look equivalent and is not: the gate treats a blank
            # session as "this agent was invoked directly", which is exactly the
            # open case, so an unreadable message would fall straight through
            # into the expensive tier with no delta at all.
            yield self._say(
                ctx, str(e),
                state={VERDICT_KEY: Tier1Verdict(
                    significant=False, reason=str(e), by_rule=True, basis="unreliable",
                ).to_dict()},
            )
            return

        delta = delta_from_envelope(envelope.get("delta") or {})
        corner = envelope.get("corner") or {}

        # The same two calls the observer makes, in the same order. The floor
        # first, so a death never reaches a model to be talked out of.
        ruled = rule_verdict(delta, self.calibration)
        if ruled is not None:
            significant, reason = ruled
            verdict = Tier1Verdict(significant=significant, reason=reason, by_rule=True)
        else:
            verdict = await self.triage.judge(delta, corner, self.calibration)

        # Carried on the event as a state delta rather than assigned onto the
        # session object. A direct assignment is visible to the next sub-agent in
        # this process and to nothing else: it never reaches the session service,
        # so it is absent from a reloaded session and absent from the State tab in
        # `adk web`, which is the one place a demo viewer would look for it.
        state = {ENVELOPE_KEY: envelope, VERDICT_KEY: verdict.to_dict()}

        if not verdict.significant:
            # The whole point of the cheap tier. The verdict is already on the
            # session, and `_gate_on_triage` below reads it and skips tier two,
            # so nothing expensive is invoked and nothing expensive is billed.
            yield self._say(
                ctx,
                f"Declined at tier one. {verdict.reason}\n\n"
                "Tier two was not consulted, so nothing expensive ran for this corner.",
                state=state,
            )
            return

        # Escalated. Hand tier two the case in the shape it reads.
        case = deliberation_case(
            name=delta.name or corner.get("name") or delta.slug,
            grade=corner.get("grade"),
            index=corner.get("index"),
            delta=envelope.get("delta_summary") or delta.summary(),
            escalation_reason=verdict.reason,
            counts=counts_from_envelope(envelope.get("counts") or {}),
            letter_age=corner.get("letterDrafted") or "unknown",
        )
        yield self._say(ctx, f"Escalated by tier one. {verdict.reason}\n\n{case}", state=state)

    def _say(
        self, ctx: InvocationContext, body: str, *, state: dict[str, Any] | None = None
    ) -> Event:
        return Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=types.Content(role="model", parts=[types.Part(text=body)]),
            actions=EventActions(state_delta=dict(state or {})),
        )


def _incoming_text(ctx: InvocationContext) -> str:
    content = getattr(ctx, "user_content", None)
    if content is None:
        return ""
    return "\n".join(part.text for part in (content.parts or []) if part.text)


def _gate_on_triage(callback_context) -> types.Content | None:
    """The conditional edge. Returning content here means tier two never runs.

    An absent verdict means this agent was not run through the graph at all, by
    `AdkDecider.decide` or by the eval harness, and the gate stays open: tier two
    is being invoked directly there, which is a decision the caller has already
    made.

    Every path through the triage agent writes a verdict, including the one that
    could not read its input, precisely so that "no verdict" keeps meaning "no
    triage ran" and never comes to mean "triage ran and said nothing".
    """
    state = callback_context.state
    if VERDICT_KEY not in state:
        return None

    verdict = state.get(VERDICT_KEY) or {}
    if verdict.get("significant"):
        return None

    reason = verdict.get("reason") or "tier one did not escalate this change."
    return types.Content(
        role="model",
        parts=[types.Part(text=(
            "Tier two was not consulted. The cheap tier settled this corner and the "
            f"expensive one was never invoked, so nothing was spent on it. {reason}"
        ))],
    )


def build_graph(
    decider_agent: LlmAgent,
    *,
    triage: Triage | None = None,
    calibration: Calibration | None = None,
    name: str = GRAPH_NAME,
) -> SequentialAgent:
    """The two-agent graph the architecture diagram shows.

    `SequentialAgent` carries a deprecation warning at this version of the ADK,
    which names `Workflow` as its replacement. It is kept because the same
    deprecation note says a Workflow cannot yet be used as an `LlmAgent`
    sub-agent, and because the migration is a change of shape rather than of
    behaviour, which is not what a build with a deadline on it should be
    spending its remaining risk on. The note is here so the next person does not
    have to rediscover it.
    """
    existing = decider_agent.before_agent_callback
    if existing is None:
        decider_agent.before_agent_callback = _gate_on_triage
    elif isinstance(existing, list):
        decider_agent.before_agent_callback = [_gate_on_triage, *existing]
    else:
        decider_agent.before_agent_callback = [_gate_on_triage, existing]

    return SequentialAgent(
        name=name,
        description=(
            "Watches a San Francisco intersection's public record, decides whether a change "
            "is worth acting on, and publishes the decision either way."
        ),
        sub_agents=[
            GemmaTriageAgent(triage=triage, calibration=calibration),
            decider_agent,
        ],
    )
