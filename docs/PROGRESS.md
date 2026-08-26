# Submission readiness

Written 2026-08-26. **Deadline: 2026-08-31, 5:00 PM PT. Five days remain.**

Every percentage below is items done over items total from the checklist under
it. Nothing here is a feel. A row moves when an artefact exists and can be
pointed at, not when it is understood.

```
Innovation and utility (40%)  [##############------]  70%   needs: actor auto-publish, one cloud round trip
Architecture (30%)            [#################---]  85%   needs: Gemma tier, poison-message handling
Demo readiness (30%)          [########------------]  40%   needs: video, architecture diagram refresh
Bonuses                       [######--------------]  30%   needs: blog, social, Gemma
------------------------------------------------------------------------------
OVERALL                       [#############-------]  65%   26 of 40 items
```

## Innovation and utility, 40 percent

The axis is how much real-world friction the agent removes on its own. Seven of
ten.

| | Item | Evidence |
| --- | --- | --- |
| done | Agent decides autonomously on a schedule | `watchdog-daily-cycle`, 07:00 PT, ENABLED |
| done | Decisions are journaled, declines included | Firestore `journal`, 50 entries |
| done | A decline is a signed decision, not an absence | `decline` tool, `adk_decider.py` |
| done | Public ingest endpoint, authenticated | `POST /api/agent/report`, bearer token |
| done | Ingest validates rather than trusts | six rejection classes, all tested |
| done | Rejections are published, not counted | `/watchdog`, Rejected ingests |
| done | Decisions render on a public page | `/watchdog`, live |
| **not** | The actor publishes automatically after each decision | actor still writes Firestore only |
| **not** | One real cloud cycle proven end to end into the diary | posted by hand, not by the actor |
| **not** | A judge can watch a decision land without being told where to look | needs the auto-publish above |

## Architecture, 30 percent

Eleven of thirteen.

| | Item | Evidence |
| --- | --- | --- |
| done | Google agent framework in use | ADK 2.7.1, `LlmAgent`, five tools |
| done | Multi-agent graph | `SequentialAgent`, triage into decider |
| done | Gemini on Vertex | `gemini-3.5-flash`, `locations/global` |
| done | Deployed on Google Cloud | two Cloud Run services, scale to zero |
| done | Persistent state | Firestore `watchdog` database |
| done | Event-driven decoupling | Pub/Sub topic and push subscription |
| done | Secrets in Secret Manager | `WATCHDOG_INGEST_TOKEN`, scoped accessor |
| done | Least privilege | four service accounts, zero Editor or Owner |
| done | Scheduled trigger | Cloud Scheduler, Pacific |
| done | Guardrails as framework callbacks | budget gate, injection screen, journal write |
| done | Cost and behaviour inspectable | activity inspector on `/watchdog` |
| **not** | Second Google model actually running | tier one is still `RuleTriage`, journaled as degraded |
| **not** | Poison-message handling proven | the 204-on-undecodable path is written, never exercised |

## Demo readiness, 30 percent

Four of ten. This is the weakest axis and the cheapest to move.

| | Item | Evidence |
| --- | --- | --- |
| done | Reproducible spin-up instructions | `README.md`, verified in a clean venv |
| done | Deployment inventory and teardown | `HANDOFF.md` |
| done | `adk web` renders the reasoning trace | confirmed locally |
| done | Filming list written | the report of 2026-08-26 |
| **not** | Demo video recorded | nothing shot |
| **not** | Architecture diagram refreshed for the graph | `docs/architecture.svg` predates the ADK port |
| **not** | Live diary linked from the submission | link exists, submission does not |
| **not** | One rehearsed run-through end to end | never rehearsed |
| **not** | Fallback recording in case Vertex quota refuses | quota already refused twice |
| **not** | Submission form filled | not started |

## Bonuses

Three of ten.

| | Item | Evidence |
| --- | --- | --- |
| done | Public decision ledger | `docs/ledger.html` and `/watchdog` |
| done | Honest degradation disclosure | every entry carries its `degraded` line |
| done | Cost transparency | activity inspector, projected and actual apart |
| **not** | Blog post | `docs/blog_draft.md` is a draft |
| **not** | Social post | `docs/social_draft.md` is a draft |
| **not** | Gemma running as tier one | stand-in only |
| **not** | Letter delivered to a real recipient | dead-ends at a clipboard |
| **not** | A stakeholder has seen it | no conversation yet |
| **not** | Prospect outreach sent | `prospects.csv` built, nothing sent |
| **not** | Second city or corridor | out of scope this week |

## What moves the number most, in order

1. **Actor auto-publish plus one cloud round trip.** Three items on the 40
   percent axis, and it is the difference between an agent that thinks and one
   that acts. Half a day.
2. **Record the video.** Six items on the 30 percent axis. The filming list is
   already written and every screen already exists.
3. **Refresh the architecture diagram.** One item, an hour, and it is on the
   axis judges read first.

Gemma is worth less than it looks: it moves one architecture item and one bonus,
costs a model integration, and the honest degradation line already tells the
story of why tier one is a rule.
