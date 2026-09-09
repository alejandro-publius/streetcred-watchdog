"""The outcome loop, and the two things it must never do.

`Calibration.adjust` enforced its bounds and journaled every change for a week
and nothing ever called it. Disclosed-but-dead code is worse than absent code:
the disclosure reads as a feature, and the reviewer who checks finds a mechanism
that has never run. This is the caller.

Two properties matter more than the arithmetic.

**It only ever raises.** Tier one's mistakes come in two kinds and one is
invisible. An escalation tier two then declined is a false positive and both
tiers left a record on the same entry. A delta tier one declined that actually
mattered is a false negative and there is no record of it anywhere, because tier
two never saw it. Evidence can therefore only ever argue for a higher bar, and a
version of this that lowered one would be inferring a number from data that by
construction cannot contain it.

**It writes nothing to the journal.** A review entry carries no actions and no
error, which is exactly the shape `ledger.summarise` counts as restraint. One per
cycle would raise the single number this project asks to be judged on, once per
cycle, forever. Same trap publisher.py records for its receipts, and the same
answer: it rides in the cycle report instead.
"""

from __future__ import annotations

import asyncio

from corner_watchdog.calibrate import MIN_EVIDENCE, outcomes_from, review
from corner_watchdog.schema import Calibration


def entry(significant=True, actions=None, tier2=True, error=None, slug="a"):
    e = {
        "slug": slug,
        "tier1": {"significant": significant, "reason": "x"},
        "actions": actions or [],
    }
    if tier2:
        e["tier2"] = {"reasoning": "y"}
    if error:
        e["error"] = error
    return e


def journal(escalations, declined, **kw):
    rows = [entry(actions=["rescore"], slug=f"c{i}", **kw) for i in range(escalations - declined)]
    rows += [entry(actions=[], slug=f"d{i}", **kw) for i in range(declined)]
    return rows


# ============================================================== the evidence floor

def test_it_refuses_on_thin_evidence_and_says_the_bar():
    r = review(journal(5, 4), Calibration())
    assert r.adjusted is False
    assert f"needs {MIN_EVIDENCE}" in r.reason
    assert "decision about the evidence, not a step that was skipped" in r.reason


def test_the_real_journal_today_is_below_the_floor():
    # Written as a test rather than a comment so it fails when it stops being
    # true, which is the moment this loop starts doing something.
    r = review(journal(5, 1), Calibration())
    assert r.escalations == 5
    assert r.adjusted is False


def test_with_enough_evidence_and_a_bad_rate_it_raises_the_bar():
    cal = Calibration()
    before = cal.reports_311_jump
    r = review(journal(MIN_EVIDENCE, MIN_EVIDENCE - 2), cal)
    assert r.adjusted is True
    assert cal.reports_311_jump > before
    assert r.before == before and r.after == cal.reports_311_jump


def test_a_healthy_rate_changes_nothing():
    cal = Calibration()
    before = cal.reports_311_jump
    r = review(journal(MIN_EVIDENCE, 2), cal)
    assert r.adjusted is False
    assert cal.reports_311_jump == before
    assert "doing its job" in r.reason


# ================================================================ the asymmetry

def test_it_never_lowers_a_threshold_however_good_the_rate():
    # The property the whole module turns on. A perfect rate is not evidence
    # that the bar could be lower: the deltas that would prove it were declined
    # at tier one and nothing ever looked at them again.
    cal = Calibration()
    before = cal.reports_311_jump
    for declined in (0, 1, 2):
        review(journal(MIN_EVIDENCE * 2, declined), cal)
    assert cal.reports_311_jump == before


def test_the_ceiling_still_refuses_and_the_reason_says_so():
    cal = Calibration()
    cal.reports_311_jump = 40  # the top of its bounds
    r = review(journal(MIN_EVIDENCE, MIN_EVIDENCE - 1), cal)
    assert r.adjusted is False
    assert "ceiling refused" in r.reason


# ================================================================== the evidence

def test_a_broken_deliberation_is_not_evidence_that_tier_one_was_wrong():
    rows = journal(MIN_EVIDENCE, MIN_EVIDENCE - 1, error="publish permanently_failed")
    out = outcomes_from(rows)
    assert out.escalations == 0, "the agent must not tune itself away from its own bugs"


def test_an_escalation_the_budget_stopped_carries_no_verdict():
    rows = [entry(actions=[], tier2=False) for _ in range(MIN_EVIDENCE)]
    assert outcomes_from(rows).escalations == 0


def test_tier_two_agreeing_and_being_budget_blocked_is_not_a_decline():
    """Tier two chose to act and the daily action budget refused every action.

    That is agreement stopped by money, not tier two declining the escalation.
    Counting it as a decline would let a starved action budget, rather than
    tier two's own judgment, argue for raising the threshold -- and with enough
    of these entries `review` would raise the bar on evidence that never spoke
    to whether tier one's escalations were any good.
    """
    rows = []
    for i in range(MIN_EVIDENCE):
        e = entry(actions=[], slug=f"blocked{i}")
        e["intents"] = ["daily action budget spent; wanted to rescore"]
        rows.append(e)

    out = outcomes_from(rows)
    assert out.escalations == MIN_EVIDENCE
    assert out.declined_at_tier_two == 0

    r = review(rows, Calibration())
    assert r.adjusted is False, (
        "a 100 percent 'decline' rate made entirely of budget-blocked acts must "
        "not raise the threshold; nothing here says tier one escalated too much"
    )


def test_a_decline_at_tier_one_is_not_an_outcome():
    rows = [entry(significant=False) for _ in range(MIN_EVIDENCE)]
    assert outcomes_from(rows).escalations == 0


# ============================================================== the restraint rate

def test_a_cycle_writes_no_journal_entry_for_the_review(tmp_path):
    """The one that would have shipped. Caught by the rehearsal containment tests."""
    from corner_watchdog.runner import run_cycle
    from corner_watchdog.store import LocalJsonStore

    store = LocalJsonStore(tmp_path / "state")
    before = len(store.read_journal())
    report = asyncio.run(
        run_cycle([], state_dir=tmp_path / "state", outbox_dir=tmp_path / "outbox")
    )
    assert report.calibration, "the review still has to be reported"
    assert report.calibration["adjusted"] is False
    assert len(store.read_journal()) == before, (
        "a review entry has no actions and no error, which the ledger counts as "
        "restraint, so one per cycle would raise the headline number forever"
    )
