"""Two ceilings, two different things, and the honesty of the numbers under them.

The action budget stops the agent doing too much to the world. The token budget
stops it spending too much thinking about it. Conflating them would be a bug: an
agent can exhaust either without touching the other, and the recoveries differ.

The honesty rule here is narrow and easy to break. Every token figure this
repository can produce is a projection, because no model has ever been called.
Reporting a projection as spend would be a cheap lie to tell in exactly the
section a judge reads looking for unit economics, so `actual` and `projected` are
separate fields, every cost record carries `projectionOnly`, and the page prints
both with labels.
"""

from __future__ import annotations

import asyncio

from corner_watchdog.actor import Actor
from corner_watchdog.brains import RuleDecider, RuleTriage
from corner_watchdog.budget import (
    TIER1_OUTPUT_TOKENS,
    TIER1_PROMPT_TOKENS,
    TIER2_OUTPUT_TOKENS,
    TIER2_PROMPT_TOKENS,
    ActionBudget,
    Cost,
    TokenBudget,
)
from corner_watchdog.bus import DirectBus
from corner_watchdog.ledger import render_document, spend
from corner_watchdog.observer import Observer
from corner_watchdog.outbox import DryRunActuator
from corner_watchdog.schema import Counts, Snapshot
from corner_watchdog.store import LocalJsonStore


def snap(*, collisions=40, fatal=1, severe=3, reports=120) -> Snapshot:
    return Snapshot(
        slug="taylor-and-turk", name="Taylor and Turk",
        counts=Counts(collisions_5y=collisions, fatal_5y=fatal, severe_5y=severe,
                      reports_311_3y=reports, district=5),
        fetched_at="2026-08-19T20:00:00+00:00", complete=True, query_fingerprint="r=80m",
    )


def corner():
    return {"slug": "taylor-and-turk", "name": "Taylor and Turk", "lat": 37.78,
            "lon": -122.41, "district": 5, "radiusMeters": 80, "grade": "F", "index": 96}


class Fake:
    def __init__(self, *snaps) -> None:
        self.q = list(snaps)

    def describe(self):
        return "fake"

    async def fetch_all(self, corners):
        return [self.q.pop(0) for _ in corners]


# ------------------------------------------------------------------- the record

def test_a_free_evaluation_records_zero_of_everything():
    c = Cost()
    assert c.projected_total == 0
    assert c.to_dict()["actualTokens"] == 0
    assert c.to_dict()["tiersConsulted"] == []


def test_a_tier_one_call_projects_the_measured_prompt_size():
    c = Cost.for_tiers("tier1")
    assert c.projected_prompt_tokens == TIER1_PROMPT_TOKENS
    assert c.projected_output_tokens == TIER1_OUTPUT_TOKENS


def test_both_tiers_sum():
    c = Cost.for_tiers("tier1", "tier2")
    assert c.projected_total == (
        TIER1_PROMPT_TOKENS + TIER1_OUTPUT_TOKENS + TIER2_PROMPT_TOKENS + TIER2_OUTPUT_TOKENS
    )
    assert c.tiers_consulted == ("tier1", "tier2")


def test_every_cost_record_says_it_is_a_projection():
    """No model has ever been called by this repository."""
    for c in (Cost(), Cost.for_tiers("tier1"), Cost.for_tiers("tier1", "tier2")):
        assert c.to_dict()["projectionOnly"] is True
        assert c.to_dict()["actualTokens"] == 0


# ------------------------------------------------------------- the token budget

def test_an_uncapped_budget_never_refuses():
    b = TokenBudget(limit=0)
    assert b.capped is False
    for _ in range(50):
        assert b.take(Cost.for_tiers("tier1", "tier2")) is True
    assert b.refused == 0


def test_a_capped_budget_refuses_the_call_that_would_cross_it():
    b = TokenBudget(limit=TIER1_PROMPT_TOKENS + TIER1_OUTPUT_TOKENS)
    assert b.take(Cost.for_tiers("tier1")) is True
    assert b.take(Cost.for_tiers("tier1")) is False
    assert b.refused == 1


