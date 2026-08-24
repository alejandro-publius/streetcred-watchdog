"""A baseline that cannot be read must not become a baseline of zero.

There are three wrong ways to handle a corrupted snapshot file and this pins the
fourth. Crashing the sweep takes out twenty four healthy corners because one file
is bad. Coercing the junk to zero produces a corner that appears to have lost
every collision it ever had, which the rule floor then declines to escalate for
exactly the wrong reason. Leaving the bad file in place means it is re-read and
re-rejected on every sweep forever and the corner never rebuilds a baseline.

So the file is moved aside, the corner is treated as having no baseline, the
comparison is refused rather than invented, the next sweep writes a fresh
snapshot, and the sweep after that compares normally. The bad document is kept,
because it is the only evidence of whatever wrote it.
"""

from __future__ import annotations

import asyncio
import json

from corner_watchdog.brains import RuleTriage
from corner_watchdog.bus import DirectBus
from corner_watchdog.observer import Observer
from corner_watchdog.schema import Counts, Snapshot
from corner_watchdog.store import LocalJsonStore

FP = "r=80m;collisions=5y"


def snap(slug="taylor-and-turk", *, collisions=40) -> Snapshot:
    return Snapshot(
        slug=slug, name="Taylor and Turk",
        counts=Counts(collisions_5y=collisions, fatal_5y=1, severe_5y=3,
                      reports_311_3y=120, district=5),
        fetched_at="2026-08-19T20:00:00+00:00", complete=True, query_fingerprint=FP,
    )


def corner(slug="taylor-and-turk"):
    return {"slug": slug, "name": "Taylor and Turk", "lat": 37.78, "lon": -122.41,
            "district": 5, "radiusMeters": 80, "grade": "F", "index": 96}


class Fake:
    def __init__(self, *snaps) -> None:
        self.q = list(snaps)

    def describe(self):
        return "fake"

    async def fetch_all(self, corners):
        return [self.q.pop(0) for _ in corners]


def corrupt(store: LocalJsonStore, slug: str, body: str) -> None:
    (store.snapshots_dir / f"{slug}.json").write_text(body)


# ------------------------------------------------------------- detection

def test_a_truncated_file_is_detected(tmp_path):
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", '{"slug": "taylor-and-turk", "counts": {"colli')
    assert store.get_snapshot("taylor-and-turk") is None
    assert "taylor-and-turk" in store.quarantined


def test_a_junk_count_is_detected_rather_than_read_as_zero(tmp_path):
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk",
            json.dumps({"slug": "taylor-and-turk", "counts": {"collisions_5y": "seventy"}}))
    assert store.get_snapshot("taylor-and-turk") is None
    assert "not a number" in store.quarantined["taylor-and-turk"]


def test_an_empty_file_is_detected(tmp_path):
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", "")
    assert store.get_snapshot("taylor-and-turk") is None


def test_a_healthy_snapshot_is_not_quarantined(tmp_path):
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap())
    assert store.get_snapshot("taylor-and-turk") is not None
    assert store.quarantined == {}


# ------------------------------------------------------------ quarantine

def test_the_bad_file_is_moved_aside_not_left_in_place(tmp_path):
    """Left in place it is re-rejected forever and the corner never recovers."""
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", "{broken")
    store.get_snapshot("taylor-and-turk")
    assert not (store.snapshots_dir / "taylor-and-turk.json").exists()


def test_the_bad_file_is_kept_not_deleted(tmp_path):
    """It is the only evidence of whatever wrote it."""
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", "{broken")
    store.get_snapshot("taylor-and-turk")
    kept = list(store.quarantine_dir.glob("taylor-and-turk.*.json"))
    assert len(kept) == 1
    assert kept[0].read_text() == "{broken"


def test_the_quarantine_is_logged_with_a_reason(tmp_path):
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", "{broken")
    store.get_snapshot("taylor-and-turk")
    log = (tmp_path / "quarantine.log").read_text()
    assert "taylor-and-turk" in log
    assert "JSONDecodeError" in log


def test_two_corrupt_reads_do_not_collide_on_one_filename(tmp_path):
    store = LocalJsonStore(tmp_path)
    for _ in range(2):
        corrupt(store, "taylor-and-turk", "{broken")
        store.get_snapshot("taylor-and-turk")
    assert len(list(store.quarantine_dir.glob("taylor-and-turk.*.json"))) == 2


# --------------------------------------------------------------- recovery

def test_the_corner_rebuilds_its_baseline_on_the_same_sweep(tmp_path):
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", "{broken")
    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake(snap(collisions=42)))
    asyncio.run(obs.sweep([corner()]))
    rebuilt = store.get_snapshot("taylor-and-turk")
    assert rebuilt is not None
    assert rebuilt.counts.collisions_5y == 42


def test_the_sweep_after_a_quarantine_compares_normally(tmp_path):
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", "{broken")
    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake(snap(collisions=42)))
    asyncio.run(obs.sweep([corner()]))

    store2 = LocalJsonStore(tmp_path)
    obs2 = Observer(store2, DirectBus(), RuleTriage("t"), fetcher=Fake(snap(collisions=42)))
    asyncio.run(obs2.sweep([corner()]))
    assert store2.read_journal()[-1]["delta"] == "No change at Taylor and Turk."


# --------------------------------------------------------------- honesty

def test_the_quarantine_is_journaled_as_itself_not_as_a_first_sighting(tmp_path):
    """"Never seen this corner" and "its baseline was destroyed" are different facts."""
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", "{broken")
    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake(snap()))
    result = asyncio.run(obs.sweep([corner()]))

    assert result.quarantined == ["taylor-and-turk"]
    entry = store.read_journal()[-1]
    assert entry["tier1"]["basis"] == "corrupt_baseline"
    assert "unreadable" in entry["delta"]
    assert entry["actions"] == []


def test_a_genuine_first_sighting_is_still_labelled_as_one(tmp_path):
    store = LocalJsonStore(tmp_path)
    obs = Observer(store, DirectBus(), RuleTriage("t"), fetcher=Fake(snap()))
    asyncio.run(obs.sweep([corner()]))
    assert store.read_journal()[-1]["tier1"]["basis"] == "first_sighting"


def test_a_corrupt_baseline_never_escalates(tmp_path):
    """Even when the fresh reading looks alarming next to nothing."""
    store = LocalJsonStore(tmp_path)
    corrupt(store, "taylor-and-turk", "{broken")
    bus = DirectBus()
    published = []

    async def collect(e):
        published.append(e)

    bus.subscribe(collect)
    obs = Observer(store, bus, RuleTriage("t"),
                   fetcher=Fake(snap(collisions=9999)))
    asyncio.run(obs.sweep([corner()]))
    assert published == []


def test_one_corrupt_file_does_not_take_out_the_healthy_corners(tmp_path):
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap("good-corner"))
    corrupt(store, "bad-corner", "{broken")

    obs = Observer(store, DirectBus(), RuleTriage("t"),
                   fetcher=Fake(snap("bad-corner"), snap("good-corner")))
    result = asyncio.run(obs.sweep([corner("bad-corner"), corner("good-corner")]))
    assert result.looked_at == 2
    assert result.quarantined == ["bad-corner"]
