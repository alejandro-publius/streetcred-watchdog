"""Guards on the enumerated values this agent puts inside a WHERE clause.

The lesson this module exists because of: `SEVERE_VALUES` held
`("Severe Injury", "Suspected Serious Injury")` from the first commit until
2026-08-19. Those are CHP SWITRS category labels. DataSF publishes
`Injury (Severe)`. The query was valid SoQL, matched zero rows, returned a clean
zero for every corner on every sweep, and made the rule "any new severe injury is
significant" a rule that could never fire. Nothing failed. Nothing could fail:
a filter that matches nothing looks exactly like a corner where nothing happened.

So every enumerated value this code filters on is pinned here against evidence
read off the live API, with the count of rows carrying that value at the time it
was read. The counts are what make the check non-circular. Comparing the filter
list to a copy of itself proves nothing; comparing it to a recorded measurement
means adding a value without verifying it fails loudly.

Two directions are checked, and they are deliberately asymmetric:

    every value we filter on must exist upstream
        or the filter silently contributes nothing

    every collision severity upstream must be known to us
        because a new severity category appearing means the totals this agent
        publishes have quietly stopped meaning what they say

The 311 allow list is not checked in that second direction. It is partial on
purpose: graffiti and noise complaints say nothing about whether a crossing is
safe, so upstream having categories we ignore is the design, not drift.
"""

from __future__ import annotations

from typing import Any

import httpx

from .datasf import BASE, DS_311, DS_CRASHES, KNOWN_SEVERITY_VALUES, SERVICE_NAMES, SEVERE_VALUES

# Read off the live API on 2026-08-20 with:
#
#   curl -sG https://data.sfgov.org/resource/ubvf-ztfx.json \
#     --data-urlencode '$select=collision_severity,count(*)' \
#     --data-urlencode '$group=collision_severity'
#
# The counts are evidence, not decoration. They are what stops this file from
# being a copy of the filter list checked against itself.
PINNED_AT = "2026-08-20"

PINNED_SEVERITY: dict[str, int] = {
    "Fatal": 622,
    "Injury (Complaint of Pain)": 41829,
    "Injury (Other Visible)": 18715,
    "Injury (Severe)": 4638,
}

# Same date, same method, against vw6y-z8j6 grouped by service_name. Only the
# nine this agent filters on are pinned; the dataset carries hundreds more.
PINNED_SERVICE_NAMES: dict[str, int] = {
    "Street Defects": 99858,
    "Street Defect": 20395,
    "Sign Repair": 99661,
    "Streetlights": 99048,
    "Sidewalk or Curb": 86623,
    "Sidewalk and Curb": 30945,
    "Blocked Street or SideWalk": 44067,
    "Blocked Street and Sidewalk": 31827,
    "Color Curb": 15487,
}


class VocabularyDrift(RuntimeError):
    """An enumerated value this agent filters on no longer means what it did.

    Raised rather than logged. A filter that matches nothing produces a number,
    and a number that is wrong is worse than a run that stopped.
    """


def check_against_pinned() -> list[str]:
    """Offline. Are the filter constants consistent with the recorded evidence?

    This is the check that runs on every cycle. It costs nothing and it catches
    the specific mistake that caused the original bug: somebody editing a tuple
    of category names from memory.
    """
    problems: list[str] = []

    for value in SEVERE_VALUES:
        if value not in PINNED_SEVERITY:
            problems.append(
                f"severity filter names {value!r}, which is not in the vocabulary recorded on "
                f"{PINNED_AT}. Either it is a guess, or the pinned evidence is stale. Run "
                f"`watchdog doctor` to read the live values before changing this."
            )

    for value in KNOWN_SEVERITY_VALUES:
        if value not in PINNED_SEVERITY:
            problems.append(
                f"KNOWN_SEVERITY_VALUES lists {value!r}, which the pinned evidence does not have"
            )

    for value in SERVICE_NAMES:
        if value not in PINNED_SERVICE_NAMES:
            problems.append(
                f"the 311 allow list names {value!r}, which is not in the vocabulary recorded on "
                f"{PINNED_AT}. An entry that matches nothing contributes a silent zero."
            )

    if not SEVERE_VALUES:
        problems.append("the severity filter is empty, which builds `in()` and matches nothing")

    return problems


def assert_pinned() -> None:
    """Fail the run rather than produce numbers from an unverified filter."""
    problems = check_against_pinned()
    if problems:
        raise VocabularyDrift(
            "the query vocabulary does not match the recorded evidence:\n  "
            + "\n  ".join(problems)
        )


async def fetch_live(client: httpx.AsyncClient | None = None) -> dict[str, dict[str, int]]:
    """The distinct values upstream carries right now, with their row counts."""
    owns = client is None
    client = client or httpx.AsyncClient()
    out: dict[str, dict[str, int]] = {}
    try:
        for label, dataset, field in (
            ("collision_severity", DS_CRASHES, "collision_severity"),
            ("service_name", DS_311, "service_name"),
        ):
            r = await client.get(
                f"{BASE}/{dataset}.json",
                params={"$select": f"{field},count(*)", "$group": field, "$limit": "500"},
                timeout=60.0,
            )
            r.raise_for_status()
            rows = r.json() or []
            out[label] = {
                row[field]: int(float(row["count"]))
                for row in rows
                if isinstance(row, dict) and row.get(field) is not None and "count" in row
            }
    finally:
        if owns:
            await client.aclose()
    return out


def check_against_live(live: dict[str, dict[str, int]]) -> list[str]:
    """Online. What the pinned evidence gets wrong about the world today."""
    problems: list[str] = []
    severity = live.get("collision_severity") or {}
    services = live.get("service_name") or {}

    if not severity:
        problems.append("the live severity vocabulary came back empty, so nothing could be checked")
    else:
        for value in SEVERE_VALUES:
            if value not in severity:
                problems.append(
                    f"severity filter names {value!r}, which DataSF no longer has. Every severe "
                    f"count this agent produces is currently zero and wrong."
                )
        # The direction that catches a category being added rather than renamed.
        for value in sorted(set(severity) - set(KNOWN_SEVERITY_VALUES)):
            problems.append(
                f"DataSF now carries a collision severity this agent has never heard of: "
                f"{value!r} ({severity[value]} rows). Totals may have stopped meaning what they say."
            )

    if not services:
        problems.append("the live 311 vocabulary came back empty, so nothing could be checked")
    else:
        for value in SERVICE_NAMES:
            if value not in services:
                problems.append(
                    f"the 311 allow list names {value!r}, which DataSF no longer has. That entry "
                    f"contributes a silent zero to every corner."
                )

    return problems


def summarise_live(live: dict[str, dict[str, int]]) -> list[str]:
    """Readable lines for the doctor's report."""
    lines: list[str] = []
    severity = live.get("collision_severity") or {}
    services = live.get("service_name") or {}
    lines.append(f"collision_severity: {len(severity)} distinct values upstream")
    for value, count in sorted(severity.items(), key=lambda kv: -kv[1]):
        mark = "filtered" if value in SEVERE_VALUES else "known" if value in KNOWN_SEVERITY_VALUES else "NEW"
        lines.append(f"  {count:>7}  {value:<30} {mark}")
    matched = sum(1 for s in SERVICE_NAMES if s in services)
    lines.append(f"311 allow list: {matched} of {len(SERVICE_NAMES)} entries match a live service name")
    return lines


def pinned_evidence() -> dict[str, Any]:
    return {
        "pinned_at": PINNED_AT,
        "collision_severity": dict(PINNED_SEVERITY),
        "service_name": dict(PINNED_SERVICE_NAMES),
    }
