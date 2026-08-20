"""Where an action lands when the agent is not allowed to touch anything.

Every action the actor decides on is rendered here, in full, to a file. Not a
log line saying a letter would have been written: the letter, with the corner's
real figures in it, in the outbox, readable. A dry run that only prints verbs
lets an obvious bug in the letter itself survive all the way to the first live
send, so the dry run renders the artefact.

The numbers in anything written here come from the snapshot the agent just
fetched and from nowhere else. Where a figure is not known locally, the text
says it is not known rather than reaching for a plausible one.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from .schema import Counts, Delta

DEFAULT_OUTBOX = Path("outbox")


def _safe(name: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in name)[:120] or "unnamed"


class DryRunActuator:
    """Renders what would be sent. Opens no sockets and holds no token."""

    def __init__(self, root: str | Path = DEFAULT_OUTBOX, *, run_id: str = "run"):
        self.root = Path(root) / _safe(run_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.written: list[str] = []

    def describe(self) -> str:
        return f"DryRunActuator writing to {self.root} (stands in for POST to StreetCred)"

    @property
    def is_live(self) -> bool:
        return False

    def _write(self, filename: str, body: str) -> str:
        path = self.root / filename
        path.write_text(body)
        rel = str(path)
        self.written.append(rel)
        return rel

    # ------------------------------------------------------------------ verbs

    async def rescore(self, corner: dict[str, Any], counts: Counts, reasoning: str) -> str:
        slug = corner.get("slug", "unknown")
        payload = {
            "kind": "rescore",
            "slug": slug,
            "note": (
                "The Danger Index is computed by StreetCred from its own weights, not by this agent. "
                "A rescore asks StreetCred to recompute from the current record; it does not carry a "
                "score this agent worked out for itself."
            ),
            "observed_counts": counts.to_dict(),
            "reasoning": reasoning,
            "would_post_to": "/api/agent/report",
            "dry_run": True,
        }
        return self._write(f"{_safe(slug)}.rescore.json", json.dumps(payload, indent=2, sort_keys=True))

    async def regenerate_letter(
        self, corner: dict[str, Any], counts: Counts, delta: Delta, reasoning: str
    ) -> str:
        slug = corner.get("slug", "unknown")
        name = corner.get("name", slug)
        district = counts.district if counts.district is not None else corner.get("district")
        addressee = f"Supervisor, District {district}" if district else "the Board of Supervisors"
        fatal_line = (
            f"{counts.fatal_5y} of those collisions killed someone. "
            if counts.fatal_5y
            else "None of those collisions killed anyone. "
        )
        body = f"""To: {addressee}
Re: {name}
Drafted: {_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
Status: DRY RUN. Not sent. Not posted. Rendered locally for review.

In the last five years, San Francisco's own collision record holds {counts.collisions_5y} injury
collisions within 150 meters of {name}. {fatal_line}{counts.severe_5y} left someone with a severe
injury. Over the last three years the city logged {counts.reports_311_3y} street-condition reports
in the same 150 meters: defects, broken lights, blocked sidewalks, curb and sign faults.

This letter is being redrafted because the record moved. {delta.summary()}

Every figure above is read from DataSF and is checkable against it. Before a letter like this is
published, StreetCred recomputes each number from the corner's own record and stores its own
answer rather than this agent's, so a figure this agent got wrong is caught on the other side of
the wire rather than printed.

--
Filed by the Corner Watchdog, an automated monitor.
Why this corner, in the agent's own words: {reasoning}
"""
        return self._write(f"{_safe(slug)}.letter.txt", body)

    async def reaudit_imagery(
        self, corner: dict[str, Any], counts: Counts, delta: Delta, reasoning: str
    ) -> str:
        slug = corner.get("slug", "unknown")
        name = corner.get("name", slug)
        body = f"""IMAGERY RE-AUDIT REQUEST
Status: DRY RUN. Not sent. No imagery was fetched and none was analysed.

Corner:    {name} ({slug})
Requested: {_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}

What moved:
  {delta.summary()}

Current record within 150 meters:
  injury collisions, 5 years        {counts.collisions_5y}
  of those, fatal                   {counts.fatal_5y}
  of those, severe injury           {counts.severe_5y}
  street-condition 311, 3 years     {counts.reports_311_3y}

Why the agent wants eyes on the imagery:
  {reasoning}

What a real run would do here: pull current street-level imagery for this
intersection and compare it against what the published audit describes. This
run did neither. Nothing below this line was observed; there is no finding to
report, and the absence of one is not a clean bill of health.
"""
        return self._write(f"{_safe(slug)}.imagery-audit.txt", body)

    async def flag(self, corner: dict[str, Any], reason: str) -> str:
        slug = corner.get("slug", "unknown")
        payload = {
            "kind": "flag",
            "slug": slug,
            "name": corner.get("name", slug),
            "reason": reason,
            "raised": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "note": "A human is meant to read this. In a dry run nobody is paged.",
            "dry_run": True,
        }
        return self._write(f"{_safe(slug)}.flag.json", json.dumps(payload, indent=2, sort_keys=True))

    # --------------------------------------------------------------- manifest

    def write_manifest(self) -> str | None:
        """An index of the run, so the outbox explains itself to whoever opens it.

        Written even when the run produced nothing, because an empty outbox and
        an outbox that was never opened look the same on disk, and only one of
        them means the agent decided to leave everything alone.
        """
        when = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        listing = "\n".join(f"  {Path(p).name}" for p in sorted(self.written)) or "  (nothing)"
        body = f"""DRY RUN OUTBOX
run:      {self.run_id}
written:  {when}
artefacts: {len(self.written)}

{listing}

Nothing in this directory was sent. No request left this machine on the acting
side of the loop; the only network reads were San Francisco's open data portal
and StreetCred's public scoreboard, both unauthenticated.

An empty listing above means the agent evaluated the watched set and decided
every change did not warrant touching anything. That is the common outcome and
it is the point. The reasoning behind each of those decisions is in the journal,
not here, because a decision that produced no artefact still produced a record.
"""
        return self._write("MANIFEST.txt", body)
