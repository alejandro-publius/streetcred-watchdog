"""The states nobody looks at until they happen.

A cycle that died after twelve corners writes twelve entries and looks, in every
other respect, exactly like a cycle where thirteen corners had nothing to report.
The page cannot tell them apart from the entries alone, which is why the expected
roster size is carried in rather than inferred from the very entries it is meant
to check.

The failure mode being guarded is the quiet one. A half-finished run that renders
as a clean page with a high restraint rate is a page that says "everything is
fine" about thirteen corners it never looked at.
"""

from __future__ import annotations

from pathlib import Path

from watchdog.ledger import coverage, cycles, render_document

DOCS = Path(__file__).resolve().parents[1] / "docs" / "states"


def entry(slug, *, run_id="run-1", basis="no_change", actions=None, ts="2026-08-21T05:00:00+00:00"):
    return {
        "ts": ts, "runId": run_id, "slug": slug, "name": slug,
        "delta": f"No change at {slug}.", "trigger": "cron",
        "tier1": {"significant": False, "reason": "nothing moved", "byRule": True, "basis": basis},
        "actions": actions or [], "intents": [],
    }


# ------------------------------------------------------------------ grouping

def test_entries_group_into_the_cycles_that_wrote_them():
    entries = [entry("a", run_id="r1"), entry("b", run_id="r1"), entry("a", run_id="r2")]
    grouped = cycles(entries)
    assert [c["run_id"] for c in grouped] == ["r1", "r2"]
    assert grouped[0]["corners"] == 2
    assert grouped[1]["corners"] == 1


def test_entries_without_a_run_id_get_their_own_labelled_bucket():
    """Written before run ids existed. Not dropped, not merged into a real cycle."""
    e = entry("a")
    del e["runId"]
    grouped = cycles([e, entry("b", run_id="r1")])
    assert {c["run_id"] for c in grouped} == {"unrecorded", "r1"}


def test_a_corner_seen_twice_in_one_cycle_counts_once():
    grouped = cycles([entry("a"), entry("a")])
    assert grouped[0]["corners"] == 1


# ------------------------------------------------------------------ coverage

def test_a_complete_cycle_is_not_flagged_as_partial():
    entries = [entry(f"c{i}") for i in range(25)]
    cov = coverage(entries, 25)
    assert cov["partial"] is False
    assert cov["covered"] == 25
    assert cov["missing"] == 0


def test_a_cycle_that_stopped_halfway_is_flagged():
    entries = [entry(f"c{i}") for i in range(12)]
    cov = coverage(entries, 25)
    assert cov["partial"] is True
    assert cov["covered"] == 12
    assert cov["missing"] == 13


def test_coverage_reports_on_the_most_recent_cycle_not_the_whole_journal():
    """A complete run yesterday must not paper over a broken one this morning."""
    entries = [entry(f"c{i}", run_id="r1") for i in range(25)]
    entries += [entry(f"c{i}", run_id="r2") for i in range(4)]
    cov = coverage(entries, 25)
    assert cov["run_id"] == "r2"
    assert cov["covered"] == 4
    assert cov["partial"] is True


def test_without_a_roster_size_the_best_previous_cycle_is_the_yardstick():
    entries = [entry(f"c{i}", run_id="r1") for i in range(25)]
    entries += [entry(f"c{i}", run_id="r2") for i in range(4)]
    cov = coverage(entries)
    assert cov["expected"] == 25
    assert cov["partial"] is True


def test_unreadable_corners_are_counted_separately_from_missing_ones():
    """Reached but unreadable, and never reached, are different failures."""
    entries = [entry(f"c{i}") for i in range(3)]
    entries += [entry(f"d{i}", basis="fetch_failed") for i in range(9)]
    cov = coverage(entries, 12)
    assert cov["partial"] is False   # all twelve were reached
    assert cov["unreadable"] == 9


def test_an_empty_journal_has_no_coverage_rather_than_zero_coverage():
    assert coverage([])["has_cycles"] is False


# ------------------------------------------------------------------ rendering

def test_a_partial_cycle_says_so_above_the_restraint_rate():
    html = render_document([entry(f"c{i}") for i in range(12)], roster_size=25)
    assert "The most recent cycle did not finish" in html
    assert "reached 12 of 25 watched corners" in html
    assert "not evidence that they were fine" in html
    assert html.index("did not finish") < html.index("restraint rate")


def test_a_complete_cycle_shows_no_banner():
    html = render_document([entry(f"c{i}") for i in range(25)], roster_size=25)
    assert "did not finish" not in html
    assert "notice-state" not in html.replace(".notice-state {", "")


def test_a_source_being_down_is_named_as_a_refusal_not_a_quiet_corner():
    entries = [entry(f"c{i}") for i in range(3)]
    entries += [entry(f"d{i}", basis="fetch_failed") for i in range(9)]
    html = render_document(entries, roster_size=12)
    assert "A source was unavailable for 9 corners" in html
    assert "baselines were left untouched" in html
    assert "refusals, not as quiet corners" in html


def test_the_empty_state_refuses_to_imply_the_corners_are_fine():
    html = render_document([])
    assert "No cycle has run yet" in html
    assert "not a claim that the watched corners are fine" in html
    assert "python -m watchdog run" in html


def test_the_empty_state_shows_no_streak_and_no_breakdown():
    html = render_document([])
    assert "Days watched" not in html
    assert "What the number is made of" not in html


# ------------------------------------------------- the committed fixture pages

def test_the_three_state_fixtures_are_committed():
    for name in ("empty.html", "partial-cycle.html", "source-down.html"):
        assert (DOCS / name).exists(), f"docs/states/{name} is missing, run tools/render_states.py"


def test_every_fixture_page_says_on_its_face_that_it_is_a_fixture():
    """A fixture page that looks like a real journal is the artefact to avoid."""
    for name in ("empty.html", "partial-cycle.html", "source-down.html"):
        text = (DOCS / name).read_text()
        assert "rendered fixture, not a record of anything that happened" in text
        assert "constructed to force the state" in text
