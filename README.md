# The Corner Watchdog

An autonomous agent that reads San Francisco's street data every morning, compares it to
what it saw yesterday, and decides on its own whether anything changed enough to act on.
Cheap triage looks at every change; expensive deliberation runs only on what triage
escalates. Most mornings it decides to do nothing, and it publishes those mornings too,
with the reasoning attached.

**The live diary: [streetcred.thealexschroeder.workers.dev/watchdog](https://streetcred.thealexschroeder.workers.dev/watchdog)**

## Origin disclosure

StreetCred, the display surface this agent publishes to, **predates this hackathon** and was
built at a prior Build Club event. The Corner Watchdog, meaning this repository and every
line in it, is **entirely new work** built for All Things Agentic. The only change made to
StreetCred for this project is one authenticated ingest endpoint and one page that renders
what the agent decided.

## Why the declines are the product

An agent that only publishes its actions is showing you a highlight reel. Anyone can build
something that fires on every change; the hard part, and the part that makes an agent
trustworthy enough to leave unsupervised, is the deciding not to. So the restraint rate is
the headline number on the public page, every decline is journaled with its reasoning as a
first-class entry, and no number anywhere is inflated to make a funnel look busier.

## Architecture

```
Cloud Scheduler  (06:40 PT daily, plus an hourly light tick)
      |
      v
OBSERVER  (ADK agent, Cloud Run)
      reads DataSF -> diffs against Firestore snapshots
      GEMMA triage per delta: significant or not          <- the reflex tier
      publishes significant deltas to Pub/Sub
      journals every evaluation, NOT-significant included
      |
      v  (Pub/Sub push)
ACTOR  (ADK agent, Cloud Run)
      GEMINI 3.7 deliberation per delta                   <- the judgment tier
      acts: rescore / re-audit / regenerate letter / flag
      or DECLINES with reasoning, journaled identically
      |
      v
Firestore: snapshots, decision journal, calibration state
StreetCred: POST /api/agent/report  (bearer token, the one trust boundary)
            GET  /watchdog          (the public diary)
```

**Two-tier cognition is the architecture, not a bolt-on.** Gemma is cheap enough to run on
every delta including the empty ones. Gemini is expensive and only ever sees what Gemma
escalated. Underneath both sits a deterministic floor in `delta.py`: any new fatal or severe
collision is significant **by rule**, decided before either model is consulted, so no model
can be talked out of escalating a death. The models only adjudicate the ambiguous middle.

## The honesty rails

The agent does not get to mark its own homework.

- Every number in an agent-written letter is checked against the corner's own DataSF record
  **by StreetCred, not by the agent**, before the letter is stored. The agent sends its own
  `verified` claim; StreetCred recomputes it, stores its own answer, and records the
  disagreement as `selfReportDisputed`.
- A letter for a corner StreetCred has never resolved is rejected with a 409 rather than
  checked against some other corner's record.
- Snapshots that failed a fetch are marked incomplete, and the delta engine **refuses to
  compare them**. A DataSF timeout returning zero rows looks exactly like a corner with no
  collisions, and that is the most expensive way this system could be wrong.
- An exhausted action budget converts an action into a journaled **intent** ("would have
  re-audited, budget reached") rather than a silent skip, so a quiet night caused by a spent
  budget cannot be mistaken for a quiet night caused by a calm city.
- Calibration adjusts thresholds from logged outcomes within hard bounds. **This is threshold
  and rule calibration from logged outcomes, not model retraining.** The public page says
  exactly that sentence and never claims otherwise.

## Spin up locally

Nothing below needs a Google Cloud project. The deterministic core runs and tests offline.

```bash
git clone https://github.com/alejandro-publius/streetcred-watchdog
cd streetcred-watchdog

python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q                 # 21 tests, no network, no credentials
```

To run against real data and a real project:

```bash
cp .env.example .env      # fill in project, location and the ingest token
# The ingest token is the one credential shared with StreetCred. Generate it with:
#   openssl rand -hex 32
# then set the SAME value as a Cloudflare Worker secret on StreetCred:
#   printf '%s' 'THE_TOKEN' | npx wrangler secret put WATCHDOG_INGEST_TOKEN
# and in this project's Secret Manager.

gcloud run deploy watchdog-observer --source . --set-env-vars SERVICE=observer
gcloud run deploy watchdog-actor    --source . --set-env-vars SERVICE=actor
```

## Requirements coverage

| Requirement | How |
| --- | --- |
| Gemini 3 or newer via Vertex AI | `gemini-3.7-flash` for tier-two deliberation |
| Agent Development Kit | Both services are ADK agents with registered tools |
| Google Cloud services (one required) | Cloud Run, Firestore, Pub/Sub, Cloud Scheduler, Secret Manager |
| Additional Google model (bonus) | Gemma for tier-one triage, structurally not decoratively |

## Repository map

| Path | What it holds |
| --- | --- |
| `src/watchdog/schema.py` | Firestore's shape as typed dataclasses. The schema doc is half the architecture writeup, so it lives in code. |
| `src/watchdog/delta.py` | `diff_snapshots` and the rule floor. Deterministic, no model, no network. |
| `src/watchdog/datasf.py` | DataSF reads, copied query-for-query from StreetCred so the two systems can never disagree about a count. |
| `src/watchdog/prompts.py` | Both prompts, versioned. The split between them is the architecture. |
| `src/watchdog/ingest.py` | Posting to StreetCred. Decides nothing, swallows nothing. |
| `tests/` | The cases where a naive diff produces a confident lie. |

## A note on the radius

The build doc specifies an 80 metre radius for corner records. StreetCred's stats query uses
**150 metres**, and its letters say "within 150 meters" in so many words. Since the governing
rule is that the two systems must never disagree about a number, this repo uses 150. The 80
metre figure is StreetCred's hazards-corroboration radius, a different query for a different
purpose.
