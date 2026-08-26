"""One image, two services. The HTTP surface Cloud Run boots.

The `Dockerfile` has pointed at `corner_watchdog.server:app` since the scaffold
and this module did not exist, which meant `gcloud run deploy` would have built
an image that crashed on start. `docs/GCP_PRECONDITIONS.md` listed exactly that
under "what is still missing after all of this". This is that gap closed.

    SERVICE=observer    POST /sweep       one full pass over the watched set
                        POST /tick        the same pass, marked hourly
    SERVICE=actor       POST /deliberate  the Pub/Sub push endpoint
    either              GET  /status      what this instance thinks it is

The status route is `/status` and not `/healthz` for a reason found the hard
way. Cloud Run's front end reserves `/healthz`: it answers that path itself with
a generic Google 404 and never forwards it to the container. Every other path on
a private service returns 403 as it should, so the symptom is one route
returning 404 while the container is demonstrably healthy and serving, which
reads as a routing bug in the application and is not one.

Why one image rather than two. The observer and the actor exchange a JSON
envelope whose shape is defined in `schema.py`, and two images built from two
commits can disagree about that shape while both look healthy. One image cannot.
`SERVICE` picks the half at boot, and `/healthz` reports which half it got, so
an instance running the wrong role is visible rather than merely wrong.

**Authentication is the platform's job, not this file's.** Both services deploy
with `--no-allow-unauthenticated`, so Cloud Run rejects any request without a
valid token before it reaches this process. The push subscription and the
scheduler each carry their own service account and their own `run.invoker`
binding scoped to one service. There is deliberately no shared secret checked
here: an app-level token would be a second, weaker authentication system sitting
behind the real one, and the weaker one is the one that gets misconfigured.

**The actor acknowledges a bad message rather than retrying it forever.** A push
endpoint that returns 500 gets the same message redelivered until the
subscription's retention runs out. For a transient fault that is what you want.
For a payload this build cannot parse it is an infinite loop that costs money
and fills the log with one corner. So an unparseable envelope is journaled as an
error, and answered 204, which is Pub/Sub's signal to stop.
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import json
import os
from typing import Any

from fastapi import FastAPI, Request, Response

from .actor import Actor
from .brains import select_brains
from .budget import ActionBudget, TokenBudget
from .cloud import FirestoreStore, PubSubBus
from .config import describe as describe_config
from .outbox import DryRunActuator
from .runner import run_cycle
from .schema import JournalEntry, Tier1Verdict
from .watched import load as load_watched

OBSERVER = "observer"
ACTOR = "actor"

# Cloud Run's filesystem is ephemeral and in-memory. The outbox is dry-run
# evidence rather than the product, so it goes somewhere writable and is
# understood to vanish with the instance. The journal is the product, and the
# journal is in Firestore.
OUTBOX_DIR = os.environ.get("OUTBOX_DIR", "/tmp/outbox")

# Whether this instance posts its decisions to StreetCred's public diary. On by
# default in the deployed services and set explicitly by the Cloud Run config,
# so a service that stops publishing is a config change somebody made rather
# than a default nobody noticed.
PUBLISH = (os.environ.get("PUBLISH_DECISIONS", "1").strip().lower() not in ("0", "false", "no"))

app = FastAPI(title="Corner Watchdog", docs_url=None, redoc_url=None)


def service_role() -> str:
    role = (os.environ.get("SERVICE") or OBSERVER).strip().lower()
    if role not in (OBSERVER, ACTOR):
        # Same rule as config.decider_name: an unrecognised value is an error,
        # never a silent default. An instance quietly booting as the observer
        # because SERVICE was misspelled would answer /healthz cheerfully and
        # never deliberate on anything.
        raise RuntimeError(
            f"SERVICE={role!r} is not {OBSERVER!r} or {ACTOR!r}. Refusing to guess which "
            "half of the agent this instance is."
        )
    return role


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


@app.get("/status")
async def healthz() -> dict[str, Any]:
    """What this instance is, and what it would run if asked.

    Deliberately more than {"ok": true}. A health check that only proves the
    process is alive tells you nothing about whether it is the service you meant
    to deploy or whether its model is wired, and both have been wrong here
    before.
    """
    role = service_role()
    return {
        "ok": True,
        "service": role,
        "project": os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        "location": os.environ.get("GOOGLE_CLOUD_LOCATION", ""),
        "config": describe_config(),
        "actionBudget": ActionBudget.from_env().limit,
        "tokenBudget": TokenBudget.from_env().limit,
        "ts": _now(),
    }


# ------------------------------------------------------------------ observer


async def _sweep(trigger: str) -> dict[str, Any]:
    """One pass over the watched set, publishing escalations onto the topic.

    `wire_actor=False` is the whole difference from a local run. On Cloud Run
    the actor is a separate service behind a push subscription, so nothing is
    subscribed in this process and the escalation genuinely leaves the building.
    """
    corners = load_watched()
    report = await run_cycle(
        corners,
        store=FirestoreStore(),
        bus=PubSubBus(),
        wire_actor=False,
        outbox_dir=OUTBOX_DIR,
        trigger=trigger,  # type: ignore[arg-type]
        # The deployed services publish. A local run does not, because posting
        # to a live site as a side effect of being run is not something a
        # developer should have to remember to turn off.
        publish=PUBLISH,
    )
    return report.as_dict()


@app.post("/sweep")
async def sweep() -> dict[str, Any]:
    if service_role() != OBSERVER:
        return {"error": "this instance is the actor, it does not sweep"}
    return await _sweep("cron")


@app.post("/tick")
async def tick() -> dict[str, Any]:
    """The hourly pass. Same work, journaled under a different trigger.

    It is the same sweep on purpose. An hourly variant that looked at fewer
    corners, or skipped the expensive tier, would make the journal's trigger
    field describe two different procedures under two names, and the ledger
    counts entries across both.
    """
    if service_role() != OBSERVER:
        return {"error": "this instance is the actor, it does not tick"}
    return await _sweep("hourly")


# --------------------------------------------------------------------- actor


def decode_push(body: dict[str, Any]) -> dict[str, Any]:
    """The envelope out of a Pub/Sub push wrapper, or raise."""
    message = body.get("message")
    if not isinstance(message, dict):
        raise ValueError("push body has no 'message' object")
    data = message.get("data")
    if not isinstance(data, str):
        raise ValueError("push message carries no base64 'data'")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"push data is not valid base64: {e}") from None
    envelope = json.loads(raw.decode("utf-8"))
    if not isinstance(envelope, dict):
        raise ValueError(f"envelope must be a JSON object, got {type(envelope).__name__}")
    return envelope


@app.post("/deliberate")
async def deliberate(request: Request) -> Response:
    """The push endpoint. One escalation in, one journal entry out.

    Returns 204 on both success and on a message this build cannot read, because
    Pub/Sub retries anything else until the subscription's retention expires. A
    poison payload retried forever is an infinite loop that bills a model on
    every attempt, so the failure is journaled here and acknowledged.
    """
    if service_role() != ACTOR:
        return Response(status_code=400, content="this instance is the observer")

    store = FirestoreStore()
    try:
        envelope = decode_push(await request.json())
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        store.append_journal(
            JournalEntry(
                ts=_now(), slug=None, name=None,
                delta="A push message arrived that this build could not read.",
                trigger="manual",
                tier1=Tier1Verdict(
                    significant=False,
                    reason=(
                        "The actor received a Pub/Sub message whose payload it could not "
                        "decode, so no corner was identified and nothing was deliberated on. "
                        "The message was acknowledged rather than retried, because a payload "
                        "this build cannot parse will not parse on the tenth attempt either."
                    ),
                    by_rule=True, basis="unreliable",
                ),
                error=f"undecodable push message: {e}",
            )
        )
        return Response(status_code=204)

    _triage, decider, model_note = select_brains()

    # The actor journals its own decision, so the actor is where that decision
    # has to be published from. The observer's sweep publishes its own entries.
    publishing = None
    if PUBLISH:
        from .ingest import StreetCredClient
        from .publisher import DecisionPublisher
        from .publishing_store import PublishingStore

        publishing = PublishingStore(
            store,
            DecisionPublisher(
                StreetCredClient(),
                append_journal=store.append_journal,
                append_publish_log=getattr(store, "append_publish_log", None),
            ),
        )
        store = publishing

    actor = Actor(
        store,
        decider,
        DryRunActuator(OUTBOX_DIR, run_id=envelope.get("runId") or "push"),
        ActionBudget.from_env(),
        degraded=model_note,
        run_id=envelope.get("runId"),
        tokens=TokenBudget.from_env(),
    )
    await actor.handle(envelope)
    # Drained before the handler returns. Cloud Run keeps the request alive for
    # the whole push, so awaiting is safe and nothing needs waitUntil semantics.
    if publishing is not None:
        await publishing.flush()
    return Response(status_code=204)
