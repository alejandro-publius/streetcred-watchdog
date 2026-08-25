"""Tier two as an ADK agent, and the one property the design rests on.

The claim this file exists to hold is that a decline is a decision. Not an empty
list, not a run that produced nothing, not a timeout that looked like restraint:
a tool call, with reasoning, validated by the same contract an action goes
through, landing in the journal in the same shape.

So the tests are paired throughout. Whatever is asserted about acting is
asserted about declining beside it, because the moment the two paths stop being
symmetrical the restraint rate on the public page stops meaning what it says.

Everything here runs against a scripted model. See tests/scripted_model.py for
why that is the only way to assert on the graph rather than on the weather.
"""

from __future__ import annotations

import asyncio

import pytest
from scripted_model import call, scripted, text

from corner_watchdog.adk_decider import (
    ACTION_TOOLS,
    ALL_TOOLS,
    TOOL_TO_ACTION,
    AdkDecider,
    DeliberationError,
)
from corner_watchdog.config import ConfigError, decider_name
from corner_watchdog.contract import ALLOWED_ACTIONS
from corner_watchdog.ports import Decider
from corner_watchdog.schema import Counts, Delta

REASONING = (
    "The letter on this corner's page states its collision figures outright, and those figures "
    "have moved, so a sentence a resident reads there is now behind the city's own record."
)
CLAIM = "The letter says 40 injury collisions in five years; the record now shows 42."
STILL_TRUE = (
    "The letter's collision and fatality figures are unchanged and its supervisor district is "
    "still correct, so every number a resident reads on that page is still right."
)


def delta(**kw) -> Delta:
    base = {"slug": "a", "name": "6th and Mission", "empty": False}
    base.update(kw)
    return Delta(**base)


def counts() -> Counts:
    return Counts(collisions_5y=42, fatal_5y=1, severe_5y=3, reports_311_3y=120, district=6)


CORNER = {"slug": "a", "name": "6th and Mission", "grade": "F", "index": 99}


def run(model, d: Delta | None = None) -> tuple:
    decider = AdkDecider(model=model)
    try:
        out = asyncio.run(
            decider.decide(
                d or delta(new_collisions=2), CORNER, counts(), "two new injury collisions"
            )
        )
    finally:
        signatures = list(decider.last_signatures)
    return out, decider, signatures


# ================================================================== the action path

def test_an_action_tool_call_becomes_a_tier_two_decision():
    model = scripted(
        [call("regenerate_letter", reasoning=REASONING, published_claim_now_wrong=CLAIM, also=[])],
        [text("done")],
    )
    out, _, signatures = run(model)

    assert out.actions == ["regenerate_letter"]
    assert out.reasoning == REASONING
    assert signatures == ["regenerate_letter"]


@pytest.mark.parametrize("tool", ACTION_TOOLS)
def test_every_action_tool_maps_onto_an_action_the_actuator_implements(tool):
    """A tool with no verb behind it is a promise the system cannot keep."""
    model = scripted(
        [call(tool, reasoning=REASONING, published_claim_now_wrong=CLAIM, also=[])],
        [text("done")],
    )
    out, _, _ = run(model)

    assert out.actions == [TOOL_TO_ACTION[tool]]
    assert TOOL_TO_ACTION[tool] in ALLOWED_ACTIONS


def test_one_call_can_commit_to_several_actions_through_also():
    """A new fatality is never left to an automated redraft alone."""
    model = scripted(
        [call("regenerate_letter", reasoning=REASONING, published_claim_now_wrong=CLAIM,
              also=["rescore", "flag"])],
        [text("done")],
    )
    out, _, signatures = run(model, delta(new_fatal=1, new_collisions=1))

    assert out.actions == ["regenerate_letter", "rescore", "flag"]
    # Still exactly one signature. `also` is part of the decision, not a second one.
    assert signatures == ["regenerate_letter"]


def test_also_is_read_in_tool_names_and_stored_in_journal_names():
    """`re_audit` is the tool; `reaudit_imagery` is what the append-only journal holds."""
    model = scripted(
        [call("rescore", reasoning=REASONING, published_claim_now_wrong=CLAIM,
              also=["re_audit"])],
        [text("done")],
    )
    out, _, _ = run(model)

    assert out.actions == ["rescore", "reaudit_imagery"]


def test_a_repeated_action_is_collapsed_rather_than_journaled_twice():
    model = scripted(
        [call("rescore", reasoning=REASONING, published_claim_now_wrong=CLAIM,
              also=["rescore", "flag"])],
        [text("done")],
    )
    out, _, _ = run(model)

    assert out.actions == ["rescore", "flag"]


# ================================================================= the decline path

def test_a_decline_is_a_tool_call_and_carries_its_reasoning():
    model = scripted(
        [call("decline", reasoning=REASONING, still_accurate=STILL_TRUE)],
        [text("done")],
    )
    out, _, signatures = run(model)

    assert out.actions == []
    assert out.reasoning == REASONING
    assert signatures == ["decline"]


def test_a_decline_lands_in_the_same_shape_as_an_action():
    """The property the restraint rate depends on. Same fields, same types."""
    declined, _, _ = run(
        scripted([call("decline", reasoning=REASONING, still_accurate=STILL_TRUE)], [text("x")])
    )
    acted, _, _ = run(
        scripted(
            [call("rescore", reasoning=REASONING, published_claim_now_wrong=CLAIM, also=[])],
            [text("x")],
        )
    )

    assert declined.to_dict().keys() == acted.to_dict().keys()
    assert type(declined.actions) is type(acted.actions)
    assert declined.reasoning and acted.reasoning


