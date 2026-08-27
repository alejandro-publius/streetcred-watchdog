# The Corner Watchdog

Devpost write-up. Every figure here is measured. Figures that move on their own,
which is the journal and the publish log, carry the time they were read; every
other figure is checked against the repository by `tools/check_numbers.py`, which
fails the build when it drifts.

## Inspiration

I moved to the Bay Area and started walking to places instead of driving to
them, and after a few months I noticed I had opinions about intersections. There
is one near me where the crossing signal gives you eleven seconds and the
crosswalk paint has been gone since before I arrived. Nothing about it is a
secret. The city publishes the collision record for that corner, and anyone can
read it, and nobody does, because reading it means knowing it exists and knowing
what to ask it.

What bothered me was not that the information was hidden. It was that the
information was sitting there, in public, being ignored by everyone including
me, and the only thing standing between a resident and it was that no one was
watching on their behalf. So I wanted something that watched. Not something that
alerted constantly, which is how a monitoring tool teaches you to ignore it, but
something that looked every morning and told you honestly that nothing had
changed, so that the morning it said something had changed you would believe it.

That turned out to be the harder half. Building an agent that acts is
straightforward. Building one whose restraint you can trust is the whole
problem, because an agent that does nothing and an agent that is broken produce
identical output unless you make it produce more.

## What it does

Every morning at 07:00 Pacific, it reads San Francisco's own collision and
street-condition records for twenty five intersections, compares each one to
what it recorded yesterday, and decides on its own whether anything changed
enough to be worth acting on.

Most mornings it decides no. It publishes those mornings too, with the reasoning
attached, at a public address nobody has to be told to look at. When it does
decide something changed, it can rescore the corner, redraft the corner's public
letter, re-audit its imagery, or flag it for a human, and it has to name which
published claim the change made wrong before it is allowed to do any of them.

The decision to do nothing is not the absence of a decision here. It is a tool
call named `decline`, it carries its reasoning, and it lands in the journal in
exactly the same shape an action does. Zero tool calls is an error and two is an
error.

## How we built it

**The countable version first.** About 51,000 lines across two repositories.
1,109 tests, all offline and all credential free: 697 on the agent in 14
seconds, 12 of which is a single lock-release test waiting on a real timeout,
and 431 on the display surface in 1.2. 25
intersections watched, pinned so the roster cannot drift without a journal
entry. 125 unauthenticated queries per sweep across 5,905 collision and
street-condition records. 227 decisions in the deployed journal and 100 publish
receipts, read from Firestore at 2026-08-26T22:05Z; both grow on every scheduled
run, so they are dated rather than pinned. Two model tiers, five tools, six ingest rejection classes, four
service accounts, zero with Editor or Owner. Eleven boxes in the architecture
diagram and every one of them is running.

**The shape.** A Cloud Scheduler job wakes an Observer service on Cloud Run. It
reads DataSF, diffs each corner against the snapshot it stored in Firestore, and
runs a deterministic floor first: a new death or severe injury escalates by rule
before any model is consulted, so no model can be talked out of the one thing
that matters most. Whatever is left, the ambiguous middle, goes to tier one,
which is Gemma on Vertex. Only what Gemma escalates is published to Pub/Sub, and
only that reaches the Actor service, where tier two is an Agent Development Kit
`LlmAgent` on Gemini with five registered tools. Across 175 real evaluations, the
number that reached tier two is four. The other 171 were free.

The two tiers are a `SequentialAgent`, and the conditional edge between them is
the architecture rather than a detail. The gate is a `before_agent_callback` on
tier two, not an early return inside it, because a sub-agent that returns early
has already been built and billed.

Every decision is written to an append-only Firestore journal and then posted to
StreetCred, the public display surface, over one authenticated endpoint with one
bearer token in one direction. The cloud writes in and reads nothing back.
StreetCred validates on content rather than trusting the sender, and refuses six
classes of claim including one it cannot verify from its own records. Refusals
are published beside the decisions, because a gate whose refusals are invisible
is indistinguishable from no gate.

Guardrails are framework callbacks rather than wrapper code: a budget gate and
an injection screen as `before_model_callback`, the journal write as an
`after_tool_callback`.

## Challenges we ran into

**Application Default Credentials lied about themselves on Cloud Run.** The
preflight check tested for a credentials file on disk. Cloud Run has no such
file; it has a metadata server. So a service whose entire identity is a working
Google credential reported "no application default credentials on this machine",
fell back to the deterministic tier, and kept running. Nothing failed. The only
thing that made it visible was the degradation line the entries carry, which
exists for exactly this and had never earned its keep before.

**Firestore's client double-encodes the default database name.** Every call
against `(default)` came back rejected, with `%2528default%2529` in the URL:
`(` encoded to `%28`, then the `%` encoded again to `%25`. Reproduced across
library versions and both transports. The fix was to stop using the default
database and create a named one.

