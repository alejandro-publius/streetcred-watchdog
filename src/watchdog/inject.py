"""Deliberate failures, so the degradation paths can be shown rather than described.

Every honest thing this agent does when something breaks is invisible until
something breaks. A demo that says "and if DataSF were down, it would refuse to
compare and keep the old baseline" is asking to be believed. A demo that turns
DataSF off on camera and reads the resulting journal entries is not.

Two rules make this safe to keep in the shipped code:

  It writes somewhere else. Injected runs default to their own state directory,
  so a rehearsed failure can never end up in the journal that gets submitted. The
  real journal should contain real events and nothing else.

  Every entry says it was injected. The provenance note lands on every journal
  entry the run produces, so a screenshot of an injected outage cannot later be
  mistaken for evidence that DataSF had an outage. This is the same rule the
  rehearsal follows for constructed baselines, applied to constructed failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .budget import ActionBudget, TokenBudget
from .schema import Snapshot


class InjectedOutage(httpx.ConnectError):
    """Raised by the failing fetcher. A real connection error's own type.

    Deliberately a real httpx error rather than a bespoke one, so the code path
    under test is the code path that runs in production. An injection that takes
    a different branch than the real failure proves nothing.
    """


class FailingFetcher:
    """Every corner raises. Stands in for the source being unreachable."""

    def __init__(self, message: str = "injected outage, DataSF was not actually contacted"):
        self.message = message

    def describe(self) -> str:
        return f"FailingFetcher, INJECTED: {self.message}"

    async def fetch_all(self, corners: list[dict[str, Any]]) -> list[Snapshot | BaseException]:
        return [InjectedOutage(self.message) for _ in corners]


class PartialFetcher:
    """Half the corners come back, the rest raise. The messier, likelier outage."""

    def __init__(self, inner, fail_every: int = 2):
        self.inner = inner
        self.fail_every = fail_every

    def describe(self) -> str:
        return f"PartialFetcher, INJECTED: every {self.fail_every} corner fails"

    async def fetch_all(self, corners: list[dict[str, Any]]) -> list[Snapshot | BaseException]:
        got = await self.inner.fetch_all(corners)
        return [
            InjectedOutage("injected partial outage") if i % self.fail_every == 0 else s
            for i, s in enumerate(got)
        ]


@dataclass(frozen=True)
class Injection:
    name: str
    what_it_shows: str
    note: str
    fetcher: Any = None
    action_budget: ActionBudget | None = None
    token_budget: TokenBudget | None = None


def available() -> dict[str, str]:
    return {
        "datasf_down": "the data source is unreachable for every corner",
        "datasf_partial": "the data source fails for some corners and not others",
        "budget_zero": "the action budget is spent, so actions become journaled intents",
        "tokens_zero": "the token budget is spent, so no tier is consulted at all",
    }


def build(name: str, *, inner_fetcher=None) -> Injection:
    """Turn a flag into the overrides that produce that failure."""
    if name not in available():
        raise ValueError(f"unknown injection {name!r}, choose from {sorted(available())}")

    stamp = (
        f"THIS FAILURE WAS INJECTED on purpose with --inject {name}. "
        f"It shows {available()[name]}. Nothing was actually wrong with any source, "
        "no budget was actually exhausted, and this run is not evidence that either "
        "happened."
    )

    if name == "datasf_down":
        return Injection(name, available()[name], stamp, fetcher=FailingFetcher())
    if name == "datasf_partial":
        from .observer import DataSFFetcher

        return Injection(
            name, available()[name], stamp,
            fetcher=PartialFetcher(inner_fetcher or DataSFFetcher()),
        )
    if name == "budget_zero":
        return Injection(name, available()[name], stamp, action_budget=ActionBudget(limit=0))
    return Injection(name, available()[name], stamp, token_budget=TokenBudget(limit=1))
