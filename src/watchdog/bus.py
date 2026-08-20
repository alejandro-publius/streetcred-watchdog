"""The observer-to-actor hop, as a direct function call.

Pub/Sub is doing three things in the deployed design: it decouples the two
services, it serialises the payload, and it lets the actor run at its own pace.
Locally only the second one can be reproduced honestly, so that is the one this
preserves. The envelope is JSON round-tripped before the actor sees it, which
means the actor cannot accidentally depend on a live object reference that would
not survive the real hop.

The subscriber is registered rather than imported, so the observer still does
not know the actor exists.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

Subscriber = Callable[[dict[str, Any]], Awaitable[None]]


class DirectBus:
    """The Pub/Sub stand-in: publish calls the subscriber, in-process."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self.published = 0

    def describe(self) -> str:
        return "DirectBus, in-process function call (stands in for Pub/Sub)"

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    async def publish(self, envelope: dict[str, Any]) -> None:
        # Round-trip through JSON exactly as the real topic would, so a payload
        # that Pub/Sub could not carry fails here rather than in production.
        wire = json.loads(json.dumps(envelope))
        self.published += 1
        for fn in self._subscribers:
            await fn(wire)
