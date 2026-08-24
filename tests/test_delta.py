"""The cases where a naive diff produces a confident lie.

Every test here exists because the obvious implementation gets it wrong in a way
that is invisible: it does not crash, it reports a number, and the number is
false. That is the failure mode this whole repo is built to avoid, so these are
the tests that matter most.
"""

from corner_watchdog.delta import diff_snapshots, rule_verdict
from corner_watchdog.schema import Calibration, Counts, Snapshot


def snap(slug="turk-taylor", name="Turk and Taylor", *, collisions=0, fatal=0, severe=0,
         reports=0, district=6, complete=True) -> Snapshot:
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
        fetched_at="2026-08-18T13:40:00Z",
        complete=complete,
    )


def test_first_sighting_is_not_a_hundred_new_collisions():
    """The bug that would spend the entire day-one budget on a baseline."""
    d = diff_snapshots(None, snap(collisions=71, fatal=2, reports=300))
    assert d.empty is True
    assert d.new_collisions == 0
    assert "first snapshot" in d.note


def test_incomplete_fetch_is_not_a_drop_to_zero():
    """A DataSF timeout returning no rows looks exactly like a safe corner."""
    old = snap(collisions=71, fatal=2, reports=300)
    new = snap(collisions=0, fatal=0, reports=0, complete=False)
    d = diff_snapshots(old, new)
    assert d.unreliable is True
    assert d.empty is True
    assert d.new_collisions == 0


def test_incomplete_on_the_old_side_also_refuses():
    old = snap(collisions=0, complete=False)
    new = snap(collisions=71)
    assert diff_snapshots(old, new).unreliable is True


def test_a_real_new_collision_is_counted():
    old = snap(collisions=71, fatal=2, severe=3, reports=300)
    new = snap(collisions=72, fatal=2, severe=3, reports=300)
    d = diff_snapshots(old, new)
    assert d.new_collisions == 1
    assert d.new_fatal == 0
    assert d.empty is False


def test_withdrawn_record_does_not_produce_negative_new_collisions():
    """The city does reclassify. Negative "new collisions" is not a thing."""
    old = snap(collisions=71)
    new = snap(collisions=69)
    d = diff_snapshots(old, new)
    assert d.new_collisions == 0
    assert "fell from 71 to 69" in d.note
    # It still counts as something changed, so it is journaled rather than hidden.
    assert d.empty is True or d.note != ""


def test_311_movement_is_signed():
    old = snap(reports=353)
    new = snap(reports=341)
    d = diff_snapshots(old, new)
    assert d.reports_311_change == -12
    assert d.empty is False
    assert "fell by 12" in d.summary()


def test_no_change_is_still_a_delta_object():
    old = snap(collisions=71, reports=300)
    new = snap(collisions=71, reports=300)
    d = diff_snapshots(old, new)
    assert d.empty is True
    assert d.summary() == "No change at Turk and Taylor."


def test_district_change_is_noticed():
    d = diff_snapshots(snap(district=6), snap(district=5))
    assert d.district_changed is True
    assert d.empty is False


# ------------------------------------------------------------------- rules

def test_a_death_escalates_before_any_model_is_consulted():
    old = snap(collisions=71, fatal=2)
    new = snap(collisions=72, fatal=3)
    d = diff_snapshots(old, new)
    verdict = rule_verdict(d, Calibration())
    assert verdict is not None
    significant, reason = verdict
    assert significant is True
    assert "before any model is consulted" in reason


def test_severe_injury_escalates_by_rule():
    d = diff_snapshots(snap(collisions=71, severe=1), snap(collisions=72, severe=2))
    verdict = rule_verdict(d, Calibration())
    assert verdict is not None and verdict[0] is True


def test_the_ambiguous_middle_is_left_to_the_model():
    """A 311 swing with no injuries is exactly what the reflex tier is for."""
    d = diff_snapshots(snap(reports=353), snap(reports=366))
    assert rule_verdict(d, Calibration()) is None


def test_unreliable_never_escalates():
    d = diff_snapshots(snap(collisions=71), snap(collisions=0, complete=False))
    verdict = rule_verdict(d, Calibration())
    assert verdict is not None and verdict[0] is False


def test_nothing_changed_declines_by_rule():
    d = diff_snapshots(snap(reports=300), snap(reports=300))
    verdict = rule_verdict(d, Calibration())
    assert verdict is not None and verdict[0] is False
