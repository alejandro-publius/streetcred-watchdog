# Demo script

Three minutes. Every command in this script exists and runs today; nothing here
is a mockup or a future tense. Timings are cumulative.

Two rules for the recording. **Do not narrate a capability you are not showing on
screen.** And **do not cut around a failure**: if a command errors on camera, that
is a better demo than a clean take, because the whole argument of this project is
that the failures are visible.

---

## The disclosure sentence, verbatim

Say this out loud at 0:12 and put it on screen as a card. Do not paraphrase it.

> StreetCred, the page this agent publishes to, was built at an earlier event.
> The Corner Watchdog is entirely new work for this hackathon, none of the Google
> Cloud integration is wired yet, and no cloud account has been touched: every
> service is behind an adapter running a local stand-in, and every decision the
> agent records says which stand-in produced it.

---

## 0:00 to 0:12 &middot; Cold open

**On screen:** the terminal, one line of output from a finished cycle:
`looked at 25, escalated 0, declined 25, acted 0, artefacts 0`

**Say:**

> This agent watched the twenty five most dangerous intersections in San Francisco
> this morning and did nothing at all. That is the product.

Hold the line on screen for two full seconds after you stop talking. Let it be
boring on purpose.

## 0:12 to 0:24 &middot; The disclosure

**On screen:** a plain card with the disclosure sentence.

**Say:** the disclosure sentence above, verbatim.

Putting it at 0:12 rather than in the last ten seconds is the point. A caveat at
the end reads as a hedge; a caveat at the start reads as the frame.

## 0:24 to 0:50 &middot; Prelude of autonomy

**On screen, 0:24:** `cat ops/dev.watchdog.cycle.plist | head -20`, the launchd
job, `StartInterval` 21600 visible.

**On screen, 0:32:** `python -m corner_watchdog doctor` running. Let the 19 checks
scroll. Do not cut. The single `WARN` line about Vertex configuration should be
readable.

**Say:**

> Nobody starts this. launchd wakes it every six hours, it takes a lock so a
> scheduled run can never collide with one I start by hand, and before it looks at
> anything it checks whether what it assumes is still true. Nineteen checks. The
> one warning is the honest one: the models are not wired, so both tiers will run
> as deterministic stand-ins, and it will say so on every decision it writes.

**On screen, 0:44:** the summary line `19 checks, 18 pass, 1 warn, 0 fail`.

## 0:50 to 1:28 &middot; Reality responds

**On screen, 0:50:** `python -m corner_watchdog run --cycles 1`, running live against
DataSF. Let the real network latency show.

**Say:**

> It reads the city's own record for all twenty five corners. Five queries each,
> a hundred and twenty five in total, against San Francisco's open data portal.
> No key, no account.

**On screen, 1:04:** scroll the journal to the entries from **2026-08-20** where
all 25 comparisons were refused with basis `methodology`. Read one aloud:

> Comparison unreliable at 6th and Mission: the query changed between these two
> looks, so the arithmetic is meaningless.

**Say:**

> This is the part I want you to see, and it is real, it is in the journal, it
> happened on the twentieth. I changed the search radius from a hundred and fifty
> metres to eighty, because I finally measured which one reproduces the figures
> StreetCred publishes. Every count at every corner moved at once. Without a guard,
> the next morning this agent would have reported a forty percent collapse in
> collisions across the whole city, with confident reasoning attached, and it would
> have been news about my own edit wearing the clothes of news about a street. It
> caught me. It refused twenty five comparisons and took no action.

This beat is the strongest thirty seconds in the demo and it needs no
embellishment, so do not add any. It is a real event with a real journal entry
and a real commit behind it.

## 1:28 to 2:04 &middot; The kill test

Decide before you record which dependency dies. **Kill DataSF**, because it is
the one the whole system depends on and the one whose failure is most
dangerous.

**On screen, 1:28:** `python -m corner_watchdog run --inject datasf_down --cycles 1`

**Say while it runs:**

> Now I take away the data source. Not by unplugging my wifi, by telling the agent
> to fail, so this is repeatable and so nobody has to take my word for what
> happened.

**On screen, 1:40:** the three lines that matter, in this order:

1. `INJECTING FAILURE: datasf_down`, and `writing to state-injected, not state, so the real journal stays real`
2. `25 comparison(s) refused as unreliable`
3. `baseline kept untouched for:` and the list of all 25 corners

**Say:**

> Every corner failed. It kept every stored baseline untouched, because a fetch
> that returned nothing looks exactly like a corner where nothing happened, and
> writing that down as the new normal would poison every future comparison. It
> wrote nothing to the real journal. And every entry it did write says the failure
> was injected on purpose and is not evidence anything was actually down, so a
> screenshot of this cannot be reused as a real outage.

## 2:04 to 2:30 &middot; The architecture, as a receipt

**On screen:** `docs/architecture.svg`, full frame. Do not zoom around; hold it
still and let the two layers do the work.

**Say, and keep this under thirty seconds:**

> Two agents, an observer and an actor, separated by a bus. Underneath both, a
> deterministic rule floor with no model and no network in it: a new death
> escalates before either tier is consulted, so nothing can be talked out of it.
> Above it, cost routing. Cheap triage sees the ambiguous middle, expensive
> deliberation only ever sees what triage escalated. The green layer is what ran.
> The amber layer is Cloud Run, Firestore, Pub/Sub, Secret Manager, Gemma and
> Gemini, and none of it is wired. Every one is a protocol with a local stand-in,
> so switching is a constructor change at one wiring site.

## 2:30 to 2:52 &middot; The ledger

**On screen, 2:30:** `open docs/ledger.html`, scrolled to the headline.

**Say:**

> Every decision it has ever made, including all the nothings. The restraint rate
> is on top, and directly underneath it the page tells you the number is not yet
> impressive: every one of those declines was settled by a rule, not weighed by a
> tier, so right now this measures a quiet city rather than a careful agent. It
> would look exactly the same if both tiers were broken. I would rather ship the
> sentence that says so than a number that flatters me.

**On screen, 2:44:** scroll to one declined entry, open its `The full journal
record` disclosure, show the raw JSON.

## 2:52 to 3:00 &middot; Close

**On screen:** the days-watched strip.

**Say:**

> It runs again in six hours whether or not anyone is watching, and whatever it
> decides, it will publish that too.

---

## Setup checklist, before you hit record

```bash
python -m corner_watchdog doctor            # expect 18 pass, 1 warn, 0 fail
rm -rf state-injected                # so the kill test starts clean on camera
python -m corner_watchdog ledger            # regenerate the page from the real journal
```

- Terminal at 16pt or larger. A judge is watching this in a browser tab.
- Light theme or dark, but set it before recording: the ledger follows the
  system theme and switching mid-take looks like a bug.
- Have `docs/architecture.svg` already open in a second tab so the 2:04 cut is
  instant.
- Do **not** run `--inject` without `--inject-state` pointing somewhere
  disposable, and do not run it at all against `state/`.

## What to cut if you are over time

In this order, and no further:

1. The raw JSON disclosure at 2:44. Ten seconds.
2. The plist at 0:24, keeping the doctor. Eight seconds.
3. The architecture beat down to two sentences, keeping the rule floor and the
   two layers. Twelve seconds.

**Never cut:** the disclosure at 0:12, the radius story at 1:04, or the sentence
at 2:30 about the restraint rate not being impressive yet. Those three are the
reason this project is worth showing.
