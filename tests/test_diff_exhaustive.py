"""Every change class, at its boundary, in both directions.

Each class gets two tests: it fires when it should, and it stays silent when it
should. A guard that only has the first is a guard nobody has proved is a guard,
because a function that returns True unconditionally passes it.

The threshold tests sit at N-1, N and N+1 deliberately. Off-by-one in a
comparison operator is invisible in every other kind of test: the code runs, a
number comes out, and the number is one escalation wrong per corner per day.
"""

from __future__ import annotations

import asyncio

import pytest

from watchdog.brains import RuleTriage
from watchdog.datasf import query_fingerprint
from watchdog.delta import diff_snapshots, rule_verdict
from watchdog.schema import Calibration, Counts, Delta, MalformedSnapshot, Snapshot

FP = query_fingerprint(80)


def snap(*, collisions=40, fatal=1, severe=3, reports=120, district=5,
         complete=True, fingerprint=FP) -> Snapshot:
    return Snapshot(
        slug="taylor-and-turk",
        name="Taylor and Turk",
        counts=Counts(collisions_5y=collisions, fatal_5y=fatal, severe_5y=severe,
                      reports_311_3y=reports, district=district),
        fetched_at="2026-08-19T20:00:00+00:00",
        complete=complete,
        query_fingerprint=fingerprint,
    )


def corner():
    return {"slug": "taylor-and-turk", "name": "Taylor and Turk", "grade": "F", "index": 96}


def escalates(delta: Delta, cal: Calibration | None = None) -> bool:
    """The full tier-one answer: the rule floor, then triage for the rest."""
    cal = cal or Calibration()
    ruled = rule_verdict(delta, cal)
    if ruled is not None:
        return ruled[0]
    return asyncio.run(RuleTriage("t").judge(delta, corner(), cal)).significant


# ============================================================ class: fatalities

def test_a_new_fatality_fires():
    assert escalates(diff_snapshots(snap(fatal=1), snap(fatal=2, collisions=41))) is True


def test_an_unchanged_fatality_count_stays_silent():
    assert escalates(diff_snapshots(snap(fatal=2), snap(fatal=2))) is False


def test_a_fatality_count_that_fell_does_not_fire():
    """Reclassification happens. A death un-dying is not an escalation."""
    d = diff_snapshots(snap(fatal=3), snap(fatal=2))
    assert d.new_fatal == 0
    assert "fatal count fell from 3 to 2" in d.note


def test_the_fatality_rule_fires_before_any_tier_is_consulted():
    d = diff_snapshots(snap(fatal=1), snap(fatal=2, collisions=41))
    ruled = rule_verdict(d, Calibration())
    assert ruled is not None and ruled[0] is True
    assert "before any model is consulted" in ruled[1]


def test_the_fatality_rule_cannot_be_disabled_by_calibration():
    cal = Calibration()
    cal.adjust("min_new_collisions", 3, "trying to raise the bar past a death")
    cal.adjust("reports_311_jump", 40, "and the other one too")
    assert escalates(diff_snapshots(snap(fatal=1), snap(fatal=2)), cal) is True


# ================================================================ class: severe

def test_a_new_severe_injury_fires():
    assert escalates(diff_snapshots(snap(severe=3), snap(severe=4, collisions=41))) is True


def test_an_unchanged_severe_count_stays_silent():
    assert escalates(diff_snapshots(snap(severe=3), snap(severe=3))) is False


def test_a_severe_count_that_fell_does_not_fire():
    d = diff_snapshots(snap(severe=4), snap(severe=3))
    assert d.new_severe == 0


# ============================================================ class: collisions

@pytest.mark.parametrize("new_count,should_fire", [(0, False), (1, True), (2, True)])
def test_the_collision_threshold_at_its_boundary(new_count, should_fire):
    """Default min_new_collisions is 1, so 0 is silent and 1 fires."""
    d = diff_snapshots(snap(collisions=40), snap(collisions=40 + new_count))
    assert d.new_collisions == new_count
    assert escalates(d) is should_fire


