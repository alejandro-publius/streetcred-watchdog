# Architecture

![The Corner Watchdog architecture](architecture.svg)

Source: [`architecture.mmd`](architecture.mmd). Regenerate with:

```bash
npx @mermaid-js/mermaid-cli -i docs/architecture.mmd -o docs/architecture.svg -b transparent
```

## Why the diagram has two layers

Because the system has two layers and only one of them exists.

The **dashed green layer ran**. Every box in it executed on a laptop, against San
Francisco's open data portal and StreetCred's public scoreboard, both
unauthenticated reads. No Google Cloud account was created, authenticated to, or
touched at any point in this project.

The **amber band did not run**. It is an inventory of what each stand-in is a
stand-in for. Drawing the two as one connected system would claim something that
is not true, and this repository's entire argument is that its output can be
trusted without checking.

The **red box is neither**. `delta.py` is deterministic arithmetic with no model,
no network and no cloud in it, and it is the piece that decides anything
expensive to get wrong. A new fatality escalates by rule, before either tier is
consulted, so no model can be talked out of it.

## What each component is for

| Rubric job | Ran tonight | Stands in for | Wired |
| --- | --- | --- | --- |
| Timed trigger | launchd or cron, rendered by `watchdog schedule` | Cloud Scheduler | no |
| Scale-to-zero runtime | `python -m corner_watchdog` | Cloud Run | no |
| Cost-routed triage | `RuleTriage` | Gemma on Vertex | no |
| Decoupled trigger | `DirectBus`, JSON round trip in process | Pub/Sub | no |
| Deliberation with reasoning traces | `RuleDecider` | Gemini on Vertex | no |
| Persistent cross-session memory | `LocalJsonStore`, `state/journal.jsonl` | Firestore | no |
| Zero credentials in code | `.env`, gitignored, never committed | Secret Manager | no |
| The one trust boundary | `DryRunActuator`, writes to `outbox/` | `POST /api/agent/report` | no |
| Public observability | `docs/ledger.html` | the same page, hosted | rendered locally |

Five of those rows are protocols in [`ports.py`](../src/corner_watchdog/ports.py):
`Store`, `Bus`, `Triage`, `Decider` and `Actuator`. Each currently has one
implementation, the local one, and the cloud column names what a second would be.
The other four rows are not protocols and should not be read as though they were:
the timed trigger is launchd or cron calling the CLI, the runtime is the process
itself, credentials are a gitignored file, and the ledger is a rendered page.

Swapping a protocol is a constructor change at one of two wiring sites,
`select_brains()` in `brains.py` for the two tiers and `run_cycle()` in
`runner.py` for the rest, and nothing above the seam knows which side is running.
The plan for doing that is [`GEMINI_WIRING.md`](GEMINI_WIRING.md).

## The one thing the diagram cannot show

Every journal entry now carries a `degraded` line naming which tier was not a
model. That is the load-bearing detail of the whole design: an agent that falls
back quietly produces output indistinguishable from one that did not, so the
fallback says so in the record rather than in a footnote.

It was not always true. The full account of how the claim was false, and of the
audit that counted, is in `LOG.md` under the burn pass. The short version is that
the journal is append only, so the entries written before the field existed cannot
gain it, and the ledger prints how many carry the line instead of rounding up.
