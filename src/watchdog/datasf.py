"""DataSF reads, deliberately identical to the ones StreetCred deploys.

The two systems publish numbers about the same corner on the same page, so if
they disagree about a count, one of them is lying and a reader cannot tell
which. Every query shape here is copied from streetcred/src/index.js getStats
and the constants are copied from streetcred/src/data.js. When those change,
this file has to change with them, and the test suite pins the shapes so the
drift is loud.

Two traps worth naming, both learned the expensive way in the other repo:

  1. The collision dataset returns counts as "11" and the 311 dataset returns
     "9.00000". Everything is parsed through int(float(...)) for that reason.
  2. A major street is often a district boundary. Within 150m of 6th and
     Market, DataSF holds 242 collision rows in District 6 and 114 in District
     5, so taking a single arbitrary row picks the wrong Supervisor. The
     district is decided by grouped majority, and the corner's configured
     district wins over it when there is one.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import httpx

from .schema import Counts, Snapshot

DS_CRASHES = "ubvf-ztfx"
DS_311 = "vw6y-z8j6"
BASE = "https://data.sfgov.org/resource"

# Copied verbatim from streetcred/src/data.js. DataSF carries case and wording
# variants of the same category, so this is an explicit allow list rather than a
# pattern match. Without it a corner's 311 count includes graffiti and noise
# complaints, which say nothing about whether a crossing is safe.
SERVICE_NAMES = [
    "Street Defects",
    "Street Defect",
    "Sign Repair",
    "Streetlights",
    "Sidewalk or Curb",
    "Sidewalk and Curb",
    "Blocked Street or SideWalk",
    "Blocked Street and Sidewalk",
    "Color Curb",
]

# Measured, not assumed. On 2026-08-19 the counts StreetCred publishes on its
# scoreboard were reproduced exactly, in all four collision severity categories,
# for six of six corners, by querying DataSF at 80 metres over five years.
# 150 metres does not reproduce them and is not close.
#
#   corner              published f/s/ov/p    datasf 80m 5y
#   6th-and-mission     0/9/15/38             0/9/15/38
#   6th-and-stevenson   1/6/14/37             1/6/14/37
#   6th-and-jessie      0/7/13/39             0/7/13/39
#   larkin-and-myrtle   0/5/15/30             0/5/15/30
#   6th-and-minna       0/5/10/36             0/5/10/36
#   4th-and-ellis       1/6/16/12             1/6/16/12
#
# The repo previously used 150 on the strength of a reading of StreetCred's
# source rather than a measurement of its output, and asserted in the README
# that 80 was a different query for a different purpose. That was wrong. The
# governing rule is that the two systems must never disagree about a number, so
# the number that reproduces StreetCred's published figures wins.
DEFAULT_RADIUS_M = 80

COLLISION_YEARS = 5

# StreetCred's scoreboard 311 figure could not be reproduced exactly at any
# window tried on 2026-08-19. At 80 metres it lands within one or two records of
# the published number at roughly 365 days and is not exact at 330, 350, 360,
# 365, 370, 380 or 400 days across four corners. The residual is unexplained.
#
# So this stays at three years, which is the agent's own window, deliberately
# longer than the scoreboard's and stated as such everywhere it is printed. Two
# numbers that are openly different quantities are honest; two numbers that
# claim to be the same thing and differ are the failure this repo is about.
REPORTS_YEARS = 3

# Every value collision_severity actually takes in ubvf-ztfx, read off the
# dataset itself on 2026-08-19 with:
#
#   curl -sG https://data.sfgov.org/resource/ubvf-ztfx.json \
#     --data-urlencode '$select=collision_severity,count(*)' \
#     --data-urlencode '$group=collision_severity'
#
# Written down because guessing at it is what went wrong. This list is not used
# to build a query; it exists so a test can assert that the filter below only
# ever names categories the dataset has.
KNOWN_SEVERITY_VALUES = (
    "Fatal",
    "Injury (Severe)",
    "Injury (Other Visible)",
    "Injury (Complaint of Pain)",
)

# Severity values that count as severe. StreetCred's score weights these
# separately from visible injuries; the agent needs them because a new severe
# injury is a rule-level escalation.
#
# This constant was wrong from the first commit until 2026-08-19. It read
# ("Severe Injury", "Suspected Serious Injury"), which are the CHP SWITRS names
# for these categories and are not what DataSF publishes. Nothing failed. The
# query was valid, matched no rows, and returned a clean zero for every corner
# on every sweep, which made "any new severe injury is significant by rule" a
# rule that could never fire. A guessed string literal in a WHERE clause is the
# purest form of the failure this repo is written against: no error, a number,
# and the number is false.
SEVERE_VALUES = ("Injury (Severe)",)


def query_fingerprint(radius_m: int) -> str:
    """Everything about the question that, if changed, changes the answer.

    Stamped onto every snapshot. Two snapshots taken under different questions
    cannot be subtracted from each other, and the difference between them is not
    news about a street corner, it is news about this repo. Without this the day
    the radius moved from 150 to 80 would have arrived in the journal as a forty
    percent collapse in collisions at all twenty five corners on the same
    morning, with reasoning attached, and nothing would have flagged it.

    Deliberately human readable rather than a hash, because the journal entry
    that refuses a comparison prints it, and "r=150m" tells a reader what
    happened where "a3f19c" does not.
    """
    severe = "+".join(sorted(SEVERE_VALUES))
    return (
        f"r={radius_m}m;collisions={COLLISION_YEARS}y;reports={REPORTS_YEARS}y;"
        f"severe={severe};services={len(SERVICE_NAMES)}"
    )


def _iso_years_ago(years: int, now: _dt.datetime | None = None) -> str:
    """The start of a window, always computed in UTC.

    UTC on purpose, and injectable on purpose. A window anchored to local time
    moves by an hour twice a year when Pacific daylight saving shifts, so two
    sweeps either side of the transition would be asking different questions
    while claiming to ask the same one, and the difference would arrive in the
    journal as news about a street corner.

    365 days per year rather than calendar arithmetic, which means the window
    slides by roughly a day every four years. That is deliberate and harmless
    here because both sides of any comparison use the same rule, and it is
    recorded in the query fingerprint if it ever changes.
    """
    now = now or _dt.datetime.now(_dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.UTC)
    return (now.astimezone(_dt.UTC) - _dt.timedelta(days=365 * years)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


def _as_int(v: Any) -> int:
    """DataSF returns integers as "11" from one dataset and "9.00000" from another."""
    try:
        return int(float(v))
    except (TypeError, ValueError, OverflowError):
        return 0


# The two aggregate shapes behave differently on an empty result set, verified
# against the live API on 2026-08-20:
#
#   count(*)            over nothing -> [{"count":"0"}]     the key is always there
#   sum(number_killed)  over nothing -> [{}]                the key is absent
#
# That difference is the whole reason these are two functions. Treating a missing
# count key as zero would turn a renamed alias into a clean zero on every corner
# forever, which is the SEVERE_VALUES failure with a different mask on. Treating
# a missing sum key as an anomaly would mark every genuinely safe corner
# incomplete. Both mistakes are silent, so both are pinned by tests.


def _count_value(rows: Any) -> tuple[int, bool]:
    """Read a count(*) response. Second element is False when it made no sense."""
    if not isinstance(rows, list) or not rows:
        return 0, False
    first = rows[0]
    if not isinstance(first, dict) or "count" not in first:
        return 0, False
    return _as_int(first["count"]), True


def _sum_value(rows: Any, key: str) -> tuple[int, bool]:
    """Read a sum() response. An absent key is zero; an absent row is not."""
    if not isinstance(rows, list) or not rows:
        return 0, False
    first = rows[0]
    if not isinstance(first, dict):
        return 0, False
    return _as_int(first.get(key)), True


async def _soql(client: httpx.AsyncClient, dataset: str, params: dict[str, str]) -> list[dict]:
    r = await client.get(f"{BASE}/{dataset}.json", params=params, timeout=30.0)
    r.raise_for_status()
    return r.json()


async def fetch_corner_records(
    slug: str,
    name: str,
    lat: float,
    lon: float,
    *,
    radius_m: int = DEFAULT_RADIUS_M,
    configured_district: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> Snapshot:
    """One corner's bounded record, in the shape the delta engine compares.

    Never raises on a partial failure. A lane that fails marks the snapshot
    incomplete, which the delta engine then refuses to compare, because a
    timeout that returns zero rows looks exactly like a corner with no
    collisions.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient()
    circle = f"within_circle(point, {lat}, {lon}, {radius_m})"
    crash_since = _iso_years_ago(COLLISION_YEARS)
    reports_since = _iso_years_ago(REPORTS_YEARS)
    crash_where = f"{circle} AND collision_datetime > '{crash_since}'"
    services = ",".join(f"'{s}'" for s in SERVICE_NAMES)
    severe_in = ",".join(f"'{s}'" for s in SEVERE_VALUES)

    complete = True
    collisions = fatal = severe = reports = 0
    district_rows: list[dict] = []

    async def _try(coro: Any, label: str) -> Any:
        """Await one lane. A failure marks the whole snapshot partial, never raises.

        `label` is unused and kept deliberately: it names the lane at the call
        site, which is the only place a reader can tell the five near-identical
        SoQL calls apart.
        """
        nonlocal complete
        try:
            return await coro
        except Exception:  # noqa: BLE001 - any lane failure marks the snapshot partial
            complete = False
            return None

    try:
        c_rows = await _try(
            _soql(client, DS_CRASHES, {"$select": "count(*)", "$where": crash_where}), "collisions"
        )
        f_rows = await _try(
            _soql(client, DS_CRASHES, {"$select": "sum(number_killed)", "$where": crash_where}), "fatal"
        )
        s_rows = await _try(
            _soql(
                client,
                DS_CRASHES,
                {"$select": "count(*)", "$where": f"{crash_where} AND collision_severity in({severe_in})"},
            ),
            "severe",
        )
        r_rows = await _try(
            _soql(
                client,
                DS_311,
                {
                    "$select": "count(*)",
                    "$where": (
                        f"{circle} AND requested_datetime > '{reports_since}' "
                        f"AND service_name in({services})"
                    ),
                },
            ),
            "reports",
        )
        d_rows = await _try(
            _soql(
                client,
                DS_CRASHES,
                {
                    "$select": "supervisor_district,count(*)",
                    "$where": circle,
                    "$group": "supervisor_district",
                },
            ),
            "district",
        )
    finally:
        if owns_client:
            await client.aclose()

    collisions, ok = _count_value(c_rows)
    complete = complete and ok
    severe, ok = _count_value(s_rows)
    complete = complete and ok
    reports, ok = _count_value(r_rows)
    complete = complete and ok
    fatal, ok = _sum_value(f_rows, "sum_number_killed")
    complete = complete and ok

    district_rows = d_rows if isinstance(d_rows, list) else []

    # Grouped majority, then the corner's configured district wins if it has one.
    # Ties break to the lower district number rather than to whatever order the
    # API happened to return, so the same data always produces the same answer.
    # A district that flips between sweeps because two groups are tied would be
    # journaled as a real district change, which it is not.
    majority: int | None = None
    ranked = sorted(
        (
            (_as_int(row.get("supervisor_district")), _as_int(row.get("count")))
            for row in district_rows
            if isinstance(row, dict)
        ),
        key=lambda t: (-t[1], t[0]),
    )
    for d, _n in ranked:
        if d > 0:
            majority = d
            break
    district = configured_district if configured_district else majority

    return Snapshot(
        slug=slug,
        name=name,
        counts=Counts(
            collisions_5y=collisions,
            fatal_5y=fatal,
            severe_5y=severe,
            reports_311_3y=reports,
            district=district,
        ),
        fetched_at=_dt.datetime.now(_dt.UTC).isoformat(),
        complete=complete,
        query_fingerprint=query_fingerprint(radius_m),
    )


async def seed_from_streetcred(origin: str, client: httpx.AsyncClient | None = None) -> list[dict]:
    """The warmed fleet and its geometry, read from StreetCred's public API.

    Used once, to give the first sweep a baseline to diff against. Diffing
    against emptiness would report every corner as brand new and spend the whole
    budget on a baseline.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient()
    try:
        r = await client.get(f"{origin}/api/board", timeout=30.0)
        r.raise_for_status()
        return (r.json() or {}).get("corners", [])
    finally:
        if owns_client:
            await client.aclose()
