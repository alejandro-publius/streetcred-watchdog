"""The guard that stops a change to this repo arriving as news about a street.

Every count in a snapshot is the answer to a question: this radius, these
windows, this severity vocabulary. Change the question and every count at every
corner moves at once. Subtracting across that change produces a delta that is
arithmetically correct, confidently reasoned, and about nothing that happened in
San Francisco.

This is not hypothetical. The radius moved from 150 metres to 80 on 2026-08-19,
after measurement showed 80 is what reproduces StreetCred's published figures.
Without this guard that edit would have arrived in the journal the next morning
as a collapse in collisions at all twenty five corners at once.
"""

from __future__ import annotations

from watchdog.datasf import COLLISION_YEARS, DEFAULT_RADIUS_M, REPORTS_YEARS, query_fingerprint
from watchdog.delta import diff_snapshots, rule_verdict
from watchdog.schema import Calibration, Counts, Snapshot


def snap(*, collisions=40, fatal=1, severe=3, reports=120, fingerprint="r=80m") -> Snapshot:
    return Snapshot(
        slug="taylor-and-turk",
        name="Taylor and Turk",
        counts=Counts(collisions_5y=collisions, fatal_5y=fatal, severe_5y=severe,
                      reports_311_3y=reports, district=5),
        fetched_at="2026-08-19T20:00:00+00:00",
        complete=True,
        query_fingerprint=fingerprint,
    )


# ------------------------------------------------------------- the fingerprint

def test_the_fingerprint_carries_every_input_that_moves_a_count():
    fp = query_fingerprint(80)
    assert "r=80m" in fp
    assert f"collisions={COLLISION_YEARS}y" in fp
    assert f"reports={REPORTS_YEARS}y" in fp
    assert "Injury (Severe)" in fp


def test_a_different_radius_is_a_different_fingerprint():
    assert query_fingerprint(80) != query_fingerprint(150)


def test_the_fingerprint_is_readable_not_a_hash():
    """The journal entry that refuses a comparison prints this."""
    fp = query_fingerprint(80)
    assert "80" in fp and ";" in fp
    assert len(fp) > 30


def test_the_default_radius_is_the_one_that_reproduces_streetcred():
    """Measured on six corners on 2026-08-19. See the comment in datasf.py."""
    assert DEFAULT_RADIUS_M == 80


# ------------------------------------------------------------------- the guard

def test_a_changed_query_refuses_to_diff():
    old = snap(collisions=94, severe=11, fingerprint=query_fingerprint(150))
    new = snap(collisions=62, severe=9, fingerprint=query_fingerprint(80))
    d = diff_snapshots(old, new)
    assert d.unreliable is True
    assert d.empty is True
    assert d.new_collisions == 0
    assert "the query changed" in d.note
    assert "r=150m" in d.note and "r=80m" in d.note


def test_a_changed_query_never_escalates():
    old = snap(fatal=3, fingerprint=query_fingerprint(150))
    new = snap(fatal=1, fingerprint=query_fingerprint(80))
    verdict = rule_verdict(diff_snapshots(old, new), Calibration())
    assert verdict is not None and verdict[0] is False


def test_a_snapshot_with_no_fingerprint_never_matches_one_that_has_it():
    """Written before the field existed, so what it measured is genuinely unknown."""
    d = diff_snapshots(snap(fingerprint=""), snap(fingerprint=query_fingerprint(80)))
    assert d.unreliable is True
    assert "not recorded" in d.note


def test_matching_fingerprints_compare_normally():
    fp = query_fingerprint(80)
    d = diff_snapshots(snap(collisions=40, fingerprint=fp), snap(collisions=42, fingerprint=fp))
    assert d.unreliable is False
    assert d.new_collisions == 2


def test_the_guard_sits_before_the_arithmetic_not_after():
    """A query change must not be able to produce a number at all."""
    old = snap(collisions=1000, fatal=50, reports=9999, fingerprint=query_fingerprint(150))
    new = snap(collisions=1, fatal=0, reports=1, fingerprint=query_fingerprint(80))
    d = diff_snapshots(old, new)
    assert (d.new_collisions, d.new_fatal, d.reports_311_change) == (0, 0, 0)


def test_the_refusal_reads_as_a_sentence():
    old = snap(fingerprint=query_fingerprint(150))
    new = snap(fingerprint=query_fingerprint(80))
    summary = diff_snapshots(old, new).summary()
    assert summary.startswith("Comparison unreliable at Taylor and Turk")
    assert "the query changed" in summary


def test_snapshot_fingerprint_survives_a_round_trip():
    fp = query_fingerprint(80)
    d = snap(fingerprint=fp).to_dict()
    assert d["query_fingerprint"] == fp
    assert Snapshot.from_dict(d).query_fingerprint == fp