def test_a_refused_call_does_not_spend():
    b = TokenBudget(limit=10)
    b.take(Cost.for_tiers("tier1"))
    assert b.spent == 0


def test_the_budget_reads_from_the_environment(monkeypatch):
    monkeypatch.setenv("DAILY_TOKEN_BUDGET", "5000")
    assert TokenBudget.from_env().limit == 5000


def test_a_junk_budget_value_falls_back_to_uncapped(monkeypatch):
    monkeypatch.setenv("DAILY_TOKEN_BUDGET", "lots")
    assert TokenBudget.from_env().capped is False


def test_the_two_budgets_are_independent():
    """An agent can exhaust either without touching the other."""
    actions = ActionBudget(limit=0)
    tokens = TokenBudget(limit=100000)
    assert actions.take("rescore") is False
    assert tokens.take(Cost.for_tiers("tier2")) is True


# -------------------------------------------------- the loop under the ceiling

def test_an_exhausted_token_budget_means_triage_is_not_consulted(tmp_path):
    """Not a judgment that the change does not matter. Nothing looked at it."""
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap(reports=120))
    obs = Observer(store, DirectBus(), RuleTriage("t"),
                   fetcher=Fake(snap(reports=124)), tokens=TokenBudget(limit=1))
    result = asyncio.run(obs.sweep([corner()]))

    assert result.token_refusals == 1
    e = store.read_journal()[-1]
    assert e["tier1"]["basis"] == "budget_exhausted"
    assert "nothing looked at it" in e["tier1"]["reason"]
    assert e["cost"]["projectedPromptTokens"] == 0


def test_a_budget_exhausted_entry_never_counts_as_restraint():
    from corner_watchdog.schema import UNJUDGED_BASES

    assert "budget_exhausted" in UNJUDGED_BASES


def test_triage_within_budget_records_what_it_would_have_cost(tmp_path):
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap(reports=120))
    obs = Observer(store, DirectBus(), RuleTriage("t"),
                   fetcher=Fake(snap(reports=124)), tokens=TokenBudget(limit=100000))
    asyncio.run(obs.sweep([corner()]))

    e = store.read_journal()[-1]
    assert e["cost"]["tiersConsulted"] == ["tier1"]
    assert e["cost"]["projectedPromptTokens"] == TIER1_PROMPT_TOKENS
    assert e["cost"]["actualTokens"] == 0


def test_a_rule_settled_evaluation_costs_nothing(tmp_path):
    """The whole economic argument for the deterministic floor."""
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap())
    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake(snap()))
    asyncio.run(obs.sweep([corner()]))

    e = store.read_journal()[-1]
    assert e["cost"]["tiersConsulted"] == []
    assert e["cost"]["projectedPromptTokens"] == 0


def test_an_exhausted_token_budget_stops_deliberation_and_journals_it(tmp_path):
    store = LocalJsonStore(tmp_path)
    actor = Actor(store, RuleDecider("t"), DryRunActuator(tmp_path / "out"),
                  ActionBudget(limit=40), tokens=TokenBudget(limit=1))
    envelope = {
        "trigger": "manual", "corner": corner(),
        "delta": {"slug": "taylor-and-turk", "name": "Taylor and Turk",
                  "new_collisions": 2, "empty": False},
        "delta_summary": "Taylor and Turk: 2 new injury collisions.",
        "counts": snap().counts.to_dict(),
        "tier1": {"significant": True, "reason": "two new injury collisions", "byRule": False},
    }
    asyncio.run(actor.handle(envelope))

    assert actor.result.deliberated == 0
    e = store.read_journal()[-1]
    assert "tier2" not in e
    assert e["actions"] == []
    assert "token budget" in e["intents"][0]


