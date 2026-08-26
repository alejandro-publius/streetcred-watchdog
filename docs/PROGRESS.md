# Submission readiness

Written 2026-08-26, updated after the architecture diagram landed. **Deadline: 2026-08-31,
5:00 PM PT. Five days remain.**

Every percentage below is items done over items total from the checklist under
it, counted by `tools/check_numbers.py` rather than typed. Nothing here is a
feel. A row moves when an artefact exists and can be pointed at, not when it is
understood.

```
Innovation and utility (40%)  [####################] 100%   nothing outstanding
Architecture (30%)            [####################] 100%   nothing outstanding
Demo readiness (30%)          [############--------]  58%   needs: video, rehearsal, submission
Bonuses                       [########------------]  40%   needs: blog, social, outreach
------------------------------------------------------------------------------
OVERALL                       [###############-----]  76%   34 of 45 items
```

This pass wired Gemma as tier one, which closes the architecture axis and one
bonus, and added the claim pass, the Devpost write-up and the demo script.

**The header used to be wrong, and that is worth naming rather than quietly
fixing.** Until this pass it read 75 percent, 30 of 40 items. Its own tables held
43 rows and 29 done, which is 67 percent. The chart and the evidence for it sit
four screens apart, and a figure written by hand at that distance drifts exactly
the way every other figure in this repository drifted before it was made a build
step. So the chart is now rendered from the rows by `tools/check_numbers.py`, and
the build fails when the two disagree. The number went down. That is what a
measurement is for.

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

Thirteen of thirteen.

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
| done | Second Google model actually running | Gemma on Vertex as tier one, `tier1.decidedBy` per entry |

## Demo readiness, 30 percent

Seven of twelve. The video is now most of what is left.

| | Item | Evidence |
| --- | --- | --- |
| done | Reproducible spin-up instructions | `README.md`, verified in a clean venv |
| done | Deployment inventory and teardown | `HANDOFF.md` |
| done | `adk web` renders the reasoning trace | confirmed locally |
| done | Filming list written | `docs/DEMO_SCRIPT.md`, nine screens in order |
| done | Devpost write-up drafted | `docs/SUBMISSION.md` |
| done | Narration script, timed and marked live or recorded | `docs/DEMO_SCRIPT.md`, ends 3:56 |
| **not** | Demo video recorded | nothing shot |
| done | Architecture diagram refreshed for the graph | `docs/architecture.png`, 11 nodes, inline in both READMEs |
| **not** | Live diary linked from the submission | link exists, submission does not |
| **not** | One rehearsed run-through end to end | never rehearsed |
| **not** | Fallback recording in case Vertex quota refuses | quota has refused twice |
| **not** | Submission form filled | not started |

## Bonuses

Four of ten.

| | Item | Evidence |
| --- | --- | --- |
| done | Public decision ledger | `docs/ledger.html` and `/watchdog` |
| done | Honest degradation disclosure | every entry carries its `degraded` line |
| done | Cost transparency | activity inspector, projected and actual apart |
| **not** | Blog post | `docs/blog_draft.md` is a draft |
| **not** | Social post | `docs/social_draft.md` is a draft |
| done | Gemma running as tier one | `google/gemma-4-26b-a4b-it-maas`, `locations/global` |
| **not** | Letter delivered to a real recipient | dead-ends at a clipboard |
| **not** | A stakeholder has seen it | no conversation yet |
| **not** | Prospect outreach sent | `prospects.csv` built, nothing sent |
| **not** | Second city or corridor | out of scope this week |

## What moves the number most, in order

1. **Record the video.** Five items on the 30 percent axis, and it is now the
   only axis holding the total down. The filming list is written, every screen
   it names exists and is live, and the diagram it opens on is current as of
   today rather than a week stale.
2. **Fill the submission form and link the live diary.** Two items, both
   clerical, both worth more than they cost.
3. **Rehearse it once end to end.** The script is written and timed; nobody has
   read it aloud against the live screens, which is where a four minute video
   turns out to be five.

## One thing the first live round trip found

The agent's first real deliberation acted, claiming it had redrafted a letter,
and StreetCred refused to publish that claim: the site holds no letter for that
corner, because the deployed actuator is a dry run that writes to `/tmp`. The
refusal is on the public page with its reason.

That is the validation gate doing exactly what it was built for on its first
real test, and it is worth stating plainly rather than filing as a bug. The
agent is allowed to decide to act. It is not allowed to tell the public it acted
until the artefact exists on the side that publishes it.
