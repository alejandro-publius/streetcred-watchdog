"""Posting to StreetCred.

The one credential shared between the two systems, used in one direction only.
StreetCred never calls the agent; the agent calls StreetCred and StreetCred
checks its arithmetic. That asymmetry is deliberate and it is why the token
lives here rather than in both places.

Nothing in this module decides anything. It serialises, posts, and reports back
what the far side said, including when the far side rejects a letter this agent
believed was fine. That rejection is the interesting case and it is returned to
the caller rather than swallowed, because a run where StreetCred disagreed with
the agent is exactly what the journal should record.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_ORIGIN = "https://streetcred.thealexschroeder.workers.dev"


@dataclass(frozen=True)
class IngestResult:
    ok: bool
    status: int
    body: dict[str, Any]

    @property
    def verified(self) -> bool | None:
        """Only meaningful for letter posts. None for every other kind."""
        return self.body.get("verified")

    @property
    def disputed(self) -> bool:
        """True when StreetCred's arithmetic disagreed with the agent's own claim."""
        return bool(self.body.get("selfReportDisputed"))


class StreetCredClient:
    def __init__(self, origin: str | None = None, token: str | None = None):
        self.origin = (origin or os.environ.get("STREETCRED_ORIGIN") or DEFAULT_ORIGIN).rstrip("/")
        # Read from the environment, which on Cloud Run is populated from Secret
        # Manager. Never written to a file, never logged, never journaled.
        self.token = token or os.environ.get("WATCHDOG_INGEST_TOKEN") or ""

    async def _post(self, payload: dict[str, Any], client: httpx.AsyncClient | None = None) -> IngestResult:
        if not self.token:
            return IngestResult(False, 0, {"error": "no ingest token configured"})
        owns = client is None
        client = client or httpx.AsyncClient()
        try:
            r = await client.post(
                f"{self.origin}/api/agent/report",
                json=payload,
                headers={"authorization": f"Bearer {self.token}"},
                timeout=45.0,
            )
            try:
                body = r.json()
            except Exception:
                body = {"error": "non json response"}
            return IngestResult(r.status_code == 200, r.status_code, body)
        except Exception as e:  # a failed post is journaled, never fatal
            return IngestResult(False, 0, {"error": str(e)[:200]})
        finally:
            if owns:
                await client.aclose()

    async def journal(self, entry, client=None) -> IngestResult:
        return await self._post(entry.to_ingest_payload(), client)

    async def rescore(self, slug: str, index: int, grade: str, client=None) -> IngestResult:
        return await self._post(
            {"kind": "rescore", "slug": slug, "index": index, "grade": grade}, client
        )

    async def letter(self, slug: str, text: str, verified: bool, client=None) -> IngestResult:
        """Post a redrafted letter.

        `verified` is this agent's own assessment. StreetCred recomputes it from
        the corner's DataSF record and stores its own answer, so a mismatch here
        is not an error to retry, it is a finding to journal.
        """
        return await self._post(
            {"kind": "letter", "slug": slug, "text": text, "verified": verified}, client
        )

    async def flag(self, slug: str, reason: str, client=None) -> IngestResult:
        return await self._post({"kind": "flag", "slug": slug, "reason": reason}, client)

    async def board(self, client=None) -> list[dict]:
        """The warmed fleet. Public, no token needed."""
        owns = client is None
        client = client or httpx.AsyncClient()
        try:
            r = await client.get(f"{self.origin}/api/board", timeout=30.0)
            r.raise_for_status()
            return (r.json() or {}).get("corners", [])
        finally:
            if owns:
                await client.aclose()
