# Decisions

Architectural decisions and the reasoning behind them. Newest entry at the top.
Each entry records what was decided, what was rejected, and what would have to be
true to reverse it.

---

## 2026-08-20: the radius was 150 and should have been 80, and the guard that catches that class of change

### The measurement

The previous entry listed "StreetCred's severe count for 6th and Mission is 9 where
DataSF returns 11, unexplained" as an open hole. It is now explained, and the cause
was larger than one number.

Querying DataSF at 80 metres over five years reproduces StreetCred's published
scoreboard counts **exactly, in all four severity categories, for six of six corners
probed**:

| corner | published f/s/ov/p | DataSF 80m 5y |
| --- | --- | --- |
| 6th-and-mission | 0/9/15/38 | 0/9/15/38 |
| 6th-and-stevenson | 1/6/14/37 | 1/6/14/37 |
| 6th-and-jessie | 0/7/13/39 | 0/7/13/39 |
| larkin-and-myrtle | 0/5/15/30 | 0/5/15/30 |
| 6th-and-minna | 0/5/10/36 | 0/5/10/36 |
| 4th-and-ellis | 1/6/16/12 | 1/6/16/12 |

150 metres does not reproduce them and is not close. Across the full watched set of
25 corners, snapshots taken at 80 metres now agree with StreetCred on **fatalities
25 of 25, severe injuries 24 of 25, and total injury collisions 23 of 25**.

**Decision:** `DEFAULT_RADIUS_M` moves from 150 to 80. The README asserted the
opposite, that StreetCred's stats query used 150 and that 80 was a different query
for a different purpose. That assertion came from reading StreetCred's source rather
than measuring its output, and it was wrong. The governing rule is that the two
systems must never disagree about a number, so the number that reproduces
StreetCred's published figures wins. The README claim has been corrected.

### What is still not resolved, stated plainly

- **Two corners still disagree.** `gough-and-haight` reports 41 collisions where
  StreetCred publishes 56, and it matches almost exactly at **90** metres (0/5/22/30
  against a published 0/5/21/30) rather than 80. `jones-and-market` is off by a
  single record. So StreetCred's corner geometry is not a uniform 80 metre circle
  for every corner, and the actual rule is not determined. 80 is the best available
  answer, not the certain one.
- **The 311 window could not be pinned.** At 80 metres the published figure sits
  within one or two records of a 365 day window and matches exactly at none of 330,
  350, 360, 365, 370, 380 or 400 days across four corners. The agent therefore keeps
  its own three year window and says so in every letter, so the two figures are
  openly different quantities rather than two claims about the same quantity that
  disagree.

### Decision: snapshots carry a fingerprint of the question they answer

Changing the radius invalidates every stored baseline. Without a guard, the next
sweep would have subtracted 80 metre counts from 150 metre counts and reported a
forty percent collapse in collisions at all twenty five corners on the same morning,
with confident reasoning attached and nothing anywhere flagging it. That is the exact
failure mode this repo exists to prevent, produced by fixing a bug.

Every snapshot now carries `query_fingerprint`, a readable string naming the radius,
both windows, the severity vocabulary and the size of the 311 allow list.
`diff_snapshots` refuses to compare across a change in it and journals the refusal
with the basis `methodology`.

**Rejected:** a hash. The journal entry that refuses a comparison prints the
fingerprint, and `r=80m;collisions=5y;...` tells a reader what happened where
`a3f19c` does not. Worth noting that no entry ever printed `r=150m`: the pre-change
baselines predated the field, so every refusal reads `not recorded then r=80m...`.

**Verified by running it:** the cycle after the radius change journaled 25 refusals
and took no action. Each names the new fingerprint and records the old side as
`not recorded`, because those baselines predated the field. That is the correct
reading rather than a gap: what they were measured under genuinely is not known. The 150 metre baselines were then
replaced by 80 metre ones and comparison resumes normally from the next sweep.

### Deviation from the instruction

`delta.py` was listed in the previous entry as kept unchanged. It has now changed:
one guard was added ahead of the arithmetic. Recorded here because the earlier entry
claimed otherwise.

---

## 2026-08-19: make the whole loop run locally, keep the cloud behind seams

### What was kept from the 2026-08-18 scaffold

Kept unchanged, because it was already the right shape and had tests that proved it:

| Kept | Why it survived tonight untouched |
| --- | --- |
| `schema.py` | The Firestore document contract as dataclasses. The local store writes exactly these shapes, so pointing this at a real Firestore later changes where documents go, not what they contain. One field was added: `Trigger` gained `"rehearsal"`. |
| `delta.py` | `diff_snapshots` and the rule floor. Three guards (first sighting, incomplete fetch, withdrawn record) and a deterministic escalation floor, all covered by tests that describe the confident lie each one prevents. Nothing tonight found a reason to touch it. |
| `prompts.py` | Both prompts, versioned. The stand-in tiers still render them on every call and discard the result, so a prompt that would fail to format against real data fails now rather than on the first Vertex call. |
| `ingest.py` | The only code in the repo that can POST. Kept, and kept unimported by the local loop, pinned by a test. |
| `Dockerfile` | Still describes the deployed shape. It boots `watchdog.server:app`, which still does not exist; see the open holes below. |
| The README's thesis | Declines as the product, the honesty rails, the two-tier split. The argument was already written down and the code caught up to it rather than the reverse. |

