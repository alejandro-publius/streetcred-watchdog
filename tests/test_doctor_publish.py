"""Doctor reads the publish log from wherever it actually lives.

The check existed and read a file. The deployed services write their receipts to
Firestore, so on a laptop it reported "no publish attempts recorded yet" while
24 decisions had been published from Cloud Run an hour earlier. That is not a
wrong answer to the question. It is a right answer to a different one, which is
the harder kind to notice, and the fix is not only to read the other store but
to say which store was read.

Both paths are driven here, and so is the fallback, because the fallback is the
one that decides whether a Firestore outage reads as "nothing published" or as
"I could not tell".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from corner_watchdog.doctor import FAIL, PASS, _publish_checks, publish_log_source
from corner_watchdog.store import LocalJsonStore

PUBLISHED = {"status": "published", "slug": "a", "decision_id": "1", "at": "2026-08-26T20:00:00+00:00"}
DEAD = {
    "status": "permanently_failed",
    "slug": "b",
    "decision_id": "2",
    "at": "2026-08-26T20:01:00+00:00",
    "why": "claimed consequence this site cannot verify",
}


def reader(rows, source):
    return lambda: (rows, source)


# Three tests below reach `corner_watchdog.cloud`, which needs the cloud extra.
# `pip install -e ".[dev]"`, which is what the README's quick start runs, does
# not install it, so those three raised ModuleNotFoundError on a clean checkout
# while passing here. Same idiom as tests/test_server.py, but per test rather
# than per module: the reader-injected cases above need no cloud and must keep
# running everywhere, because they are the ones that guard the reporting.
def _has_cloud() -> bool:
    # find_spec on a dotted name imports the parents, and `google` here is a
    # namespace package contributed by google-adk that has no `cloud` under it,
    # so the lookup raises rather than returning None. Caught, because the
    # question being asked is "is it installed", and an exception is an answer.
    try:
        return importlib.util.find_spec("google.cloud.firestore") is not None
    except (ImportError, ValueError):
        return False


needs_cloud = pytest.mark.skipif(
    not _has_cloud(), reason="the cloud extra is not installed"
)


# ================================================================== the answers

def test_a_clean_run_passes_and_names_its_source():
    checks = _publish_checks(Path("state"), reader([PUBLISHED, PUBLISHED], "Firestore, watchdog in p"))
    assert len(checks) == 1
    assert checks[0].status == PASS
    assert "2 reached the diary" in checks[0].detail
    assert "Firestore, watchdog in p" in checks[0].detail


def test_a_dead_publish_fails_and_names_the_reason():
    checks = _publish_checks(Path("state"), reader([PUBLISHED, DEAD], "Firestore, watchdog in p"))
    assert checks[0].status == FAIL
    assert "1 reached the diary, 1 did not" in checks[0].detail
    assert "claimed consequence" in checks[0].detail


def test_an_empty_log_says_where_it_looked():
    # The bug this file is about. "No publish attempts recorded yet" is only
    # useful if the reader can tell which store was consulted.
    checks = _publish_checks(Path("state"), reader([], "the local file at state"))
    assert checks[0].status == PASS
    assert "the local file at state" in checks[0].detail


# ================================================================== the sources

def test_with_no_project_configured_it_reads_the_local_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    store = LocalJsonStore(tmp_path / "state")
    store.append_publish_log(PUBLISHED)

    log, source = publish_log_source(tmp_path / "state")
    assert len(log) == 1
    assert "local file" in source


@needs_cloud
def test_with_a_project_configured_it_reads_firestore(tmp_path, monkeypatch):
    # The deployed path. Nothing here opens a network connection: the Firestore
    # client is replaced, because what is under test is which store doctor
    # chooses, not whether Google's client works.
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "streetcred-506117")

    class FakeStore:
        database = "watchdog"

        def __init__(self, *a, **k) -> None:
            pass

        def read_publish_log(self, limit=None):
            return [PUBLISHED, DEAD]

    import corner_watchdog.cloud as cloud

    monkeypatch.setattr(cloud, "FirestoreStore", FakeStore)

    log, source = publish_log_source(tmp_path / "state")
    assert len(log) == 2
    assert source == "Firestore, watchdog in streetcred-506117"


@needs_cloud
def test_a_firestore_failure_falls_back_and_says_so(tmp_path, monkeypatch):
    # The important one. A Firestore that cannot be read must not read as
    # "nothing has been published", because that is the same output as a healthy
    # agent that has published nothing, and the two need different actions.
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "streetcred-506117")
    LocalJsonStore(tmp_path / "state").append_publish_log(PUBLISHED)

    class Exploding:
        def __init__(self, *a, **k) -> None:
            raise RuntimeError("no credentials on this machine")

    import corner_watchdog.cloud as cloud

    monkeypatch.setattr(cloud, "FirestoreStore", Exploding)

    log, source = publish_log_source(tmp_path / "state")
    assert len(log) == 1, "it falls back to the file rather than reporting nothing"
    assert "Firestore could not be read" in source
    assert "RuntimeError" in source


@needs_cloud
def test_the_check_surfaces_the_fallback_source_to_a_reader(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "streetcred-506117")

    class Exploding:
        def __init__(self, *a, **k) -> None:
            raise RuntimeError("boom")

    import corner_watchdog.cloud as cloud

    monkeypatch.setattr(cloud, "FirestoreStore", Exploding)

    checks = _publish_checks(tmp_path / "state")
    assert "Firestore could not be read" in checks[0].detail


# ================================================================== the window

# The check used to fail on any dead receipt ever recorded, so one bad batch on
# 2026-08-26 meant it could never be green again. A check that can only fail is
# a check people learn to skip, and DEMO_SCRIPT.md tells a presenter to run this
# one on camera. The state now reflects a stated window; the history is still
# printed, because forgiving a failure by age would be the opposite mistake.

NOW = "2026-08-27T12:00:00+00:00"


def at(stamp, **over):
    row = {"status": "published", "slug": "a", "decision_id": "x", "at": stamp}
    row.update(over)
    return row


def clock():
    import datetime as dt

    return dt.datetime.fromisoformat(NOW)


def check(rows, hours=24):
    return _publish_checks(
        Path("state"), reader(rows, "Firestore, watchdog in p"), now=clock(), window_hours=hours
    )[0]


def test_an_old_dead_batch_does_not_fail_a_healthy_agent():
    c = check([
        at("2026-08-20T20:25:00+00:00", status="permanently_failed", why="claimed consequence"),
        at("2026-08-27T09:00:00+00:00"),
    ])
    assert c.status == PASS
    assert "1 reached the diary, 0 did not" in c.detail


def test_the_old_batch_is_still_reported_with_its_count_and_date():
    c = check([
        at("2026-08-20T20:25:00+00:00", status="permanently_failed", why="nope"),
        at("2026-08-20T20:26:00+00:00", status="permanently_failed", why="nope"),
        at("2026-08-27T09:00:00+00:00"),
    ])
    assert "2 dead receipt(s) on 2026-08-20" in c.detail, c.detail
    assert "retained" in c.detail


def test_the_window_is_named_in_the_output():
    assert "the last 24 hours" in check([at("2026-08-27T09:00:00+00:00")]).detail


def test_a_recent_failure_still_fails():
    c = check([
        at("2026-08-27T09:00:00+00:00"),
        at("2026-08-27T10:00:00+00:00", status="permanently_failed", why="unknown corner"),
    ])
    assert c.status == FAIL
    assert "unknown corner" in c.detail


def test_a_failure_inside_the_window_is_not_double_counted_as_history():
    c = check([at("2026-08-27T10:00:00+00:00", status="permanently_failed", why="x")])
    assert c.status == FAIL
    assert "Older than" not in c.detail


def test_no_attempts_in_the_window_says_so_and_keeps_the_history():
    c = check([at("2026-08-20T20:25:00+00:00", status="permanently_failed", why="x")])
    assert c.status == PASS
    assert "no publish attempts in the last 24 hours" in c.detail
    assert "1 dead receipt(s) on 2026-08-20" in c.detail


def test_a_receipt_with_an_unreadable_date_counts_as_recent():
    # Erring the other way would let a broken timestamp hide a live failure.
    c = check([at("not a date", status="permanently_failed", why="broken clock")])
    assert c.status == FAIL


def test_a_wider_window_pulls_the_old_batch_back_into_the_state():
    rows = [at("2026-08-20T20:25:00+00:00", status="permanently_failed", why="x")]
    assert check(rows, hours=24).status == PASS
    assert check(rows, hours=24 * 30).status == FAIL, "the window is the only thing forgiving it"
