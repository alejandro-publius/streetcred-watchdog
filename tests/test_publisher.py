"""Every journaled decision reaches the diary, or says why it did not.

The property being defended is not "publishing works". It is that the two sides
can be reconciled: for every decision in the journal there is either an entry in
the diary or a record saying why there is not. A publish that fails silently
leaves a hole between them and nothing pointing at it, and a reader comparing
the two would conclude the agent decided less than it did.

The other half is the poison rule. StreetCred validates on content, so a 400
means the payload is wrong and will be wrong on the tenth attempt too. Retrying
it burns the backoff window, delays every decision behind it, and on the Pub/Sub
path is how one bad record holds a subscription open until its retention
expires. A 400 is dead on arrival. Only a transport fault or a 5xx is retried,
and even that stops.
"""

from __future__ import annotations

import asyncio

import pytest

from corner_watchdog.publisher import (
    DEAD,
    DUPLICATE,
    PUBLISHED,
    DecisionPublisher,
    decision_id_for,
)
from corner_watchdog.publishing_store import PublishingStore
from corner_watchdog.schema import Counts, JournalEntry, Snapshot, Tier1Verdict, Tier2Decision
from corner_watchdog.store import LocalJsonStore


class Reply:
    def __init__(self, status, body=None) -> None:
        self.status = status
        self.body = body or {}
        self.ok = status == 200