Changed, with reason:

- `datasf.py` kept its query shapes and lost one wrong constant. `SEVERE_VALUES`
  named CHP SWITRS category labels rather than the ones DataSF publishes, so the
  severe-injury filter matched nothing on every sweep from the first commit. See
  `LOG.md` for the evidence. The rest of the file is unchanged.
- `pyproject.toml` moved every Google package into an optional `cloud` extra. A
  dependency you cannot avoid installing is not behind an adapter no matter what
  the architecture diagram says.

### What was built tonight

Everything that runs between the seams, and the seams themselves.

- `ports.py` names every cloud dependency as a Protocol.
- `store.py`, `bus.py`, `brains.py`, `outbox.py`, `live.py` implement the local
  side of each one.
- `observer.py`, `actor.py`, `budget.py`, `runner.py`, `cli.py` are the loop.
- `watched.py` fetches the watched set, `ledger.py` renders the journal,
  `rehearsal.py` exercises the expensive half without observing anything.
- 55 new tests, bringing the suite to 76, all offline.

### Decision: the stand-ins are policy, not simulated models

`RuleTriage` and `RuleDecider` do not imitate Gemma and Gemini. They apply the
policy those models were going to be asked to apply, deterministically, and every
journal entry written while one is wired carries a `degraded` line naming which
tier was not a model.

**Rejected:** calling a small local model so the demo could say a model ran. That
buys a sentence in a pitch and costs the one property this project is about. An
agent that degrades quietly produces output indistinguishable from one that did
not, and the whole argument here is that the output can be trusted.

**Reversing it:** wire real clients in `select_brains()`. It is the only function
that changes, and the `degraded` line becomes `None`.

### Decision: the observer journals its own declines

A decline never travels to the actor. It is written the moment tier one makes it.

**Why:** declines are the common case and the headline number. Routing them
through the expensive tier to be told what is already known would make the
restraint rate a function of the actor's uptime, and would put the cheapest
outcome on the most expensive path.

### Decision: an incomplete fetch never becomes the new baseline

If a corner's fetch came back partial, the stored snapshot is left alone.

**Why:** overwriting it means the next sweep compares a good fetch against a
broken one and reports a swing that did not happen. One bad minute at DataSF would
poison a corner for as long as the agent runs. The comparison is journaled as
unreliable and the old baseline stays.

### Decision: the live path exists and refuses

`LiveActuator` implements the `Actuator` protocol and raises on every verb.

**Rejected:** leaving it unwritten, which hides whether the interface fits until
the worst moment. Also rejected: leaving it callable behind a flag, which is how a
dry run becomes a live send by way of one wrong argument. It reads no token and
imports no HTTP client, pinned by a test, because a module that reads a credential
in order to refuse to use it is one edit away from using it.

**Reversing it:** the three blockers named in `live.py` all have to be true,
including a human having read a full dry-run outbox and agreed with every letter.

### Decision: the rehearsal constructs the past, never the present

Two cycles minutes apart against a five-year rolling window produce no change, so
the deliberation tier, the budget and the letter renderer would never run. The
rehearsal fixes that by taking the real snapshot on disk as the current reading and
constructing the *previous* one.

**Why that inversion:** no number in the rehearsal's current record is invented,
and the invented number is the one being subtracted from, which is the one nothing
is published from. It writes to its own state directory, every entry carries
trigger `rehearsal`, every entry admits its baseline was constructed, and the
ledger excludes all of it from the restraint rate.

**Rejected:** mutating the real snapshots to force a delta, which would have put
fabricated numbers into the journal that is the product.

### Decision: the archived broken run was kept, not deleted

The two cycles run before the severity fix were moved to
`state-precheck-broken-severe/` rather than removed. A journal computed from a
query known to be broken should not be rendered as the product, and it should not
be quietly discarded either.

### Open holes, named rather than hidden

- `watchdog/server.py` does not exist, so the `Dockerfile` would not boot. Nothing
  tonight needed it and pretending otherwise would be worse than saying so.
- No ADK agent, no registered tools, no Vertex client. The requirements table in
  the README describes the deployed design, not this build.
- Calibration can be adjusted and persisted but nothing adjusts it yet. No
  feedback loop reads outcomes and moves a threshold.
- The 150 metre radius, the five-year and three-year windows, and StreetCred's
  points ordering are all taken from StreetCred without independent verification
  that its published numbers use the same windows. Two of its severe counts differ
  from DataSF's by a small margin, which is unexplained.
