"""The other side of two seams: Firestore for the store, Pub/Sub for the bus.

`ports.py` has named these two protocols since the first commit and `store.py`
and `bus.py` have been the local implementations of them. This is the pair that
runs on Cloud Run, and the only reason it is one module rather than two is that
neither is long: the shapes were already decided in `schema.py`, so there is
nothing here but translation.

Three things are worth reading before the code.

**The journal stays append only, and Firestore does not enforce that for you.**
A local JSONL file cannot lose the lines already written when a run crashes
halfway through appending one. A Firestore document can be overwritten by
anything holding a reference to it. So entries are written with `create()` into
documents keyed by timestamp and a random suffix, which fails rather than
overwriting if the id somehow already exists. A decision journal that a later
run can quietly rewrite is not a decision journal, and "we used a database"
is not on its own a guarantee of anything.

**Reads are bounded.** `read_journal` takes a limit, because the local
implementation reads a file that this repository controls the size of and this
one reads a collection that grows every morning forever. An unbounded read here
is a page that takes longer to render every day until one day it does not
render, which is a failure that arrives slowly enough to be nobody's fault.

**The database is named `watchdog` rather than `(default)`, and that is a
workaround for a real bug rather than a preference.** Every call against the
default database fails with `InvalidArgument: 400 Invalid database id
%28default%29`. The REST transport shows why: the request goes to
`.../databases/%2528default%2529/documents:commit`, which is `(default)`
percent-encoded twice. The server decodes once, sees `%28default%29`, and
rejects it.

What was ruled out before concluding that: it reproduces on a laptop and on a
clean Cloud Run instance, on google-cloud-firestore 2.22 and 2.29, on grpcio
1.76 and 1.83, and on both the gRPC and REST transports. A hand-built REST call
with a literal `(default)` in the path succeeds against the same database with
the same credentials, so the server and the database are fine and the client is
double-encoding. A named database contains no characters that need encoding, so
it takes the same code path and works. `FIRESTORE_DATABASE` overrides it.

**The malformed-snapshot path is preserved.** `get_snapshot` refuses a document
it cannot parse rather than coercing it, exactly as the local store does, and
records why in `quarantined` so the observer journals the corner as "the
baseline was unreadable" rather than as "we have never seen this corner". The
difference matters more in Firestore than on disk: there is no file to move
aside, so the document is marked rather than relocated.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from typing import Any

from google.cloud import firestore, pubsub_v1

from .schema import Calibration, JournalEntry, MalformedSnapshot, Snapshot

SNAPSHOTS = "snapshots"
JOURNAL = "journal"
CALIBRATION = "calibration"
CALIBRATION_DOC = "state"

# Not "(default)". See the module docstring: the client double-encodes the
# parentheses and every call against the default database is rejected.
DEFAULT_DATABASE = "watchdog"

# How many journal entries a page render will read. The ledger groups by cycle
# and the agent writes at most one entry per watched corner per sweep, so this
# is several weeks of history and still one bounded query.
DEFAULT_JOURNAL_LIMIT = 2000


class FirestoreStore:
    """The real Store. Same three collections the local one writes as files."""

    def __init__(
        self,
        project: str | None = None,
        *,
        client: Any = None,
        database: str | None = None,
        journal_limit: int = DEFAULT_JOURNAL_LIMIT,
    ) -> None:
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        self.database = database or os.environ.get("FIRESTORE_DATABASE") or DEFAULT_DATABASE
        self.db = client or firestore.Client(
            project=self.project or None, database=self.database
        )
        self.journal_limit = journal_limit
        # Same contract as LocalJsonStore.quarantined: slug -> why. The observer
        # reads it to tell "unreadable baseline" apart from "never seen".
        self.quarantined: dict[str, str] = {}

    def describe(self) -> str:
        return (
            f"FirestoreStore, project {self.project or 'inferred'}, "
            f"database {self.database}, three collections"
        )

    # ------------------------------------------------------------- snapshots

    def get_snapshot(self, slug: str) -> Snapshot | None:
        doc = self.db.collection(SNAPSHOTS).document(slug).get()
        if not doc.exists:
            return None
        try:
            return Snapshot.from_dict(doc.to_dict() or {})
        except MalformedSnapshot as e:
            # Not deleted and not coerced. The document is the only evidence of
            # whatever wrote it, so it is marked and left, and the corner
            # rebuilds a baseline on this sweep.
            self.quarantined[slug] = f"{type(e).__name__}: {str(e)[:160]}"
            self.db.collection(SNAPSHOTS).document(slug).set(
                {
                    "quarantinedAt": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
                    "quarantineReason": self.quarantined[slug],
                },
                merge=True,
            )
            return None

    def put_snapshot(self, snapshot: Snapshot) -> None:
        self.db.collection(SNAPSHOTS).document(snapshot.slug).set(snapshot.to_dict())

    def all_snapshots(self) -> list[Snapshot]:
        out: list[Snapshot] = []
        for doc in self.db.collection(SNAPSHOTS).stream():
            try:
                out.append(Snapshot.from_dict(doc.to_dict() or {}))
            except MalformedSnapshot:
                # The roster-drop survey, same as the local store: a read-only
                # scan does not get to quarantine anything.
                continue
        return out

    # --------------------------------------------------------------- journal

    def append_journal(self, entry: JournalEntry) -> None:
        """Append only, enforced rather than intended.

        `create` raises if the document id already exists, so this cannot
        overwrite an entry even if a caller somehow produced a colliding id. The
        id is sortable so the ledger can order by it without an index.
        """
        doc_id = f"{entry.ts}-{uuid.uuid4().hex[:8]}"
        self.db.collection(JOURNAL).document(doc_id).create(entry.to_dict())

    def read_journal(self, limit: int | None = None) -> list[dict[str, Any]]:
        query = (
            self.db.collection(JOURNAL)
            .order_by("ts", direction=firestore.Query.DESCENDING)
            .limit(limit or self.journal_limit)
        )
        entries = [doc.to_dict() or {} for doc in query.stream()]
        # The ledger reads oldest first; the query is newest first so the limit
        # keeps the recent end rather than the ancient one.
        entries.reverse()
        return entries

    # ----------------------------------------------------------- calibration

    def get_calibration(self) -> Calibration:
        doc = self.db.collection(CALIBRATION).document(CALIBRATION_DOC).get()
        c = Calibration()
        if not doc.exists:
            return c
        d = doc.to_dict() or {}
        c.reports_311_jump = int(d.get("reports_311_jump", c.reports_311_jump))
        c.min_new_collisions = int(d.get("min_new_collisions", c.min_new_collisions))
        c.history = list(d.get("history") or [])
        # Bounds stay code. Reloading them from a document would let an edited
        # database widen the limits that exist to stop one unusual week from
        # swinging the agent, which is the whole point of having bounds.
        return c

    def put_calibration(self, calibration: Calibration) -> None:
        self.db.collection(CALIBRATION).document(CALIBRATION_DOC).set(calibration.to_dict())


class PubSubBus:
    """The real Bus. Publishes the same envelope DirectBus round-trips locally."""

    def __init__(
        self,
        topic: str | None = None,
        project: str | None = None,
        *,
        publisher: Any = None,
    ) -> None:
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        self.topic_id = topic or os.environ.get("DELTA_TOPIC", "corner-deltas")
        self.publisher = publisher or pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(self.project, self.topic_id)
        self.published = 0

    def describe(self) -> str:
        return f"PubSubBus, topic {self.topic_id} in {self.project or 'inferred project'}"

    async def publish(self, envelope: dict[str, Any]) -> None:
        """One escalation onto the topic.

        Blocking on the publish future rather than firing and forgetting. A
        sweep that exits while its escalations are still in a client-side buffer
        loses them silently, and a lost escalation is a corner the journal says
        was escalated and the actor never saw.
        """
        payload = json.dumps(envelope).encode("utf-8")
        future = self.publisher.publish(self.topic_path, payload)
        future.result(timeout=30)
        self.published += 1