def test_deliberation_within_budget_adds_its_projection_to_tier_ones(tmp_path):
    store = LocalJsonStore(tmp_path)
    actor = Actor(store, RuleDecider("t"), DryRunActuator(tmp_path / "out"),
                  ActionBudget(limit=40), tokens=TokenBudget(limit=100000))
    envelope = {
        "trigger": "manual", "corner": corner(),
        "delta": {"slug": "taylor-and-turk", "name": "Taylor and Turk",
                  "new_collisions": 2, "empty": False},
        "delta_summary": "Taylor and Turk: 2 new injury collisions.",
        "counts": snap().counts.to_dict(),
        "tier1": {"significant": True, "reason": "two new injury collisions", "byRule": False},
        "cost": Cost.for_tiers("tier1").to_dict(),
    }
    asyncio.run(actor.handle(envelope))

    e = store.read_journal()[-1]
    assert e["cost"]["tiersConsulted"] == ["tier1", "tier2"]
    assert e["cost"]["projectedPromptTokens"] == TIER1_PROMPT_TOKENS + TIER2_PROMPT_TOKENS
    assert e["cost"]["actualTokens"] == 0


def test_the_action_budget_still_converts_actions_into_intents(tmp_path):
    """The behaviour the README has promised since the first commit."""
    store = LocalJsonStore(tmp_path)
    actor = Actor(store, RuleDecider("t"), DryRunActuator(tmp_path / "out"),
                  ActionBudget(limit=1), tokens=TokenBudget())
    envelope = {
        "trigger": "manual", "corner": corner(),
        "delta": {"slug": "taylor-and-turk", "name": "Taylor and Turk",
                  "new_collisions": 2, "empty": False},
        "delta_summary": "two new injury collisions",
        "counts": snap().counts.to_dict(),
        "tier1": {"significant": True, "reason": "two new injury collisions", "byRule": False},
    }
    asyncio.run(actor.handle(envelope))

    e = store.read_journal()[-1]
    assert e["actions"] == ["rescore"]
    assert e["intents"] and "budget reached" in e["intents"][0]


# ------------------------------------------------------------------- the page

def visible_text(html: str) -> str:
    """The page as a reader sees it: tags stripped, whitespace normalised."""
    import re

    stripped = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", stripped).split())


def entry(cost=None, **over):
    e = {
        "ts": "2026-08-20T05:00:00+00:00", "slug": "a", "name": "A",
        "delta": "No change at A.", "trigger": "cron",
        "tier1": {"significant": False, "reason": "nothing moved", "byRule": True,
                  "basis": "no_change"},
        "actions": [], "intents": [],
        "cost": cost if cost is not None else Cost().to_dict(),
    }
    e.update(over)
    return e


def test_spend_separates_measured_from_projected():
    entries = [entry()] * 24 + [entry(Cost.for_tiers("tier1", "tier2").to_dict())]
    sp = spend(entries)
    assert sp["actual"] == 0
    assert sp["projected_total"] > 0
    assert sp["free"] == 24
    assert sp["consulted"] == {"tier1": 1, "tier2": 1}


def test_the_page_reports_zero_actual_and_labels_the_projection():
    html = render_document([entry()] * 24 + [entry(Cost.for_tiers("tier1", "tier2").to_dict())])
    assert "tokens actually spent" in html
    assert "would have cost with the models wired" in html
    assert "no model has been called by this repository" in html
    # The count and its label sit in adjacent spans, so read the page as text.
    assert "24 of 25 evaluations settled without consulting any tier" in visible_text(html)


def test_an_all_free_journal_projects_nothing():
    html = render_document([entry()] * 10)
    sp = spend([entry()] * 10)
    assert sp["projected_total"] == 0
    assert "Tier consultations: none" in html


def test_entries_without_a_cost_field_do_not_break_the_total():
    """Written before the field existed."""
    bare = entry()
    del bare["cost"]
    assert spend([bare, entry()])["projected_total"] == 0
