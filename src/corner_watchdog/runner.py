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
    # What reached the public diary. Empty when publishing was not enabled,
    # which is not the same as nothing having been published and reads that way
    # in the report.
    publish: dict[str, Any] = field(default_factory=dict)
    # What the outcome review decided about tier one's own threshold. Always
    # present, including when it decided to move nothing, because a review that
    # refused and a review that never ran are the same absence otherwise.
    calibration: dict[str, Any] = field(default_factory=dict)

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
            "publish": self.publish,
            "calibration": self.calibration,
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
    bus: Any = None,
    wire_actor: bool = True,
    publish: bool = False,
    calibrate: bool = True,
) -> CycleReport:
    """One full pass: observe, diff, triage, decide, act dry, journal.

    `bus` and `wire_actor` are what let this same function drive the deployed
    observer. On Cloud Run the actor is a different service behind a push
    subscription, so the observer publishes to Pub/Sub and nothing is subscribed
    in this process. Locally the actor is wired to a DirectBus and the whole
    loop runs in one pass, which is the default and what every existing caller
    gets.
    """
    # Before anything is fetched. A cycle that runs with an unverified filter
    # produces numbers, and a wrong number is worse than a run that stopped.
    assert_pinned()

    started = _dt.datetime.now(_dt.UTC)
    run_id = run_id or started.strftime("%Y%m%dT%H%M%SZ")

    store = store or LocalJsonStore(state_dir)

    # Every journaled decision reaches the public diary, or says why it did not.
    #
    # Wrapped rather than called at each journal site: the actor writes entries
    # in three places and the ADK decider's after-tool callback writes a fourth,
    # and the one that got forgotten would be a decision that never reached the
    # diary with nothing saying so.
    #
    # Off by default. A local run must not post to a live site as a side effect
    # of being run, and the deployed services turn it on explicitly.
    publisher_store = None
    if publish:
        from .ingest import StreetCredClient
        from .publisher import DecisionPublisher
        from .publishing_store import PublishingStore

        publisher_store = PublishingStore(
            store,
            DecisionPublisher(
                StreetCredClient(),
                append_journal=store.append_journal,
                append_publish_log=getattr(store, "append_publish_log", None),
            ),
        )
        store = publisher_store

    bus = bus if bus is not None else DirectBus()
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
    if wire_actor:
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

    # Drained once, after the sweep and the actor have both finished writing.
    # Publishing inside the write would make the Store protocol async and push
    # the change into every caller and both store implementations.
    if publisher_store is not None:
        await publisher_store.flush()
        report.publish = publisher_store.result.as_dict()

    # Always, including when the run acted on nothing. An empty outbox and an
    # outbox nobody opened are indistinguishable without this.
    manifest = getattr(act, "write_manifest", None)
    if callable(manifest):
        manifest()

    # The outcome loop, last, so it reads a journal that includes this run. It
    # moves at most one threshold and only ever upward, and on this journal it
    # refuses for want of evidence, which is the answer it should give.
    #
    # Deliberately NOT written into the journal, and the reason is the same one
    # publisher.py records for its receipts. A review entry carries no actions
    # and no error, which is exactly the shape the ledger counts as restraint,
    # so one per cycle would raise the single number this project asks to be
    # judged on, once per cycle, forever. It rides in the cycle report, which
    # the CLI persists to runs.json, and an adjustment additionally lands in the
    # calibration document's own history with its before, after and evidence.
    if calibrate:
        from .calibrate import review

        current = store.get_calibration()
        outcome = review(store.read_journal(), current)
        report.calibration = outcome.to_dict()
        if outcome.adjusted:
            store.put_calibration(current)

    report.finished = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    return report