class FakeClient:
    """Answers with a scripted sequence, then repeats the last answer."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies) or [Reply(200)]
        self.posts: list[dict] = []

    async def post_journal(self, payload):
        self.posts.append(payload)
        i = min(len(self.posts) - 1, len(self.replies) - 1)
        return self.replies[i]


def entry(**over) -> JournalEntry:
    base = {
        "ts": "2026-08-26T09:00:00+00:00",
        "slug": "6th-and-mission",
        "name": "6th and Mission",
        "delta": "311 reports rose by 4.",
        "trigger": "cron",
        "tier1": Tier1Verdict(significant=True, reason="A swing worth a closer look.", basis="triage"),
        "tier2": Tier2Decision(reasoning="Nothing published is wrong, so this is a decline.", actions=[]),
        "run_id": "run-1",
    }
    base.update(over)
    return JournalEntry(**base)


def publisher(client, **kw):
    kw.setdefault("sleep", lambda _s: asyncio.sleep(0))
    return DecisionPublisher(client, **kw)


# ================================================================ the happy path

def test_a_decision_is_published_once():
    c = FakeClient(Reply(200, {"accepted": True}))
    r = asyncio.run(publisher(c).publish(entry()))
    assert r.status == PUBLISHED
    assert r.attempts == 1
    assert len(c.posts) == 1


def test_the_payload_carries_a_stable_decision_id():
    # The id is what makes a repost idempotent on the far side, so it has to be
    # identical across retries rather than regenerated per attempt.
    c = FakeClient(Reply(500), Reply(200, {"accepted": True}))
    e = entry()
    asyncio.run(publisher(c).publish(e))
    ids = {p["decisionId"] for p in c.posts}
    assert len(ids) == 1, f"the id changed between attempts: {ids}"
    assert ids.pop() == decision_id_for(e)


def test_a_duplicate_is_a_success_not_a_failure():
    # The actor retries and the site is idempotent. A second landing means the
    # first one worked, and counting it as a failure would send someone looking
    # for a fault that is actually the retry rail doing its job.
    c = FakeClient(Reply(200, {"accepted": True, "duplicate": True}))
    r = asyncio.run(publisher(c).publish(entry()))
    assert r.status == DUPLICATE
    assert r.ok is True


# ==================================================================== the retry

def test_a_5xx_is_retried_with_backoff_and_can_succeed():
    waits = []
    c = FakeClient(Reply(503), Reply(503), Reply(200, {"accepted": True}))

    async def sleep(s):
        waits.append(s)

    r = asyncio.run(DecisionPublisher(c, sleep=sleep).publish(entry()))
    assert r.status == PUBLISHED
    assert r.attempts == 3
    assert waits == [2.0, 4.0], f"backoff was not exponential: {waits}"


def test_a_transport_fault_is_retried():
    c = FakeClient(Reply(0, {"error": "connection reset"}), Reply(200, {"accepted": True}))
    r = asyncio.run(publisher(c).publish(entry()))
    assert r.status == PUBLISHED


# ============================================================== the poison rule

def test_a_validation_rejection_is_never_retried():
    # The one that matters for the Pub/Sub path. A payload the site refuses on
    # content will be refused identically forever, and retrying it is how one
    # record holds a subscription open until its retention expires.
    c = FakeClient(Reply(400, {"why": "unknown corner", "error": "unknown corner: nope"}))
    r = asyncio.run(publisher(c).publish(entry()))
    assert r.status == DEAD
    assert r.attempts == 1
    assert len(c.posts) == 1, "a refused payload must not be posted twice"
    assert "unknown corner" in r.why


@pytest.mark.parametrize("status", [400, 401, 403, 413, 422])
def test_no_4xx_that_judges_the_payload_is_retried(status):
    c = FakeClient(Reply(status, {"error": "refused"}))
    r = asyncio.run(publisher(c).publish(entry()))
    assert r.status == DEAD
    assert len(c.posts) == 1


def test_a_persistent_fault_stops_rather_than_retrying_forever():
    c = FakeClient(Reply(503))
    r = asyncio.run(publisher(c).publish(entry()))
    assert r.status == DEAD
    assert len(c.posts) == 4, "four attempts, then it stops"
    assert "after 4 attempts" in r.why


def test_429_is_retried_because_it_is_about_timing_not_content():
    c = FakeClient(Reply(429), Reply(200, {"accepted": True}))
    r = asyncio.run(publisher(c).publish(entry()))
    assert r.status == PUBLISHED
    assert len(c.posts) == 2


# ============================================================= reconciliation

def test_a_dead_publish_is_journaled_as_a_failed_publish():
    journaled: list[JournalEntry] = []
    c = FakeClient(Reply(400, {"why": "unknown corner"}))
    asyncio.run(publisher(c, append_journal=journaled.append).publish(entry()))

    assert len(journaled) == 1, "a decision that never reached the diary must leave a record"
    rec = journaled[0]
    assert rec.error and rec.error.startswith("publish ")
    assert "unknown corner" in rec.error


def test_a_successful_publish_writes_no_journal_entry():
    # A receipt per decision in the journal would raise the restraint rate once
    # per decision forever, because the ledger counts an entry with no actions
    # as restraint.
    journaled: list[JournalEntry] = []
    c = FakeClient(Reply(200, {"accepted": True}))
    asyncio.run(publisher(c, append_journal=journaled.append).publish(entry()))
    assert journaled == []


def test_every_publish_writes_a_receipt_either_way():
    receipts: list[dict] = []
    for reply in (Reply(200, {"accepted": True}), Reply(400, {"why": "nope"})):
        asyncio.run(publisher(FakeClient(reply), append_publish_log=receipts.append).publish(entry()))
    assert len(receipts) == 2, "the log is what lets the journal and the diary be reconciled"
    assert {r["status"] for r in receipts} == {PUBLISHED, DEAD}
    for r in receipts:
        assert r["decision_id"] and r["at"]


# ============================================================== the store hook

def snap(slug="a"):
    return Snapshot(slug=slug, name=slug.upper(), counts=Counts(collisions_5y=1), query_fingerprint="r=80m")


def test_the_wrapper_journals_first_and_publishes_after(tmp_path):
    # The decision is the thing that cannot be recreated. A publish that fails
    # must not be able to cost it.
    inner = LocalJsonStore(tmp_path / "state")
    c = FakeClient(Reply(500))
    store = PublishingStore(inner, publisher(c, append_journal=inner.append_journal))

    store.append_journal(entry())
    assert len(inner.read_journal()) == 1, "journaled before anything was posted"
    assert c.posts == [], "nothing posts until the flush"

    asyncio.run(store.flush())
    assert len(c.posts) == 4
    # One decision, plus the record that publishing it failed.
    assert len(inner.read_journal()) == 2
    assert inner.read_journal()[1]["error"].startswith("publish ")


def test_a_failed_publish_entry_does_not_try_to_publish_itself(tmp_path):
    # Otherwise its own publish could fail, journaling another one, forever.
    inner = LocalJsonStore(tmp_path / "state")
    c = FakeClient(Reply(400, {"why": "nope"}))
    store = PublishingStore(inner, publisher(c, append_journal=inner.append_journal))

    store.append_journal(entry())
    asyncio.run(store.flush())
    posts_after_first = len(c.posts)
    asyncio.run(store.flush())
    assert len(c.posts) == posts_after_first, "the failure record must not be published"


def test_the_wrapper_passes_everything_else_through(tmp_path):
    inner = LocalJsonStore(tmp_path / "state")
    store = PublishingStore(inner, publisher(FakeClient()))
    store.put_snapshot(snap())
    assert store.get_snapshot("a").slug == "a"
    assert len(store.all_snapshots()) == 1
    assert store.get_calibration().reports_311_jump == 15
    assert "publishing decisions to StreetCred" in store.describe()
