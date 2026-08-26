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

from pathlib import Path

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


def test_the_check_surfaces_the_fallback_source_to_a_reader(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "streetcred-506117")

    class Exploding:
        def __init__(self, *a, **k) -> None:
            raise RuntimeError("boom")

    import corner_watchdog.cloud as cloud

    monkeypatch.setattr(cloud, "FirestoreStore", Exploding)

    checks = _publish_checks(tmp_path / "state")
    assert "Firestore could not be read" in checks[0].detail
