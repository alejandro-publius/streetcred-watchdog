"""Breaking things on purpose, and the bug that doing so uncovered.

Every honest thing this agent does when something fails is invisible until
something fails. So the failures are injectable, which turns "it would refuse to
compare and keep the old baseline" from a claim into a thing you can watch.

Injection carries its own risk and both guards against it are tested here. An
injected run writes to its own state directory, so a rehearsed outage can never
reach the journal that gets submitted. And every entry it writes says it was
injected, so a screenshot of a fake outage cannot later be offered as evidence of
a real one.

The last section holds a bug that only appeared once a spent budget could be
simulated: an entry whose actions were all refused by the budget has an empty
actions list, and the restraint rate was counting it as restraint. An agent that
decided to act and was stopped is not exercising restraint.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from watchdog.actor import Actor
from watchdog.brains import RuleDecider
from watchdog.budget import ActionBudget, TokenBudget
from watchdog.inject import (
    FailingFetcher,
    InjectedOutage,
    PartialFetcher,
    available,
    build,
)
from watchdog.ledger import render_document, summarise
from watchdog.outbox import DryRunActuator
from watchdog.runner import run_cycle
from watchdog.schema import Counts, Snapshot
from watchdog.store import LocalJsonStore


def snap(slug="a", *, collisions=40) -> Snapshot:
    return Snapshot(
        slug=slug, name=slug.upper(),
        counts=Counts(collisions_5y=collisions, fatal_5y=1, severe_5y=3,
                      reports_311_3y=120, district=6),
        fetched_at="2026-08-20T05:00:00+00:00", complete=True, query_fingerprint="r=80m",
    )


def corner(slug="a"):
    return {"slug": slug, "name": slug.upper(), "lat": 37.78, "lon": -122.41,
            "district": 6, "radiusMeters": 80, "grade": "F", "index": 99}


class Ok:
    def describe(self):
        return "ok"

    async def fetch_all(self, corners):
        return [snap(c["slug"]) for c in corners]


# ------------------------------------------------------------------ the catalogue

def test_every_advertised_injection_can_be_built():
    for name in available():
        inj = build(name)
        assert inj.name == name
        assert inj.what_it_shows
        assert inj.note


def test_an_unknown_injection_is_refused():
    with pytest.raises(ValueError) as e:
        build("delete_everything")
    assert "unknown injection" in str(e.value)


def test_every_injection_note_says_it_was_injected():
    """A screenshot of a fake outage must never pass as a real one."""
    for name in available():
        note = build(name).note
        assert "INJECTED on purpose" in note
        assert "is not evidence that either happened" in note


# ---------------------------------------------------------------- the outage

def test_the_failing_fetcher_raises_a_real_connection_error():
    """The code path under test must be the one that runs in production."""
    import httpx

    assert issubclass(InjectedOutage, httpx.ConnectError)


def test_every_corner_fails_when_the_source_is_down():
    got = asyncio.run(FailingFetcher().fetch_all([corner("a"), corner("b")]))
    assert all(isinstance(g, InjectedOutage) for g in got)


def test_a_partial_outage_fails_some_and_not_others():
    got = asyncio.run(PartialFetcher(Ok(), fail_every=2).fetch_all(
        [corner("a"), corner("b"), corner("c"), corner("d")]
    ))
    assert isinstance(got[0], InjectedOutage)
    assert isinstance(got[1], Snapshot)
    assert isinstance(got[2], InjectedOutage)


def test_an_injected_outage_keeps_every_baseline_untouched(tmp_path):
    """The behaviour the demo exists to show, asserted rather than narrated."""
    store = LocalJsonStore(tmp_path / "state")
    store.put_snapshot(snap("a", collisions=40))

    report = asyncio.run(run_cycle(
        [corner("a")], store=store, outbox_dir=tmp_path / "out", run_id="t",
        fetcher=build("datasf_down").fetcher,
        extra_degradation=build("datasf_down").note,
    ))

    assert report.sweep.unreliable == 1
    assert store.get_snapshot("a").counts.collisions_5y == 40  # untouched
    entry = store.read_journal()[-1]
    assert entry["tier1"]["basis"] == "fetch_failed"
    assert entry["actions"] == []
    assert "INJECTED on purpose" in entry["degraded"]


def test_an_injected_outage_takes_no_action_at_all(tmp_path):
    store = LocalJsonStore(tmp_path / "state")
    store.put_snapshot(snap("a"))
    report = asyncio.run(run_cycle(
        [corner("a")], store=store, outbox_dir=tmp_path / "out", run_id="t",
        fetcher=build("datasf_down").fetcher,
    ))
    assert report.actor.acted == 0
    assert report.actor.artefacts == []


# --------------------------------------------------------------- the budgets

def test_a_zero_action_budget_turns_every_action_into_an_intent(tmp_path):
    store = LocalJsonStore(tmp_path)
    actor = Actor(store, RuleDecider("t"), DryRunActuator(tmp_path / "out"),
                  build("budget_zero").action_budget)
    asyncio.run(actor.handle({
        "trigger": "manual", "corner": corner("a"),
        "delta": {"slug": "a", "name": "A", "new_collisions": 2, "empty": False},
        "delta_summary": "two new injury collisions",
        "counts": snap().counts.to_dict(),
        "tier1": {"significant": True, "reason": "two new", "byRule": False},
    }))

    e = store.read_journal()[-1]
    assert e["actions"] == []
    assert len(e["intents"]) >= 2
    assert all("budget reached" in i for i in e["intents"])


def test_a_zero_token_budget_stops_the_tier_being_consulted():
    assert build("tokens_zero").token_budget.limit == 1


# ------------------------------------------------------- it writes somewhere else

def test_an_injected_run_can_be_pointed_at_its_own_state(tmp_path):
    """So a rehearsed failure never reaches the journal that gets submitted."""
    real = LocalJsonStore(tmp_path / "state")
    real.put_snapshot(snap("a"))
    injected = LocalJsonStore(tmp_path / "state-injected")

    asyncio.run(run_cycle(
        [corner("a")], store=injected, outbox_dir=tmp_path / "out", run_id="t",
        fetcher=build("datasf_down").fetcher, extra_degradation=build("datasf_down").note,
    ))

    assert real.read_journal() == []
    assert injected.read_journal()


def test_the_cli_defaults_injected_runs_to_a_separate_state_dir():
    from watchdog.cli import build_parser

    args = build_parser().parse_args(["run", "--inject", "datasf_down"])
    assert args.inject_state == "state-injected"
    assert args.inject_state != args.state


def test_the_cli_refuses_an_injection_it_does_not_know():
    from watchdog.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--inject", "nonsense"])


# ------------------------------------ the bug the budget injection uncovered

def blocked_entry():
    """The decider chose actions; the budget refused every one."""
    return {
        "ts": "2026-08-20T05:00:00+00:00", "slug": "a", "name": "A",
        "delta": "two new injury collisions", "trigger": "manual",
        "tier1": {"significant": True, "reason": "two new", "byRule": False, "basis": "triage"},
        "tier2": {"reasoning": "the letter cites a figure that moved", "actions": ["rescore"]},
        "actions": [],
        "intents": ["would have rescored the corner, budget reached"],
    }


def held_entry():
    return {
        "ts": "2026-08-20T05:00:00+00:00", "slug": "b", "name": "B",
        "delta": "No change at B.", "trigger": "manual",
        "tier1": {"significant": False, "reason": "nothing moved", "byRule": True,
                  "basis": "no_change"},
        "actions": [], "intents": [],
    }


def test_a_budget_blocked_entry_is_not_counted_as_restraint():
    """It decided to act and was stopped. That is the opposite of restraint."""
    s = summarise([held_entry(), blocked_entry()])
    assert s["held"] == 1
    assert s["blocked"] == 1
    assert s["restraint"] == 50.0


def test_a_journal_of_only_blocked_entries_has_a_zero_restraint_rate():
    """Before this fix it read 100 percent."""
    s = summarise([blocked_entry()] * 5)
    assert s["held"] == 0
    assert s["blocked"] == 5
    assert s["restraint"] == 0.0


def test_a_partly_refused_entry_still_counts_as_having_acted():
    e = blocked_entry()
    e["actions"] = ["rescore"]
    e["intents"] = ["would have redrafted the letter, budget reached"]
    s = summarise([e])
    assert s["acted"] == 1
    assert s["blocked"] == 0


def test_the_page_says_blocked_entries_are_counted_as_neither():
    html = render_document([held_entry(), blocked_entry()])
    assert "wanted to act and were stopped by a spent budget" in html
    assert "is not exercising restraint" in html


def test_the_actor_does_not_record_a_budget_block_as_a_decline(tmp_path):
    store = LocalJsonStore(tmp_path)
    actor = Actor(store, RuleDecider("t"), DryRunActuator(tmp_path / "out"),
                  ActionBudget(limit=0), tokens=TokenBudget())
    asyncio.run(actor.handle({
        "trigger": "manual", "corner": corner("a"),
        "delta": {"slug": "a", "name": "A", "new_collisions": 2, "empty": False},
        "delta_summary": "two new injury collisions",
        "counts": snap().counts.to_dict(),
        "tier1": {"significant": True, "reason": "two new", "byRule": False},
    }))
    assert actor.result.blocked == 1
    assert actor.result.declined == 0
    assert actor.result.acted == 0


def test_a_genuine_decline_is_still_recorded_as_one(tmp_path):
    store = LocalJsonStore(tmp_path)
    actor = Actor(store, RuleDecider("t"), DryRunActuator(tmp_path / "out"),
                  ActionBudget(limit=40), tokens=TokenBudget())
    asyncio.run(actor.handle({
        "trigger": "manual", "corner": corner("a"),
        "delta": {"slug": "a", "name": "A", "empty": False, "note": "nothing that moves a figure"},
        "delta_summary": "something moved that changes no figure",
        "counts": snap().counts.to_dict(),
        "tier1": {"significant": True, "reason": "escalated for a look", "byRule": False},
    }))
    assert actor.result.declined == 1
    assert actor.result.blocked == 0
