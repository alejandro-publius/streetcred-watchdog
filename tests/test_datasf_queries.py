"""Guards on the string literals that go into DataSF queries.

These are not exciting tests and they are the ones that would have caught the
worst bug in the repo. A category name that does not exist produces a valid
query, no error, and a clean zero on every sweep forever. There is nothing to
notice unless something asserts that the names are real.

Everything here is offline. The dataset's own vocabulary is pinned as a constant
in datasf.py alongside the command that produced it, so refreshing it is a
documented step rather than an act of memory.
"""

from __future__ import annotations

from corner_watchdog.datasf import (
    KNOWN_SEVERITY_VALUES,
    SERVICE_NAMES,
    SEVERE_VALUES,
    _as_int,
)


def test_every_severity_we_filter_on_exists_in_the_dataset():
    """The bug: the filter named CHP's category labels, not DataSF's."""
    unknown = [v for v in SEVERE_VALUES if v not in KNOWN_SEVERITY_VALUES]
    assert unknown == [], f"these severity values match nothing in ubvf-ztfx: {unknown}"


def test_severe_does_not_quietly_swallow_the_other_categories():
    """Severe means severe. Pain and other-visible are counted, not escalated."""
    assert "Injury (Complaint of Pain)" not in SEVERE_VALUES
    assert "Injury (Other Visible)" not in SEVERE_VALUES
    assert "Fatal" not in SEVERE_VALUES  # fatalities come from number_killed


def test_severe_filter_is_not_empty():
    """An empty tuple would build `in()` and take the count silently to zero."""
    assert len(SEVERE_VALUES) >= 1


def test_the_311_allow_list_holds_no_blank_or_duplicate_names():
    assert all(s.strip() for s in SERVICE_NAMES)
    assert len(set(SERVICE_NAMES)) == len(SERVICE_NAMES)


def test_the_311_allow_list_still_excludes_the_categories_that_say_nothing_about_safety():
    """Graffiti and noise at a busy corner are not evidence about the crossing."""
    for noise in ("Graffiti", "Noise Report", "Encampments", "Street and Sidewalk Cleaning"):
        assert noise not in SERVICE_NAMES


def test_datasf_integer_parsing_survives_both_of_its_formats():
    """The collision dataset says "11" and the 311 dataset says "9.00000"."""
    assert _as_int("11") == 11
    assert _as_int("9.00000") == 9
    assert _as_int(None) == 0
    assert _as_int("") == 0
