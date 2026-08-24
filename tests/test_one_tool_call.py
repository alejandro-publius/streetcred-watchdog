"""Exactly one tool call, and what happens to the runs that manage neither.

The rule is that a deliberation ends in exactly one signature. Zero is an error.
Two is an error. Neither is a decline, and the distinction is the whole point:
an agent that broke and an agent that chose to do nothing both finish with an
empty actions list, and that empty list is exactly what the ledger's headline
restraint rate reads.

So a failure is journaled with an `error` field rather than raised out of the
sweep or quietly dropped. Three properties are held here and each one has a way
of going wrong that produces a page that looks better than the agent was:

    the entry exists            a dropped failure is a corner with no record,
                                which reads as a morning that never happened
    the entry says it failed    an entry with no actions and no error is
                                indistinguishable from restraint
    the sweep continues         one broken deliberation must not end the
                                morning for the other twenty four corners
"""

from __future__ import annotations

import asyncio

import pytest
from scripted_model import call, scripted, text

from corner_watchdog.actor import Actor
from corner_watchdog.adk_decider import AdkDecider
from corner_watchdog.budget import ActionBudget
from corner_watchdog.ledger import summarise
from corner_watchdog.outbox import DryRunActuator
from corner_watchdog.ports import DeliberationError
from corner_watchdog.schema import Counts, Delta
from corner_watchdog.store import LocalJsonStore

REASONING = (
    "The letter on this corner's page states its collision figures outright, and those figures "
    "have moved, so a sentence a resident reads there is now behind the city's own record."
)
CLAIM = "The letter says 40 injury collisions in five years; the record now shows 42."
STILL_TRUE = (
    "The letter's collision and fatality figures are unchanged and its supervisor district is "
    "still correct, so every number a resident reads on that page is still right."
)

CORNER = {"slug": "a", "name": "6th and Mission", "grade": "F", "index": 99}


def deliberate(model):
    decider = AdkDecider(model=model)
    delta = Delta(slug="a", name="6th and Mission", new_collisions=2, empty=False)
    counts = Counts(collisions_5y=42, fatal_5y=1, severe_5y=3, reports_311_3y=120, district=6)
    return asyncio.run(decider.decide(delta, CORNER, counts, "two new injury collisions"))


def envelope() -> dict:
    return {
        "trigger": "manual",
        "corner": CORNER,
        "delta": {"slug": "a", "name": "6th and Mission", "new_collisions": 2, "empty": False},
        "delta_summary": "6th and Mission: 2 new injury collisions.",
        "counts": {"collisions_5y": 42, "fatal_5y": 1, "severe_5y": 3, "reports_311_3y": 120},
        "tier1": {"significant": True, "reason": "two new injury collisions", "basis": "triage"},
    }


def run_actor(tmp_path, model):
    store = LocalJsonStore(tmp_path / "state")
    actor = Actor(
        store,
        AdkDecider(model=model),
        DryRunActuator(tmp_path / "outbox", run_id="t"),
        ActionBudget(limit=40),
    )
    asyncio.run(actor.handle(envelope()))
    return store, actor.result


# ============================================================== one: the action path

def test_an_action_path_ends_in_exactly_one_signature(tmp_path):
    model = scripted(
        [call("rescore", reasoning=REASONING, published_claim_now_wrong=CLAIM, also=[])],
        [text("done")],
    )
    store, result = run_actor(tmp_path, model)
    entries = store.read_journal()

    assert len(entries) == 1
    assert entries[0]["actions"] == ["rescore"]
    assert not entries[0].get("error")
    assert (result.acted, result.declined, result.errored) == (1, 0, 0)


# ============================================================= two: the decline path

def test_a_decline_carries_its_reasoning_and_is_not_an_error(tmp_path):
    model = scripted(
        [call("decline", reasoning=REASONING, still_accurate=STILL_TRUE)],
        [text("done")],
    )
    store, result = run_actor(tmp_path, model)
    entries = store.read_journal()

    assert len(entries) == 1
    assert entries[0]["actions"] == []
    assert entries[0]["tier2"]["reasoning"] == REASONING
    assert not entries[0].get("error")
    assert (result.acted, result.declined, result.errored) == (0, 1, 0)


