# Architecture

![The Corner Watchdog architecture](architecture.svg)

Source: [`architecture.mmd`](architecture.mmd). Regenerate with:

```bash
npx @mermaid-js/mermaid-cli -i docs/architecture.mmd -o docs/architecture.svg -b transparent
```

## The agent graph

This is the part that changed. Tier two is an Agent Development Kit `LlmAgent`
and the two tiers are now a `SequentialAgent`, so the cost-routed cascade is a
graph rather than a call sequence.

```
SequentialAgent "corner_watchdog"
  |
  +-- GemmaTriageAgent            a custom BaseAgent wrapping the triage path
  |     |                         unchanged: delta.py's rule floor first, then
  |     |                         the Triage implementation, in that order
  |     |
  |     +-- did not escalate ---> tier two is skipped, not entered and excused
  |
  +-- corner_watchdog_decider     LlmAgent, five registered tools
        |
        +-- rescore              \
        +-- regenerate_letter     |  four actions, each requiring the published
        +-- re_audit              |  claim it corrects to be named first
        +-- flag                 /
        +-- decline                 doing nothing, signed and journaled
```

The agent must call exactly one of those five. That is the design claim of the
project expressed as code: doing nothing is not silence, it is a decision with
reasoning attached, landing in the journal in the same shape as an action. Zero
tool calls is an error and two is an error, and neither is counted as restraint.
See [`adk_decider.py`](../src/corner_watchdog/adk_decider.py).

The edge between the two agents is conditional and it is the expensive one. It is
a `before_agent_callback` on tier two rather than `end_invocation` on tier one,
because every sub-agent runs against its own copy of the invocation context: a
triage agent ending its own invocation does not stop the sequence, and the
version that gets this wrong produces an identical journal while billing a model
on every quiet corner. Across the 175 evaluations in the real journal, four would
have reached tier two.

Three guardrails run inside the invocation rather than around it, as ADK
callbacks, so the `adk web` console, the eval set and the production sweep cannot
be run without them:

| Callback | What it does |
| --- | --- |
| `before_model` | The daily action budget. No budget, no model call, and the entry says the deliberation did not happen. |
| `before_model` | The prompt-injection screen on text that arrived from a public API. Not sanitised, not silently declined, journaled with the matched phrase quoted. |
| `after_tool` | The journal write, at the moment the decision is signed. |

Run it locally with `adk web agents`. The graph is exposed for the ADK's tooling
in [`agents/corner_watchdog_graph/agent.py`](../agents/corner_watchdog_graph/agent.py),
which builds the same graph production runs rather than one shaped for a demo.

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
| Cost-routed triage | `GemmaTriageAgent` wrapping `RuleTriage` | Gemma on Vertex | the graph node is real, the model is not |
| Decoupled trigger | `DirectBus`, JSON round trip in process | Pub/Sub | no |
| Agent framework | `SequentialAgent` over two agents, five registered tools | the same, on Cloud Run | yes |
| Deliberation with reasoning traces | `AdkDecider`, an `LlmAgent` | Gemini on Vertex | yes, the agent; the model needs a project |
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

`Decider` is the one that now has two real implementations rather than one.
`DECIDER=adk` is the default and `DECIDER=rule` keeps the deterministic stand-in
selectable, so the two can be compared on the same journal rather than by
argument. The actor cannot tell which one it was handed, which is what makes the
comparison worth anything.

## The one thing the diagram cannot show

Every journal entry now carries a `degraded` line naming which tier was not a
model. That is the load-bearing detail of the whole design: an agent that falls
back quietly produces output indistinguishable from one that did not, so the
fallback says so in the record rather than in a footnote.

It was not always true. The full account of how the claim was false, and of the
audit that counted, is in `LOG.md` under the burn pass. The short version is that
the journal is append only, so the entries written before the field existed cannot
gain it, and the ledger prints how many carry the line instead of rounding up.