**Cloud Run reserves `/healthz`.** The platform answers that path itself with
its own 404 and never forwards it. A health endpoint on the single most obvious
name is invisible to everything outside the container, and the failure looks
like a routing bug in your own app. Renamed to `/status`, with a test that pins
the name so nobody helpfully renames it back.

**Image text corruption is a property of the model class, not of one vendor.**
Piloting a cheaper image path, every render garbled the street signs and
reproduced a watermark as invented words. That is disqualifying for a product
whose whole argument is that every figure traces to a checkable record: a
photograph of a named intersection carrying a fabricated street sign is the
first thing anyone looking to discredit it would find. The finding was that
neither rung of the cheaper ladder solved it, so it was not a budget problem.
Cost of finding out: 767 free-tier units and no deploy.

**A counter read the wrong number and did not know.** The documentation guard
ran `pytest --collect-only`, read the first integer out of it, and ignored the
exit code. Run under the wrong interpreter, five files fail to import, pytest
prints "530 tests collected, 5 errors" and exits non-zero, and the guard's
`--fix` mode wrote 530 into the README where 661 was true. A partial collection
is not a smaller suite. It now refuses rather than guessing, and it names the
interpreter it could not collect under.

## Accomplishments that we're proud of

The restraint rate is a real measurement and it is defended against itself. It
is trivially gameable by declining everything, so three things are kept out of
the numerator, each found by breaking the page on purpose: an entry that
errored, an entry where the agent wanted to act and the budget refused it, and a
decline that a rule settled by observing there was nothing to compare. That last
split is the one that matters, because a rate that folds them together describes
a quiet city while reading as a careful agent.

Guards that fail the build when the prose stops being true. A check that flips
its own state the moment an ADK import lands and fails until the README catches
up. A check that holds the README to what the wiring code actually wires. A
check that renders the progress chart from the checklist under it, which caught
the chart claiming 75 percent when its own tables said 67. Every guard is
mutation tested, because a green new test proves nothing until you break the
thing on purpose and watch it go red.

And the first real cloud deliberation was refused by our own validation gate.
The agent claimed it had redrafted a letter; the site holds no letter for that
corner, because the actuator is a dry run. That refusal is on the public page
with its reason. It is the best thing that happened all week.

## What we learned

The failure mode worth designing against is not the agent doing something wrong.
It is the agent producing output indistinguishable from correct while being
wrong. Every hard bug here had that shape: credentials that reported themselves
absent while working, a health check invisible from outside, a counter reading a
smaller number from a broken run, a progress bar four screens from its own
evidence. None of them threw. All of them were caught by something that compared
a claim to the thing it was a claim about.

The corollary is that honesty has to be a build step. A degradation note written
by hand is a note that stops being written. The version of this project that
carried its admissions in prose had a README asserting every journal entry
carried a degradation line while not one of the first 150 did.

We also learned that "which tier decided this" is a per-entry fact and not a
per-run one. Gemma reaches Vertex through a shared pool that refuses roughly one
call in three, so one sweep produces entries from the model and entries from the
rule that stood in. A run-level note is identical on both and therefore true of
neither.

## What's next

Give the outcome loop something to work with. `calibrate.review` now runs every
cycle and reads what tier two did with tier one's escalations, but five
escalations have reached tier two and its floor is twenty, so it refuses and says
so. It needs a month of quiet mornings and a few loud ones before it moves
anything, which is the honest answer and not a fast one.

Then a second corridor, and the letter reaching a real recipient, which needs a
human to read a full dry-run outbox and agree with every letter in it. That is a
boundary rather than a step, and it is not going to be crossed by a flag.

## Bonuses

- **Public decision ledger.** Every decision, every decline, every rejected
  ingest, each with its reasoning, at `/watchdog`.
- **Honest degradation disclosure.** Every entry carries which tier decided it,
  and the ledger prints how many entries carry the field rather than claiming
  all of them do, because the journal is append only.
- **Cost transparency.** An activity inspector with projected and actual spend
  kept apart.
- **Two Google models.** Gemma as the reflex tier, Gemini as the judgment tier,
  on one credential path with no second key.

## Built With

Python, `google-adk` 2.7.1, Google Cloud Run, Firestore, Pub/Sub, Cloud
Scheduler, Secret Manager, Vertex AI, Gemma, Gemini, FastAPI, Cloudflare
Workers, Workers KV, JavaScript, DataSF open data.

## Try it out

- **The public diary**, where the agent's decisions land:
  <https://streetcred.thealexschroeder.workers.dev/watchdog>
- **The display surface** it publishes to:
  <https://streetcred.thealexschroeder.workers.dev>
- **The agent's source**, including the architecture diagram, the patterns
  write-up and the log of what went wrong: this repository.

Run the whole loop locally against live city data, with no credentials and no
cloud account, in three commands. The README has them.
