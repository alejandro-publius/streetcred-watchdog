"""Tier one is Gemma, and every entry says which tier actually decided it.

The property under test is not "Gemma works". It is that a reader of the journal
can tell a Gemma verdict from a rule verdict, on the entry, without knowing how
the run was configured.

That distinction is load bearing because Gemma's failures are per call rather
than per run. The managed pool answers about two calls in three and refuses the
rest with a queue-full 429, so a single sweep can produce entries from both. A
run-level degradation note is identical on all of them and therefore says nothing
true about any of them.

The failure this prevents: a corner nobody looked at, journaled as a corner
judged unimportant. Those are the same shape in a journal unless something on the
entry says otherwise.
"""

from __future__ import annotations

import asyncio
import json

from corner_watchdog.brains import GemmaTriage, RuleTriage
from corner_watchdog.schema import Calibration, Delta, Tier1Verdict


class Reply:
    def __init__(self, text) -> None:
        self.text = text


class FakeClient:
    """Answers with a scripted sequence, then repeats the last answer."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.calls: list[str] = []

    @property
    def models(self):
        return self

    def generate_content(self, *, model, contents):
        self.calls.append(contents)
        answer = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return Reply(answer)


def gemma(*answers, **kw):
    kw.setdefault("sleep", lambda _s: asyncio.sleep(0))
    return GemmaTriage(client=FakeClient(*answers), project="p", location="global", **kw)


def verdict(v="ignore", reason="Ordinary weekly variance at a busy crossing.", conf=0.8):
    return json.dumps({"verdict": v, "reason": reason, "confidence": conf})


def delta(**over) -> Delta:
    # empty defaults to True, which renders as "No change at ..." and would hand
    # every test a prompt about nothing. The fake client ignores the prompt, but a
    # fixture that quietly describes the wrong situation is how a test starts
    # passing for a reason nobody intended.
    base = {
        "slug": "6th-and-mission", "name": "6th and Mission",
        "reports_311_change": 3, "empty": False,
    }
    base.update(over)
    return Delta(**base)


def judge(tier, d=None) -> Tier1Verdict:
    return asyncio.run(tier.judge(d or delta(), {"grade": "F", "index": 91}, Calibration()))


# ============================================================ the label is the point

def test_a_gemma_decided_entry_is_labelled_as_gemma():
    v = judge(gemma(verdict()))
    assert "Gemma" in v.decided_by
    assert "gemma-4-26b-a4b-it-maas" in v.decided_by
    assert "Vertex" in v.decided_by


def test_a_rule_decided_entry_is_labelled_as_the_rule():
    v = judge(RuleTriage("no project on this machine"))
    assert "RuleTriage" in v.decided_by
    assert "Gemma" not in v.decided_by


def test_a_fallback_is_labelled_as_the_rule_not_as_gemma():
    # The one that matters. Gemma was wired, Gemma was called, Gemma did not
    # answer, and a rule produced the verdict. Naming Gemma here would put a
    # model's name on an entry no model saw.
    v = judge(gemma(RuntimeError("429 RESOURCE_EXHAUSTED: The request queue is full")))
    assert "RuleTriage" in v.decided_by
    assert v.decided_by.startswith("RuleTriage")
    assert "Gemma did not answer" in v.decided_by
    assert "429" in v.decided_by, "the reason travels with the entry, not just the log"


def test_the_two_labels_are_distinguishable_without_knowing_the_wiring():
    live = judge(gemma(verdict()))
    fell = judge(gemma(RuntimeError("503 UNAVAILABLE")))
    assert live.decided_by != fell.decided_by


# =================================================================== the retry

def test_a_queue_full_429_is_retried_and_can_succeed():
    tier = gemma(RuntimeError("429 RESOURCE_EXHAUSTED: The request queue is full"), verdict())
    v = judge(tier)
    assert "Gemma" in v.decided_by
    assert len(tier._client.calls) == 2


def test_a_non_retryable_error_is_not_retried():
    tier = gemma(RuntimeError("403 PERMISSION_DENIED"))
    judge(tier)
    assert len(tier._client.calls) == 1, "a permissions failure does not clear on a retry"


def test_it_stops_rather_than_retrying_forever():
    tier = gemma(RuntimeError("429 RESOURCE_EXHAUSTED"))
    v = judge(tier)
    assert len(tier._client.calls) == 3
    assert "after 3 attempt(s)" in v.decided_by


# =================================================================== the parse

def test_an_escalation_is_read_as_significant():
    v = judge(gemma(verdict("escalate", "Four new injury collisions since the last look.")))
    assert v.significant is True
    assert v.basis == "triage"
    assert v.by_rule is False


def test_an_ignore_is_read_as_not_significant():
    v = judge(gemma(verdict("ignore")))
    assert v.significant is False
    assert v.basis == "triage"


def test_a_defer_is_not_flattened_into_an_ignore():
    # A defer says the evidence cannot be judged and an ignore says the change
    # does not matter. Those are opposite claims and the vocabulary already
    # carries the difference, so losing it here would be a silent downgrade.
    v = judge(gemma(verdict("defer", "The comparison rests on a partial fetch.")))
    assert v.significant is False
    assert v.basis == "triage_defer"


def test_a_fenced_json_block_still_parses():
    tier = gemma("```json\n" + verdict("escalate", "A real change.") + "\n```")
    assert judge(tier).significant is True


def test_prose_instead_of_json_falls_back_rather_than_guessing():
    tier = gemma("I think this one is probably fine, honestly.")
    v = judge(tier)
    assert "RuleTriage" in v.decided_by
    assert "did not parse" in v.decided_by


def test_a_verdict_outside_the_schema_is_refused():
    tier = gemma(json.dumps({"verdict": "maybe", "reason": "unsure", "confidence": 0.5}))
    assert "RuleTriage" in judge(tier).decided_by


def test_an_empty_reason_is_refused_because_the_reason_is_published():
    tier = gemma(json.dumps({"verdict": "ignore", "reason": "", "confidence": 0.9}))
    assert "RuleTriage" in judge(tier).decided_by


# ============================================================== what it admits

def test_a_gemma_tier_makes_no_run_level_degradation_claim():
    # Tier one is a model in this wiring, so there is nothing to admit at the run
    # level. The per-call admission lives on the entry that needs it.
    assert gemma(verdict()).degraded is None


def test_the_verdict_serialises_the_label_for_the_journal():
    v = judge(gemma(verdict()))
    assert "Gemma" in v.to_dict()["decidedBy"]


# ============================================================== across the bus

def test_the_label_survives_the_envelope_round_trip():
    """The escalated entries are journaled by the actor, not the observer.

    Found by running the rehearsal and reading the journal: four of six entries
    had no label at all, and they were the four that escalated. The observer
    stamps the verdict and then serialises it onto the bus; the actor rebuilds a
    Tier1Verdict from the wire and was rebuilding it field by field, so any field
    added later is silently dropped. The entries that cross this boundary are
    exactly the ones a model decided, which made this the one place the label
    mattered most and the one place it was missing.
    """
    from corner_watchdog.actor import Actor
    from corner_watchdog.schema import Tier1Verdict

    stamped = Tier1Verdict(
        significant=True,
        reason="Two new injury collisions since the last look.",
        basis="triage",
        decided_by="Gemma, google/gemma-4-26b-a4b-it-maas, Vertex global (triage-v2)",
    )
    wire = stamped.to_dict()
    assert wire["decidedBy"] == stamped.decided_by, "the observer must put it on the wire"

    rebuilt = Tier1Verdict(
        significant=bool(wire.get("significant")),
        reason=wire.get("reason", ""),
        confidence=wire.get("confidence"),
        by_rule=bool(wire.get("byRule")),
        basis=wire.get("basis"),
        decided_by=wire.get("decidedBy"),
    )
    assert rebuilt.decided_by == stamped.decided_by

    # And the actor's own reconstruction, so this does not pass while the code
    # under test still drops the field.
    import inspect

    source = inspect.getsource(Actor.handle)
    assert 'decided_by=t1.get("decidedBy")' in source, (
        "the actor rebuilds Tier1Verdict field by field, so a new field has to be "
        "added there too or it is dropped for every escalated entry"
    )
