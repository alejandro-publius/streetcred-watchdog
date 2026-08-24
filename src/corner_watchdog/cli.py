"""One command, the whole loop.

    python -m corner_watchdog run --cycles 2

Fetches the watched set if it is missing, then for each cycle: reads the city's
current record for every watched corner, diffs it against the stored snapshot,
triages, deliberates on whatever was escalated, acts into a local outbox in dry
run, journals every evaluation including the declines, and renders the ledger.

No Google project, no service account, no emulator, no keys. The two networks it
touches are San Francisco's open data portal and StreetCred's public scoreboard,
both unauthenticated reads.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from . import doctor as doctor_mod
from . import inject as inject_mod
from . import ledger as ledger_mod
from . import roster as roster_mod
from . import schedule as schedule_mod
from . import watched as watched_mod
from .rehearsal import rehearse
from .runner import run_cycle


def _p(msg: str = "") -> None:
    print(msg, flush=True)


async def _ensure_watched(path: Path, count: int, origin: str) -> list[dict[str, Any]]:
    """Load the pinned watched set, or fetch one if there is none.

    Deliberately never refreshes an existing roster. A roster that refetched
    itself between runs would mean yesterday's baselines belong to a different
    set of corners than today's, with nothing saying so. Refreshing is an
    explicit act: `watchdog watched`.
    """
    if path.exists():
        doc = watched_mod.load_doc(path)
        corners = doc.get("corners") or []
        if corners:
            problem = watched_mod.verify(doc)
            _p(
                f"  watched set: {len(corners)} corners from {path}, "
                f"roster {doc.get('roster_hash', 'unhashed')}"
            )
            if problem:
                _p(f"  WARNING: {problem}")
            return corners
    _p(f"  watched set missing, fetching the worst {count} from StreetCred's public scoreboard")
    doc = await watched_mod.fetch_worst(count, origin=origin)
    watched_mod.save(doc, path)
    _p(f"  wrote {doc['count']} corners to {path}, roster {doc['roster_hash']}")
    return doc["corners"]


def _print_report(report, index: int, total: int) -> None:
    s, a = report.sweep, report.actor
    _p(f"  looked at {s.looked_at}, escalated {s.escalated}, declined at triage {s.declined}")
    if s.first_sightings:
        _p(f"  {s.first_sightings} first sighting(s): no baseline yet, nothing to compare")
    if s.unreliable:
        _p(f"  {s.unreliable} comparison(s) refused as unreliable")
    if s.incomplete_fetches:
        _p(f"  baseline kept untouched for: {', '.join(s.incomplete_fetches)}")
    if s.roster_drops:
        _p(f"  no longer watching, journaled: {', '.join(s.roster_drops)}")
    _p(f"  deliberated on {a.deliberated}, acted on {a.acted}, declined after deliberation {a.declined}")
    if a.actions_taken:
        _p(f"  actions: {', '.join(a.actions_taken)}")
    if a.intents:
        _p(f"  budget refused: {'; '.join(a.intents)}")
    if a.artefacts:
        _p(f"  wrote {len(a.artefacts)} dry-run artefact(s) to the outbox")
    _p(f"  cycle {index}/{total} done at {report.finished}")


async def _cmd_run(args: argparse.Namespace) -> int:
    """The hand-started loop. Takes the same lock the scheduler does.

    It did not, until an audit read the FAQ's claim that a scheduled run can
    never overlap with one started by hand and checked it. Only `tick` took the
    lock, so the promise held in exactly one direction and the interesting
    collision, somebody running this while the six-hourly job was mid-sweep, was
    the one it did not cover.
    """
    try:
        with schedule_mod.cycle_lock(args.state):
            return await _run_cycles(args)
    except schedule_mod.CycleAlreadyRunning as e:
        _p(f"Refusing to start: {e}.")
        _p("Two cycles at once would interleave writes to the same snapshots and journal.")
        return 4


async def _run_cycles(args: argparse.Namespace) -> int:
    _p("The Corner Watchdog, local loop.")

    injection = None
    state_dir = args.state
    if args.inject:
        injection = inject_mod.build(args.inject)
        # Injected runs write somewhere else on purpose, so a rehearsed failure
        # can never end up in the journal that gets submitted.
        state_dir = args.inject_state
        _p("")
        _p(f"  INJECTING FAILURE: {args.inject}")
        _p(f"  {injection.what_it_shows}")
        _p(f"  writing to {state_dir}, not {args.state}, so the real journal stays real")
        _p("  every entry this run writes will say it was injected")

    corners = await _ensure_watched(Path(args.watched), args.count, args.origin)

    reports = []
    for i in range(1, args.cycles + 1):
        _p("")
        _p(f"cycle {i} of {args.cycles}")
        report = await run_cycle(
            corners,
            state_dir=state_dir,
            outbox_dir=args.outbox,
            run_id=f"cycle-{i}",
            trigger="manual",
            fetcher=injection.fetcher if injection else None,
            action_budget=injection.action_budget if injection else None,
            token_budget=injection.token_budget if injection else None,
            extra_degradation=injection.note if injection else None,
        )
        if i == 1:
            _p("  wiring:")
            for k, v in report.wiring.items():
                _p(f"    {k:14} {v}")
            if report.degraded:
                _p(f"  degraded: {report.degraded}")
        _print_report(report, i, args.cycles)
        reports.append(report.as_dict())

    runs_path = Path(state_dir) / "runs.json"
    runs_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if runs_path.exists():
        try:
            existing = json.loads(runs_path.read_text())
        except json.JSONDecodeError:
            existing = []
    runs_path.write_text(json.dumps(existing + reports, indent=2))

    if not args.no_ledger:
        out = ledger_mod.render_to_file(
            state_dir=state_dir, out_path=args.ledger,
            rehearsal_dir=args.rehearsal_state, watched_path=args.watched,
        )
        _p("")
        _p(f"ledger written to {out}")
    return 0


async def _cmd_watched(args: argparse.Namespace) -> int:
    path = Path(args.watched)
    fresh = await watched_mod.fetch_worst(args.count, origin=args.origin)

    existing = watched_mod.load_doc(path) if path.exists() else None
    if existing:
        d = roster_mod.drift(
            [c["slug"] for c in existing.get("corners") or []],
            [c["slug"] for c in fresh["corners"]],
        )
        _p(f"pinned roster:  {existing.get('roster_hash', 'unhashed')} from {existing.get('fetched_at')}")
        _p(f"scoreboard now: {fresh['roster_hash']}")
        for line in roster_mod.describe(d):
            _p(line)
        if d["membership_changed"] and not args.accept_drift:
            _p("")
            _p("Refusing to overwrite the pinned watched set.")
            _p("Every stored baseline belongs to the roster that produced it, so replacing")
            _p("the roster silently would leave yesterday's snapshots describing a different")
            _p("set of corners than today's. Re-run with --accept-drift to take the new one.")
            _p("Corners that leave the roster are journaled on the next cycle rather than")
            _p("simply disappearing.")
            return 3

    watched_mod.save(fresh, path)
    _p(f"wrote {fresh['count']} corners to {path}, roster {fresh['roster_hash']}")
    _p(f"source: {fresh['source']}")
    for c in fresh["corners"]:
        _p(f"  {c['scoreboard_rank']:>2}. {c['points']:>6}  {c['grade']}  {c['name']}")
    if fresh["dropped_for_missing_coordinates"]:
        _p(f"dropped for missing coordinates: {fresh['dropped_for_missing_coordinates']}")
    return 0


async def _cmd_rehearse(args: argparse.Namespace) -> int:
    injection = inject_mod.build(args.inject) if args.inject else None
    if injection:
        _p(f"INJECTING FAILURE: {args.inject}, {injection.what_it_shows}")
        _p("")
    return await rehearse(
        state_dir=args.state,
        rehearsal_dir=args.rehearsal_state,
        outbox_dir=args.outbox,
        printer=_p,
        injection=injection,
    )


async def _cmd_tick(args: argparse.Namespace) -> int:
    """One cycle, safe to run from launchd or cron.

    Differs from `run` in exactly two ways that matter to a scheduler: it takes
    the cycle lock so it can never overlap with another run, and it is terse
    enough that a log file of these is readable.
    """
    try:
        with schedule_mod.cycle_lock(args.state):
            corners = await _ensure_watched(Path(args.watched), args.count, args.origin)
            report = await run_cycle(
                corners,
                state_dir=args.state,
                outbox_dir=args.outbox,
                run_id=f"tick-{report_stamp()}",
                trigger="cron",
            )
            s, a = report.sweep, report.actor
            _p(
                f"{report.finished} looked at {s.looked_at}, escalated {s.escalated}, "
                f"declined {s.declined}, acted {a.acted}, artefacts {len(a.artefacts)}"
            )
            if s.roster_drops:
                _p(f"{report.finished} no longer watching: {', '.join(s.roster_drops)}")
            ledger_mod.render_to_file(
                state_dir=args.state, out_path=args.ledger,
                rehearsal_dir=args.rehearsal_state, watched_path=args.watched,
            )
        return 0
    except schedule_mod.CycleAlreadyRunning as e:
        # Not a failure. The scheduler fired while a cycle was still going, which
        # is the case the lock exists for.
        _p(f"skipped, {e}")
        return 4


def report_stamp() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")


async def _cmd_schedule(args: argparse.Namespace) -> int:
    repo = Path.cwd()
    python = schedule_mod.default_python()
    out = Path(args.schedule_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(schedule_mod.plist(repo=repo, python=python, hour_interval=args.every_hours))

    _p(f"wrote {out}")
    _p("")
    _p("crontab line:")
    _p(f"  {schedule_mod.crontab_line(repo=repo, python=python, hour_interval=args.every_hours)}")
    _p("")
    for line in schedule_mod.install_instructions(plist_path=out):
        _p(line)

    held = schedule_mod.read_lock(args.state)
    if held:
        _p("")
        _p(f"note: a cycle lock is currently held: {held}")
    return 0


async def _cmd_doctor(args: argparse.Namespace) -> int:
    _p("The Corner Watchdog, checking what has to be true before a cycle is worth running.")
    _p("")
    checks = await doctor_mod.run_checks(
        state_dir=args.state, watched_path=args.watched,
        origin=args.origin, offline=args.offline,
    )
    return doctor_mod.render(checks, printer=_p)


async def _cmd_ledger(args: argparse.Namespace) -> int:
    if args.corner:
        out = ledger_mod.render_corner_to_file(
            args.corner, state_dir=args.state, watched_path=args.watched
        )
        entries = ledger_mod.corner_history(
            ledger_mod.LocalJsonStore(args.state).read_journal(), args.corner
        )
        _p(f"corner history written to {out} ({len(entries)} entries)")
        if not entries:
            _p("that corner has no journal entries, which means it has never been evaluated,")
            _p("not that it is fine")
        return 0

    out = ledger_mod.render_to_file(
        state_dir=args.state, out_path=args.ledger,
        rehearsal_dir=args.rehearsal_state, watched_path=args.watched,
    )
    _p(f"ledger written to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="watchdog", description=__doc__)
    p.add_argument("--state", default="state", help="local stand-in for Firestore")
    p.add_argument("--rehearsal-state", default="state-rehearsal", help="where rehearsal entries live")
    p.add_argument("--inject-state", default="state-injected", help="where injected-failure runs write")
    p.add_argument("--outbox", default="outbox", help="where dry-run artefacts are written")
    p.add_argument("--watched", default="data/watched.json")
    p.add_argument("--ledger", default="docs/ledger.html")
    p.add_argument("--origin", default=watched_mod.DEFAULT_ORIGIN)
    p.add_argument("--count", type=int, default=watched_mod.WATCHED_COUNT)

    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="the whole loop: observe, diff, triage, decide, act dry, journal")
    run.add_argument("--cycles", type=int, default=1)
    run.add_argument(
        "--inject",
        choices=sorted(inject_mod.available()),
        help="break something on purpose to show the degradation path, into --inject-state",
    )
    run.add_argument("--no-ledger", action="store_true", help="skip rendering the ledger at the end")
    run.add_argument(
        "--live",
        action="store_true",
        help="refused: the live path is a stub and posts nothing",
    )
    run.set_defaults(fn=_cmd_run)

    w = sub.add_parser("watched", help="refetch the worst corners from StreetCred's public scoreboard")
    w.add_argument(
        "--accept-drift",
        action="store_true",
        help="overwrite the pinned roster even though its membership changed",
    )
    w.set_defaults(fn=_cmd_watched)

    r = sub.add_parser(
        "rehearse",
        help="exercise the action path offline against a constructed baseline, kept out of the real journal",
    )
    r.add_argument(
        "--inject",
        choices=sorted(inject_mod.available()),
        help="break something on purpose while exercising the action path",
    )
    r.set_defaults(fn=_cmd_rehearse)

    t = sub.add_parser("tick", help="one cycle under the lock, safe for launchd or cron")
    t.set_defaults(fn=_cmd_tick)

    sc = sub.add_parser(
        "schedule", help="render the launchd and cron configuration, install nothing"
    )
    sc.add_argument("--every-hours", type=int, default=6)
    sc.add_argument("--schedule-out", default="ops/dev.watchdog.cycle.plist")
    sc.set_defaults(fn=_cmd_schedule)

    d = sub.add_parser("doctor", help="check environment, sources, vocabulary and stored state")
    d.add_argument("--offline", action="store_true", help="skip the checks that need network")
    d.set_defaults(fn=_cmd_doctor)

    lg = sub.add_parser("ledger", help="re-render the ledger from the journal on disk")
    lg.add_argument(
        "--corner",
        help="render one corner's full history instead, oldest first, to docs/corners/<slug>.html",
    )
    lg.set_defaults(fn=_cmd_ledger)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "live", False):
        _p("Refusing --live.")
        _p("")
        _p("The live path is a stub. Nothing in this build posts to StreetCred, and the flag exists")
        _p("so that asking for the live path gets a clear refusal rather than a silent dry run that")
        _p("everyone later remembers as having been live. What is missing before it can be honoured:")
        _p("  1. WATCHDOG_INGEST_TOKEN, matched by the same secret on StreetCred's Worker")
        _p("  2. StreetCred's /api/agent/report deployed and verifying the agent's arithmetic")
        _p("  3. a human reading a full outbox from a dry run first and agreeing with every letter")
        return 2
    return asyncio.run(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
