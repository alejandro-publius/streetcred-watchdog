"""Wiring. The one place that knows which side of every seam is real.

Everything above this file is written against the protocols in ports.py, so this
is the only module that would change when Firestore, Pub/Sub and Vertex come
online. If a cloud client name ever appears anywhere else in this package,
something has leaked.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .actor import Actor, ActorResult
from .brains import select_brains
from .budget import ActionBudget, TokenBudget
from .bus import DirectBus
from .observer import Fetcher, Observer, SweepResult
from .outbox import DryRunActuator
from .ports import Actuator
from .schema import Trigger
from .store import LocalJsonStore
from .vocabulary import assert_pinned


@dataclass
class CycleReport:
    run_id: str
    started: str
    finished: str = ""
    trigger: str = "manual"
    sweep: SweepResult = field(default_factory=SweepResult)
    actor: ActorResult = field(default_factory=ActorResult)
    degraded: str | None = None
    wiring: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started": self.started,
            "finished": self.finished,
            "trigger": self.trigger,
            "sweep": self.sweep.as_dict(),
            "actor": self.actor.as_dict(),
            "degraded": self.degraded,
            "wiring": self.wiring,
        }


async def run_cycle(
    corners: list[dict[str, Any]],
    *,
    state_dir: str | Path = "state",
    outbox_dir: str | Path = "outbox",
    run_id: str | None = None,
    trigger: Trigger = "manual",
    actuator: Actuator | None = None,
    store: LocalJsonStore | None = None,
    fetcher: Fetcher | None = None,
    extra_degradation: str | None = None,
    action_budget: ActionBudget | None = None,
    token_budget: TokenBudget | None = None,
) -> CycleReport:
    """One full pass: observe, diff, triage, decide, act dry, journal."""
    # Before anything is fetched. A cycle that runs with an unverified filter
    # produces numbers, and a wrong number is worse than a run that stopped.
    assert_pinned()

    started = _dt.datetime.now(_dt.timezone.utc)
    run_id = run_id or started.strftime("%Y%m%dT%H%M%SZ")

    store = store or LocalJsonStore(state_dir)
    bus = DirectBus()
    triage, decider, model_note = select_brains()
    # Tier two always consults its model, so the model caveat always applies to
    # the actor's entries. The observer decides which of its own entries it
    # applies to, because the rule floor answers many of them without a model.
    degraded = " ".join(p for p in (extra_degradation, model_note) if p) or None
    act: Actuator = actuator or DryRunActuator(outbox_dir, run_id=run_id)
    budget = action_budget or ActionBudget.from_env()
    tokens = token_budget or TokenBudget.from_env()

    observer = Observer(
        store, bus, triage, fetcher=fetcher, degraded=model_note,
        provenance=extra_degradation, run_id=run_id, tokens=tokens
    )
    actor = Actor(store, decider, act, budget, degraded=degraded, run_id=run_id, tokens=tokens)
    bus.subscribe(actor.handle)

    report = CycleReport(
        run_id=run_id,
        started=started.isoformat(timespec="seconds"),
        trigger=trigger,
        degraded=degraded,
        wiring={
            "store": store.describe(),
            "bus": bus.describe(),
            "observations": observer.fetcher.describe(),
            "triage": triage.describe(),
            "decider": decider.describe(),
            "actuator": act.describe(),
            "budget": f"{budget.limit} actions for the day",
            "tokens": (
                f"{tokens.limit} projected tokens for the day"
                if tokens.capped else "no token ceiling set"
            ),
        },
    )

    report.sweep = await observer.sweep(corners, trigger=trigger)
    report.actor = actor.result

    # Always, including when the run acted on nothing. An empty outbox and an
    # outbox nobody opened are indistinguishable without this.
    manifest = getattr(act, "write_manifest", None)
    if callable(manifest):
        manifest()

    report.finished = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    return report
