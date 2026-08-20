# Social drafts

**Drafts only. Nothing here has been posted anywhere, and nothing here should be
posted by anyone but the author.**

Both are written against the state of the repo on 2026-08-20. Every number in
them is measured. Before posting either, re-run `python -m watchdog doctor` and
check the figures still hold, because a post is harder to correct than a page.

---

## LinkedIn

> I spent three days building an agent that watches the twenty five most dangerous
> intersections in San Francisco. It has made 175 decisions so far. Every one of
> them was to do nothing.
>
> That is the part I want to talk about.
>
> The first time I ran it against live data, every corner reported zero severe
> injuries. The city's own board said one of them had nine. My filter was querying
> `collision_severity in('Severe Injury')`. San Francisco publishes that category
> as `Injury (Severe)`. The query was valid, it ran without complaint, it matched
> exactly zero rows, and it had been returning a clean zero on every corner on
> every sweep since the first commit.
>
> Nothing failed. Nothing could. A filter that matches nothing looks exactly like
> a corner where nothing happened. The safety rule I had written that said "any
> new severe injury escalates before any model is consulted" was a rule that could
> never once have fired.
>
> So now the public page leads with the restraint rate, and directly underneath it
> says the number is not yet impressive: every decline so far was settled by a
> rule, not weighed by a tier, so right now it measures a quiet city rather than a
> careful agent.
>
> I would rather ship the sentence that says so than a number that flatters me.
>
> Built for #AllThingsAgenticHackathon. None of the Google Cloud integration is
> wired yet: every service is behind an adapter running a local stand-in, and every
> decision the agent records says which stand-in produced it.

**Word count:** 258. **Checks before posting:** the 150 figure comes from the
journal and moves every cycle. Re-count it, or say "more than a hundred".

---

## X

> Built an agent that watches SF's 25 worst intersections. 175 decisions so far,
> all of them "do nothing".
>
> Then I found my severity filter had matched zero rows since the first commit.
> Valid query, no error, clean zero on every corner, forever.
>
> Nothing failed. Nothing could.

**Characters:** 268 of 280.

### Shorter variant, if the thread needs a hook post

> My agent's safety rule was: any new severe injury escalates before any model is
> consulted.
>
> That rule could never have fired. The filter had been matching zero rows since
> the first commit.
>
> No error. Just a number, and the number was false.

**Characters:** 246 of 280.

---

## What not to claim in either

Written down because these are the sentences that would be easy to write and are
not true:

- Do **not** say Gemini or Gemma are running. They are not wired.
- Do **not** say it is deployed, live, or in production. It runs on a laptop.
- Do **not** say it has caught a real change at a real corner. It has not; the
  city was quiet for the whole build, and the one real event worth citing is the
  agent catching **my** change, not the city's.
- Do **not** round 150 up to "hundreds", and do not describe the restraint rate as
  a hundred percent without the sentence explaining why that is not impressive
  yet.
- Do **not** imply StreetCred was built for this hackathon. It predates it.
