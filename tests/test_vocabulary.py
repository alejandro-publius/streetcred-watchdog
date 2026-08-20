"""The guard that would have caught the bug this whole repo learned from.

`SEVERE_VALUES` named CHP's category labels rather than DataSF's for the entire
life of the project. The query was valid, matched zero rows, and returned a clean
zero on every corner on every sweep. There was nothing to notice, because a
filter that matches nothing is indistinguishable from a corner where nothing
happened.

The check is deliberately asymmetric, and the asymmetry is the interesting part.
Every value we filter on must exist upstream, in both directions for collision
severity, but only in one direction for 311, because that allow list is partial
on purpose.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from watchdog.datasf import KNOWN_SEVERITY_VALUES, SERVICE_NAMES
from watchdog.vocabulary import (
    PINNED_SERVICE_NAMES,
    PINNED_SEVERITY,
    VocabularyDrift,
    assert_pinned,
    check_against_live,
    check_against_pinned,
    fetch_live,
    summarise_live,
)

LIVE_OK = {
    "collision_severity": {
        "Fatal": 622,
        "Injury (Complaint of Pain)": 41829,
        "Injury (Other Visible)": 18715,
        "Injury (Severe)": 4638,
    },
    "service_name": dict.fromkeys(SERVICE_NAMES, 1),
}


# ------------------------------------------------------- the repo as it stands

def test_the_shipped_filters_match_the_pinned_evidence():
    assert check_against_pinned() == []
    assert_pinned() is None


def test_the_pinned_evidence_carries_counts_not_just_names():
    """Counts are what stop this from being the filter list checked against itself."""
    assert all(isinstance(v, int) and v > 0 for v in PINNED_SEVERITY.values())
    assert all(isinstance(v, int) and v > 0 for v in PINNED_SERVICE_NAMES.values())


def test_every_known_severity_is_pinned():
    assert set(KNOWN_SEVERITY_VALUES) == set(PINNED_SEVERITY)


# ------------------------------------------------- drift against the pinned set

def test_the_original_bug_would_now_fail_loudly(monkeypatch):
    """The exact wrong tuple that shipped in the first commit."""
    monkeypatch.setattr(
        "watchdog.vocabulary.SEVERE_VALUES", ("Severe Injury", "Suspected Serious Injury")
    )
    problems = check_against_pinned()
    assert len(problems) == 2
    assert "Severe Injury" in problems[0]
    assert "is not in the vocabulary recorded" in problems[0]


def test_an_unverified_311_category_fails_loudly(monkeypatch):
    monkeypatch.setattr("watchdog.vocabulary.SERVICE_NAMES", [*SERVICE_NAMES, "Potholes"])
    problems = check_against_pinned()
    assert any("Potholes" in p and "silent zero" in p for p in problems)


def test_an_empty_severity_filter_is_caught(monkeypatch):
    """An empty tuple builds `in()` and takes every severe count to zero."""
    monkeypatch.setattr("watchdog.vocabulary.SEVERE_VALUES", ())
    assert any("matches nothing" in p for p in check_against_pinned())


def test_assert_pinned_raises_a_named_error(monkeypatch):
    monkeypatch.setattr("watchdog.vocabulary.SEVERE_VALUES", ("Made Up Category",))
    with pytest.raises(VocabularyDrift) as e:
        assert_pinned()
    assert "does not match the recorded evidence" in str(e.value)
    assert "Made Up Category" in str(e.value)


def test_a_cycle_refuses_to_run_on_an_unverified_filter(monkeypatch, tmp_path):
    """Numbers from an unverified filter are worse than no numbers."""
    from watchdog.runner import run_cycle

    monkeypatch.setattr("watchdog.vocabulary.SEVERE_VALUES", ("Made Up Category",))
    with pytest.raises(VocabularyDrift):
        asyncio.run(run_cycle([], state_dir=tmp_path, outbox_dir=tmp_path / "out"))


# ------------------------------------------------------- drift against the live

def test_a_healthy_live_vocabulary_reports_nothing():
    assert check_against_live(LIVE_OK) == []


def test_a_renamed_severity_upstream_is_caught():
    live = {**LIVE_OK, "collision_severity": {"Fatal": 1, "Injury (Serious)": 4638}}
    problems = check_against_live(live)
    assert any("no longer has" in p and "zero and wrong" in p for p in problems)


def test_a_brand_new_severity_category_is_caught():
    """The direction that catches an addition rather than a rename."""
    live = {**LIVE_OK}
    live["collision_severity"] = {**LIVE_OK["collision_severity"], "Injury (Catastrophic)": 12}
    problems = check_against_live(live)
    assert any("never heard of" in p and "Injury (Catastrophic)" in p for p in problems)


def test_a_311_category_we_ignore_is_not_reported_as_drift():
    """The allow list is partial on purpose. Graffiti is not a safety signal."""
    live = {**LIVE_OK, "service_name": {**LIVE_OK["service_name"], "Graffiti": 870421}}
    assert check_against_live(live) == []


def test_a_missing_311_category_is_reported():
    live = {**LIVE_OK, "service_name": {n: 1 for n in SERVICE_NAMES if n != "Color Curb"}}
    assert any("Color Curb" in p for p in check_against_live(live))


def test_an_empty_live_response_is_reported_rather_than_passing():
    """Nothing checked must never read as everything fine."""
    problems = check_against_live({"collision_severity": {}, "service_name": {}})
    assert len(problems) == 2
    assert all("came back empty" in p for p in problems)


# ------------------------------------------------------------------ the fetch

def test_fetch_live_parses_a_grouped_response():
    def handler(request: httpx.Request) -> httpx.Response:
        field = request.url.params["$group"]
        if field == "collision_severity":
            return httpx.Response(200, json=[
                {"collision_severity": "Fatal", "count": "622"},
                {"collision_severity": "Injury (Severe)", "count": "4638"},
            ])
        return httpx.Response(200, json=[{"service_name": "Color Curb", "count": "15487"}])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_live(c)

    live = asyncio.run(go())
    assert live["collision_severity"]["Injury (Severe)"] == 4638
    assert live["service_name"]["Color Curb"] == 15487


def test_fetch_live_skips_rows_it_cannot_read():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[
            {"collision_severity": "Fatal", "count": "622"},
            {"collision_severity": None, "count": "9"},
            {"count": "3"},
            "not a row",
        ])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_live(c)

    live = asyncio.run(go())
    assert live["collision_severity"] == {"Fatal": 622}


def test_the_summary_marks_which_values_are_filtered_and_which_are_new():
    live = {**LIVE_OK}
    live["collision_severity"] = {**LIVE_OK["collision_severity"], "Injury (Catastrophic)": 12}
    lines = "\n".join(summarise_live(live))
    assert "Injury (Severe)" in lines and "filtered" in lines
    assert "Injury (Catastrophic)" in lines and "NEW" in lines
    assert "9 of 9 entries match" in lines
