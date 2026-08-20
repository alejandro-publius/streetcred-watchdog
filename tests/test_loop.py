"""The local loop, end to end, with no network and no clock dependency.

The tests that matter here are the ones that pin behaviour somebody would
plausibly "simplify" later and thereby break quietly:

  a bad fetch must not become the new baseline
  a decline must be journaled, not dropped
  an exhausted budget must produce an intent, not a silent skip
  the dry run must produce the artefact, not a log line about it
  the live path must refuse rather than fall through to dry
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from watchdog.actor import Actor
from watchdog.brains import RuleDecider, RuleTriage
from watchdog.budget import ActionBudget
from watchdog.bus import DirectBus
from watchdog.cli import main as cli_main
from watchdog.observer import Observer
from watchdog.outbox import DryRunActuator
from watchdog.runner import run_cycle
from watchdog.schema import Calibration, Counts, Delta, JournalEntry, Snapshot, Tier1Verdict
from watchdog.store import LocalJsonStore


def snap(slug="taylor-and-turk", name="Taylor and Turk", *, collisions=40, fatal=1, severe=3,
         reports=120, district=5, complete=True) -> Snapshot:
    return Snapshot(
        slug=slug,
        name=name,
        counts=Counts(
            collisions_5y=collisions,
            fatal_5y=fatal,
            severe_5y=severe,
            reports_311_3y=reports,
            district=district,
        ),
        fetched_at="2026-08-19T20:00:00+00:00",
        complete=complete,
    )


def corner(slug="taylor-and-turk", name="Taylor and Turk"):
    return {
        "slug": slug,
        "name": name,
        "lat": 37.7835,
        "lon": -122.4110,
        "district": 5,
        "radiusMeters": 150,
        "grade": "F",
        "index": 96,
    }


class FakeFetcher:
    """Hands back prepared snapshots. Opens nothing."""

    def __init__(self, *snapshots) -> None:
        self.queue = list(snapshots)

    def describe(self) -> str:
        return "FakeFetcher, prepared snapshots, no network"

    async def fetch_all(self, corners):
        return [self.queue.pop(0) for _ in corners]


# ------------------------------------------------------------------- the store

def test_store_round_trips_a_snapshot(tmp_path):
    s = LocalJsonStore(tmp_path)
    assert s.get_snapshot("taylor-and-turk") is None
    s.put_snapshot(snap())
    got = s.get_snapshot("taylor-and-turk")
    assert got is not None
    assert got.counts.collisions_5y == 40
    assert got.counts.district == 5


def test_store_journal_is_append_only(tmp_path):
    s = LocalJsonStore(tmp_path)
    for i in range(3):
        s.append_journal(
            JournalEntry(
                ts=f"2026-08-19T0{i}:00:00+00:00",
                slug="a",
                name="A",
                delta="No change at A.",
                trigger="manual",
                tier1=Tier1Verdict(significant=False, reason="nothing moved", by_rule=True),
            )
        )
    entries = s.read_journal()
    assert len(entries) == 3
    assert [e["ts"] for e in entries] == sorted(e["ts"] for e in entries)


def test_a_hostile_slug_cannot_escape_the_state_directory(tmp_path):
    """Slugs arrive from somebody else's public API."""
    s = LocalJsonStore(tmp_path / "state")
    s.put_snapshot(snap(slug="../../etc/passwd", name="nope"))
    escaped = (tmp_path / "etc").exists() or (tmp_path.parent / "etc").exists()
    assert not escaped
    assert list((tmp_path / "state" / "snapshots").glob("*.json"))


def test_a_torn_journal_line_does_not_hide_the_rest(tmp_path):
    s = LocalJsonStore(tmp_path)
    s.append_journal(
        JournalEntry(ts="1", slug="a", name="A", delta="d", trigger="manual",
                     tier1=Tier1Verdict(significant=False, reason="r"))
    )
    with s.journal_path.open("a") as fh:
        fh.write('{"ts": "2", "hal\n')
    s.append_journal(
        JournalEntry(ts="3", slug="b", name="B", delta="d", trigger="manual",
                     tier1=Tier1Verdict(significant=False, reason="r"))
    )
    assert [e["ts"] for e in s.read_journal()] == ["1", "3"]


