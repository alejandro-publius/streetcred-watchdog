"""One command, the whole loop.

    python -m watchdog run --cycles 2

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

from . import ledger as ledger_mod
from . import watched as watched_mod
from .rehearsal import rehearse
from .runner import run_cycle


def _p(msg: str = "") -> None:
    print(msg, flush=True)


async def _ensure_watched(path: Path, count: int, origin: str) -> list[dict[str, Any]]:
    if path.exists():
        corners = watched_mod.load(path)
        if corners:
            _p(f"  watched set: {len(corners)} corners from {path}")
            return corners
    _p(f"  watched set missing, fetching the worst {count} from StreetCred's public scoreboard")
    doc = await watched_mod.fetch_worst(count, origin=origin)
    watched_mod.save(doc, path)
    _p(f"  wrote {doc['count']} corners to {path}")
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
    _p(f"  deliberated on {a.deliberated}, acted on {a.acted}, declined after deliberation {a.declined}")
    if a.actions_taken:
        _p(f"  actions: {', '.join(a.actions_taken)}")
    if a.intents:
        _p(f"  budget refused: {'; '.join(a.intents)}")
    if a.artefacts:
        _p(f"  wrote {len(a.artefacts)} dry-run artefact(s) to the outbox")
    _p(f"  cycle {index}/{total} done at {report.finished}")


async def _cmd_run(args: argparse.Namespace) -> int:
    _p("The Corner Watchdog, local loop.")
    corners = await _ensure_watched(Path(args.watched), args.count, args.origin)

    reports = []
    for i in range(1, args.cycles + 1):
        _p("")
        _p(f"cycle {i} of {args.cycles}")
        report = await run_cycle(
            corners,
            state_dir=args.state,
            outbox_dir=args.outbox,
            run_id=f"cycle-{i}",
            trigger="manual",
        )
        if i == 1:
            _p("  wiring:")
            for k, v in report.wiring.items():
                _p(f"    {k:14} {v}")
            if report.degraded:
                _p(f"  degraded: {report.degraded}")
        _print_report(report, i, args.cycles)
        reports.append(report.as_dict())

    runs_path = Path(args.state) / "runs.json"
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
            state_dir=args.state, out_path=args.ledger, rehearsal_dir=args.rehearsal_state
        )
        _p("")
        _p(f"ledger written to {out}")
    return 0


async def _cmd_watched(args: argparse.Namespace) -> int:
    doc = await watched_mod.fetch_worst(args.count, origin=args.origin)
    path = watched_mod.save(doc, args.watched)
    _p(f"wrote {doc['count']} corners to {path}")
    _p(f"source: {doc['source']}")
    for c in doc["corners"]:
        _p(f"  {c['scoreboard_rank']:>2}. {c['points']:>6}  {c['grade']}  {c['name']}")
    if doc["dropped_for_missing_coordinates"]:
        _p(f"dropped for missing coordinates: {doc['dropped_for_missing_coordinates']}")
    return 0


async def _cmd_rehearse(args: argparse.Namespace) -> int:
    return await rehearse(
        state_dir=args.state,
        rehearsal_dir=args.rehearsal_state,
        outbox_dir=args.outbox,
        printer=_p,
    )


async def _cmd_ledger(args: argparse.Namespace) -> int:
    out = ledger_mod.render_to_file(
        state_dir=args.state, out_path=args.ledger, rehearsal_dir=args.rehearsal_state
    )
    _p(f"ledger written to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="watchdog", description=__doc__)
    p.add_argument("--state", default="state", help="local stand-in for Firestore")
    p.add_argument("--rehearsal-state", default="state-rehearsal", help="where rehearsal entries live")
    p.add_argument("--outbox", default="outbox", help="where dry-run artefacts are written")
    p.add_argument("--watched", default="data/watched.json")
    p.add_argument("--ledger", default="docs/ledger.html")
    p.add_argument("--origin", default=watched_mod.DEFAULT_ORIGIN)
    p.add_argument("--count", type=int, default=watched_mod.WATCHED_COUNT)

    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="the whole loop: observe, diff, triage, decide, act dry, journal")
    run.add_argument("--cycles", type=int, default=1)
    run.add_argument("--no-ledger", action="store_true", help="skip rendering the ledger at the end")
    run.add_argument(
        "--live",
        action="store_true",
        help="refused: the live path is a stub and posts nothing",
    )
    run.set_defaults(fn=_cmd_run)

    w = sub.add_parser("watched", help="refetch the worst corners from StreetCred's public scoreboard")
    w.set_defaults(fn=_cmd_watched)

    r = sub.add_parser(
        "rehearse",
        help="exercise the action path offline against a constructed baseline, kept out of the real journal",
    )
    r.set_defaults(fn=_cmd_rehearse)

    lg = sub.add_parser("ledger", help="re-render the ledger from the journal on disk")
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