def test_a_decline_still_counts_as_restraint_on_the_page(tmp_path):
    model = scripted(
        [call("decline", reasoning=REASONING, still_accurate=STILL_TRUE)],
        [text("done")],
    )
    store, _ = run_actor(tmp_path, model)

    stats = summarise(store.read_journal())
    assert stats["held"] == 1
    assert stats["errored"] == 0
    assert stats["restraint"] == 100.0


# =========================================================== three: the no-tool path

def test_prose_with_no_tool_call_raises_rather_than_returning_a_decline():
    """At the decider's own boundary, before anything downstream can read it."""
    model = scripted([text("I think this corner is probably fine, honestly.")])

    with pytest.raises(DeliberationError, match="without a tool call"):
        deliberate(model)


def test_prose_with_no_tool_call_is_journaled_as_an_error(tmp_path):
    model = scripted([text("I think this corner is probably fine, honestly.")])
    store, result = run_actor(tmp_path, model)
    entries = store.read_journal()

    assert len(entries) == 1, "a failed deliberation must still leave a record"
    assert entries[0]["error"]
    assert entries[0]["actions"] == []
    assert (result.acted, result.declined, result.errored) == (0, 0, 1)


def test_a_no_tool_error_is_never_counted_as_restraint(tmp_path):
    """The assertion the whole design rests on."""
    model = scripted([text("Nothing to do here.")])
    store, _ = run_actor(tmp_path, model)

    stats = summarise(store.read_journal())
    assert stats["errored"] == 1
    assert stats["held"] == 0
    assert stats["restraint"] == 0.0


def test_the_page_says_it_failed_rather_than_showing_a_quiet_morning(tmp_path):
    from corner_watchdog.ledger import render_document

    model = scripted([text("Nothing to do here.")])
    store, _ = run_actor(tmp_path, model)

    html = render_document(store.read_journal())
    assert "No decision was reached" in html
    assert "not counted as one" in html


# ============================================================ four: two tool calls

def test_signing_twice_is_an_error_rather_than_the_last_one_winning():
    model = scripted(
        [
            call("rescore", reasoning=REASONING, published_claim_now_wrong=CLAIM, also=[]),
            call("decline", reasoning=REASONING, still_accurate=STILL_TRUE),
        ],
        [text("done")],
    )
    with pytest.raises(DeliberationError, match="signed 2 tools"):
        deliberate(model)


def test_signing_twice_is_journaled_as_an_error_not_as_the_decline(tmp_path):
    """The dangerous ordering: an action then a decline, where last-wins reads as restraint."""
    model = scripted(
        [
            call("rescore", reasoning=REASONING, published_claim_now_wrong=CLAIM, also=[]),
            call("decline", reasoning=REASONING, still_accurate=STILL_TRUE),
        ],
        [text("done")],
    )
    store, result = run_actor(tmp_path, model)
    entries = store.read_journal()

    assert result.errored == 1
    assert result.declined == 0
    assert entries[0]["error"]
    assert summarise(entries)["restraint"] == 0.0


# ================================================================ five: the sweep

def test_one_broken_deliberation_does_not_end_the_morning(tmp_path):
    """The failure is contained to its own corner and the next one still gets a record."""
    store = LocalJsonStore(tmp_path / "state")
    actuator = DryRunActuator(tmp_path / "outbox", run_id="t")

    broken = Actor(store, AdkDecider(model=scripted([text("no")])), actuator, ActionBudget(limit=40))
    asyncio.run(broken.handle(envelope()))

    working = Actor(
        store,
        AdkDecider(model=scripted(
            [call("decline", reasoning=REASONING, still_accurate=STILL_TRUE)], [text("done")]
        )),
        actuator,
        ActionBudget(limit=40),
    )
    second = envelope()
    second["corner"] = {**CORNER, "slug": "b", "name": "Turk and Taylor"}
    asyncio.run(working.handle(second))

    entries = store.read_journal()
    assert len(entries) == 2
    assert entries[0]["error"] and not entries[1].get("error")

    stats = summarise(entries)
    assert (stats["errored"], stats["held"]) == (1, 1)
    assert stats["restraint"] == 50.0
