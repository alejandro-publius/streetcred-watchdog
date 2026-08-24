"""What the fetch layer does when DataSF answers badly.

Everything here runs against a mock transport, so it is offline and exact. The
cases are the ones that do not raise: a body that parses, has the right shape,
and carries the wrong meaning. Those are the ones that reach the journal wearing
a confident sentence.

The governing distinction, verified against the live API on 2026-08-20:

    count(*)            over an empty set -> [{"count":"0"}]   key always present
    sum(number_killed)  over an empty set -> [{}]              key absent

So an absent count key is an anomaly and an absent sum key is a real zero. Get
that backwards in either direction and the failure is silent.
"""

from __future__ import annotations

import asyncio
import datetime as _dt

import httpx
import pytest

from corner_watchdog.datasf import (
    DS_311,
    _as_int,
    _count_value,
    _iso_years_ago,
    _sum_value,
    fetch_corner_records,
)

CORNER = {"slug": "taylor-and-turk", "name": "Taylor and Turk", "lat": 37.7835, "lon": -122.4110}


def transport(handler):
    return httpx.MockTransport(handler)


def responder(*, collisions=None, fatal=None, severe=None, reports=None, district=None,
              status=200, body=None):
    """Route each of the five lanes to its own canned response.

    The lanes are told apart by their select and where clauses, which is exactly
    how the real code distinguishes them, so a change to one query shape shows up
    here as a routing miss rather than passing quietly.
    """
    defaults = {
        "collisions": [{"count": "40"}],
        "fatal": [{"sum_number_killed": "1"}],
        "severe": [{"count": "3"}],
        "reports": [{"count": "120"}],
        "district": [{"supervisor_district": "5", "count": "30"}],
    }
    lanes = {
        "collisions": defaults["collisions"] if collisions is None else collisions,
        "fatal": defaults["fatal"] if fatal is None else fatal,
        "severe": defaults["severe"] if severe is None else severe,
        "reports": defaults["reports"] if reports is None else reports,
        "district": defaults["district"] if district is None else district,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if body is not None:
            return httpx.Response(status, content=body)
        url = str(request.url)
        select = request.url.params.get("$select", "")
        where = request.url.params.get("$where", "")
        if DS_311 in url:
            lane = "reports"
        elif "$group" in request.url.params:
            lane = "district"
        elif "sum(number_killed)" in select:
            lane = "fatal"
        elif "collision_severity in" in where:
            lane = "severe"
        else:
            lane = "collisions"
        payload = lanes[lane]
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, int):  # an HTTP status to return
            return httpx.Response(payload, json={"error": True})
        return httpx.Response(200, json=payload)

    return handler


def fetch(handler, **kwargs):
    async def go():
        async with httpx.AsyncClient(transport=transport(handler)) as client:
            return await fetch_corner_records(
                CORNER["slug"], CORNER["name"], CORNER["lat"], CORNER["lon"],
                client=client, **kwargs
            )

    return asyncio.run(go())


# ------------------------------------------------------------------ the happy path

def test_a_clean_response_produces_a_complete_snapshot():
    s = fetch(responder())
    assert s.complete is True
    assert (s.counts.collisions_5y, s.counts.fatal_5y, s.counts.severe_5y) == (40, 1, 3)
    assert s.counts.reports_311_3y == 120
    assert s.counts.district == 5
    assert s.query_fingerprint


def test_the_two_integer_formats_both_parse():
    """The collision dataset says "11" and the 311 dataset says "9.00000"."""
    s = fetch(responder(collisions=[{"count": "11"}], reports=[{"count": "9.00000"}]))
    assert s.counts.collisions_5y == 11
    assert s.counts.reports_311_3y == 9
    assert s.complete is True


# ----------------------------------------------------- a corner with nothing on it

def test_a_genuinely_empty_corner_is_complete_not_broken():
    """count returns "0" and sum returns an empty object. Both are real answers."""
    s = fetch(responder(
        collisions=[{"count": "0"}], severe=[{"count": "0"}], reports=[{"count": "0"}],
        fatal=[{}], district=[],
    ))
    assert s.complete is True
    assert s.counts.collisions_5y == 0
    assert s.counts.fatal_5y == 0
    assert s.counts.district is None


