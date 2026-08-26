# Submission readiness

Written 2026-08-26, updated after the loop closed. **Deadline: 2026-08-31,
5:00 PM PT. Five days remain.**

Every percentage below is items done over items total from the checklist under
it. Nothing here is a feel. A row moves when an artefact exists and can be
pointed at, not when it is understood.

```
Innovation and utility (40%)  [####################] 100%   nothing outstanding
Architecture (30%)            [##################--]  92%   needs: Gemma tier
Demo readiness (30%)          [########------------]  40%   needs: video, architecture diagram refresh
Bonuses                       [######--------------]  30%   needs: blog, social, Gemma
------------------------------------------------------------------------------
OVERALL                       [###############-----]  75%   30 of 40 items
```

Previous pass: 65 percent, 26 of 40. The loop closing moved three items on the
highest-weighted axis and one on architecture.

## Innovation and utility, 40 percent

Ten of ten. The agent decides on its own and what it decides reaches a public
page without anyone being told where to look.

| | Item | Evidence |
| --- | --- | --- |
| done | Agent decides autonomously on a schedule | `watchdog-daily-cycle`, 07:00 PT, ENABLED |
| done | Decisions are journaled, declines included | Firestore `journal` |
| done | A decline is a signed decision, not an absence | `decline` tool, `adk_decider.py` |
| done | Public ingest endpoint, authenticated | `POST /api/agent/report` |
| done | Ingest validates rather than trusts | six rejection classes, all tested |
| done | Rejections are published, not counted | `/watchdog`, Rejected ingests |
| done | Decisions render on a public page | `/watchdog`, live |
| done | The actor publishes automatically after each decision | `PublishingStore`, run 20260826T202501Z |
| done | One real cloud cycle proven end to end into the diary | 24 published, 0 failed |
| done | A judge can watch a decision land unaided | homepage links the diary |

## Architecture, 30 percent

Twelve of thirteen.

| | Item | Evidence |
| --- | --- | --- |
| done | Google agent framework in use | ADK 2.7.1, `LlmAgent`, five tools |
| done | Multi-agent graph | `SequentialAgent`, triage into decider |
| done | Gemini on Vertex | `gemini-3.5-flash`, `locations/global` |
| done | Deployed on Google Cloud | two Cloud Run services, scale to zero |
| done | Persistent state | Firestore `watchdog` database |
| done | Event-driven decoupling | Pub/Sub topic and push subscription |
| done | Secrets in Secret Manager | version 2, scoped accessor on both services |
| done | Least privilege | four service accounts, zero Editor or Owner |
| done | Scheduled trigger | Cloud Scheduler, Pacific |
| done | Guardrails as framework callbacks | budget gate, injection screen, journal write |
| done | Cost and behaviour inspectable | activity inspector on `/watchdog` |
| done | Poison handling proven | a 4xx is dead on arrival, never retried, journaled |
| **not** | Second Google model actually running | tier one is still `RuleTriage`, journaled as degraded |

## Demo readiness, 30 percent

Four of ten. The weakest axis and the cheapest to move.

| | Item | Evidence |
| --- | --- | --- |
| done | Reproducible spin-up instructions | `README.md`, verified in a clean venv |
| done | Deployment inventory and teardown | `HANDOFF.md` |
| done | `adk web` renders the reasoning trace | confirmed locally |
| done | Filming list written | report of 2026-08-26 |
| **not** | Demo video recorded | nothing shot |
| **not** | Architecture diagram refreshed for the graph | `docs/architecture.svg` predates the ADK port |
| **not** | Live diary linked from the submission | link exists, submission does not |
| **not** | One rehearsed run-through end to end | never rehearsed |
| **not** | Fallback recording in case Vertex quota refuses | quota has refused twice |
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

1. **Record the video.** Six items on the 30 percent axis, and it is now the
   only axis holding the total down. The filming list is written and every
   screen it names exists and is live.
2. **Refresh the architecture diagram.** One item, an hour, on the axis judges
   read first.
3. **Gemma as tier one.** One architecture item and one bonus, and it costs a
   model integration. Still the lowest ratio of the three: the honest
   degradation line already tells the story of why tier one is a rule.

## One thing the first live round trip found

The agent's first real deliberation acted, claiming it had redrafted a letter,
and StreetCred refused to publish that claim: the site holds no letter for that
corner, because the deployed actuator is a dry run that writes to `/tmp`. The
refusal is on the public page with its reason.

That is the validation gate doing exactly what it was built for on its first
real test, and it is worth stating plainly rather than filing as a bug. The
agent is allowed to decide to act. It is not allowed to tell the public it acted
until the artefact exists on the side that publishes it.
