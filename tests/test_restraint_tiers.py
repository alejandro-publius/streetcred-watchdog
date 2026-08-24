"""The distinction the whole ledger turns on.

"The agent declined" covers two completely different events. A rule can observe
that there is no baseline yet, or that nothing moved, and decline without
anything having weighed anything. Or a tier can look at a real change and choose
not to act. Adding those together produces a restraint rate that describes a
quiet city and reads as a careful agent, and it would look identical if both
tiers were broken.

These tests hold the two apart, and hold the page to saying which it has.
"""

from __future__ import annotations

import asyncio

from corner_watchdog.brains import RuleTriage
from corner_watchdog.bus import DirectBus
from corner_watchdog.ledger import render_document, summarise
from corner_watchdog.observer import Observer
from corner_watchdog.schema import UNJUDGED_BASES, Counts, Snapshot, Tier1Verdict
from corner_watchdog.store import LocalJsonStore


def snap(*, collisions=40, fatal=1, severe=3, reports=120, complete=True) -> Snapshot:
    return Snapshot(
        slug="taylor-and-turk",
        name="Taylor and Turk",
        counts=Counts(collisions_5y=collisions, fatal_5y=fatal, severe_5y=severe,
                      reports_311_3y=reports, district=5),
        fetched_at="2026-08-19T20:00:00+00:00",
        complete=complete,
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


def _sweep(tmp_path, *, baseline=None, observed=None):
    """Returns the journal entry for a decline, which the observer writes itself."""
    store, published = _sweep_raw(tmp_path, baseline=baseline, observed=observed)
    return store.read_journal()[-1]


def _sweep_raw(tmp_path, *, baseline=None, observed=None):
    """Returns the store and anything the observer escalated onto the bus."""
    store = LocalJsonStore(tmp_path)
    if baseline is not None:
        store.put_snapshot(baseline)
    bus = DirectBus()
    published: list[dict] = []

    async def collect(envelope):
        published.append(envelope)

    bus.subscribe(collect)
    obs = Observer(store, bus, RuleTriage("t"), fetcher=Fake(observed))
    asyncio.run(obs.sweep([corner()]))
    return store, published


# ------------------------------------------------------- the basis is recorded

def test_a_first_sighting_is_labelled_as_having_no_baseline(tmp_path):
    entry = _sweep(tmp_path, baseline=None, observed=snap())
    assert entry["tier1"]["basis"] == "first_sighting"


def test_an_unchanged_corner_is_labelled_as_nothing_changed(tmp_path):
    entry = _sweep(tmp_path, baseline=snap(), observed=snap())
    assert entry["tier1"]["basis"] == "no_change"


def test_an_incomplete_fetch_is_labelled_unreliable(tmp_path):
    entry = _sweep(tmp_path, baseline=snap(), observed=snap(collisions=0, complete=False))
    assert entry["tier1"]["basis"] == "unreliable"


def test_a_new_fatality_is_labelled_as_the_rule_floor(tmp_path):
    """It escalates rather than declining, so the basis rides the envelope."""
    _store, published = _sweep_raw(
        tmp_path, baseline=snap(fatal=1), observed=snap(fatal=2, collisions=41)
    )
    assert len(published) == 1
    assert published[0]["tier1"]["basis"] == "rule_fatal"
    assert published[0]["tier1"]["significant"] is True


def test_an_ambiguous_change_is_labelled_as_triage(tmp_path):
    """The only basis on this list that means something actually weighed it."""
    entry = _sweep(tmp_path, baseline=snap(reports=120), observed=snap(reports=124))
    assert entry["tier1"]["basis"] == "triage"
    assert entry["tier1"]["byRule"] is False


def test_the_unjudged_set_does_not_contain_triage():
    assert "triage" not in UNJUDGED_BASES
    assert {"first_sighting", "no_change", "unreliable"} <= UNJUDGED_BASES


def test_a_verdict_knows_whether_anything_weighed_it():
    assert Tier1Verdict(significant=False, reason="r", basis="no_change").involved_judgment is False
    assert Tier1Verdict(significant=False, reason="r", basis="triage").involved_judgment is True


# --------------------------------------------------- the page says which it has

def entry(basis, *, actions=None, tier2=None):
    e = {
        "ts": "2026-08-19T20:00:00+00:00",
        "slug": "taylor-and-turk",
        "name": "Taylor and Turk",
        "delta": "No change at Taylor and Turk.",
        "trigger": "manual",
        "tier1": {"significant": False, "reason": "a reason", "byRule": basis != "triage",
                  "basis": basis},
        "actions": actions or [],
        "intents": [],
    }
    if tier2:
        e["tier2"] = tier2
    return e


def test_summarise_splits_observed_declines_from_weighed_ones():
    entries = [entry("no_change")] * 3 + [entry("first_sighting")] * 2 + [entry("triage")]
    s = summarise(entries)
    assert s["held"] == 6
    assert s["unjudged_declines"] == 5
    assert s["judged_declines"] == 1
    assert s["triage_declines"] == 1
    assert s["deliberated_declines"] == 0


def test_a_deliberated_decline_counts_as_weighed_not_observed():
    entries = [entry("triage", tier2={"reasoning": "still nothing wrong", "actions": []})]
    s = summarise(entries)
    assert s["judged_declines"] == 1
    assert s["deliberated_declines"] == 1
    assert s["triage_declines"] == 0


def test_an_all_rule_journal_says_the_number_measures_a_quiet_city():
    """The exact case tonight's real journal is in. The page must not flatter it."""
    html = render_document([entry("no_change")] * 25 + [entry("first_sighting")] * 25)
    assert "None of these 50 declines involved a judgment call" in html
    assert "measurement of a quiet city" in html
    assert "would look exactly the same if both tiers were broken" in html


def test_a_journal_with_real_judgment_reports_how_much():
    html = render_document(
        [entry("no_change")] * 8
        + [entry("triage")]
        + [entry("triage", tier2={"reasoning": "weighed and declined", "actions": []})]
    )
    assert "2 of these 10 declines involved a judgment call" in html
    assert "1 at triage" in html
    assert "1 after deliberation" in html
    assert "The other 8 were settled by a rule" in html


def test_the_breakdown_tags_each_row_as_weighed_or_observed():
    html = render_document([entry("no_change"), entry("triage")])
    assert "split-observed" in html
    assert "split-judged" in html
    assert "nothing changed" in html
    assert "triage weighed it" in html


def test_the_breakdown_is_above_the_journal_not_buried_under_it():
    html = render_document([entry("no_change"), entry("triage")])
    assert html.index("What the number is made of") < html.index("The journal")


def test_an_entry_with_no_basis_counts_as_observed_never_as_weighed():
    """A missing field must not inflate the one claim this breakdown deflates."""
    bare = {
        "ts": "2026-08-19T20:00:00+00:00",
        "slug": "a", "name": "A", "delta": "No change at A.", "trigger": "manual",
        "tier1": {"significant": False, "reason": "written before basis existed"},
        "actions": [], "intents": [],
    }
    s = summarise([bare] * 4)
    assert s["judged_declines"] == 0
    assert s["unjudged_declines"] == 4

    html = render_document([bare] * 4)
    assert "None of these 4 declines involved a judgment call" in html
    assert "basis not recorded, older entry" in html
    # Scoped to the restraint breakdown: the spend section further down uses the
    # same tag classes for a different distinction, measured versus projected.
    import re
    block = re.search(r'<div class="breakdown breakdown-restraint">.*?</div>', html, re.S).group(0)
    assert 'class="split-tag split-judged"' not in block
    assert 'class="split-tag split-observed"' in block


def test_an_acted_entry_is_not_counted_as_a_decline():
    s = summarise([entry("rule_fatal", actions=["rescore"]), entry("no_change")])
    assert s["held"] == 1
    assert s["acted"] == 1
    assert s["unjudged_declines"] == 1
