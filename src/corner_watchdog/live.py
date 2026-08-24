"""The live path. It exists, it satisfies the interface, and it refuses.

There are three ways to handle a path that is not ready. You can leave it
unwritten, and find out at the worst moment that the interface never fit. You
can write it and leave it callable, which is how a dry run becomes a live send
by way of one wrong flag. Or you can write it, wire it into the same protocol
everything else implements, and have every verb refuse with a specific reason.

This is the third. `LiveActuator` is a real implementation of `Actuator`, so if
the protocol changes underneath it this file stops type checking, which is the
whole point of keeping it. Every verb raises. Nothing here opens a socket, and
the token is never read, because a module that reads a credential in order to
refuse to use it is one edit away from using it.

`ingest.py` holds the actual posting code and predates tonight. Nothing in the
local loop imports it, and a test pins that.
"""

from __future__ import annotations

from typing import Any, NoReturn

from .schema import Counts, Delta

BLOCKERS = (
    (
        "WATCHDOG_INGEST_TOKEN is not provisioned, and the matching secret is not set on "
        "StreetCred's Worker"
    ),
    (
        "StreetCred's /api/agent/report has not been deployed, so there is nothing on the far "
        "side to recompute the agent's arithmetic and dispute it"
    ),
    "no human has read a full dry-run outbox end to end and agreed with every letter in it",
)


class LivePathRefused(RuntimeError):
    """Raised instead of sending. Carries the reasons, not a stack trace."""


def _refuse(verb: str, slug: str) -> NoReturn:
    reasons = "\n".join(f"  {i}. {b}" for i, b in enumerate(BLOCKERS, start=1))
    raise LivePathRefused(
        f"Refusing to {verb} {slug} on the live path.\n\n"
        f"This build does not post to StreetCred. What is missing:\n{reasons}\n\n"
        "Until all three are true, run the dry path and read the outbox."
    )


class LiveActuator:
    """Implements the protocol so the seam stays honest. Sends nothing."""

    def describe(self) -> str:
        return "LiveActuator, a stub that refuses every verb (no live path in this build)"

    @property
    def is_live(self) -> bool:
        # True in the sense that matters: this is the path that would reach the
        # outside world. Reporting False to make a caller relax would be the
        # exact lie this class exists to prevent.
        return True

    async def rescore(self, corner: dict[str, Any], counts: Counts, reasoning: str) -> str:
        _refuse("rescore", corner.get("slug", "an unknown corner"))

    async def regenerate_letter(
        self, corner: dict[str, Any], counts: Counts, delta: Delta, reasoning: str
    ) -> str:
        _refuse("post a letter for", corner.get("slug", "an unknown corner"))

    async def reaudit_imagery(
        self, corner: dict[str, Any], counts: Counts, delta: Delta, reasoning: str
    ) -> str:
        _refuse("request an imagery re-audit for", corner.get("slug", "an unknown corner"))

    async def flag(self, corner: dict[str, Any], reason: str) -> str:
        _refuse("raise a flag on", corner.get("slug", "an unknown corner"))
