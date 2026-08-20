# Wiring the real models

What has to happen the morning a Vertex project exists. Written now, while the
shape of the problem is fresh, so that the day it is done is a day of typing
rather than a day of decisions.

Nothing in this document has been done. No cloud account has been touched by
this repo at any point.

---

## 1. Where the models are called from

There is exactly one function to change:

```
src/watchdog/brains.py :: select_brains()
```

Everything above it is written against the `Triage` and `Decider` protocols in
`ports.py`, so the loop, the observer, the actor, the budget and the ledger do
not know or care which side of the seam is running. `select_brains()` currently
returns `RuleTriage` and `RuleDecider` plus a sentence explaining that they are
stand-ins. Wiring the models means returning `VertexTriage` and
`VertexDecider` plus `None`.

The two new classes go in a new file, `src/watchdog/vertex.py`, and must
implement exactly:

```python
class VertexTriage:
    def describe(self) -> str: ...
    @property
    def degraded(self) -> str | None: ...          # None when the model really ran
    async def judge(self, delta, corner, calibration) -> Tier1Verdict: ...

class VertexDecider:
    def describe(self) -> str: ...
    @property
    def degraded(self) -> str | None: ...
    async def decide(self, delta, corner, counts, escalation_reason) -> Tier2Decision: ...
```

They render the prompts that already exist in `prompts.py`, send them, and push
the reply through `contract.py`'s `parse_triage` / `parse_deliberation`, which
already reject unknown fields, empty reasoning, invented action verbs, and an
`act` verdict that has not named the claim it is correcting. None of that
validation needs writing; it needs calling.

## 2. Endpoint and models

| tier | model | why |
| --- | --- | --- |
| one, triage | `gemma-3-27b-it` | runs on every ambiguous delta, so it has to be cheap |
| two, deliberation | `gemini-3.7-flash` | only ever sees what tier one escalated |

Both are called through Vertex AI in `GOOGLE_CLOUD_LOCATION`, which
`.env.example` already carries as `us-central1`, using the `google-genai` client
already listed in the `cloud` extra in `pyproject.toml`:

```python
from google import genai
client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
```

Both model ids are already in `.env.example` as `TRIAGE_MODEL` and
`DELIBERATION_MODEL`. Read them from the environment rather than hardcoding, so
that changing a model is a config change and shows up in the journal's wiring
block rather than in a diff.

**Confirm both model ids against the current Vertex model list before the first
call.** They were written into `.env.example` on 2026-08-18 and this repo has
never made a request, so they are unverified. A model id that does not exist
fails loudly, which is the good case; a model id that silently resolves to
something else is the bad one.

## 3. Authentication

**On Cloud Run:** application default credentials, no key file, nothing in the
repo. Give the service account `roles/aiplatform.user` and let the metadata
server supply the token. `genai.Client(vertexai=True, ...)` picks ADC up with no
further configuration.

**Locally:** `gcloud auth application-default login`, once. That writes
`~/.config/gcloud/application_default_credentials.json`, which is exactly the
file `brains.vertex_is_configured()` already looks for. Nothing else changes:
the moment that file and `GOOGLE_CLOUD_PROJECT` both exist, the configuration
check flips.

**Never:** a service account JSON in the repo. `.gitignore` already carries
`service-account*.json` and `*.key`, and `.env` has never been committed
(verified with `git log --all --full-history -- .env`).

## 4. What a cycle costs

Measured, not estimated. These are the real rendered prompts for a real corner,
6th and Mission, on 2026-08-20:

| | prompt chars | prompt tokens (chars / 4) | output tokens (mean of worked examples) |
| --- | --- | --- | --- |
| triage | 1,060 | ~265 | ~77 |
| deliberation | 1,609 | ~402 | ~184 |

Two token estimators agree within 12 percent (`chars/4` gives 265 for triage,
`words x 1.33` gives 238), so the order of magnitude is safe even though neither
is a real tokenizer. **Re-measure with the provider's own token counter before
quoting any of this as a cost.**