def test_a_decline_without_naming_what_is_still_accurate_is_refused():
    """The contract applies to a tool call exactly as it applied to JSON."""
    model = scripted(
        [call("decline", reasoning=REASONING, still_accurate="ok")],
        [text("done")],
    )
    with pytest.raises(DeliberationError, match="decision contract"):
        run(model)


def test_an_action_without_naming_the_wrong_claim_is_refused():
    model = scripted(
        [call("rescore", reasoning=REASONING, published_claim_now_wrong="", also=[])],
        [text("done")],
    )
    with pytest.raises(DeliberationError, match="decision contract"):
        run(model)


def test_an_action_name_the_actuator_does_not_implement_is_refused():
    """`also` is model-supplied text, so it goes through the contract like everything else."""
    model = scripted(
        [call("rescore", reasoning=REASONING, published_claim_now_wrong=CLAIM,
              also=["delete_the_corner"])],
        [text("done")],
    )
    with pytest.raises(DeliberationError, match="decision contract"):
        run(model)


# ======================================================================= the seam

def test_the_adk_decider_satisfies_the_same_protocol_as_the_stand_in():
    """The actor must not be able to tell which one it was handed."""
    assert isinstance(AdkDecider(model=scripted()), Decider)


def test_every_tool_is_either_an_action_or_the_decline():
    assert set(ALL_TOOLS) == set(ACTION_TOOLS) | {"decline"}
    assert set(TOOL_TO_ACTION.values()) == set(ALLOWED_ACTIONS)


def test_describe_names_the_tools_so_the_journal_records_which_agent_ran():
    described = AdkDecider(model=scripted()).describe()
    for tool in ALL_TOOLS:
        assert tool in described


# ====================================================================== the config

def test_the_default_decider_is_the_adk_agent():
    assert decider_name({}) == "adk"


def test_the_stand_in_stays_selectable_for_comparison():
    assert decider_name({"DECIDER": "rule"}) == "rule"


@pytest.mark.parametrize("value", ["adkk", "gemini", "none", "rules", "ADK_"])
def test_an_unrecognised_decider_raises_rather_than_falling_back(value):
    """A typo must not quietly run the stand-in while the operator believes otherwise."""
    with pytest.raises(ConfigError):
        decider_name({"DECIDER": value})


def test_an_empty_value_reads_as_unset_rather_than_as_an_error():
    """`DECIDER=` in a .env file means the operator left it blank, not that they meant nothing."""
    assert decider_name({"DECIDER": ""}) == "adk"
    assert decider_name({"DECIDER": "   "}) == "adk"


def test_a_case_and_whitespace_variant_is_still_recognised():
    assert decider_name({"DECIDER": " ADK "}) == "adk"


# ============================================================== the offline promise

def test_the_suite_cannot_reach_vertex_by_accident():
    """conftest scrubs the environment. If that stops being true, this fails."""
    import os

    from conftest import VERTEX_ENV

    assert [name for name in VERTEX_ENV if os.environ.get(name)] == []
    assert os.environ["DECIDER"] == "rule"


def test_the_default_wiring_does_not_build_a_live_decider_without_a_project(monkeypatch):
    """`DECIDER=adk` with no Vertex project runs the stand-in and says so loudly."""
    from corner_watchdog.brains import RuleDecider, select_brains

    monkeypatch.setenv("DECIDER", "adk")
    _triage, decider, note = select_brains()

    assert isinstance(decider, RuleDecider)
    assert "DECIDER=adk was requested" in note
    assert "Nothing on this entry was decided by a model" in note


# ============================================== the two facts the evidence package states

def test_the_case_says_the_counts_are_the_totals_after_the_change():
    """Found by reading what a real model said back.

    The first live deliberation reasoned that collisions had "risen from 42 to
    44" when 42 was already the total after the change. The evidence package
    listed the delta and the counts next to each other and left which was which
    to inference, and the inference went the wrong way. That reasoning is
    published verbatim beside the actions, so a wrong number in it is a wrong
    number on a public page.
    """
    from corner_watchdog.prompts import deliberation_case

    case = deliberation_case(
        name="6th and Mission", grade="F", index=99,
        delta="6th and Mission: 2 new injury collisions.",
        escalation_reason="two new injury collisions",
        counts=counts(),
    )
    # Whitespace-normalised: the prompt is wrapped for reading, so the sentence
    # this asserts on is split across lines in the source.
    flat = " ".join(case.split())
    assert "already include the change described above" in flat
    assert "totals after it, not before it" in flat


def test_the_case_carries_the_letters_age_when_the_corner_knows_it():
    """The prompt has asked since it was written; nothing supplied it until now.

    It is the one fact that can make an escalated change need no correction: a
    letter drafted after the change already states the new figures, so redrafting
    churns the page to no effect. Without it every deliberation is told "unknown"
    and can never reach that conclusion.
    """
    model = scripted(
        [call("decline", reasoning=REASONING, still_accurate=STILL_TRUE)], [text("done")]
    )
    decider = AdkDecider(model=model)
    corner = {**CORNER, "letterDrafted": "today, after this change was recorded"}
    asyncio.run(
        decider.decide(delta(reports_311_change=16), corner, counts(), "a 311 swing past the bar")
    )

    shown = "\n".join(model.prompts_seen())
    assert "today, after this change was recorded" in shown


def test_a_corner_that_does_not_know_its_letters_age_still_says_unknown():
    model = scripted(
        [call("decline", reasoning=REASONING, still_accurate=STILL_TRUE)], [text("done")]
    )
    decider = AdkDecider(model=model)
    asyncio.run(
        decider.decide(delta(reports_311_change=16), CORNER, counts(), "a 311 swing past the bar")
    )

    shown = "\n".join(model.prompts_seen())
    assert "last drafted unknown" in shown
