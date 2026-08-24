"""Render the ledger's edge states to files, so they can be looked at.

An empty page, a page for a run that died halfway, and a page for a run where a
source was down are all states this agent will be in at some point, and all three
are states nobody looks at until they happen, by which time the page is being
read by somebody trying to work out what went wrong.

The entries below are **constructed**, not observed. They are labelled as such on
every page produced, in the page itself and not only in this file, because a
fixture page that looks like a real journal is exactly the artefact this project
should not produce. The corner names and their records are real, read from this
repo's own snapshots; the failures are invented to force the state.

    python tools/render_states.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from corner_watchdog.ledger import render_document  # noqa: E402

OUT = REPO / "docs" / "states"

FIXTURE_BANNER = (
    "This page is a rendered fixture, not a record of anything that happened. The corner names "
    "and their counts are real, read from this repo's snapshots on 2026-08-20. The failures are "
    "constructed to force the state so it can be looked at before it happens for real."
)

REAL_CORNERS = [
    ("6th-and-mission", "6th and Mission"),
    ("6th-and-stevenson", "6th and Stevenson"),
    ("6th-and-jessie", "6th and Jessie"),
    ("larkin-and-myrtle", "Larkin and Myrtle"),
    ("6th-and-minna", "6th and Minna"),
    ("4th-and-ellis", "4th and Ellis"),
    ("gough-and-market", "Gough and Market"),
    ("5th-and-cyril-magnin", "5th and Cyril Magnin"),
    ("8th-and-minna", "8th and Minna"),
    ("cyril-magnin-and-eddy", "Cyril Magnin and Eddy"),
    ("6th-and-natoma", "6th and Natoma"),
    ("gough-and-haight", "Gough and Haight"),
]


def entry(slug, name, *, basis, reason, delta, run_id, ts, degraded=None):
    e = {
        "ts": ts,
        "runId": run_id,
        "slug": slug,
        "name": name,
        "delta": delta,
        "trigger": "cron",
        "tier1": {"significant": False, "reason": reason, "byRule": True, "basis": basis},
        "actions": [],
        "intents": [],
    }
    if degraded:
        e["degraded"] = degraded
    return e


def state_empty():
    return [], 25


def state_partial():
    """A cycle that died after twelve of twenty five corners."""
    return [
        entry(slug, name,
              basis="no_change",
              reason="Nothing changed at this corner since the last look.",
              delta=f"No change at {name}.",
              run_id="tick-20260821T054500Z",
              ts=f"2026-08-21T05:{45 + i:02d}:00+00:00")
        for i, (slug, name) in enumerate(REAL_CORNERS)
    ], 25


def state_source_down():
    """A complete cycle where DataSF refused nine of twenty five corners."""
    ok = [
        entry(slug, name,
              basis="no_change",
              reason="Nothing changed at this corner since the last look.",
              delta=f"No change at {name}.",
              run_id="tick-20260821T114500Z",
              ts=f"2026-08-21T11:{45 + i:02d}:00+00:00")
        for i, (slug, name) in enumerate(REAL_CORNERS[:3])
    ]
    down = [
        entry(slug, name,
              basis="fetch_failed",
              reason=("The fetch failed outright, so there is nothing to compare and nothing to "
                      "judge. The previous baseline is kept untouched."),
              delta=f"Could not read the city's record for {name}.",
              run_id="tick-20260821T114500Z",
              ts=f"2026-08-21T11:{48 + i:02d}:00+00:00",
              degraded="Read failed: ReadTimeout.")
        for i, (slug, name) in enumerate(REAL_CORNERS[3:12])
    ]
    return ok + down, 12


PAGES = {
    "empty.html": ("No cycle has run yet", state_empty),
    "partial-cycle.html": ("A cycle that stopped halfway", state_partial),
    "source-down.html": ("A source was unavailable", state_source_down),
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, (label, build) in PAGES.items():
        entries, roster = build()
        html = render_document(entries, roster_size=roster)
        # Stamped into the page itself, not just this file.
        html = html.replace(
            '<div class="wrap">',
            f'<div class="wrap"><section class="notice"><p><strong>Fixture: {label}.</strong> '
            f"{FIXTURE_BANNER}</p></section>",
            1,
        )
        (OUT / filename).write_text(html)
        print(f"wrote docs/states/{filename}  ({len(entries)} entries, roster {roster})")
    (OUT / "README.md").write_text(
        "# Ledger states\n\n"
        "Rendered fixtures of the states the ledger can be in, so they can be reviewed before\n"
        "they happen for real. Regenerate with `python tools/render_states.py`.\n\n"
        + "\n".join(f"- `{f}` {label.lower()}" for f, (label, _) in PAGES.items())
        + "\n\nEvery page carries a banner saying it is a fixture. The corner names and counts\n"
        "in them are real; the failures are constructed.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
