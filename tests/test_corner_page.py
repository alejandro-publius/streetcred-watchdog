"""One corner's whole history, in the order it happened.

The main ledger is a feed and reads newest first. This page is a history and
reads oldest first, because the shape worth seeing is a long run of mornings
where nothing happened followed by the morning something did, and that shape is
invisible in reverse.

The honesty rule this page has to hold is the same one as everywhere else, in a
new place: a corner with no entries has not been checked and found fine, it has
not been checked.
"""

from __future__ import annotations

import json

from watchdog.ledger import corner_history, render_corner_document, render_corner_to_file
from watchdog.schema import Counts, Snapshot
from watchdog.store import LocalJsonStore


def entry(slug="6th-and-mission", *, ts, run_id=None, actions=None, delta=None, name="6th and Mission"):
    e = {
        "ts": ts, "slug": slug, "name": name,
        "delta": delta or f"No change at {name}.", "trigger": "cron",
        "tier1": {"significant": False, "reason": "Nothing changed since the last look.",
                  "byRule": True, "basis": "no_change"},
        "actions": actions or [], "intents": [],
    }
    if run_id:
        e["runId"] = run_id
    return e


# ------------------------------------------------------------------ filtering

def test_only_this_corner_appears():
    entries = [entry(ts="1"), entry("other-corner", ts="2", name="Other"), entry(ts="3")]
    history = corner_history(entries, "6th-and-mission")
    assert len(history) == 2
    assert all(e["slug"] == "6th-and-mission" for e in history)


def test_the_history_runs_oldest_first():
    entries = [entry(ts="2026-08-20T20:00:00+00:00"), entry(ts="2026-08-19T05:00:00+00:00")]
    history = corner_history(entries, "6th-and-mission")
    assert history[0]["ts"] < history[1]["ts"]


def test_the_page_renders_the_history_in_that_order():
    html = render_corner_document("6th-and-mission", [
        entry(ts="2026-08-19T05:00:00+00:00", delta="No change at 6th and Mission."),
        entry(ts="2026-08-20T05:00:00+00:00", delta="3 new injury collisions."),
    ])
    assert html.index("2026-08-19") < html.index("2026-08-20")


# -------------------------------------------------------------------- content

def test_the_current_record_is_shown_with_the_query_that_produced_it():
    snap = Snapshot(
        slug="6th-and-mission", name="6th and Mission",
        counts=Counts(collisions_5y=62, fatal_5y=0, severe_5y=9, reports_311_3y=239, district=6),
        fetched_at="2026-08-20T05:53:44+00:00", complete=True,
        query_fingerprint="r=80m;collisions=5y",
    )
    html = render_corner_document("6th-and-mission", [entry(ts="1")], snapshot=snap.to_dict())
    assert "62" in html and "239" in html
    assert "r=80m;collisions=5y" in html
    assert "within 80 metres" in " ".join(html.split())  # the markup wraps mid-sentence


def test_the_scoreboard_standing_is_shown_when_known():
    html = render_corner_document(
        "6th-and-mission", [entry(ts="1")],
        corner={"name": "6th and Mission", "grade": "F", "index": 99, "radiusMeters": 80},
    )
    assert "Grade F, Danger Index 99" in html


def test_evaluations_are_counted_and_split_by_outcome():
    history = [entry(ts=str(i)) for i in range(4)] + [entry(ts="9", actions=["rescore"])]
    html = render_corner_document("6th-and-mission", history)
    assert "evaluations" in html
    assert "ended in nothing" in html
    assert "ended in action" in html


def test_missing_run_ids_are_shown_as_unrecorded_not_as_zero_cycles():
    """A bare 0 would say no cycles ran, while meaning the field did not exist."""
    html = render_corner_document("6th-and-mission", [entry(ts="1"), entry(ts="2")])
    assert "cycles not recorded" in html
    assert ">0</span><span class=\"k\">cycles<" not in html


def test_recorded_run_ids_are_counted():
    html = render_corner_document("6th-and-mission", [
        entry(ts="1", run_id="r1"), entry(ts="2", run_id="r1"), entry(ts="3", run_id="r2"),
    ])
    assert ">2</span><span class=\"k\">cycles<" in html


# -------------------------------------------------------------------- honesty

def test_a_corner_with_no_entries_says_it_has_never_been_evaluated():
    html = render_corner_document("some-corner", [])
    assert "has never evaluated this corner" in html
    assert "not that the corner is fine" in html


def test_declines_are_rendered_in_full_here_too():
    html = render_corner_document("6th-and-mission", [entry(ts="1")])
    assert "Nothing changed since the last look." in html
    assert "No action taken." in html


def test_the_page_says_where_it_came_from():
    html = render_corner_document("6th-and-mission", [entry(ts="1")])
    assert "state/journal.jsonl" in html
    assert "6th-and-mission" in html


# ------------------------------------------------------------------- the file

def test_rendering_to_a_file_reads_the_journal_and_the_roster(tmp_path):
    store = LocalJsonStore(tmp_path / "state")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "journal.jsonl").write_text(
        json.dumps(entry(ts="2026-08-20T05:00:00+00:00")) + "\n"
    )
    store.put_snapshot(Snapshot(
        slug="6th-and-mission", name="6th and Mission",
        counts=Counts(collisions_5y=62, fatal_5y=0, severe_5y=9, reports_311_3y=239, district=6),
        fetched_at="2026-08-20T05:53:44+00:00", complete=True, query_fingerprint="r=80m",
    ))
    watched = tmp_path / "watched.json"
    watched.write_text(json.dumps({"corners": [
        {"slug": "6th-and-mission", "name": "6th and Mission", "grade": "F",
         "index": 99, "radiusMeters": 80}
    ]}))

    out = render_corner_to_file(
        "6th-and-mission", state_dir=tmp_path / "state",
        out_path=tmp_path / "page.html", watched_path=watched,
    )
    html = out.read_text()
    assert "Grade F, Danger Index 99" in html
    assert "62" in html
    assert html.startswith("<!doctype html>")


def test_a_hostile_slug_does_not_escape_the_output_directory(tmp_path):
    """Slugs originate from somebody else's public API."""
    out = render_corner_to_file(
        "../../escaped", state_dir=tmp_path / "state",
        out_path=tmp_path / "safe.html", watched_path=tmp_path / "nope.json",
    )
    assert out == tmp_path / "safe.html"
    assert not (tmp_path.parent / "escaped.html").exists()