def test_calibration_bounds_are_code_not_data(tmp_path):
    """An edited state file must not be able to widen the safety limits."""
    s = LocalJsonStore(tmp_path)
    s.calibration_path.parent.mkdir(parents=True, exist_ok=True)
    s.calibration_path.write_text(
        json.dumps({"reports_311_jump": 15, "min_new_collisions": 1,
                    "bounds": {"min_new_collisions": [0, 999]}, "history": []})
    )
    c = s.get_calibration()
    c.adjust("min_new_collisions", 0, "trying to widen the floor from a file")
    assert c.min_new_collisions == 1


# --------------------------------------------------------------------- the bus

def test_the_bus_round_trips_through_json():
    """Anything Pub/Sub could not carry must fail locally, not in production."""
    bus = DirectBus()
    seen = []

    async def sub(envelope):
        seen.append(envelope)

    bus.subscribe(sub)
    asyncio.run(bus.publish({"corner": {"slug": "a"}, "n": 1}))
    assert seen == [{"corner": {"slug": "a"}, "n": 1}]
    assert bus.published == 1


def test_the_bus_refuses_a_payload_pubsub_could_not_carry():
    bus = DirectBus()
    with pytest.raises(TypeError):
        asyncio.run(bus.publish({"snapshot": snap()}))


# ------------------------------------------------------------------ the brains

def _judge(delta, cal=None):
    return asyncio.run(RuleTriage("test").judge(delta, corner(), cal or Calibration()))


def test_triage_escalates_a_new_collision_at_the_threshold():
    v = _judge(Delta(slug="a", name="A", new_collisions=1, empty=False))
    assert v.significant is True
    assert v.by_rule is False


def test_triage_declines_ordinary_311_variance():
    v = _judge(Delta(slug="a", name="A", reports_311_change=4, empty=False))
    assert v.significant is False
    assert "variance" in v.reason


def test_triage_escalates_a_311_swing_past_the_bar():
    v = _judge(Delta(slug="a", name="A", reports_311_change=22, empty=False))
    assert v.significant is True


def test_triage_respects_a_raised_threshold():
    cal = Calibration()
    cal.adjust("reports_311_jump", 40, "a noisy month")
    v = _judge(Delta(slug="a", name="A", reports_311_change=22, empty=False), cal)
    assert v.significant is False


def test_the_decider_can_decline_an_escalation():
    """Tier two returning nothing is a considered outcome, not a failure."""
    d = Delta(slug="a", name="A", empty=False, note="something moved that changes no figure")
    decision = asyncio.run(RuleDecider("test").decide(d, corner(), Counts(), "escalated for a look"))
    assert decision.actions == []
    assert "decline" in decision.reasoning


def test_a_new_fatality_produces_a_flag_as_well_as_a_redraft():
    d = Delta(slug="a", name="A", new_collisions=1, new_fatal=1, empty=False)
    decision = asyncio.run(RuleDecider("test").decide(d, corner(), Counts(), "rule floor"))
    assert "flag" in decision.actions
    assert "regenerate_letter" in decision.actions
    assert decision.actions.count("regenerate_letter") == 1


# ------------------------------------------------------------------ the budget

def test_an_exhausted_budget_becomes_an_intent_not_a_skip():
    b = ActionBudget(limit=1)
    assert b.take("rescore") is True
    assert b.take("regenerate_letter") is False
    assert "budget reached" in ActionBudget.intent_for("regenerate_letter")
    assert b.refused == ["regenerate_letter"]


def test_budget_intents_reach_the_journal(tmp_path):
    store = LocalJsonStore(tmp_path)
    actor = Actor(store, RuleDecider("test"), DryRunActuator(tmp_path / "outbox"), ActionBudget(limit=1))
    envelope = {
        "trigger": "manual",
        "corner": corner(),
        "delta": {"slug": "taylor-and-turk", "name": "Taylor and Turk", "new_collisions": 2, "empty": False},
        "delta_summary": "Taylor and Turk: 2 new injury collisions.",
        "counts": snap().counts.to_dict(),
        "tier1": {"significant": True, "reason": "two new injury collisions", "byRule": False},
    }
    asyncio.run(actor.handle(envelope))
    entry = store.read_journal()[-1]
    assert entry["actions"] == ["rescore"]
    assert entry["intents"] and "budget reached" in entry["intents"][0]


