"""The rehearsal, and the one way it can lie.

A rehearsal exists to prove the expensive half of the loop runs. If it announces
a scenario it did not actually construct, it proves the opposite of what it
claims while looking identical in the output, which is worse than not running.

The first version of rehearsal.py did exactly that: it subtracted a fatality
from a corner whose real fatal count was zero, floored at zero, produced no
delta, and printed "a new fatality" anyway. These tests hold that shut.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from watchdog.rehearsal import SCENARIOS, _can_absorb, _lower, rehearse
from watchdog.schema import Counts, Snapshot
from watchdog.store import LocalJsonStore


def snap(slug, name, *, collisions, fatal, severe, reports) -> Snapshot:
    return Snapshot(
        slug=slug,
        name=name,
        counts=Counts(
            collisions_5y=collisions,
            fatal_5y=fatal,
            severe_5y=severe,
            reports_311_3y=reports,
            district=6,
        ),
        fetched_at="2026-08-19T20:00:00+00:00",
        complete=True,
    )


def test_a_corner_without_a_fatality_cannot_host_the_fatality_scenario():
    """The exact bug: max(0, 0 - 1) is 0, and the scenario silently evaporates."""
    barren = snap("a", "A", collisions=50, fatal=0, severe=5, reports=400)
    assert _can_absorb(barren, {"fatal_5y": 1, "collisions_5y": 1}) is False

    rich = snap("b", "B", collisions=50, fatal=2, severe=5, reports=400)
    assert _can_absorb(rich, {"fatal_5y": 1, "collisions_5y": 1}) is True


def test_lowering_a_record_it_can_absorb_actually_moves_the_number():
    now = snap("b", "B", collisions=50, fatal=2, severe=5, reports=400)
    before = _lower(now, {"fatal_5y": 1, "collisions_5y": 1})
    assert before.counts.fatal_5y == 1
    assert before.counts.collisions_5y == 49
    assert now.counts.fatal_5y - before.counts.fatal_5y == 1


def test_a_constructed_baseline_says_it_was_constructed():
    before = _lower(snap("b", "B", collisions=50, fatal=2, severe=5, reports=400), {"fatal_5y": 1})
    assert before.fetched_at == "constructed baseline, not observed"


def _setup(tmp_path, snapshots):
    state = tmp_path / "state"
    store = LocalJsonStore(state)
    for s in snapshots:
        store.put_snapshot(s)
    watched = tmp_path / "watched.json"
    watched.write_text(
        json.dumps(
            {
                "corners": [
                    {"slug": s.slug, "name": s.name, "lat": 37.78, "lon": -122.41,
                     "district": 6, "radiusMeters": 150, "grade": "F", "index": 99}
                    for s in snapshots
                ]
            }
        )
    )
    return state, watched


def test_an_unrunnable_scenario_is_named_out_loud(tmp_path):
    """Every watched corner here has zero fatalities, so that scenario cannot run."""
    snapshots = [
        snap(f"c{i}", f"Corner {i}", collisions=50, fatal=0, severe=5, reports=400)
        for i in range(6)
    ]
    state, watched = _setup(tmp_path, snapshots)
    lines: list[str] = []

    code = asyncio.run(
        rehearse(
            state_dir=state,
            rehearsal_dir=tmp_path / "rehearsal",
            outbox_dir=tmp_path / "outbox",
            watched_path=watched,
            printer=lines.append,
        )
    )
    out = "\n".join(lines)
    assert code == 0
    assert "NOT REHEARSED" in out
    assert "a new fatality" in out


def test_the_fatality_scenario_actually_reaches_the_flag_action(tmp_path):
    snapshots = [
        snap("c0", "Corner 0", collisions=50, fatal=2, severe=5, reports=400),
        snap("c1", "Corner 1", collisions=50, fatal=0, severe=5, reports=400),
        snap("c2", "Corner 2", collisions=50, fatal=0, severe=0, reports=400),
        snap("c3", "Corner 3", collisions=50, fatal=0, severe=0, reports=400),
        snap("c4", "Corner 4", collisions=50, fatal=0, severe=0, reports=400),
        snap("c5", "Corner 5", collisions=50, fatal=0, severe=0, reports=400),
    ]
    state, watched = _setup(tmp_path, snapshots)
    lines: list[str] = []

    asyncio.run(
        rehearse(
            state_dir=state,
            rehearsal_dir=tmp_path / "rehearsal",
            outbox_dir=tmp_path / "outbox",
            watched_path=watched,
            printer=lines.append,
        )
    )

    entries = LocalJsonStore(tmp_path / "rehearsal").read_journal()
    fatal_entries = [e for e in entries if "fatal" in e["delta"]]
    assert fatal_entries, "the fatality scenario produced no journal entry"
    assert "flag" in fatal_entries[0]["actions"]
    assert fatal_entries[0]["tier1"]["byRule"] is True


def test_every_rehearsal_entry_admits_its_baseline_was_constructed(tmp_path):
    snapshots = [
        snap(f"c{i}", f"Corner {i}", collisions=50, fatal=2, severe=5, reports=400)
        for i in range(6)
    ]
    state, watched = _setup(tmp_path, snapshots)

    asyncio.run(
        rehearse(
            state_dir=state,
            rehearsal_dir=tmp_path / "rehearsal",
            outbox_dir=tmp_path / "outbox",
            watched_path=watched,
            printer=lambda _: None,
        )
    )

    entries = LocalJsonStore(tmp_path / "rehearsal").read_journal()
    assert entries
    for e in entries:
        assert e["trigger"] == "rehearsal"
        assert "constructed, not observed" in (e.get("degraded") or "")


def test_the_rehearsal_never_writes_into_the_real_journal(tmp_path):
    snapshots = [
        snap(f"c{i}", f"Corner {i}", collisions=50, fatal=2, severe=5, reports=400)
        for i in range(6)
    ]
    state, watched = _setup(tmp_path, snapshots)

    asyncio.run(
        rehearse(
            state_dir=state,
            rehearsal_dir=tmp_path / "rehearsal",
            outbox_dir=tmp_path / "outbox",
            watched_path=watched,
            printer=lambda _: None,
        )
    )

    assert LocalJsonStore(state).read_journal() == []
    assert LocalJsonStore(tmp_path / "rehearsal").read_journal()


def test_the_rehearsal_refuses_without_real_snapshots_to_work_from(tmp_path):
    """It must never invent both sides of a comparison."""
    state, watched = _setup(tmp_path, [])
    lines: list[str] = []
    code = asyncio.run(
        rehearse(
            state_dir=state,
            rehearsal_dir=tmp_path / "rehearsal",
            outbox_dir=tmp_path / "outbox",
            watched_path=watched,
            printer=lines.append,
        )
    )
    assert code == 1
    assert "Run a real cycle first" in "\n".join(lines)


def test_every_scenario_declares_something_the_loop_can_act_on():
    descriptions = [d for d, _ in SCENARIOS]
    assert len(set(descriptions)) == len(descriptions)
    assert any(lower.get("fatal_5y") for _, lower in SCENARIOS)
    assert any(lower.get("severe_5y") for _, lower in SCENARIOS)
    assert any(not lower for _, lower in SCENARIOS)  # the do-nothing case
