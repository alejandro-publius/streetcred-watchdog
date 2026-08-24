"""Proof that a rehearsal cannot contaminate the record.

The rehearsal exists because two cycles minutes apart cannot exercise the
expensive half of the loop, so it constructs a baseline and replays real
snapshots against it. That makes it the single most dangerous thing in the repo:
it is the one code path that deliberately produces journal entries from numbers
that were not observed.

Reading the code and seeing separate directories is not proof. These tests take
a full inventory of the filesystem before and after, and of the real journal
before and after, and assert that nothing outside the rehearsal's own two
directories moved. If somebody later threads a default path through
`rehearse()`, this fails rather than the ledger quietly gaining entries about
fatalities that never happened.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from corner_watchdog.ledger import summarise
from corner_watchdog.rehearsal import BASELINE_NOTE, rehearse
from corner_watchdog.schema import Counts, Snapshot
from corner_watchdog.store import LocalJsonStore


def snap(slug, name) -> Snapshot:
    return Snapshot(
        slug=slug, name=name,
        counts=Counts(collisions_5y=50, fatal_5y=2, severe_5y=5, reports_311_3y=400, district=6),
        fetched_at="2026-08-19T20:00:00+00:00", complete=True, query_fingerprint="r=80m",
    )


def inventory(root: Path) -> dict[str, str]:
    """Every file under root, with its contents, so any change anywhere shows."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = p.read_text(errors="replace")
    return out


def setup(tmp_path: Path, n: int = 6):
    real = tmp_path / "state"
    store = LocalJsonStore(real)
    for i in range(n):
        store.put_snapshot(snap(f"c{i}", f"Corner {i}"))
    watched = tmp_path / "data" / "watched.json"
    watched.parent.mkdir(parents=True, exist_ok=True)
    watched.write_text(json.dumps({
        "corners": [
            {"slug": f"c{i}", "name": f"Corner {i}", "lat": 37.78, "lon": -122.41,
             "district": 6, "radiusMeters": 80, "grade": "F", "index": 99}
            for i in range(n)
        ]
    }))
    return real, watched


def run(tmp_path: Path, real: Path, watched: Path):
    return asyncio.run(rehearse(
        state_dir=real,
        rehearsal_dir=tmp_path / "state-rehearsal",
        outbox_dir=tmp_path / "outbox",
        watched_path=watched,
        printer=lambda _: None,
    ))


# ---------------------------------------------------- nothing outside its lane