# ----------------------------------------------------------------- the outbox

def test_the_dry_run_renders_the_letter_itself(tmp_path):
    act = DryRunActuator(tmp_path)
    path = asyncio.run(
        act.regenerate_letter(
            corner(), snap().counts,
            Delta(slug="a", name="Taylor and Turk", new_collisions=2, empty=False),
            "two new injury collisions on the record",
        )
    )
    body = Path(path).read_text()
    assert "DRY RUN" in body
    assert "40 injury" in body  # the real count, not a placeholder
    assert "Supervisor, District 5" in body
    assert act.is_live is False


def test_the_letter_says_so_when_nobody_was_killed(tmp_path):
    act = DryRunActuator(tmp_path)
    counts = Counts(collisions_5y=12, fatal_5y=0, severe_5y=1, reports_311_3y=30, district=5)
    path = asyncio.run(
        act.regenerate_letter(corner(), counts, Delta(slug="a", name="A", empty=False), "r")
    )
    assert "None of those collisions killed anyone" in Path(path).read_text()


def test_an_unknown_action_is_a_loud_bug(tmp_path):
    actor = Actor(LocalJsonStore(tmp_path), RuleDecider("t"), DryRunActuator(tmp_path), ActionBudget())
    with pytest.raises(ValueError):
        asyncio.run(actor._run("teleport", corner(), Counts(), Delta(slug="a", name="A"), "r"))


# ------------------------------------------------------------------- the sweep

def test_an_incomplete_fetch_does_not_become_the_new_baseline(tmp_path):
    """One bad minute at DataSF must not poison a corner permanently."""
    store = LocalJsonStore(tmp_path)
    store.put_snapshot(snap(collisions=40))

    observer = Observer(store, DirectBus(), RuleTriage("t"),
                        fetcher=FakeFetcher(snap(collisions=0, fatal=0, severe=0, reports=0, complete=False)))
    result = asyncio.run(observer.sweep([corner()]))

    assert result.unreliable == 1
    assert store.get_snapshot("taylor-and-turk").counts.collisions_5y == 40
    entry = store.read_journal()[-1]
    assert entry["actions"] == []
    assert "unreliable" in entry["tier1"]["reason"]


def test_a_failed_fetch_is_journaled_as_a_corner_we_could_not_read(tmp_path):
    store = LocalJsonStore(tmp_path)
    observer = Observer(store, DirectBus(), RuleTriage("t"),
                        fetcher=FakeFetcher(TimeoutError("datasf said no")))
    result = asyncio.run(observer.sweep([corner()]))
    assert result.unreliable == 1
    entry = store.read_journal()[-1]
    assert "Could not read" in entry["delta"]
    assert "TimeoutError" in entry["degraded"]


def test_the_first_sighting_escalates_nothing(tmp_path):
    store = LocalJsonStore(tmp_path)
    bus = DirectBus()
    published = []
    bus.subscribe(lambda e: _collect(published, e))
    observer = Observer(store, bus, RuleTriage("t"), fetcher=FakeFetcher(snap()))
    result = asyncio.run(observer.sweep([corner()]))
    assert result.first_sightings == 1
    assert result.escalated == 0
    assert published == []
    assert store.read_journal()[-1]["actions"] == []


async def _collect(sink, envelope):
    sink.append(envelope)


# ------------------------------------------------------------- the whole cycle

def test_a_full_cycle_acts_and_journals(tmp_path):
    """Baseline, then a genuine change: escalate, deliberate, act, journal."""
    store = LocalJsonStore(tmp_path / "state")
    store.put_snapshot(snap(collisions=40, fatal=1))

    report = asyncio.run(
        run_cycle(
            [corner()],
            store=store,
            outbox_dir=tmp_path / "outbox",
            run_id="t",
            fetcher=FakeFetcher(snap(collisions=42, fatal=2)),
        )
    )

    assert report.sweep.escalated == 1
    assert report.actor.acted == 1
    assert "flag" in report.actor.actions_taken

    entry = store.read_journal()[-1]
    assert entry["tier1"]["byRule"] is True
    assert "before any model is consulted" in entry["tier1"]["reason"]
    assert entry["tier2"]["reasoning"]
    assert set(entry["actions"]) >= {"rescore", "regenerate_letter", "flag"}
    assert entry["degraded"]  # the stand-ins admitted themselves

    written = sorted(p.name for p in (tmp_path / "outbox" / "t").iterdir())
    assert "taylor-and-turk.letter.txt" in written
    assert "taylor-and-turk.flag.json" in written