# ------------------------------------------------------------- the silent failures

def test_a_renamed_count_alias_marks_the_snapshot_incomplete():
    """The SEVERE_VALUES lesson at the response layer: not zero, unknown."""
    s = fetch(responder(collisions=[{"total": "40"}]))
    assert s.complete is False
    assert s.counts.collisions_5y == 0  # the value is meaningless and the flag says so


def test_an_empty_array_from_a_count_query_marks_incomplete():
    """count(*) always returns a row. An empty array is not a quiet corner."""
    s = fetch(responder(severe=[]))
    assert s.complete is False


def test_an_empty_array_from_the_sum_query_marks_incomplete():
    s = fetch(responder(fatal=[]))
    assert s.complete is False


def test_a_null_count_is_not_silently_zero():
    s = fetch(responder(reports=[{"count": None}]))
    assert s.counts.reports_311_3y == 0
    assert s.complete is True  # the key was there, the value parsed to zero


def test_a_non_dict_row_marks_incomplete():
    s = fetch(responder(collisions=["forty"]))
    assert s.complete is False


def test_a_non_list_body_marks_incomplete():
    s = fetch(responder(collisions={"count": "40"}))
    assert s.complete is False


# ---------------------------------------------------------------- transport faults

@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503])
def test_every_error_status_marks_incomplete_and_never_raises(status):
    s = fetch(responder(collisions=status))
    assert s.complete is False
    assert s.counts.collisions_5y == 0


def test_malformed_json_marks_incomplete():
    s = fetch(responder(body=b"{not json at all"))
    assert s.complete is False


def test_an_html_error_page_marks_incomplete():
    s = fetch(responder(body=b"<html><body>502 Bad Gateway</body></html>"))
    assert s.complete is False


def test_a_timeout_marks_incomplete():
    s = fetch(responder(reports=httpx.ReadTimeout("too slow")))
    assert s.complete is False


def test_one_failed_lane_does_not_discard_the_others():
    """Partial is still worth recording, as long as it knows it is partial."""
    s = fetch(responder(severe=500))
    assert s.complete is False
    assert s.counts.collisions_5y == 40
    assert s.counts.reports_311_3y == 120


def test_every_lane_failing_still_returns_a_snapshot():
    s = fetch(responder(collisions=500, fatal=500, severe=500, reports=500, district=500))
    assert s.complete is False
    assert s.slug == "taylor-and-turk"


# ------------------------------------------------------------ the district lane

def test_the_district_is_the_grouped_majority_not_the_first_row():
    """A major street is often a boundary. The bigger group wins."""
    s = fetch(responder(district=[
        {"supervisor_district": "5", "count": "114"},
        {"supervisor_district": "6", "count": "242"},
    ]))
    assert s.counts.district == 6


def test_a_tie_breaks_deterministically_rather_than_by_api_order():
    """Otherwise a tied corner flips district between sweeps and it reads as news."""
    rows = [{"supervisor_district": "9", "count": "50"}, {"supervisor_district": "3", "count": "50"}]
    first = fetch(responder(district=rows))
    second = fetch(responder(district=list(reversed(rows))))
    assert first.counts.district == second.counts.district == 3


def test_a_duplicated_district_row_does_not_change_the_winner():
    s = fetch(responder(district=[
        {"supervisor_district": "6", "count": "242"},
        {"supervisor_district": "6", "count": "242"},
        {"supervisor_district": "5", "count": "114"},
    ]))
    assert s.counts.district == 6


def test_a_zero_district_is_skipped_rather_than_reported():
    s = fetch(responder(district=[
        {"supervisor_district": "0", "count": "900"},
        {"supervisor_district": "6", "count": "12"},
    ]))
    assert s.counts.district == 6


def test_a_configured_district_overrides_the_majority():
    s = fetch(responder(district=[{"supervisor_district": "6", "count": "242"}]),
              configured_district=9)
    assert s.counts.district == 9


def test_garbage_district_rows_do_not_crash_the_lane():
    s = fetch(responder(district=["nonsense", {"supervisor_district": "x", "count": "y"},
                                  {"supervisor_district": "6", "count": "3"}]))
    assert s.counts.district == 6


