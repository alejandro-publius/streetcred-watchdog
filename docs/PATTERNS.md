# What this is, in the vocabulary you already have

Six patterns, named the way they are usually named, each with the part of this
repository that implements it and the test that fails if the claim stops being
true. A pattern nobody can fail is a label, not a property, so every paragraph
below ends with what breaks.

Where the honest answer is narrower than the pattern's usual claim, the
paragraph says so rather than rounding up. Three of them are narrower.

## Sequential orchestration, and why the order is the point

The two tiers are an Agent Development Kit `SequentialAgent` over a custom
`BaseAgent` for triage and an `LlmAgent` for judgment. Sequential is not chosen
because the work happens to be ordered. It is chosen because **tier one exists
to stop tier two running**, and that is only expressible as a gate between two
stages. The gate is a `before_agent_callback` on tier two rather than
`end_invocation` on tier one, because every sub-agent runs against its own copy
of the invocation context: a triage agent that ends its own invocation does not
end the sequence, and tier two runs anyway. A callback that returns content is
checked before the second agent is entered at all, so a quiet corner costs
nothing rather than costing a little. Across the 175 evaluations in the real
journal, four would have reached tier two.
*Guarded by* `tests/test_adk_graph.py::test_a_declined_delta_never_reaches_tier_two`,
which asserts the expensive agent was never constructed, not merely that it
returned early.

## Crash recovery, from per-corner snapshots

The sweep commits each corner's snapshot to Firestore as it finishes that
corner, inside the loop, not as a batch at the end. A run that dies at corner
twelve has eleven committed baselines, and the next run diffs the remaining
corners from where it stopped rather than re-deciding the ones already settled.
The recovery property depends on a second rule that is easy to miss: an
incomplete fetch does **not** overwrite the baseline. Writing a partial snapshot
would make the next comparison read a failed read as a drop to zero, which is
the most dangerous wrong answer this system can produce, because a corner's
collisions falling to zero looks exactly like good news.
*Guarded by* `tests/test_delta.py::test_incomplete_fetch_is_not_a_drop_to_zero`
and `tests/test_diff_exhaustive.py::test_an_incomplete_snapshot_hides_even_a_fatality`.

## Human approval as a boundary, not a step

The letter is drafted in full, with the corner's real figures, and it is never
sent. `DryRunActuator` renders what would go out and opens no socket.
`LiveActuator` exists, implements the same protocol so the interface cannot rot,
and refuses every verb with a named blocker; it does not read the credential at
all, because a module that reads a token in order to decline to use it is one
edit from using it. This is a boundary rather than an approval step: there is no
"approve" button that would flip it, and turning it on is a code change that has
to pass the same gate as any other. `flag` is a first-class tool beside the
four actions, so asking for a human is a decision the agent can make and sign,
not an absence of one.
*Guarded by* an import rule in `tools/check.sh` asserting the decision path
never imports `ingest.py`, plus the refusal tests on every `LiveActuator` verb.

## Idempotency, at four different layers

Each of these solves a different double-write, and none of them substitutes for
another. **Skip-existing**: a corner whose frame is already cached and whose tier
does not warrant an audit short-circuits without regenerating imagery.
**Hash coherence**: a before-and-after pair is served only when both halves carry
the same `frameSha`, so a refreshed source photograph cannot silently pair
today's before with yesterday's after. **Append-only journal**: entries are
written with `create()` rather than `set()`, so a retried write fails instead of
overwriting a decision. **Duplicate-id rejection**: every published decision
carries a stable `decisionId` built from the run, the corner and the timestamp,
and StreetCred accepts the first and answers a repeat with `duplicate: true`,
which the publisher counts as success rather than failure, because a second
landing means the first one worked.
*Guarded by* `a duplicate decision id is accepted once and stored once` and
`republishing the same render cannot duplicate the state` in the StreetCred
suite, and `test_a_duplicate_is_a_success_not_a_failure` here.

## Memory, which is not the same as persistence

Persistence is writing state down. Memory is state that changes what happens
next, and only some of what this agent stores does that. **Snapshots are memory**:
there is no decision without them, because the thing being judged is the
difference between what the city says now and what the agent itself recorded
last time, and a corner with no stored baseline is journaled as a first sighting
rather than as no change. **Calibration is memory**: the thresholds tier one
judges against are read from the store on every corner, they persist across
runs and processes, and they are bounded so no single week can move them past a
floor or a ceiling.

**The outcome loop is now memory too, and it is the narrowest of the three.**
`calibrate.review` runs at the end of every cycle, reads what tier two did with
tier one's escalations, and moves at most one threshold. It only ever raises one,
and the asymmetry is the design rather than a shortcut: an escalation tier two
declined is a false positive and both tiers left a record on the same entry, while
a delta tier one declined that actually mattered is a false negative with no record
anywhere, because tier two never saw it. Evidence here can only ever argue for a
higher bar. On the current journal it refuses outright: five escalations have
reached tier two and the floor is twenty, so nothing moves and the refusal is
reported. That is the restraint thesis applied to the agent's own knobs.

One thing commonly grouped here is **not** memory in this build. The streak and
the per-corner history are computed from the journal for the ledger to render;
nothing reads them to decide anything.
*Guarded by* `tests/test_calibration.py` for the bounds, the refusal of unknown
keys and the journaling of every adjustment, and by
`tests/test_calibrate_outcomes.py` for the loop, mutation tested both ways: let it
lower a threshold and the asymmetry test goes red, drop the evidence floor and a
cycle starts writing a journal entry the ledger would count as restraint.

## The metric-gaming line

The headline number is a restraint rate, and a restraint rate is trivially
gamed: an agent that declines everything scores one hundred percent. That is not
a flaw to be argued away, it is the reason the number is never published alone.
Every decline is a tool call carrying its own reasoning, in the same shape an
action lands in, rendered at the same visual weight, and linked to the raw
journal record. So the claim being made is not "it restrained itself" but "here
is every occasion it did, with what it said at the time, and you can read them."
Three things are kept out of the numerator, each found by breaking the page on
purpose and reading what it then claimed. An entry that **errored** has an empty
action list and looks identical to a decline, so it is pulled out first: the
agent's own bugs must not raise its score. An entry where the decider **wanted to
act and the budget refused** is the opposite of restraint and is counted
separately. And declines settled by a **rule observing there was nothing to
compare** are split out from declines where a tier weighed a real change, because
a rate that adds them together describes a quiet city while reading as a careful
agent. The page prints that split above the number. A corner nobody looked at is
not a corner judged unimportant.
*Guarded by* `tests/test_cost.py::test_a_budget_exhausted_entry_never_counts_as_restraint`,
with the error and unjudged splits computed in `ledger.summarise` and rendered
beside the rate rather than folded into it.

The same distinction runs through `doctor`'s publish check. Its pass or fail
state answers "is it publishing now", over a 24 hour window it names in its own
output, and a separate line answers "has it ever failed to publish", over the
whole log, with the count and the date. It used to answer only the second
question and call the result a failure, which meant that after one bad batch it
could never be green again. A check that can only fail is a check people learn
to skip. Nothing is deleted and nothing is forgiven by age: an old failure stays
on the page as an old failure, which is a different claim from a current one.
*Guarded by* the window tests in `tests/test_doctor_publish.py`, mutation tested
both ways: remove the window and the historical batch fails a healthy agent
again, remove the history line and the record disappears.
