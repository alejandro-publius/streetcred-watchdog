"""Everything that has to be true before a cycle is worth running.

Written after three separate bugs that all had the same shape: the code ran, a
number came out, and the number was false. `SEVERE_VALUES` matched nothing for a
fortnight. A renamed count alias parsed as a clean zero. A radius read from source
rather than measured disagreed with the page it was published beside. None of
them raised. All three would have been caught by asking, out loud, before the
sweep, whether the things this agent assumes are still true.

So this asks. It is the first thing to run when something looks wrong, and the
first thing to show anybody who wants to know whether to believe the output.

Three statuses and they mean different things:

    pass   checked, and it is as expected
    warn   checked, and it is not as expected, but the loop is still honest
    fail   checked, and running a cycle would produce numbers worth nothing

A degraded tier is a `warn`, not a `fail`, because the loop handles it correctly
and says so on every entry. A drifted query vocabulary is a `fail`, because
nothing downstream can tell that the numbers are wrong.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import vocabulary
from .brains import vertex_is_configured
from .datasf import BASE, DS_311, DS_CRASHES, query_fingerprint
from .schedule import read_lock
from .schema import MalformedSnapshot, Snapshot
from .store import LocalJsonStore
from .watched import verify as verify_roster

PASS, WARN, FAIL = "pass", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str


def _env_checks() -> list[Check]:
    out = [
        Check(
            "python",
            PASS if sys.version_info >= (3, 11) else FAIL,
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}, "
            "3.11 or newer required",
        )
    ]

    ok, why = vertex_is_configured()
    out.append(
        Check(
            "vertex configuration",
            WARN if not ok else PASS,
            f"{why}. Both tiers will run as deterministic stand-ins, and every journal "
            "entry will say so." if not ok else "present",
        )
    )

    budget = os.environ.get("DAILY_ACTION_BUDGET", "40 (default)")
    tokens = os.environ.get("DAILY_TOKEN_BUDGET", "unset, no token ceiling")
    out.append(Check("action budget", PASS, str(budget)))
    out.append(Check("token budget", PASS, str(tokens)))

    # Present is fine; committed would not be. The gitignore is the real guard and
    # is tested elsewhere, but an operator running this wants to see it stated.
    out.append(
        Check(
            "credentials",
            PASS,
            ".env present and gitignored" if Path(".env").exists() else ".env absent",
        )
    )
    return out


def _roster_checks(watched_path: Path) -> list[Check]:
    if not watched_path.exists():
        return [Check("watched set", WARN, f"{watched_path} missing, a run will fetch one")]
    try:
        doc = json.loads(watched_path.read_text())
    except json.JSONDecodeError as e:
        return [Check("watched set", FAIL, f"{watched_path} is not readable JSON: {e}")]

    corners = doc.get("corners") or []
    out = [Check("watched set", PASS if corners else FAIL, f"{len(corners)} corners")]

    problem = verify_roster(doc)
    out.append(
        Check("roster hash", WARN if problem else PASS, problem or f"{doc.get('roster_hash')} intact")
    )

    missing = [c.get("slug") for c in corners if not (c.get("lat") and c.get("lon"))]
    out.append(
        Check(
            "corner geometry",
            FAIL if missing else PASS,
            f"{len(missing)} corners without coordinates: {missing}" if missing
            else "every corner has coordinates",
        )
    )

    radii = {c.get("radiusMeters") for c in corners}
    out.append(
        Check(
            "query radius",
            PASS if len(radii) <= 1 else WARN,
            f"{radii.pop() if len(radii) == 1 else sorted(r for r in radii if r)} metres",
        )
    )
    return out


def publish_log_source(state_dir: Path, reader=None) -> tuple[list, str]:
    """The publish log, from wherever it actually lives, and where that was.

    The deployed services write their receipts to Firestore and a laptop writes
    them to a file. A check that only ever read the file reported "no publish
    attempts recorded yet" on a machine whose whole job is running that check,
    while 24 decisions had been published from Cloud Run an hour earlier. That
    is not a wrong answer to the question, it is a right answer to a different
    one, which is the harder kind to notice.

    Firestore first when a project is configured, because that is where the
    deployed agent writes and the deployed agent is the one whose state anybody
    asking this question cares about. The file is the fallback and the source is
    always named in the answer, so a reader can tell which store was consulted
    rather than having to know.
    """
    if reader is not None:
        return reader()

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if project:
        try:
            from .cloud import FirestoreStore

            store = FirestoreStore()
            return store.read_publish_log(), f"Firestore, {store.database} in {project}"
        except Exception as e:  # noqa: BLE001 - a failed read falls back and says so
            local = LocalJsonStore(state_dir)
            return local.read_publish_log(), (
                f"the local file, because Firestore could not be read: {type(e).__name__}"
            )

    return LocalJsonStore(state_dir).read_publish_log(), f"the local file at {state_dir}"


# How far back this check's pass or fail state looks. Stated in the output on
# every run, because a health check whose window is implicit is one whose green
# nobody can interpret.
PUBLISH_WINDOW_HOURS = 24


def _parse_at(value) -> _dt.datetime | None:
    try:
        parsed = _dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.UTC)


def _publish_checks(
    state_dir: Path, reader=None, now=None, window_hours: int = PUBLISH_WINDOW_HOURS
) -> list[Check]:
    """Decisions that never reached the public diary, judged over a window.

    A failed publish is journaled, so it is already visible to anyone reading
    the journal. It is surfaced here as well because nobody reads a journal
    looking for something they do not know went wrong, and a hole between the
    agent's record and the public one is exactly the kind of quiet disagreement
    this project exists to refuse.

    The window is the part that took a second pass. This check used to fail on
    any dead receipt ever recorded, which meant that after one bad batch on
    2026-08-26 it could never be green again no matter how healthy the agent
    became. A check that can only ever fail is a check people learn to skip, and
    the demo script tells a presenter to run this one on camera.

    So the two questions are separated. **Is it publishing now** is answered over
    the last `window_hours` and decides pass or fail. **Has it ever failed to
    publish** is answered over the whole log and is always reported, with the
    count and the date, whether or not it is inside the window. Nothing is
    deleted and nothing is forgiven by age: an old failure stays on the page as
    an old failure, which is a different claim from a current one and needs to
    read differently.

    A receipt with no readable timestamp counts as recent. Erring the other way
    would let an unparseable date hide a live failure, and the whole point of
    the window is that it never does that.
    """
    log, source = publish_log_source(state_dir, reader)
    now = now or _dt.datetime.now(_dt.UTC)
    cutoff = now - _dt.timedelta(hours=window_hours)
    window = f"the last {window_hours} hours"

    if not log:
        return [Check("decisions published", PASS, f"no publish attempts recorded in {source}")]

    def recent(r) -> bool:
        at = _parse_at(r.get("at"))
        return at is None or at >= cutoff

    dead_all = [r for r in log if r.get("status") == "permanently_failed"]
    recent_log = [r for r in log if recent(r)]
    recent_dead = [r for r in recent_log if r.get("status") == "permanently_failed"]
    recent_ok = [r for r in recent_log if r.get("status") in ("published", "duplicate")]

    # Always printed, never used to decide the state. This is the record.
    older_dead = [r for r in dead_all if r not in recent_dead]
    if older_dead:
        days = sorted({str(r.get("at", ""))[:10] for r in older_dead if r.get("at")})
        when = f"{days[0]} to {days[-1]}" if len(days) > 1 else (days[0] if days else "an unrecorded date")
        history = (
            f" Older than {window}: {len(older_dead)} dead receipt(s) on {when}, retained."
        )
    else:
        history = ""

    if not recent_log:
        return [
            Check(
                "decisions published",
                PASS,
                f"no publish attempts in {window}, from {source}.{history}",
            )
        ]

    detail = (
        f"{len(recent_ok)} reached the diary, {len(recent_dead)} did not, "
        f"of {len(recent_log)} attempted in {window}, from {source}"
    )
    if recent_dead:
        why = str(recent_dead[-1].get("why", ""))[:120]
        return [Check("decisions published", FAIL, f"{detail}. Most recent failure: {why}.{history}")]
    return [Check("decisions published", PASS, f"{detail}.{history}")]


def _state_checks(state_dir: Path) -> list[Check]:
    store = LocalJsonStore(state_dir)
    out: list[Check] = []

    files = sorted(store.snapshots_dir.glob("*.json"))
    bad: list[str] = []
    fingerprints: set[str] = set()
    for path in files:
        try:
            snap = Snapshot.from_dict(json.loads(path.read_text()))
            fingerprints.add(snap.query_fingerprint or "not recorded")
        except (json.JSONDecodeError, OSError, MalformedSnapshot) as e:
            bad.append(f"{path.name}: {type(e).__name__}")

    out.append(
        Check(
            "snapshot integrity",
            FAIL if bad else PASS,
            f"{len(bad)} unreadable of {len(files)}: {bad}" if bad
            else f"{len(files)} snapshots readable",
        )
    )

    current = query_fingerprint(80)
    if not fingerprints:
        out.append(Check("query fingerprint", WARN, "no snapshots stored yet"))
    elif fingerprints == {current}:
        out.append(Check("query fingerprint", PASS, f"all snapshots at {current}"))
    else:
        out.append(
            Check(
                "query fingerprint",
                WARN,
                f"{len(fingerprints)} different queries in the store: {sorted(fingerprints)}. "
                "The next sweep will refuse those comparisons and rebuild, which is correct.",
            )
        )

    journal = store.journal_path
    if journal.exists():
        lines = journal.read_text().splitlines()
        torn = sum(1 for line in lines if line.strip() and not _is_json(line))
        out.append(
            Check(
                "journal",
                WARN if torn else PASS,
                f"{len(lines) - torn} entries readable"
                + (f", {torn} torn lines skipped" if torn else ""),
            )
        )
    else:
        out.append(Check("journal", WARN, "empty, no cycle has run yet"))

    held = read_lock(state_dir)
    out.append(
        Check(
            "cycle lock",
            WARN if held else PASS,
            f"held by pid {held.get('pid')} since {held.get('started')}" if held else "free",
        )
    )

    quarantine = state_dir / "quarantine"
    if quarantine.exists() and any(quarantine.iterdir()):
        n = len(list(quarantine.glob("*.json")))
        out.append(Check("quarantine", WARN, f"{n} snapshot(s) quarantined, see quarantine.log"))
    return out


def _is_json(line: str) -> bool:
    try:
        json.loads(line)
        return True
    except json.JSONDecodeError:
        return False


def _vocab_offline() -> list[Check]:
    problems = vocabulary.check_against_pinned()
    return [
        Check(
            "query vocabulary, pinned",
            FAIL if problems else PASS,
            "; ".join(problems) if problems
            else f"filters match the evidence recorded on {vocabulary.PINNED_AT}",
        )
    ]


async def _network_checks(origin: str, client: httpx.AsyncClient | None = None) -> list[Check]:
    """Injectable so the failure paths can be tested without a real outage."""
    out: list[Check] = []
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        for label, url, params in (
            ("DataSF, collisions", f"{BASE}/{DS_CRASHES}.json", {"$select": "count(*)"}),
            ("DataSF, 311", f"{BASE}/{DS_311}.json", {"$select": "count(*)"}),
            ("StreetCred scoreboard", f"{origin}/api/city", {"page": "1"}),
        ):
            try:
                # Timed here rather than read off the response. httpx's own
                # `.elapsed` raises unless the body has been read, and this whole
                # block catches Exception, so a healthy source would have come
                # back as a failure. A doctor that cries wolf is worse than none.
                started = time.perf_counter()
                r = await client.get(url, params=params)
                took = time.perf_counter() - started
                out.append(
                    Check(
                        label,
                        PASS if r.status_code == 200 else FAIL,
                        f"HTTP {r.status_code} in {took:.2f}s",
                    )
                )
            except Exception as e:  # noqa: BLE001 - a source being down is a finding, not a crash
                out.append(Check(label, FAIL, f"{type(e).__name__}: {str(e)[:80]}"))

        try:
            live = await vocabulary.fetch_live(client)
            problems = vocabulary.check_against_live(live)
            out.append(
                Check(
                    "query vocabulary, live",
                    FAIL if problems else PASS,
                    "; ".join(problems) if problems
                    else f"{len(live.get('collision_severity') or {})} severities upstream, "
                    "every filtered value present",
                )
            )
        except Exception as e:  # noqa: BLE001 - the doctor reports failures, never raises them
            out.append(Check("query vocabulary, live", WARN, f"could not check: {type(e).__name__}"))
    finally:
        if owns:
            await client.aclose()
    return out


def _live_path_check() -> list[Check]:
    from .live import BLOCKERS

    return [
        Check(
            "live path",
            PASS,
            f"stub, refuses every verb, {len(BLOCKERS)} blockers named. Nothing posts.",
        )
    ]


async def run_checks(
    *,
    state_dir: str | Path = "state",
    watched_path: str | Path = "data/watched.json",
    origin: str = "https://streetcred.thealexschroeder.workers.dev",
    offline: bool = False,
    client: httpx.AsyncClient | None = None,
) -> list[Check]:
    checks: list[Check] = []
    checks += _env_checks()
    checks += _roster_checks(Path(watched_path))
    checks += _state_checks(Path(state_dir))
    checks += _publish_checks(Path(state_dir))
    checks += _vocab_offline()
    checks += _live_path_check()
    if not offline:
        checks += await _network_checks(origin, client)
    return checks


def render(checks: list[Check], printer=print) -> int:
    """Print the table. Returns the exit code: nonzero when anything failed."""
    width = max(len(c.name) for c in checks) + 2
    marks = {PASS: "pass", WARN: "WARN", FAIL: "FAIL"}
    for c in checks:
        printer(f"  {marks[c.status]:<5} {c.name:<{width}} {c.detail}")

    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    printer("")
    printer(
        f"{len(checks)} checks, {len(checks) - len(failed) - len(warned)} pass, "
        f"{len(warned)} warn, {len(failed)} fail"
    )
    if failed:
        printer("")
        printer("Do not trust a cycle run in this state. What failed:")
        for c in failed:
            printer(f"  {c.name}: {c.detail}")
        return 1
    if warned:
        printer("The warnings above are states the loop handles and journals honestly.")
    return 0
