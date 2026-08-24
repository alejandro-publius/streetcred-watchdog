"""The two-agent graph, and the one edge that is not just wiring.

Everything here is really one assertion said several ways: tier two must not be
invoked for a corner tier one settled. It is the difference between an agent
that costs four model calls across 175 evaluations and one that costs 175, and
it is the property that would break silently, because a graph that runs both
tiers every time produces exactly the same journal as one that does not.

So the tests read `model.was_called` rather than the journal. The journal cannot
tell the difference, which is the whole reason this file exists.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from scripted_model import call, scripted, text

from corner_watchdog.adk_decider import build_decider_agent
from corner_watchdog.adk_graph import (
    GRAPH_NAME,
    TRIAGE_AGENT_NAME,
    VERDICT_KEY,
    GemmaTriageAgent,
    MalformedEnvelope,
    build_graph,
    parse_envelope,
)
from corner_watchdog.brains import RuleTriage
from corner_watchdog.delta import rule_verdict
from corner_watchdog.schema import Calibration, Delta

REASONING = (
    "The letter on this corner's page states its collision figures outright, and those figures "
    "have moved, so a sentence a resident reads there is now behind the city's own record."
)
CLAIM = "The letter says 40 injury collisions in five years; the record now shows 42."

BASE = {
    "corner": {"slug": "a", "name": "6th and Mission", "grade": "F", "index": 99},
    "delta_summary": "6th and Mission: 2 new injury collisions.",
    "counts": {"collisions_5y": 42, "fatal_5y": 1, "severe_5y": 3, "reports_311_3y": 120},
}


def envelope(**delta) -> dict:
    base = {"slug": "a", "name": "6th and Mission", "empty": False}
    base.update(delta)
    return {**BASE, "delta": base}


def acting_model():
    return scripted(
        [call("rescore", reasoning=REASONING, published_claim_now_wrong=CLAIM, also=[])],
        [text("done")],
    )


def drive(message: str, model):
    """Run the graph on one message and report what happened."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    graph = build_graph(build_decider_agent(model=model))

    async def go():
        runner = InMemoryRunner(agent=graph, app_name="t")
        session = await runner.session_service.create_session(app_name="t", user_id="u")
        authors, tools, said = [], [], []
        async for event in runner.run_async(
            user_id="u",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            authors.append(event.author)
            for part in (event.content.parts if event.content else []) or []:
                if part.function_call:
                    tools.append(part.function_call.name)
                if part.text:
                    said.append(part.text)
        finished = await runner.session_service.get_session(
            app_name="t", user_id="u", session_id=session.id
        )
        return authors, tools, said, dict(finished.state if finished else {})

    return asyncio.run(go())


# ============================================================ the conditional edge

def test_a_declined_delta_never_reaches_tier_two():
    """The assertion the cost-routed cascade rests on. The journal cannot show this."""
    model = acting_model()
    authors, tools, _said, _state = drive(json.dumps(envelope(empty=True)), model)

    assert model.was_called is False, "the expensive tier was invoked for a quiet corner"
    assert tools == []
    assert TRIAGE_AGENT_NAME in authors


def test_an_escalated_delta_does_reach_tier_two():
    """The gate has to be a gate, not a wall."""
    model = acting_model()
    _authors, tools, _said, _state = drive(json.dumps(envelope(new_collisions=2)), model)

    assert model.was_called is True
    assert tools == ["rescore"]


def test_a_new_fatality_reaches_tier_two_by_rule_without_consulting_tier_one():
    """A death is settled by the floor, before any reflex model could be talked out of it."""
    model = acting_model()
    _authors, tools, _said, state = drive(
        json.dumps(envelope(new_fatal=1, new_collisions=1)), model
    )

    assert state[VERDICT_KEY]["byRule"] is True
    assert tools == ["rescore"]


def test_an_ordinary_311_wobble_is_settled_by_tier_one_alone():
    model = acting_model()
    _authors, tools, _said, state = drive(json.dumps(envelope(reports_311_change=3)), model)

    assert model.was_called is False
    assert state[VERDICT_KEY]["significant"] is False
    assert tools == []


# ================================================================ behaviour identical

@pytest.mark.parametrize(
    "delta_kwargs",
    [
        {"empty": True},
        {"new_fatal": 1, "new_collisions": 1},
        {"new_severe": 1, "new_collisions": 1},
        {"new_collisions": 2},
        {"reports_311_change": 3},
        {"reports_311_change": 22},
        {"district_changed": True},
        {"empty": True, "unreliable": True, "note": "a snapshot was incomplete"},
    ],
)
def test_the_graph_reaches_the_same_verdict_as_the_path_it_wraps(delta_kwargs):
    """Identical because it is the same two calls, not because it was matched by hand."""
    model = acting_model()
    _authors, _tools, _said, state = drive(json.dumps(envelope(**delta_kwargs)), model)

    base = {"slug": "a", "name": "6th and Mission", "empty": False}
    base.update(delta_kwargs)
    delta = Delta(**base)
    calibration = Calibration()

    ruled = rule_verdict(delta, calibration)
    if ruled is not None:
        expected_significant, expected_reason = ruled
    else:
        verdict = asyncio.run(
            RuleTriage("under test").judge(delta, BASE["corner"], calibration)
        )
        expected_significant, expected_reason = verdict.significant, verdict.reason

    assert state[VERDICT_KEY]["significant"] is expected_significant
    assert state[VERDICT_KEY]["reason"] == expected_reason


# ================================================================= the input contract

def test_a_message_that_is_not_an_envelope_is_refused_by_name():
    with pytest.raises(MalformedEnvelope, match="not JSON"):
        parse_envelope("have a look at 6th and mission please")


def test_json_without_a_delta_is_refused_rather_than_treated_as_no_change():
    with pytest.raises(MalformedEnvelope, match="no `delta`"):
        parse_envelope('{"corner": {"slug": "a"}}')


def test_an_unreadable_message_does_not_fall_through_into_the_expensive_tier():
    """The dangerous direction. An open gate here bills a model on garbage input."""
    model = acting_model()
    _authors, tools, said, state = drive("hello there", model)

    assert model.was_called is False
    assert tools == []
    assert state[VERDICT_KEY]["significant"] is False
    assert any("not JSON" in s for s in said)


# ======================================================================= the shape

def test_the_graph_is_two_agents_in_order():
    graph = build_graph(build_decider_agent(model=scripted()))

    assert graph.name == GRAPH_NAME
    assert [a.name for a in graph.sub_agents] == [TRIAGE_AGENT_NAME, "corner_watchdog_decider"]


def test_the_triage_agent_holds_a_triage_implementation_rather_than_its_own_rules():
    agent = GemmaTriageAgent()
    assert isinstance(agent.triage, RuleTriage)


def test_the_agent_package_exposes_the_same_graph_adk_web_would_load():
    """A console that runs a different agent than production is a demo of itself."""
    import sys
    from pathlib import Path

    agents_dir = str(Path(__file__).resolve().parents[1] / "agents")
    if agents_dir not in sys.path:
        sys.path.insert(0, agents_dir)
    from corner_watchdog_graph.agent import root_agent

    assert root_agent.name == GRAPH_NAME
    assert [a.name for a in root_agent.sub_agents] == [
        TRIAGE_AGENT_NAME,
        "corner_watchdog_decider",
    ]
