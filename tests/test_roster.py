"""The watched set as a claim, and what happens when it moves.

The roster is read from page one of a scoreboard ordered by points that change
on every sweep. It is not a fixed list, it is a snapshot of a ranking. The
failure this guards is quiet: a corner drops out, the sweep never sees it, no
entry is written, and the journal for that morning is indistinguishable from one
where the corner was fine.
"""

from __future__ import annotations

import asyncio
import json

from watchdog.brains import RuleTriage
from watchdog.bus import DirectBus
from watchdog.observer import Observer
from watchdog.roster import describe, drift, roster_hash
from watchdog.schema import UNJUDGED_BASES, Counts, Snapshot
from watchdog.store import LocalJsonStore
from watchdog.watched import verify


def snap(slug, name=None) -> Snapshot:
    return Snapshot(
        slug=slug,
        name=name or slug,
        counts=Counts(collisions_5y=40, fatal_5y=1, severe_5y=3, reports_311_3y=120, district=6),
        fetched_at="2026-08-19T20:00:00+00:00",
        complete=True,
        query_fingerprint="r=80m",
    )


def corner(slug):
    return {"slug": slug, "name": slug, "lat": 37.78, "lon": -122.41,
            "district": 6, "radiusMeters": 80, "grade": "F", "index": 99}


class Fake:
    def __init__(self, *snaps):
        self.q = list(snaps)

    def describe(self):
        return "fake"

    async def fetch_all(self, corners):
        return [self.q.pop(0) for _ in corners]


# -------------------------------------------------------------------- hashing

def test_the_hash_ignores_ordering():
    """The scoreboard reorders constantly. Only membership is drift."""
    assert roster_hash(["a", "b", "c"]) == roster_hash(["c", "a", "b"])


def test_the_hash_notices_a_swap():
    assert roster_hash(["a", "b", "c"]) != roster_hash(["a", "b", "d"])


def test_the_hash_notices_a_size_change():
    assert roster_hash(["a", "b"]) != roster_hash(["a", "b", "c"])


# ---------------------------------------------------------------------- drift

def test_drift_names_what_joined_and_left():
    d = drift(["a", "b", "c"], ["b", "c", "d"])
    assert d["added"] == ["d"]
    assert d["removed"] == ["a"]
    assert d["unchanged"] == 2
    assert d["membership_changed"] is True


def test_a_pure_reorder_is_reported_but_is_not_membership_drift():
    d = drift(["a", "b", "c"], ["c", "b", "a"])
    assert d["membership_changed"] is False
    assert d["reordered"] is True
    assert "the ranking moved" in " ".join(describe(d))


def test_an_identical_roster_reports_no_change():
    d = drift(["a", "b"], ["a", "b"])
    assert d["membership_changed"] is False
    assert d["reordered"] is False
    assert "membership unchanged" in " ".join(describe(d))


# ------------------------------------------------------------- tamper detection

def test_a_hand_edited_roster_is_detected():
    doc = {"roster_hash": roster_hash(["a", "b"]), "corners": [{"slug": "a"}, {"slug": "z"}]}
    problem = verify(doc)
    assert problem is not None
    assert "edited after it was saved" in problem


def test_an_intact_roster_verifies_clean():
    doc = {"roster_hash": roster_hash(["a", "b"]), "corners": [{"slug": "a"}, {"slug": "b"}]}
    assert verify(doc) is None


def test_a_roster_without_a_hash_says_so_rather_than_passing():
    assert "cannot be detected" in verify({"corners": [{"slug": "a"}]})


# ------------------------------------------------------- the drop is journaled

def test_a_corner_that_leaves_the_roster_is_journaled(tmp_path):
    """The whole point: absence has to be legible."""
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap("dropped-corner"))
    store.put_snapshot(snap("still-watched"))

    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake(snap("still-watched")))
    result = asyncio.run(obs.sweep([corner("still-watched")]))

    assert result.roster_drops == ["dropped-corner"]
    entries = store.read_journal()
    drop = [e for e in entries if e["slug"] == "dropped-corner"]
    assert len(drop) == 1
    assert drop[0]["tier1"]["basis"] == "roster_drop"
    assert drop[0]["actions"] == []
    assert "stopped looking" in drop[0]["tier1"]["reason"]


def test_the_drop_entry_does_not_claim_the_corner_improved(tmp_path):
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap("dropped-corner"))
    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake())
    asyncio.run(obs.sweep([]))
    reason = store.read_journal()[0]["tier1"]["reason"]
    assert "not a statement that the corner improved" in reason


def test_a_dropped_corner_keeps_its_baseline(tmp_path):
    """If it returns to the roster the comparison should resume, not restart."""
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap("dropped-corner"))
    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake())
    asyncio.run(obs.sweep([]))
    assert store.get_snapshot("dropped-corner") is not None


def test_a_roster_drop_is_never_counted_as_judgment():
    assert "roster_drop" in UNJUDGED_BASES


def test_nothing_is_journaled_when_the_roster_is_intact(tmp_path):
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap("a"))
    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake(snap("a")))
    result = asyncio.run(obs.sweep([corner("a")]))
    assert result.roster_drops == []
    assert all(e["tier1"].get("basis") != "roster_drop" for e in store.read_journal())


# ------------------------------------------------------------------ the pinning

def test_refetch_refuses_to_overwrite_a_changed_roster(tmp_path, monkeypatch, capsys):
    from watchdog import cli

    path = tmp_path / "watched.json"
    path.write_text(json.dumps({
        "roster_hash": roster_hash(["a", "b"]),
        "fetched_at": "2026-08-19T20:00:00+00:00",
        "corners": [{"slug": "a"}, {"slug": "b"}],
    }))

    async def fake_fetch(count, *, origin, client=None):
        return {"count": 2, "roster_hash": roster_hash(["a", "z"]), "source": "test",
                "dropped_for_missing_coordinates": [],
                "corners": [{"slug": "a", "name": "A", "scoreboard_rank": 1, "points": 1, "grade": "F"},
                            {"slug": "z", "name": "Z", "scoreboard_rank": 2, "points": 1, "grade": "F"}]}

    monkeypatch.setattr(cli.watched_mod, "fetch_worst", fake_fetch)
    code = cli.main(["--watched", str(path), "watched"])
    out = capsys.readouterr().out

    assert code == 3
    assert "Refusing to overwrite" in out
    assert "left the watched set:   b" in out
    assert "joined the watched set: z" in out
    # Untouched on disk.
    assert json.loads(path.read_text())["roster_hash"] == roster_hash(["a", "b"])


def test_accept_drift_takes_the_new_roster(tmp_path, monkeypatch, capsys):
    from watchdog import cli

    path = tmp_path / "watched.json"
    path.write_text(json.dumps({
        "roster_hash": roster_hash(["a", "b"]),
        "corners": [{"slug": "a"}, {"slug": "b"}],
    }))

    async def fake_fetch(count, *, origin, client=None):
        return {"count": 2, "roster_hash": roster_hash(["a", "z"]), "source": "test",
                "dropped_for_missing_coordinates": [],
                "corners": [{"slug": "a", "name": "A", "scoreboard_rank": 1, "points": 1, "grade": "F"},
                            {"slug": "z", "name": "Z", "scoreboard_rank": 2, "points": 1, "grade": "F"}]}

    monkeypatch.setattr(cli.watched_mod, "fetch_worst", fake_fetch)
    code = cli.main(["--watched", str(path), "watched", "--accept-drift"])
    assert code == 0
    assert json.loads(path.read_text())["roster_hash"] == roster_hash(["a", "z"])
