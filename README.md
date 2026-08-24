# The Corner Watchdog

An autonomous agent that reads San Francisco's street data every morning, compares it to
what it saw yesterday, and decides on its own whether anything changed enough to act on.
Most mornings it decides to do nothing. It publishes those mornings too, with the
reasoning attached.

I moved to the Bay Area and ended up spending a lot of time thinking about the
intersections I walk through. This is what came of that: a machine that watches the
twenty five worst corners in the city, on its own schedule, and tells you what it decided
not to do.

**The ledger: [`docs/ledger.html`](docs/ledger.html)** &middot;
**[Architecture](docs/architecture.md)** &middot;
**[Decisions and rejections](DECISIONS.md)** &middot;
**[What went wrong](LOG.md)**

---

## Disclosure

Read this before the rest.

- **StreetCred, the display surface this agent publishes to, predates this hackathon.**
  It was built at a prior Build Club event. The Corner Watchdog, meaning this repository
  and every line in it, is entirely new work built for All Things Agentic.
- **None of the Google Cloud integration is wired.** Not Vertex, not Gemini, not Gemma,
  not Firestore, not Pub/Sub, not Cloud Run. Every one of them sits behind an adapter with
  a working local stand-in, and **no Google Cloud account has been created, authenticated
  to, or touched at any point in this project.** The plan for wiring them is
  [`docs/GEMINI_WIRING.md`](docs/GEMINI_WIRING.md).
  Cloud setup is a ten minute operator task: see [`docs/GCP_PRECONDITIONS.md`](docs/GCP_PRECONDITIONS.md), then [`scripts/preflight_gcp.sh`](scripts/preflight_gcp.sh) to verify.
  The Agent Development Kit port is planned build-window work: `google-adk` is staged in the `cloud` extra and imported by nothing, and `tools/check_adk_claims.py` fails the build if this page ever says otherwise.
- **The agent has never posted anything anywhere.** The live path exists, implements the
  interface, and refuses on every verb.
- **Nothing in this repo has ever observed a real change at a watched corner.** The city
  was quiet for the whole build. Every number below reflects that.

## What it does

- **Watches 25 corners** taken from StreetCred's public scoreboard, pinned so the roster
  cannot drift silently, and journals a corner the moment it stops watching it.
- **Reads the city's own record**, 5,905 collision and street-condition records across the
  watched set, in 125 unauthenticated queries per sweep.
- **Diffs against yesterday** with a deterministic engine that refuses to compare a partial
  fetch, a corrupted baseline, or two readings taken under different queries.
- **Routes by cost.** A cheap tier sees every change; an expensive tier only ever sees what
  the cheap one escalated. Deaths and severe injuries never reach either: they escalate by
  rule, before any model is consulted.
- **Acts into a local outbox** in dry run, rendering the actual letter with the corner's
  actual figures rather than a log line saying a letter would have been written.
- **Publishes every decision**, including and especially the ones that ended in nothing,
  with the reasoning verbatim and a link to the raw journal record.
- **Says when it is degraded.** Every entry now carries a line naming which tier was not
  a model, and the ledger prints how many entries carry it rather than claiming all of
  them do: the journal is append only, so entries written before that field existed
  cannot gain it.

## The numbers

All measured from this repository, on 2026-08-20.

| | |
| --- | --- |
| Agents | 2, an observer and an actor, separated by a bus |
| Cognition tiers | 2, plus a deterministic rule floor beneath both |
| Corners watched | 25 |
| City records covered per sweep | 5,905 (1,136 collision, 4,769 street-condition) |
| Fatalities in the watched set's five year record | 12 |
| Severe injuries in the same record | 129 |
| DataSF queries per sweep | 125, unauthenticated |
| Evaluations journaled | 175 |
| Actions taken | 0 |
| Restraint rate | 100 percent, and the ledger explains why that number is not yet impressive |
| Tests | 503, offline, no credentials, under a second |
| Runtime dependencies | 1 (`httpx`) |
| Google Cloud accounts touched | 0 |

The restraint rate is 100 percent and the ledger says, on its own front page, what that is
made of: 171 of the 175 declines were settled by a rule rather than weighed by a tier, so
the number still mostly measures a quiet city rather than a careful agent. The other four
are the first real ones. On the sweep at 16:01 on 2026-08-20 the city's 311 counts moved at
four watched corners, tier one weighed each and declined as ordinary variance. A number
that flatters the system is worth less than one that explains itself.