Per cycle over 25 corners, the two bounding cases:

| scenario | triage calls | deliberation calls | prompt tokens | output tokens |
| --- | --- | --- | --- | --- |
| every delta settled by rule | 0 | 0 | 0 | 0 |
| every corner ambiguous, all escalate | 25 | 25 | ~16,675 | ~6,525 |

The first row is not a hypothetical. Across the 100 evaluations in this repo's
real journal, the count that would have reached a model is **zero**: 25 settled
as `no_change`, 25 as `methodology`, and 50 predate the basis field. The rule
floor and the empty-delta guard absorb the overwhelming majority of a quiet
morning, which is the entire economic argument for the two-tier split.

A realistic daily figure sits far closer to the first row than the second. It
cannot be stated honestly yet, because this repo has never observed a real
change at a watched corner, so there is no measured escalation rate to
multiply. **That number should come from a week of scheduled cycles, not from
this document.**

Cost is therefore left as arithmetic rather than a figure:

```
cost per cycle = (prompt tokens x input rate) + (output tokens x output rate)
```

**Fill in the two rates from the current Vertex price list at the time of
wiring.** They are deliberately not written here: quoting a per-million rate
from memory is exactly the kind of plausible unverified number this project
exists to refuse, and the arithmetic above turns the real rates into a cost in
one multiplication.

The existing `DAILY_ACTION_BUDGET` caps *actions*, not tokens. If token spend
needs a ceiling, that is a second counter and it belongs in `budget.py` beside
the first one, not bolted onto the model client.

## 5. When the model fails mid-cycle

The contract already has the right verdict for this, and it is not "decline".

**Tier one fails** (timeout, 429, 5xx, a reply that fails `parse_triage`):
the delta is journaled as a `defer` with basis `triage_defer`, `degraded` naming
the failure, and **is not escalated**. Nothing is spent on a delta whose triage
never happened. The stored snapshot is still written, so the next cycle compares
against fresh data rather than re-diffing the same change.

**Tier two fails:** the entry is journaled with verdict `defer`, no actions, and
`what_would_resolve_it` naming the failure. The escalation is not retried inside
the cycle and no letter is drafted from a deliberation that did not complete.

**Why defer and not decline, specifically:** a decline is a claim that the agent
looked and judged no action necessary. It counts as restraint on the public
page. A model that timed out did not judge anything, and counting that as
restraint would inflate the one number this project asks to be trusted on. The
ledger already excludes `triage_defer` from the judged-decline count for exactly
this reason.

**Retry policy:** none inside a cycle. The next scheduled cycle is at most six
hours away, the snapshot is already stored, and a corner whose triage failed
gets a normal comparison next time. Retrying inside the cycle turns a provider
having a bad minute into 25 corners times N attempts against the same
struggling endpoint.

**One exception, and it must be built deliberately:** if the rule floor fired,
the escalation is not model-dependent and must not be lost to a tier-two
outage. A new fatality that Gemini could not deliberate on still gets `flag`,
by rule, journaled as such. Do not let a provider outage silently swallow a
death.

## 6. Order of work

1. `gcloud auth application-default login`, confirm `vertex_is_configured()`
   flips to True.
2. Confirm both model ids exist in the project's Vertex model list.
3. Write `src/watchdog/vertex.py` against the two protocols.
4. Test it against the ten worked examples in `src/prompts/`: feed each example
   input, assert the reply parses. Do not assert it matches the example answer;
   the examples teach judgment, they are not a regression fixture.
5. Point `select_brains()` at it behind an env flag, so the stand-ins remain one
   variable away.
6. Run one cycle by hand. Read all 25 journal entries. Confirm `degraded` is
   `None` on the entries a model decided, and that it is not `None` on any
   entry a rule decided.
7. Only then let the schedule run it.

Step 6 is the one that is tempting to skip and is the reason for the whole
document. The first cycle where a model writes text that gets published is the
first cycle where a mistake becomes a public claim about a street corner.