@pytest.mark.parametrize("new_count,should_fire", [(2, False), (3, True), (4, True)])
def test_a_raised_collision_threshold_moves_the_boundary_with_it(new_count, should_fire):
    cal = Calibration()
    cal.adjust("min_new_collisions", 3, "a fortnight of noise")
    d = diff_snapshots(snap(collisions=40), snap(collisions=40 + new_count))
    assert escalates(d, cal) is should_fire


def test_a_withdrawn_collision_never_becomes_a_negative_escalation():
    d = diff_snapshots(snap(collisions=71), snap(collisions=69))
    assert d.new_collisions == 0
    assert escalates(d) is False
    assert "fell from 71 to 69" in d.note


# =================================================================== class: 311

@pytest.mark.parametrize("swing,should_fire", [(14, False), (15, True), (16, True)])
def test_the_311_threshold_at_its_boundary(swing, should_fire):
    d = diff_snapshots(snap(reports=120), snap(reports=120 + swing))
    assert d.reports_311_change == swing
    assert escalates(d) is should_fire


@pytest.mark.parametrize("swing,should_fire", [(-14, False), (-15, True), (-16, True)])
def test_a_falling_311_count_uses_the_same_threshold_as_a_rising_one(swing, should_fire):
    """A cluster of reports disappearing is as interesting as one appearing."""
    d = diff_snapshots(snap(reports=120), snap(reports=120 + swing))
    assert d.reports_311_change == swing
    assert escalates(d) is should_fire


def test_a_raised_311_threshold_silences_a_swing_that_used_to_fire():
    cal = Calibration()
    cal.adjust("reports_311_jump", 40, "a noisy month at a busy corner")
    assert escalates(diff_snapshots(snap(reports=120), snap(reports=142)), cal) is False


def test_a_311_swing_below_the_bar_is_still_recorded_as_a_change():
    """Silent is not the same as invisible. It is journaled, it just does not escalate."""
    d = diff_snapshots(snap(reports=120), snap(reports=124))
    assert d.empty is False
    assert "rose by 4" in d.summary()


# ============================================================== class: district

def test_a_district_change_fires():
    assert escalates(diff_snapshots(snap(district=6), snap(district=5))) is True


def test_an_unchanged_district_stays_silent():
    assert escalates(diff_snapshots(snap(district=6), snap(district=6))) is False


@pytest.mark.parametrize("old_d,new_d", [(None, 6), (6, None), (None, None)])
def test_an_unknown_district_on_either_side_is_not_a_change(old_d, new_d):
    """Not knowing is not the same as knowing it moved."""
    d = diff_snapshots(snap(district=old_d), snap(district=new_d))
    assert d.district_changed is False


# ============================================================ class: no change

def test_an_identical_pair_declines_by_rule():
    d = diff_snapshots(snap(), snap())
    assert d.empty is True
    assert d.summary() == "No change at Taylor and Turk."
    ruled = rule_verdict(d, Calibration())
    assert ruled is not None and ruled[0] is False


# =========================================================== class: unreliable

@pytest.mark.parametrize("old_ok,new_ok", [(True, False), (False, True), (False, False)])
def test_an_incomplete_snapshot_on_either_side_refuses_to_compare(old_ok, new_ok):
    d = diff_snapshots(snap(collisions=71, complete=old_ok),
                       snap(collisions=0, complete=new_ok))
    assert d.unreliable is True
    assert d.new_collisions == 0
    assert escalates(d) is False


def test_an_incomplete_snapshot_hides_even_a_fatality():
    """A failed fetch must not be able to manufacture a death, or erase one."""
    d = diff_snapshots(snap(fatal=1), snap(fatal=9, complete=False))
    assert d.new_fatal == 0
    assert escalates(d) is False


# ========================================================== class: first sight

def test_a_first_sighting_declines_whatever_the_numbers_are():
    d = diff_snapshots(None, snap(collisions=999, fatal=9, severe=9, reports=9999))
    assert d.empty is True
    assert d.new_collisions == 0
    assert escalates(d) is False
    assert "first snapshot" in d.note