## Quick start

Verified in a clean clone and a fresh virtual environment on 2026-08-20: 15 packages
installed including pip itself and the project, none of them Google, all 503 tests green.

```bash
git clone https://github.com/alejandro-publius/streetcred-watchdog
cd streetcred-watchdog

python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # one runtime dependency: httpx

pytest -q                        # 503 tests, no network, no credentials
python -m corner_watchdog run --cycles 2  # the whole loop, twice, against live DataSF
open docs/ledger.html            # every decision, restraint rate on top
```

Two cycles minutes apart will correctly find that nothing changed, which means the
expensive half of the loop never runs. To exercise it:

```bash
python -m corner_watchdog rehearse      # constructed baselines, kept out of the real journal
python -m corner_watchdog doctor        # 19 checks: environment, sources, vocabulary, stored state
python -m corner_watchdog schedule      # renders launchd and cron config, installs nothing
python -m corner_watchdog ledger --corner 6th-and-mission
```

## Patterns

Named in the vocabulary the Agent Development Kit uses, with an honest column for whether
they are built.

| Pattern | How it appears here | Status |
| --- | --- | --- |
| Event-driven fan-out | The observer publishes escalations to a bus; the actor subscribes and never reads the observer's state. Locally the bus is an in-process call that round-trips through JSON, so a payload Pub/Sub could not carry fails here rather than in production. | built |
| Cost-routed cascade | A deterministic floor answers most deltas for free, a cheap tier takes the ambiguous middle, and an expensive tier only ever sees escalations. Across 175 real evaluations, the number that would have reached a model is four. | built |
| Human-in-the-loop | `flag` is a first-class action, mandatory alongside any redraft on a new fatality. The live path additionally refuses to send until a human has read a full dry-run outbox and agreed with every letter in it. | built as a gate |
| Decline queue | Declines are journaled by the observer at the moment they are made, never routed through the expensive tier, and rendered at the same visual weight as actions. | built |
| Review and critique verifier | StreetCred recomputes every figure in an agent-written letter from the corner's own record and stores its own answer, recording disagreement as `selfReportDisputed`. The agent does not get to mark its own homework. | planned, not deployed |
| Bounded self-calibration | Thresholds move from logged outcomes inside hard floors and ceilings, with every adjustment journaled with its before and after. This is threshold nudging, not model retraining, and the public page says exactly that. | schema and bounds built, nothing adjusts them yet |

## Why the declines are the product

An agent that only publishes its actions is showing you a highlight reel. Anyone can build
something that fires on every change. The hard part, and the part that makes an agent
trustworthy enough to leave unsupervised, is the deciding not to.

So the restraint rate is the headline number, every decline is a first-class entry with its
reasoning attached, and the page breaks that number down into what was actually weighed
versus what a rule merely observed, because those are different events and adding them
together produces a number that describes a quiet city while reading as a careful agent.

## What went wrong

**A filter that matched nothing, for the entire life of the project.**

`SEVERE_VALUES` held `("Severe Injury", "Suspected Serious Injury")` from the first commit.
Those are CHP's category names. DataSF publishes `Injury (Severe)`. The query was valid
SoQL, matched zero rows, and returned a clean zero for every corner on every sweep, which
made the rule "any new severe injury is significant" a rule that could never fire.

Nothing failed. Nothing could fail. A filter matching nothing is indistinguishable from a
corner where nothing happened. It was found by running the loop against live data and
noticing that all 25 corners reported zero severe injuries while StreetCred's own board
showed 9 at one of them.

Two things came out of it that are worth more than the fix. Every enumerated value the code
puts in a WHERE clause is now pinned against the live vocabulary with the row count carried
alongside, and a cycle refuses to start if they disagree. And the same class of bug turned
up twice more once I knew to look: a `count(*)` alias rename parsing as zero, and a tie in
the district group-by resolving to whatever order the API returned, so a tied corner would
flip district between sweeps and journal it as a real change.

**Then fixing a different bug nearly caused the exact failure this repo exists to prevent.**
Measuring against StreetCred's published figures showed the radius should be 80 metres, not
150. Changing it would have made the next sweep subtract 80 metre counts from 150 metre
counts and report a 40 percent collapse in collisions at all 25 corners on the same
morning, with confident reasoning attached. Snapshots now carry a fingerprint of the query
that produced them and the delta engine refuses to subtract across a change in it. The
cycle after the change journaled 25 refusals naming both fingerprints and took no action.

