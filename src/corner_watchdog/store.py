"""Firestore's three collections, as three files on this laptop.

    state/snapshots/{slug}.json   one document per watched corner, overwritten
    state/journal.jsonl           append only, one JSON object per line
    state/calibration.json        one document

The shapes are the dataclasses in schema.py and nothing else, so the day this is
pointed at a real Firestore the documents that arrive are the documents that
were always being written. The journal is JSONL rather than a JSON array for one
specific reason: appending a line cannot corrupt the lines already written, and
a decision journal that a crashed run can truncate is not a decision journal.

Nothing here deletes. Snapshots are overwritten because that is what a snapshot
is; journal entries never are.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

from .schema import Calibration, JournalEntry, MalformedSnapshot, Snapshot

DEFAULT_STATE_DIR = Path("state")


def _slug_filename(slug: str) -> str:
    """Keep a slug from escaping the snapshots directory.

    Slugs come from StreetCred's public API, which is somebody else's server.
    A slug of "../../etc/passwd" should produce a silly filename, not a write
    outside the state directory.
    """
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in slug)
    return (safe or "unnamed")[:120] + ".json"


class LocalJsonStore:
    """The Firestore stand-in. No account, no emulator, no network."""

    def __init__(self, root: str | os.PathLike[str] = DEFAULT_STATE_DIR) -> None:
        self.root = Path(root)
        self.snapshots_dir = self.root / "snapshots"
        self.quarantine_dir = self.root / "quarantine"
        self.journal_path = self.root / "journal.jsonl"
        self.calibration_path = self.root / "calibration.json"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        # slug -> why it was quarantined during this process's lifetime. Read by
        # the observer so a corner whose baseline was thrown away is journaled
        # as exactly that, rather than as a corner nobody has ever seen.
        self.quarantined: dict[str, str] = {}

    def describe(self) -> str:
        return f"LocalJsonStore at {self.root} (stands in for Firestore)"

    # ------------------------------------------------------------- snapshots

    def get_snapshot(self, slug: str) -> Snapshot | None:
        """The stored baseline, or None if there is not a usable one.

        A document that cannot be read is moved aside rather than left in place.
        Left in place it would be re-read and re-rejected on every sweep forever,
        and the corner would never rebuild a baseline; moved aside, the next
        sweep writes a fresh one and comparison resumes the sweep after that.
        The bad document is kept, not deleted, because it is the only evidence
        of whatever wrote it.
        """
        path = self.snapshots_dir / _slug_filename(slug)
        if not path.exists():
            return None
        try:
            return Snapshot.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError, MalformedSnapshot) as e:
            self._quarantine(path, slug, f"{type(e).__name__}: {str(e)[:160]}")
            return None

    def _quarantine(self, path: Path, slug: str, reason: str) -> None:
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.quarantine_dir / f"{_slug_filename(slug)[:-5]}.{stamp}.json"
        # Cannot move it, so at least do not pretend the baseline is fine.
        with contextlib.suppress(OSError):
            path.replace(target)
        self.quarantined[slug] = reason
        with (self.root / "quarantine.log").open("a") as fh:
            fh.write(f"{_dt.datetime.now(_dt.UTC).isoformat(timespec='seconds')} "
                     f"{slug} -> {target.name}: {reason}\n")

    def put_snapshot(self, snapshot: Snapshot) -> None:
        path = self.snapshots_dir / _slug_filename(snapshot.slug)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))
        tmp.replace(path)

    def all_snapshots(self) -> list[Snapshot]:
        out: list[Snapshot] = []
        for path in sorted(self.snapshots_dir.glob("*.json")):
            try:
                out.append(Snapshot.from_dict(json.loads(path.read_text())))
            except (json.JSONDecodeError, OSError, MalformedSnapshot):
                # Left in place on purpose. This is the roster-drop scan, and
                # quarantining from a read-only survey would move a file out
                # from under the sweep that is about to look at it properly.
                continue
        return out

    # --------------------------------------------------------------- journal

    def append_journal(self, entry: JournalEntry) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a") as fh:
            fh.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")

    def read_journal(self) -> list[dict[str, Any]]:
        if not self.journal_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.journal_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                # One torn line does not get to hide the rest of the journal.
                continue
        return entries

    # ----------------------------------------------------------- calibration

    def get_calibration(self) -> Calibration:
        if not self.calibration_path.exists():
            return Calibration()
        try:
            d = json.loads(self.calibration_path.read_text())
        except (json.JSONDecodeError, OSError):
            return Calibration()
        c = Calibration()
        c.reports_311_jump = int(d.get("reports_311_jump", c.reports_311_jump))
        c.min_new_collisions = int(d.get("min_new_collisions", c.min_new_collisions))
        c.history = list(d.get("history") or [])
        # Bounds are code, not data. Reloading them from a file would let an
        # edited state file widen the very limits that exist to stop one
        # unusual week from swinging the agent.
        return c

    def put_calibration(self, calibration: Calibration) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.calibration_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(calibration.to_dict(), indent=2, sort_keys=True))
        tmp.replace(self.calibration_path)