def test_a_full_cycle_that_declines_journals_the_decline(tmp_path):
    store = LocalJsonStore(tmp_path / "state")
    store.put_snapshot(snap(reports=120))

    report = asyncio.run(
        run_cycle(
            [corner()],
            store=store,
            outbox_dir=tmp_path / "outbox",
            run_id="t",
            fetcher=FakeFetcher(snap(reports=124)),
        )
    )

    assert report.sweep.escalated == 0
    assert report.sweep.declined == 1
    entry = store.read_journal()[-1]
    assert entry["actions"] == []
    assert "variance" in entry["tier1"]["reason"]
    # The manifest is written either way; nothing else is.
    written = sorted(p.name for p in (tmp_path / "outbox" / "t").iterdir())
    assert written == ["MANIFEST.txt"]
    assert "(nothing)" in (tmp_path / "outbox" / "t" / "MANIFEST.txt").read_text()


def test_two_cycles_against_an_unchanged_city_stay_quiet(tmp_path):
    store = LocalJsonStore(tmp_path / "state")
    for _ in range(2):
        asyncio.run(
            run_cycle([corner()], store=store, outbox_dir=tmp_path / "outbox", run_id="t",
                      fetcher=FakeFetcher(snap()))
        )
    entries = store.read_journal()
    assert len(entries) == 2
    assert all(e["actions"] == [] for e in entries)
    assert entries[1]["delta"] == "No change at Taylor and Turk."


# --------------------------------------------------------------- the live path

def test_the_live_flag_refuses_and_does_not_fall_through_to_dry(capsys):
    code = cli_main(["run", "--live"])
    out = capsys.readouterr().out
    assert code == 2
    assert "Refusing --live" in out
    assert "Nothing in this build posts to StreetCred" in out


def test_nothing_in_the_local_loop_imports_the_streetcred_poster():
    """ingest.py holds the only code that can POST. The local loop must not reach it."""
    import watchdog.actor as a
    import watchdog.observer as o
    import watchdog.outbox as ob
    import watchdog.runner as r

    for mod in (a, o, ob, r):
        src = Path(mod.__file__).read_text()
        assert "from .ingest" not in src and "import ingest" not in src


def test_the_live_actuator_refuses_every_verb():
    """It implements the protocol so the seam keeps type checking. It sends nothing."""
    from watchdog.live import LiveActuator, LivePathRefused

    live = LiveActuator()
    assert live.is_live is True

    calls = [
        live.rescore(corner(), Counts(), "r"),
        live.regenerate_letter(corner(), Counts(), Delta(slug="a", name="A"), "r"),
        live.reaudit_imagery(corner(), Counts(), Delta(slug="a", name="A"), "r"),
        live.flag(corner(), "r"),
    ]
    for call in calls:
        with pytest.raises(LivePathRefused) as excinfo:
            asyncio.run(call)
        assert "does not post to StreetCred" in str(excinfo.value)
        assert "WATCHDOG_INGEST_TOKEN" in str(excinfo.value)


def test_the_live_actuator_never_reads_the_token():
    """A module that reads a credential in order to refuse is one edit from using it."""
    from watchdog import live

    src = Path(live.__file__).read_text()
    assert "environ" not in src
    assert "httpx" not in src


def test_the_manifest_is_written_even_when_nothing_was_acted_on(tmp_path):
    act = DryRunActuator(tmp_path, run_id="quiet")
    path = act.write_manifest()
    body = Path(path).read_text()
    assert "artefacts: 0" in body
    assert "Nothing in this directory was sent" in body
    assert "did not warrant touching anything" in body