# ------------------------------------------------------------------ scale sanity

def test_a_corner_returning_ten_times_the_expected_rows_is_just_a_big_number():
    s = fetch(responder(collisions=[{"count": "400"}], reports=[{"count": "12000"}]))
    assert s.counts.collisions_5y == 400
    assert s.counts.reports_311_3y == 12000
    assert s.complete is True


def test_an_absurd_count_does_not_overflow_or_raise():
    s = fetch(responder(collisions=[{"count": "9" * 40}]))
    assert s.counts.collisions_5y > 0
    assert s.complete is True


def test_a_negative_count_is_carried_not_clamped_at_the_fetch_layer():
    """Flooring belongs in the delta engine, where it can be explained."""
    s = fetch(responder(collisions=[{"count": "-5"}]))
    assert s.counts.collisions_5y == -5


# ------------------------------------------------------------------ the parsers

@pytest.mark.parametrize("raw,expected", [
    ("11", 11), ("9.00000", 9), ("0", 0), ("-3", -3), ("1e3", 1000),
    (None, 0), ("", 0), ("abc", 0), ([], 0), ({}, 0), ("NaN", 0), ("inf", 0),
])
def test_integer_parsing_survives_everything_datasf_might_send(raw, expected):
    assert _as_int(raw) == expected


def test_count_value_rejects_shapes_that_are_not_a_count():
    assert _count_value([]) == (0, False)
    assert _count_value(None) == (0, False)
    assert _count_value("[]") == (0, False)
    assert _count_value([{"total": "4"}]) == (0, False)
    assert _count_value([{"count": "4"}]) == (4, True)


def test_sum_value_treats_an_absent_key_as_zero_but_an_absent_row_as_unknown():
    assert _sum_value([{}], "sum_number_killed") == (0, True)
    assert _sum_value([], "sum_number_killed") == (0, False)
    assert _sum_value([{"sum_number_killed": "2"}], "sum_number_killed") == (2, True)


# --------------------------------------------------------------------- the clock

def test_the_window_is_computed_in_utc_whatever_the_local_clock_says():
    pacific_midnight = _dt.datetime(2026, 8, 20, 7, 0, 0, tzinfo=_dt.UTC)
    assert _iso_years_ago(5, pacific_midnight) == "2021-08-21T07:00:00"


def test_one_minute_either_side_of_pacific_midnight_moves_the_window_by_one_minute():
    """It must move smoothly, not jump a day, which is what a local-time anchor does."""
    before = _dt.datetime(2026, 8, 20, 6, 59, tzinfo=_dt.UTC)
    after = _dt.datetime(2026, 8, 20, 7, 1, tzinfo=_dt.UTC)
    assert _iso_years_ago(5, before) == "2021-08-21T06:59:00"
    assert _iso_years_ago(5, after) == "2021-08-21T07:01:00"


def test_the_spring_dst_transition_does_not_shift_the_window_by_an_hour():
    """2026-03-08 is when Pacific springs forward. UTC does not care, and neither must this."""
    before = _dt.datetime(2026, 3, 8, 9, 30, tzinfo=_dt.UTC)
    after = _dt.datetime(2026, 3, 8, 10, 30, tzinfo=_dt.UTC)
    delta = _dt.datetime.fromisoformat(_iso_years_ago(3, after)) - _dt.datetime.fromisoformat(
        _iso_years_ago(3, before)
    )
    assert delta == _dt.timedelta(hours=1)


def test_a_naive_datetime_is_treated_as_utc_rather_than_local():
    naive = _dt.datetime(2026, 8, 20, 7, 0, 0)  # noqa: DTZ001 - naive is the point of this test
    aware = _dt.datetime(2026, 8, 20, 7, 0, 0, tzinfo=_dt.UTC)
    assert _iso_years_ago(5, naive) == _iso_years_ago(5, aware)


def test_the_window_start_is_always_in_the_past():
    now = _dt.datetime(2026, 8, 20, 12, 0, tzinfo=_dt.UTC)
    for years in (1, 3, 5, 10):
        assert _dt.datetime.fromisoformat(_iso_years_ago(years, now)) < now.replace(tzinfo=None)
