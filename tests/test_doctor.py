"""The pre-flight check, and the line it draws between warn and fail.

The distinction is the whole design. A degraded tier is a warning: the loop
handles it correctly and says so on every entry it writes, so a cycle run in that
state is still honest. A drifted query vocabulary is a failure: nothing
downstream can tell that the numbers are wrong, which is precisely the condition
that produced every serious bug in this repository.

Getting that line in the wrong place is worse than having no doctor at all,
because a green table is a claim.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from corner_watchdog.datasf import query_fingerprint
from corner_watchdog.doctor import FAIL, PASS, WARN, Check, render, run_checks
from corner_watchdog.roster import roster_hash
from corner_watchdog.schema import Counts, Snapshot
from corner_watchdog.store import LocalJsonStore


def by_name(checks, name):
    return next(c for c in checks if c.name == name)


def healthy(tmp_path):
    """A state directory and roster that should come back clean."""
    state = tmp_path / "state"
    store = LocalJsonStore(state)
    store.put_snapshot(Snapshot(
        slug="a", name="A",
        counts=Counts(collisions_5y=40, fatal_5y=1, severe_5y=3, reports_311_3y=120, district=6),
        fetched_at="2026-08-20T05:00:00+00:00", complete=True,
        query_fingerprint=query_fingerprint(80),
    ))
    watched = tmp_path / "watched.json"
    watched.write_text(json.dumps({
        "roster_hash": roster_hash(["a"]),
        "corners": [{"slug": "a", "name": "A", "lat": 37.78, "lon": -122.41,
                     "district": 6, "radiusMeters": 80}],
    }))
    return state, watched


def check(tmp_path, **over):
    state, watched = over.pop("paths", None) or healthy(tmp_path)
    return asyncio.run(run_checks(state_dir=state, watched_path=watched, offline=True, **over))


# ------------------------------------------------------------------- the table

def test_a_healthy_repo_has_no_failures(tmp_path):
    checks = check(tmp_path)
    assert [c for c in checks if c.status == FAIL] == []


def test_render_returns_zero_when_nothing_failed(capsys):
    assert render([Check("a", PASS, "fine")], printer=print) == 0


def test_render_returns_nonzero_when_anything_failed(capsys):
    assert render([Check("a", PASS, "fine"), Check("b", FAIL, "broken")], printer=print) == 1


def test_a_failure_is_repeated_with_the_reason_not_just_counted(capsys):
    render([Check("query vocabulary", FAIL, "severity filter matches nothing")], printer=print)
    out = capsys.readouterr().out
    assert "Do not trust a cycle run in this state" in out
    assert "severity filter matches nothing" in out


def test_warnings_are_explained_as_states_the_loop_handles(capsys):
    render([Check("vertex", WARN, "no credentials")], printer=print)
    assert "the loop handles and journals honestly" in capsys.readouterr().out


def test_every_check_reports_a_detail_not_just_a_status(tmp_path):
    for c in check(tmp_path):
        assert c.detail.strip(), f"{c.name} has no detail"


# --------------------------------------------------- warn: honest but degraded

def test_a_missing_vertex_project_warns_rather_than_fails(tmp_path, monkeypatch):
    """The loop handles this correctly and says so on every entry."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    assert by_name(check(tmp_path), "vertex configuration").status == WARN


def test_a_missing_watched_set_warns_because_a_run_will_fetch_one(tmp_path):
    state = tmp_path / "state"
    LocalJsonStore(state)
    checks = asyncio.run(run_checks(state_dir=state, watched_path=tmp_path / "nope.json",
                                    offline=True))
    assert by_name(checks, "watched set").status == WARN


def test_a_hand_edited_roster_warns(tmp_path):
    state, watched = healthy(tmp_path)
    doc = json.loads(watched.read_text())
    doc["corners"].append({"slug": "smuggled", "name": "S", "lat": 1, "lon": 2, "radiusMeters": 80})
    watched.write_text(json.dumps(doc))
    assert by_name(check(tmp_path, paths=(state, watched)), "roster hash").status == WARN


def test_mixed_query_fingerprints_warn_because_the_sweep_will_rebuild(tmp_path):
    state, watched = healthy(tmp_path)
    store = LocalJsonStore(state)
    store.put_snapshot(Snapshot(slug="b", name="B", counts=Counts(),
                                fetched_at="x", complete=True,
                                query_fingerprint=query_fingerprint(150)))
    c = by_name(check(tmp_path, paths=(state, watched)), "query fingerprint")
    assert c.status == WARN
    assert "refuse those comparisons and rebuild" in c.detail


def test_an_empty_journal_warns_rather_than_failing(tmp_path):
    assert by_name(check(tmp_path), "journal").status == WARN


def test_a_held_cycle_lock_warns(tmp_path):
    from corner_watchdog.schedule import cycle_lock

    state, watched = healthy(tmp_path)
    with cycle_lock(state):
        c = by_name(check(tmp_path, paths=(state, watched)), "cycle lock")
    assert c.status == WARN
    assert "held by pid" in c.detail


def test_quarantined_snapshots_are_surfaced(tmp_path):
    state, watched = healthy(tmp_path)
    store = LocalJsonStore(state)
    (store.snapshots_dir / "broken.json").write_text("{not json")
    store.get_snapshot("broken")  # quarantines it
    c = by_name(check(tmp_path, paths=(state, watched)), "quarantine")
    assert c.status == WARN
    assert "quarantine.log" in c.detail


