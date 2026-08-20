"""The watched set: the worst corners on StreetCred's public scoreboard.

Read from `/api/city`, which is the same paginated endpoint the public
scoreboard page itself reads, unauthenticated, no token. The rows arrive already
ranked by StreetCred's own points, so the worst twenty five are the first twenty
five rows of page one and this module does not re-rank them. Re-sorting by
Danger Index instead would look equivalent and would not be: the index saturates
at 99, so seventeen corners tie at the top and the tie order would be arbitrary.
Points do not saturate, and they are what StreetCred itself orders by.

What is deliberately not done here: no corner is invented, no geometry is
guessed, and a row missing coordinates is dropped rather than centred on
something plausible. The watched set is a claim about which corners the agent
is responsible for, and a corner in it that the city does not have at those
coordinates makes every number downstream wrong.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

import httpx

DEFAULT_ORIGIN = "https://streetcred.thealexschroeder.workers.dev"
DEFAULT_PATH = Path("data/watched.json")
WATCHED_COUNT = 25
DEFAULT_RADIUS_M = 150


async def fetch_worst(
    count: int = WATCHED_COUNT, *, origin: str = DEFAULT_ORIGIN, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """The worst `count` corners, in StreetCred's own published order."""
    owns = client is None
    client = client or httpx.AsyncClient()
    try:
        r = await client.get(f"{origin}/api/city", params={"page": "1"}, timeout=30.0)
        r.raise_for_status()
        payload = r.json() or {}
    finally:
        if owns:
            await client.aclose()

    rows: list[dict[str, Any]] = payload.get("rows") or []
    if not rows:
        raise RuntimeError("StreetCred's scoreboard returned no rows; refusing to write an empty watched set")

    corners: list[dict[str, Any]] = []
    dropped: list[str] = []
    for rank, row in enumerate(rows, start=1):
        if len(corners) >= count:
            break
        lat, lon = row.get("lat"), row.get("lon")
        if not lat or not lon:
            dropped.append(row.get("slug", f"row {rank}"))
            continue
        corners.append(
            {
                "slug": row["slug"],
                "name": row.get("name") or row["slug"],
                "lat": float(lat),
                "lon": float(lon),
                "district": row.get("district"),
                "radiusMeters": DEFAULT_RADIUS_M,
                # Carried for the prompts, which tell each tier what the public
                # page currently claims about this corner. Never used as an
                # input to the delta arithmetic.
                "grade": row.get("grade"),
                "index": row.get("index"),
                "points": row.get("points"),
                "scoreboard_rank": rank,
            }
        )

    if len(corners) < count:
        raise RuntimeError(
            f"only {len(corners)} usable corners on the scoreboard's first page, wanted {count}"
        )

    return {
        "source": f"{origin}/api/city page 1, rows in StreetCred's published order",
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "sweep_date": payload.get("sweepDate"),
        "scoreboard_total": payload.get("total"),
        "count": len(corners),
        "dropped_for_missing_coordinates": dropped,
        "corners": corners,
    }


def save(doc: dict[str, Any], path: str | Path = DEFAULT_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n")
    return p


def load(path: str | Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    doc = json.loads(Path(path).read_text())
    return doc.get("corners") or []
