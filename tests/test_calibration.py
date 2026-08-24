"""Calibration is threshold nudging from logged outcomes. It is not retraining,
the README says so in those words, and these tests pin the bounds that keep one
unusual week from swinging the agent into ignoring everything.
"""

from corner_watchdog.schema import Calibration, JournalEntry, Tier1Verdict, Tier2Decision


def test_adjustment_is_recorded_with_before_and_after():
    c = Calibration()
    assert c.adjust("reports_311_jump", 20, "3 of 4 escalations last week were noise") is True
    assert c.reports_311_jump == 20
    assert c.history[-1]["from"] == 15
    assert c.history[-1]["to"] == 20
    assert "noise" in c.history[-1]["evidence"]


def test_adjustment_is_clamped_to_bounds():
    c = Calibration()
    c.adjust("reports_311_jump", 9999, "a very strange week")
    assert c.reports_311_jump == 40  # the ceiling, not 9999
    assert c.history[-1]["requested"] == 9999


def test_adjustment_cannot_disable_the_collision_floor():
    c = Calibration()
    c.adjust("min_new_collisions", 0, "trying to ignore collisions")
    assert c.min_new_collisions == 1  # the floor holds


def test_a_no_op_adjustment_is_not_journaled():
    c = Calibration()
    assert c.adjust("reports_311_jump", 15, "same value") is False
    assert c.history == []


def test_unknown_key_is_refused():
    c = Calibration()
    assert c.adjust("not_a_threshold", 5, "nope") is False


def test_history_is_bounded():
    c = Calibration()
    for i in range(200):
        c.adjust("reports_311_jump", 5 + (i % 30), f"round {i}")
    assert len(c.history) <= 60


# ---------------------------------------------------------------- journal

def test_a_decline_serialises_with_its_reasoning_intact():
    e = JournalEntry(
        ts="2026-08-18T13:40:00Z",
        slug="turk-taylor",
        name="Turk and Taylor",
        delta="311 reports rose by 4.",
        trigger="cron",
        tier1=Tier1Verdict(significant=False, reason="Inside normal weekly variance.", confidence=0.83),
    )
    p = e.to_ingest_payload()
    assert p["kind"] == "journal_entry"
    assert p["tier1"]["significant"] is False
    assert p["tier1"]["confidence"] == 0.83
    assert "tier2" not in p  # cleaned, not sent as null
    assert p["actions"] == []


def test_a_rule_fired_entry_says_so():
    e = JournalEntry(
        ts="2026-08-18T13:40:00Z",
        slug="turk-taylor",
        name="Turk and Taylor",
        delta="1 new fatal collision.",
        trigger="cron",
        tier1=Tier1Verdict(significant=True, reason="Any new fatality is significant by rule.", by_rule=True),
        tier2=Tier2Decision(reasoning="The letter cites a count that is now wrong.", actions=["rescore"]),
        actions=["rescore"],
        intents=["re-audited the imagery, budget reached"],
    )
    p = e.to_ingest_payload()
    assert p["tier1"]["byRule"] is True
    assert p["tier2"]["actions"] == ["rescore"]
    assert p["intents"] == ["re-audited the imagery, budget reached"]