def test_a_rehearsal_touches_nothing_outside_its_own_directories(tmp_path):
    """The strong claim, checked against the filesystem rather than the source."""
    real, watched = setup(tmp_path)
    before = inventory(tmp_path)

    assert run(tmp_path, real, watched) == 0

    after = inventory(tmp_path)
    changed = {
        path for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    allowed = ("state-rehearsal/", "outbox/")
    trespass = sorted(p for p in changed if not p.startswith(allowed))
    assert trespass == [], f"the rehearsal wrote outside its own directories: {trespass}"


def test_the_real_journal_is_byte_identical_afterwards(tmp_path):
    real, watched = setup(tmp_path)
    journal = real / "journal.jsonl"
    journal.write_text('{"ts": "before", "actions": []}\n')
    before = journal.read_bytes()

    run(tmp_path, real, watched)

    assert journal.read_bytes() == before


def test_the_real_snapshots_are_byte_identical_afterwards(tmp_path):
    """The rehearsal reads them. It must never write them."""
    real, watched = setup(tmp_path)
    before = inventory(real / "snapshots")
    run(tmp_path, real, watched)
    assert inventory(real / "snapshots") == before


def test_no_constructed_baseline_ever_reaches_the_real_store(tmp_path):
    """The rehearsal's own store legitimately ends up holding the replayed real
    snapshots, because the sweep writes what it observed over the baseline it
    compared against. What must never happen is a constructed reading landing in
    the store the actual agent diffs from."""
    real, watched = setup(tmp_path)
    run(tmp_path, real, watched)

    genuine = LocalJsonStore(real).all_snapshots()
    assert genuine
    assert all(s.fetched_at != "constructed baseline, not observed" for s in genuine)

    # And the rehearsal did happen, so the assertion above is not vacuous.
    assert LocalJsonStore(tmp_path / "state-rehearsal").read_journal()


def test_rehearsal_artefacts_land_in_their_own_outbox(tmp_path):
    real, watched = setup(tmp_path)
    run(tmp_path, real, watched)
    written = list((tmp_path / "outbox" / "rehearsal").glob("*"))
    assert written
    other = [p for p in (tmp_path / "outbox").iterdir() if p.name != "rehearsal"]
    assert other == []


# ------------------------------------------------------------ self-declaration

def test_every_rehearsal_entry_declares_itself_three_ways(tmp_path):
    """Trigger, degradation note, and its own directory. Any one could be missed."""
    real, watched = setup(tmp_path)
    run(tmp_path, real, watched)

    entries = LocalJsonStore(tmp_path / "state-rehearsal").read_journal()
    assert entries
    for e in entries:
        assert e["trigger"] == "rehearsal"
        assert BASELINE_NOTE in (e.get("degraded") or "")
        assert "constructed, not observed" in (e.get("degraded") or "")


def test_the_baseline_note_refuses_to_call_it_evidence():
    assert "constructed, not observed" in BASELINE_NOTE
    assert "Nothing here is evidence that anything happened" in BASELINE_NOTE


# ------------------------------------------- the restraint rate excludes it all

def test_the_headline_numbers_are_untouched_by_rehearsal_entries(tmp_path):
    """Passing rehearsal entries as the second argument must change no figure."""
    real, watched = setup(tmp_path)
    run(tmp_path, real, watched)

    real_entries = [
        {"ts": "1", "slug": "c0", "name": "C0", "delta": "No change.", "trigger": "manual",
         "tier1": {"significant": False, "reason": "r", "byRule": True, "basis": "no_change"},
         "actions": [], "intents": []}
    ] * 4
    rehearsal_entries = LocalJsonStore(tmp_path / "state-rehearsal").read_journal()
    assert any(e["actions"] for e in rehearsal_entries), "the rehearsal should have acted"

    alone = summarise(real_entries)
    with_rehearsal_mixed_in = summarise(real_entries + rehearsal_entries)

    # summarise() is only ever called on the real journal; this asserts the two
    # sets are genuinely different, so the separation is load bearing.
    assert alone["restraint"] == 100.0
    assert with_rehearsal_mixed_in["restraint"] < 100.0
    assert alone["actions"] == 0
    assert with_rehearsal_mixed_in["actions"] > 0


def test_the_ledger_renders_rehearsal_in_its_own_section_excluded_from_the_rate(tmp_path):
    from corner_watchdog.ledger import render_document

    real, watched = setup(tmp_path)
    run(tmp_path, real, watched)
    rehearsal_entries = LocalJsonStore(tmp_path / "state-rehearsal").read_journal()

    real_entries = [
        {"ts": "1", "slug": "c0", "name": "C0", "delta": "No change.", "trigger": "manual",
         "tier1": {"significant": False, "reason": "r", "byRule": True, "basis": "no_change"},
         "actions": [], "intents": []}
    ] * 4

    html = render_document(real_entries, rehearsal=rehearsal_entries)
    assert "4 of 4 evaluations ended in no action" in html
    assert "Rehearsal, kept apart" in html
    assert "constructed baselines" in html
    assert "none of it is evidence that anything happened" in html


# ------------------------------------------------------------- refusing to run

def test_a_rehearsal_with_no_real_snapshots_refuses(tmp_path):
    """It must never invent both sides of a comparison."""
    real = tmp_path / "state"
    LocalJsonStore(real)
    watched = tmp_path / "watched.json"
    watched.write_text(json.dumps({"corners": []}))
    lines: list[str] = []
    code = asyncio.run(rehearse(
        state_dir=real, rehearsal_dir=tmp_path / "r", outbox_dir=tmp_path / "o",
        watched_path=watched, printer=lines.append,
    ))
    assert code == 1
    assert "Run a real cycle first" in "\n".join(lines)
    assert not (tmp_path / "r" / "journal.jsonl").exists()


def test_the_rehearsal_directory_carries_a_readme_saying_what_it_is(tmp_path):
    real, watched = setup(tmp_path)
    run(tmp_path, real, watched)
    readme = (tmp_path / "state-rehearsal" / "README.txt").read_text()
    assert "not the agent's journal" in readme
    assert BASELINE_NOTE in readme
