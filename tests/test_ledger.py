"""The ledger, and the two claims it makes that a reader cannot verify by eye.

The restraint rate is the headline number on a page whose whole argument is that
it is not inflated, so the arithmetic behind it is pinned here. So is the rule
that a decline renders at the same weight as an action, because that one degrades
silently: nothing breaks when a decline quietly becomes a one-line summary, the
page just starts lying by omission.
"""

from __future__ import annotations

import re

from watchdog.ledger import render_document, summarise


def entry(*, name="Taylor and Turk", slug="taylor-and-turk", actions=None, reason="nothing moved",
          by_rule=False, tier2=None, intents=None, degraded=None, ts="2026-08-19T20:00:00+00:00"):
    e = {
        "ts": ts,
        "slug": slug,
        "name": name,
        "delta": "No change at Taylor and Turk.",
        "trigger": "manual",
        "tier1": {"significant": bool(tier2), "reason": reason, "byRule": by_rule},
        "actions": actions or [],
        "intents": intents or [],
    }
    if tier2:
        e["tier2"] = tier2
    if degraded:
        e["degraded"] = degraded
    return e


def test_restraint_rate_counts_every_evaluation():
    entries = [entry() for _ in range(9)] + [entry(actions=["rescore"])]
    s = summarise(entries)
    assert s["total"] == 10
    assert s["held"] == 9
    assert s["acted"] == 1
    assert s["restraint"] == 90.0


def test_restraint_rate_of_an_empty_journal_is_not_a_crash():
    assert summarise([])["restraint"] == 0.0


def test_a_deliberated_decline_counts_as_restraint_not_as_action():
    """Tier two saying no is the expensive decline, and it still counts as held."""
    entries = [entry(tier2={"reasoning": "still nothing published is wrong", "actions": []})]
    s = summarise(entries)
    assert s["held"] == 1
    assert s["escalated"] == 1
    assert s["restraint"] == 100.0


def test_the_page_prints_the_definition_beside_the_number():
    html = render_document([entry(), entry(actions=["rescore"])])
    assert "1 of 2 evaluations ended in no action" in html
    assert "50" in html


def without_traces(html: str) -> str:
    """The page as a reader sees it before opening any disclosure."""
    return re.sub(r'<details class="trace">.*?</details>', "", html, flags=re.S)


def test_a_decline_renders_with_its_reasoning_at_full_size():
    declined = entry(reason="Inside ordinary weekly variance for a corner this busy.")
    acted = entry(slug="6th-market", name="6th and Market", actions=["rescore"],
                  tier2={"reasoning": "the letter cites a figure that moved", "actions": ["rescore"]})
    html = render_document([declined, acted])
    visible = without_traces(html)

    # The reasoning and the outcome are in the open, not behind the disclosure.
    assert "Inside ordinary weekly variance" in visible
    assert "No action taken." in visible
    # Same element, same class, no collapsing and no separate thinner treatment.
    assert html.count('class="entry entry-') == 2
    assert "display:none" not in html.replace(" ", "")


def test_the_only_thing_behind_a_disclosure_is_the_raw_record():
    """Expandable is fine. Hiding a decline's reasoning behind it is not."""
    html = render_document([entry(reason="Inside ordinary weekly variance for a corner this busy.")])
    assert html.count("<details") == 1
    assert "The full journal record" in html
    assert "Inside ordinary weekly variance" in without_traces(html)


def test_declines_and_actions_get_the_same_number_of_disclosures():
    html = render_document([entry(), entry(actions=["rescore"])])
    assert html.count("<details") == 2


def test_budget_intents_are_visible_on_the_page():
    html = render_document([
        entry(actions=["rescore"], intents=["would have redrafted the letter, budget reached"])
    ])
    assert "Budget refused" in html
    assert "would have redrafted the letter, budget reached" in html


def test_degradation_is_stated_once_at_the_top():
    note = "Tier one ran as deterministic rules, not Gemma: no credentials."
    visible = without_traces(render_document([entry(degraded=note), entry(degraded=note)]))
    assert visible.count(note) == 3  # once in the notice, once per entry caveat


def test_rehearsal_is_walled_off_from_the_headline():
    real = [entry() for _ in range(4)]
    fake = [entry(actions=["rescore", "flag"], slug="6th-market", name="6th and Market")]
    html = render_document(real, rehearsal=fake)
    assert "4 of 4 evaluations ended in no action" in html
    assert "Rehearsal, kept apart" in html
    assert "constructed baselines" in html


def test_entries_render_newest_first():
    html = render_document([
        entry(ts="2026-08-19T10:00:00+00:00", name="Older corner"),
        entry(ts="2026-08-19T20:00:00+00:00", name="Newer corner"),
    ])
    assert html.index("Newer corner") < html.index("Older corner")


def test_reasoning_is_escaped_not_injected():
    html = render_document([entry(reason="<script>alert('x')</script> and then some")])
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_both_themes_define_every_colour_token():
    """A token defined only inside a media query renders one theme on the other's ground."""
    html = render_document([entry()])
    for token in ("--ground", "--surface", "--ink", "--muted", "--hairline", "--held", "--acted"):
        assert html.count(f"{token}:") >= 3  # bare :root, the media query, and the explicit stamp
    assert "background: var(--ground)" in html


def test_the_degradation_notice_says_how_many_entries_carry_it():
    """An unqualified "every entry" was false here for 150 entries.

    The journal is append only, so entries written before the field existed can
    never gain it. Counting is the only honest way to make the claim.
    """
    note = "Tier one ran as deterministic rules, not Gemma: no credentials."
    html = render_document([entry(degraded=note), entry(), entry()])
    assert "1 of 3 entries carry this admission" in without_traces(html)
    assert "cannot gain it" in html
    assert "append only" in html


def test_a_fully_labelled_journal_says_so_without_hedging():
    note = "Tier one ran as deterministic rules, not Gemma: no credentials."
    html = render_document([entry(degraded=note), entry(degraded=note)])
    assert "All 2 entries carry this admission" in without_traces(html)
    assert "cannot gain it" not in html