def test_a_torn_journal_line_warns_and_reports_how_many(tmp_path):
    state, watched = healthy(tmp_path)
    (state / "journal.jsonl").write_text('{"ts": "1"}\n{torn\n{"ts": "2"}\n')
    c = by_name(check(tmp_path, paths=(state, watched)), "journal")
    assert c.status == WARN
    assert "1 torn" in c.detail


# ---------------------------------------------------- fail: numbers worth nothing

def test_a_drifted_vocabulary_fails(tmp_path, monkeypatch):
    """Nothing downstream can tell the numbers are wrong. That is the line."""
    monkeypatch.setattr("corner_watchdog.vocabulary.SEVERE_VALUES", ("Severe Injury",))
    c = by_name(check(tmp_path), "query vocabulary, pinned")
    assert c.status == FAIL
    assert "Severe Injury" in c.detail


def test_an_unreadable_snapshot_fails(tmp_path):
    state, watched = healthy(tmp_path)
    (state / "snapshots" / "broken.json").write_text('{"counts": {"collisions_5y": "seventy"}}')
    c = by_name(check(tmp_path, paths=(state, watched)), "snapshot integrity")
    assert c.status == FAIL
    assert "MalformedSnapshot" in c.detail


def test_a_corner_without_coordinates_fails(tmp_path):
    state, watched = healthy(tmp_path)
    doc = json.loads(watched.read_text())
    doc["corners"][0]["lat"] = None
    watched.write_text(json.dumps(doc))
    assert by_name(check(tmp_path, paths=(state, watched)), "corner geometry").status == FAIL


def test_an_unparseable_watched_set_fails(tmp_path):
    state, watched = healthy(tmp_path)
    watched.write_text("{not json")
    assert by_name(check(tmp_path, paths=(state, watched)), "watched set").status == FAIL


# ------------------------------------------------------------ the network checks

def transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_reachable_sources_pass(tmp_path):
    def handler(request):
        if "data.sfgov.org" in str(request.url) and "$group" in request.url.params:
            return httpx.Response(200, json=[
                {"collision_severity": "Fatal", "count": "1"},
                {"collision_severity": "Injury (Severe)", "count": "2"},
                {"collision_severity": "Injury (Other Visible)", "count": "3"},
                {"collision_severity": "Injury (Complaint of Pain)", "count": "4"},
                {"service_name": "Street Defects", "count": "5"},
            ])
        return httpx.Response(200, json=[{"count": "1"}])

    state, watched = healthy(tmp_path)

    async def go():
        async with transport(handler) as client:
            return await run_checks(state_dir=state, watched_path=watched, client=client)

    checks = asyncio.run(go())
    assert by_name(checks, "DataSF, collisions").status == PASS
    assert by_name(checks, "StreetCred scoreboard").status == PASS


def test_a_source_that_is_down_fails_rather_than_crashing(tmp_path):
    def handler(request):
        raise httpx.ConnectError("no route to host")

    state, watched = healthy(tmp_path)

    async def go():
        async with transport(handler) as client:
            return await run_checks(state_dir=state, watched_path=watched, client=client)

    checks = asyncio.run(go())
    c = by_name(checks, "DataSF, collisions")
    assert c.status == FAIL
    assert "ConnectError" in c.detail


def test_a_non_200_from_a_source_fails(tmp_path):
    def handler(request):
        return httpx.Response(503, json={})

    state, watched = healthy(tmp_path)

    async def go():
        async with transport(handler) as client:
            return await run_checks(state_dir=state, watched_path=watched, client=client)

    assert by_name(asyncio.run(go()), "DataSF, 311").status == FAIL


def test_a_renamed_severity_upstream_fails_the_live_check(tmp_path):
    def handler(request):
        if "$group" in request.url.params:
            return httpx.Response(200, json=[{"collision_severity": "Injury (Serious)", "count": "9"}])
        return httpx.Response(200, json=[{"count": "1"}])

    state, watched = healthy(tmp_path)

    async def go():
        async with transport(handler) as client:
            return await run_checks(state_dir=state, watched_path=watched, client=client)

    c = by_name(asyncio.run(go()), "query vocabulary, live")
    assert c.status == FAIL
    assert "zero and wrong" in c.detail


def test_offline_skips_every_network_check(tmp_path):
    names = {c.name for c in check(tmp_path)}
    assert "DataSF, collisions" not in names
    assert "query vocabulary, live" not in names
    assert "query vocabulary, pinned" in names


# ------------------------------------------------------------------ the live path

def test_the_doctor_states_that_nothing_posts(tmp_path):
    c = by_name(check(tmp_path), "live path")
    assert c.status == PASS
    assert "Nothing posts" in c.detail


def test_the_cli_exposes_doctor_and_returns_its_code(tmp_path, capsys):
    from corner_watchdog.cli import main

    state, watched = healthy(tmp_path)
    code = main(["--state", str(state), "--watched", str(watched), "doctor", "--offline"])
    out = capsys.readouterr().out
    assert code == 0
    assert "checks," in out
    assert "live path" in out
