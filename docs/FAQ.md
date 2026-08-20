# Questions a judge would reasonably ask

Written before anyone asked them, which is the only time these are worth
anything. Where the answer is bad, it says so.

---

## Why two agents and not thirty four?

Because I could not name a job for a thirty fifth.

The split that exists is load-bearing: an observer that looks and a decider that
acts, separated by a bus, because on Cloud Run they are separate services behind
a push subscription and the observer genuinely cannot read the actor's state. The
local bus round-trips its payload through JSON for exactly that reason, so
anything Pub/Sub could not carry fails on a laptop rather than in production.

A larger swarm would have been easy to build and easy to demo. It would also have
been an architecture diagram in search of a problem, and every extra agent is
another place a number can be invented. The number of agents is not the
interesting variable here. Whether you can trust what they wrote down is.

## Why are the declines the product?

The main argument is in the README, under "Why the declines are the product",
and is not repeated here.

There is a second reason, less flattering, and it is only here. The failure mode of an automated
monitor is not silence, it is confident noise. A system that redrafts a letter
every morning trains its readers to ignore it within a week. Restraint is the
feature that keeps the output worth reading.

## Your restraint rate is 100 percent. Is that not trivially achievable by doing nothing?

Yes, and the page says so before you get a chance to ask.

Almost. 171 of the 175 declines were settled by a rule: most by observing that
nothing had changed, twenty five by refusing a comparison outright because the
query had changed underneath them.

The other four are the first real thing this agent has done. On the sweep at
16:01 on 2026-08-20, San Francisco's 311 data moved: three watched corners gained
a street-condition report and one lost one. Tier one weighed each of the four and
declined, because a swing of one at a corner that already has hundreds on file is
ordinary variance and the bar is fifteen. Those four are the only entries in the
journal where anything looked at a real change and chose to leave it alone.

Four out of a hundred and seventy five is not a track record. It is the number
being something other than zero for the first time, and the page prints it as
four rather than rounding it into the rest. The ledger prints that breakdown
directly under the headline number, in the same eyeline, and states that the
figure currently measures a quiet city rather than a careful agent and would look
identical if both tiers were broken.

The number becomes meaningful the first time a decline appears with basis
`triage` or a tier two verdict of `decline`. It has not happened yet. The city
was quiet for the whole build.

## Why do the grades never move when there is press coverage?

Because press is not a count and the grade is computed from counts.

A newspaper article about a corner is evidence that people are paying attention
to it, not evidence that its collision record changed. Letting coverage move a
published safety grade would mean the grade tracks salience rather than harm,
and the corners that get written about are not the same corners as the corners
where people get hurt.

Press is designed to escalate in tier one, and `src/prompts/triage.md` carries a
worked example of it. Being straight about the state of that: the rendered tier
one prompt in `prompts.py` has no press field yet, and nothing in this repo
produces a press signal, so that example teaches an input the loop cannot
currently supply. Tier two does take press, as `none on file`.

What press escalates to, once wired, is a *look*, because the published page
cites what is on file and a new item means the page is now missing something a
reader would expect to see. Escalation is not action.

## What happens when the laptop is closed?

Nothing runs, and the page says nothing ran.

The days-watched strip on the ledger is drawn from journal timestamps rather than
from a run counter, so a day with no cycle renders as a hollow cell and is named
in prose with the length of the longest gap. A monitor that reports an unbroken
streak while quietly omitting the days it was switched off is making the same
move as publishing only its actions, which the README's restraint section covers.

`launchd` fires `watchdog tick` every six hours with `RunAtLoad` set to false,
deliberately, so that opening the lid does not turn a schedule into a burst
against a public data portal. Both `tick` and `run` take the same cycle lock, so
a scheduled run cannot overlap with one started by hand. A lock whose owner
process is gone is broken straight away; one whose owner is still alive is broken
only after an hour. Either way the break is recorded in `state/locks.log` rather
than the decision journal, because machine noise must not inflate the denominator
of the restraint rate.

## What would filing an actual Open311 report require?

More than a token, which is the honest short answer.

Technically it is small: Open311 has a documented POST endpoint and San Francisco
runs an instance. The reasons it has not been built are not technical.

1. **A false report has a cost somebody else pays.** Every figure in a filed
   report would come from this agent's own arithmetic against a query I have
   already been wrong about once, on a radius I only measured correctly on the
   twentieth. A wrong 311 report wastes an inspector's morning.
2. **Nothing here is rate limited against a public queue.** The action budget
   caps actions per day, not reports per corner per week, and the difference
   matters when the recipient is a city department rather than a file.
3. **There is no retraction path.** The journal is append only by design, which
   is right for a record and wrong for something that has left the building.
   Before anything files, there has to be a way to withdraw a filing and say so.
4. **No human has read a full outbox.** That is one of the three blockers already
   named in `live.py`, and it applies with more force to a city system than to
   StreetCred.

The current design routes toward a human instead: `flag` is a first-class action
and is mandatory alongside any redraft when a fatality appears.

## Why is none of the Google Cloud integration wired?

Because I ran out of evening, and because the part I chose to spend it on was
making the loop trustworthy rather than making it hosted.

That was a real trade and I would make it again. What exists is a loop that runs
end to end with every cloud dependency behind a protocol, both prompts written in
full with ten worked examples the test suite parses against the decision schema,
and a wiring plan with measured token counts. What does not exist is a single
call to Vertex.

The thing that keeps this honest rather than merely unfinished: every journal
entry now says which tier was not a model. An agent that degrades quietly
produces output indistinguishable from one that did not, which would make the
entire record worthless.

That claim was itself false until an audit counted, and the ledger now prints how
many entries carry the line rather than claiming all of them do. The full account
of how it was false is in `LOG.md`, under the audit section of the burn pass.

## How do I know the agent has not posted anything?

Four ways, in increasing order of how much you have to trust me.

1. `live.py` implements the actuator protocol and raises on every verb. It reads
   no token and imports no HTTP client, and a test asserts both.
2. `tools/check.sh` greps the local loop for any import of `ingest.py`, the one
   module that can POST, and fails if it finds one.
3. A `WATCHDOG_INGEST_TOKEN` does exist in the local `.env`, and this is the
   more useful fact rather than the embarrassing one: nothing posted anyway.
   Nothing in the package loads `.env`, so the value never reaches the process
   environment and `StreetCredClient` resolves an empty token. The guarantee is
   not that the credential is missing; it is that the code refuses even when it
   is not. `.env` is gitignored and `git log --all --full-history -- .env`
   returns nothing, so it has never been committed.
4. Every dry-run outbox carries a `MANIFEST.txt` saying what was rendered and
   that nothing was sent, written even on runs that produced no artefacts.

## What is the biggest thing still wrong?

Two corners disagree with StreetCred and I do not know why.

`gough-and-haight` reports 41 injury collisions where StreetCred publishes 56,
and it matches almost exactly at 90 metres rather than the 80 that reproduces six
other corners exactly. So StreetCred's corner geometry is not a uniform circle
and I have not worked out what it is. The 311 window could not be pinned at all,
at any of seven window lengths tried.

Both are written up in `DECISIONS.md` under a heading that says they are
unresolved, because the alternative was to round them away.