# ========================================================== class: methodology

def test_a_changed_query_declines_whatever_the_numbers_are():
    d = diff_snapshots(snap(collisions=40, fingerprint=query_fingerprint(150)),
                       snap(collisions=999, fatal=9, fingerprint=query_fingerprint(80)))
    assert d.unreliable is True
    assert escalates(d) is False


# ============================================================ summary wording

@pytest.mark.parametrize("n,expected", [(1, "1 new fatal collision"), (2, "2 new fatal collisions")])
def test_fatality_wording_is_singular_at_one(n, expected):
    d = diff_snapshots(snap(fatal=0, collisions=40), snap(fatal=n, collisions=40 + n))
    assert expected in d.summary()


@pytest.mark.parametrize("n,expected", [(1, "1 new injury collision"), (3, "3 new injury collisions")])
def test_plain_collision_wording_is_singular_at_one(n, expected):
    d = diff_snapshots(snap(collisions=40), snap(collisions=40 + n))
    assert expected in d.summary()


def test_the_summary_separates_fatal_severe_and_plain_collisions():
    old = snap(collisions=40, fatal=1, severe=3)
    new = snap(collisions=45, fatal=2, severe=4)
    text = diff_snapshots(old, new).summary()
    assert "1 new fatal collision" in text
    assert "1 new severe injury collision" in text
    assert "3 new injury collisions" in text  # 5 total, less 1 fatal, less 1 severe


def test_the_summary_never_reports_a_negative_plain_count():
    """More fatal than total is impossible in real data and must not print as -1."""
    old = snap(collisions=40, fatal=0, severe=0)
    new = snap(collisions=40, fatal=1, severe=1)
    text = diff_snapshots(old, new).summary()
    assert "-" not in text


# ================================================== malformed stored snapshots

def test_a_snapshot_missing_every_field_loads_as_an_empty_one():
    s = Snapshot.from_dict({})
    assert s.slug == ""
    assert s.counts.collisions_5y == 0
    assert s.complete is True
    assert s.query_fingerprint == ""


@pytest.mark.parametrize("absent", [None, ""])
def test_an_absent_count_in_a_stored_snapshot_is_a_real_zero(absent):
    s = Snapshot.from_dict({"slug": "a", "counts": {"collisions_5y": absent}})
    assert s.counts.collisions_5y == 0


@pytest.mark.parametrize("junk", ["seventy", [], {}, float("nan"), float("inf"), "1,000"])
def test_a_junk_count_refuses_to_load_rather_than_becoming_zero(junk):
    """Silently becoming zero is the SEVERE_VALUES failure with a different mask."""
    with pytest.raises(MalformedSnapshot):
        Snapshot.from_dict({"slug": "a", "counts": {"collisions_5y": junk}})


def test_a_stored_snapshot_with_a_null_counts_block_does_not_crash():
    s = Snapshot.from_dict({"slug": "a", "counts": None})
    assert s.counts.collisions_5y == 0


def test_a_counts_block_that_is_not_an_object_is_refused():
    with pytest.raises(MalformedSnapshot):
        Snapshot.from_dict({"slug": "a", "counts": ["collisions"]})


def test_a_document_that_is_not_an_object_is_refused():
    with pytest.raises(MalformedSnapshot):
        Snapshot.from_dict(["not", "a", "snapshot"])


def test_a_junk_district_is_refused_rather_than_carried():
    with pytest.raises(MalformedSnapshot):
        Snapshot.from_dict({"slug": "a", "counts": {"district": "district six"}})


def test_a_stored_snapshot_with_a_string_complete_flag_is_read_as_truthy():
    assert Snapshot.from_dict({"complete": "false"}).complete is True  # any non-empty string
    assert Snapshot.from_dict({"complete": ""}).complete is False


def test_a_cosmetic_field_being_absent_is_tolerated():
    """Strict about numbers, forgiving about everything else."""
    s = Snapshot.from_dict({"counts": {"collisions_5y": 40}})
    assert s.slug == "" and s.name == ""
    assert s.counts.collisions_5y == 40