Full evidence in [`LOG.md`](LOG.md).

## Requirements coverage

Honest column first.

| Criterion | Where it lives | Wired |
| --- | --- | --- |
| Gemini 3 or newer via Vertex AI | `src/prompts/deliberation.md`, `contract.py`, `brains.select_brains()` | **no**, `RuleDecider` stands in |
| Agent Development Kit | not built | **no** |
| Google Cloud services | all behind `ports.py`, plan in `docs/GEMINI_WIRING.md` | **no**, five local stand-ins |
| Additional Google model | `src/prompts/triage.md`, tier one | **no**, `RuleTriage` stands in |
| Autonomous operation | `schedule.py`, `watchdog tick` under a lock | yes, locally |
| Persistent memory | `store.py`, `state/journal.jsonl`, append only | yes, locally |
| Observability | `ledger.py`, `docs/ledger.html`, `docs/states/` | yes |
| Safety and restraint | `delta.py` rule floor, `live.py` refusal, `budget.py` intents | yes |

## Considered and rejected

Fuller versions in [`DECISIONS.md`](DECISIONS.md).

- **Calling a small local model so the demo could say a model ran.** Buys a sentence in a
  pitch, costs the one property this project is about.
- **Mutating real snapshots to force an interesting delta for the demo.** The rehearsal
  constructs the *past* instead, never the present, and every entry it writes says so.
- **A hash for the query fingerprint.** The journal entry that refuses a comparison prints
  it, and `r=80m;collisions=5y;...` tells a reader what happened where `a3f19c` does
  not. No entry ever printed `r=150m`: the old baselines predated the field, so the
  refusals read `not recorded then r=80m...`, which is itself the right answer.
- **Coercing a corrupted stored count to zero.** That is the SEVERE_VALUES failure with a
  different mask. It refuses to load and the file is quarantined instead.
- **Leaving the live path unwritten, or callable behind a flag.** Unwritten hides whether
  the interface fits until the worst moment; callable is how a dry run becomes a live send
  by way of one wrong argument.
- **Quoting Vertex prices from memory in the cost estimate.** Token counts are measured;
  the rates are left blank with the arithmetic beside them.

## Repository map

| Path | What it holds |
| --- | --- |
| `src/corner_watchdog/ports.py` | Every cloud dependency, named as a protocol. The seams. |
| `src/corner_watchdog/delta.py` | `diff_snapshots` and the rule floor. Deterministic, no model, no network. |
| `src/corner_watchdog/datasf.py` | DataSF reads, and the constants that were wrong for a fortnight. |
| `src/corner_watchdog/vocabulary.py` | Guards on every enumerated value that goes into a query. |
| `src/corner_watchdog/observer.py` | The sweep: look, compare, triage, escalate or decline. |
| `src/corner_watchdog/actor.py` | Deliberate on what was escalated, then act or decline. |
| `src/corner_watchdog/contract.py` | The decision schema both tiers must answer in, with a validator. |
| `src/prompts/` | Both prompts in full, with ten worked examples the test suite parses. |
| `src/corner_watchdog/live.py` | The live path. Implements the interface, refuses every verb. |
| `src/corner_watchdog/ledger.py` | The journal as a page, restraint rate on top, declines at full size. |
| `tests/` | 503 of them. The cases where a naive implementation produces a confident lie. |
| `LOG.md`, `DECISIONS.md` | What was found by running it, and what was decided and rejected. |

## A note on the radius

This repo used 150 metres until 2026-08-20, on the strength of reading StreetCred's source
rather than measuring its output. That was wrong.

Querying DataSF at **80 metres over five years** reproduces StreetCred's published
scoreboard counts exactly, in all four severity categories, for six of six corners probed.
Across the whole watched set, 80 metres agrees with StreetCred on fatalities at 25 of 25
corners, severe injuries at 24 of 25, and total injury collisions at 23 of 25.

Two corners still disagree. `gough-and-haight` matches at roughly 90 metres rather than 80,
so StreetCred's corner geometry is not a uniform circle and the exact rule is not known.
The 311 window could not be pinned at all. The agent keeps its own three year window and
says so in every letter, so the two figures are openly different quantities rather than two
claims about the same thing that disagree.
