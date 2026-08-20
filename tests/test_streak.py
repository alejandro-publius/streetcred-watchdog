"""Days watched, and days not watched, counted from the journal.

A streak is the easiest number on a monitoring page to inflate, because the
inflation is done by omission rather than by arithmetic. Skip the days nothing
ran and every run of days looks unbroken. That is the same move as publishing
only the mornings the agent acted, which is the move this whole project exists
to refuse, so the gaps are counted, returned, and drawn.

Counted from journal entries rather than from a run log on purpose: a run that
started, crashed and wrote nothing is not a day anything was watched, whatever a
counter incremented.
"""

from __future__ import annotations

from watchdog.ledger import render_document, streak


def entry(ts, *, actions=None):
    return {
        "ts": ts, "slug": "a", "name": "A", "delta": "No change at A.", "trigger": "cron",
        "tier1": {"significant": False, "reason": "nothing moved", "byRule": True,
                  "basis": "no_change"},
        "actions": actions or [], "intents": [],
    }


def test_an_empty_journal_has_no_streak_rather_than_a_zero_day_one():
    st = streak([])
    assert st["days"] == []
    assert st["elapsed"] == 0
    assert st["ran"] == 0


def test_a_single_day_counts_as_one_of_one():
    st = streak([entry("2026-08-20T05:00:00+00:00"), entry("2026-08-20T18:00:00+00:00")])
    assert st["ran"] == 1
    assert st["elapsed"] == 1
    assert st["gaps"] == []


def test_many_entries_on_one_day_are_still_one_day():
    st = streak([entry("2026-08-20T05:00:00+00:00") for _ in range(50)])
    assert st["ran"] == 1


def test_a_missed_day_is_counted_as_missed():
    st = streak([entry("2026-08-18T05:00:00+00:00"), entry("2026-08-20T05:00:00+00:00")])
    assert st["elapsed"] == 3
    assert st["ran"] == 2
    assert st["gaps"] == ["2026-08-19"]
    assert st["longest_gap"] == 1


def test_consecutive_missed_days_report_the_longest_run():
    st = streak([entry("2026-08-10T05:00:00+00:00"), entry("2026-08-20T05:00:00+00:00")])
    assert st["elapsed"] == 11
    assert st["ran"] == 2
    assert len(st["gaps"]) == 9
    assert st["longest_gap"] == 9


def test_the_span_can_be_extended_to_today_so_silence_since_shows():
    """A monitor that stopped a week ago must not show a full bar."""
    st = streak([entry("2026-08-14T05:00:00+00:00")], today="2026-08-20")
    assert st["elapsed"] == 7
    assert st["ran"] == 1
    assert st["longest_gap"] == 6


def test_a_today_before_the_first_entry_does_not_produce_a_negative_span():
    st = streak([entry("2026-08-20T05:00:00+00:00")], today="2026-08-01")
    assert st["elapsed"] == 1


def test_an_unreadable_timestamp_is_skipped_not_guessed():
    st = streak([entry("2026-08-20T05:00:00+00:00"), entry("not a date"), entry("")])
    assert st["ran"] == 1
    assert st["days"] == ["2026-08-20"]


def test_the_calendar_marks_every_day_in_the_span():
    st = streak([entry("2026-08-18T05:00:00+00:00"), entry("2026-08-20T05:00:00+00:00")])
    assert [d["ran"] for d in st["calendar"]] == [True, False, True]


# ------------------------------------------------------------------ rendering

def test_the_page_states_the_ratio_and_how_it_is_counted():
    html = render_document([entry("2026-08-18T05:00:00+00:00"), entry("2026-08-20T05:00:00+00:00")])
    assert "Cycles ran on 2 of the 3 days" in html
    assert "counted from journal entries rather than from a run" in html


def test_a_gap_is_named_on_the_page_not_smoothed_away():
    html = render_document([entry("2026-08-10T05:00:00+00:00"), entry("2026-08-20T05:00:00+00:00")])
    assert "9 days with no cycle at all" in html
    assert "not counted as anything" in html


def test_an_unbroken_span_says_so_plainly():
    html = render_document([entry("2026-08-19T05:00:00+00:00"), entry("2026-08-20T05:00:00+00:00")])
    assert "No day in that span passed without a cycle." in html


def test_missed_days_render_as_a_different_cell_than_run_days():
    html = render_document([entry("2026-08-18T05:00:00+00:00"), entry("2026-08-20T05:00:00+00:00")])
    assert html.count('class="day day-ran"') == 2
    assert html.count('class="day day-missed"') == 1


def test_a_missed_cell_says_so_on_hover_for_anyone_who_cannot_see_colour():
    html = render_document([entry("2026-08-18T05:00:00+00:00"), entry("2026-08-20T05:00:00+00:00")])
    assert 'title="2026-08-19, no cycle"' in html


def test_an_empty_journal_renders_no_streak_section_at_all():
    """Better to show nothing than a bar that implies a day was watched."""
    assert "Days watched" not in render_document([])
