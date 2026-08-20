# I built an agent that watches San Francisco's worst intersections, and mostly it does nothing

*Draft. This project was created for the purposes of entering the All Things Agentic Hackathon.*

---

Over the last three days my laptop has been reading San Francisco's collision
records, comparing them against what it saw last time, and deciding whether
anything had changed enough to be worth acting on. It has made 175 decisions.
Every single one of them was to do nothing.

I think that is the interesting part, so it is the part the public page leads
with.

## The thing it is actually for

There is a page called StreetCred that grades every intersection in the city.
I built it at an earlier event. It is a snapshot: it tells you that 6th and
Mission has sixty two injury collisions on its record over five years, nine of
them severe, and it grades that F.

The problem with a snapshot is that a city keeps moving after you take one. Some
corner's numbers change, the published grade goes stale, and the letter on that
corner's page starts stating a figure that is no longer true. Nobody notices,
because nobody re-reads a page that already exists.

So the Corner Watchdog watches the twenty five worst corners on that board. Every
cycle it pulls their current record from the city's open data portal, diffs it
against a stored snapshot, and routes what it finds through two tiers of
judgment. Underneath both tiers is a deterministic rule floor with no model in
it at all: a new fatality or a new severe injury escalates by rule, before either
tier is consulted, so nothing can be reasoned out of escalating a death. The
tiers only ever adjudicate the ambiguous middle, and the expensive one only ever
sees what the cheap one sent up.

Most mornings there is no ambiguous middle. The city is mostly quiet, most
changes are noise, and the correct answer is to leave the page alone.

## The bug that is the reason I would show you this project

The first time I ran the loop against live data, every single one of the twenty
five corners reported zero severe injuries. StreetCred's own board said 6th and
Mission had nine.

The query looked like this:

```
collision_severity in('Severe Injury', 'Suspected Serious Injury')
```

Those are the California Highway Patrol's category names. San Francisco's data
portal publishes the category as `Injury (Severe)`. The filter was valid, it ran
without complaint, it matched exactly zero rows, and it returned a clean zero for
every corner on every sweep since the first commit.

Nothing failed. Nothing *could* fail. That is the whole point. A filter that
matches nothing is indistinguishable from a corner where nothing happened. There
was no error to see, no exception in a log, no red anywhere. There was a number,
and the number was false, and the rule I had written that said "any new severe
injury is significant, before any model is consulted" was a rule that could never
once have fired.

I have written a lot of code that was wrong. I do not think I have written much
that was wrong so quietly.

The fix took a minute. What took the rest of the evening was working out what
else was shaped like that. Two more, as it turned out. A response whose count
field had been renamed would parse as zero rather than as an error. And a tie in
the supervisor-district lookup resolved to whatever order the API happened to
return them in, so a corner sitting on a district boundary would flip districts
between sweeps and the agent would faithfully journal it as a real change.

Now every enumerated value this code puts into a query is pinned against the live
vocabulary, with the row count that value carried on the day it was checked. The
count is what makes it honest: comparing a list to a copy of itself proves
nothing. And the cycle refuses to start if the pinned evidence and the code
disagree, because numbers produced by an unverified filter are worse than no
numbers.

## Then fixing a different bug nearly did the same thing again

While chasing the severe-injury discrepancy I found something bigger. I had been
querying a hundred and fifty metre radius around each corner, on the strength of
having read StreetCred's source. When I actually measured it, eighty metres
reproduced StreetCred's published counts exactly, in all four severity
categories, on six of six corners.

So I changed it. And then I stopped, because I realised what changing it would
do. Every count at every corner would move at once. The next morning the agent
would have compared eighty metre counts against hundred-and-fifty metre counts
and reported a forty percent collapse in collisions across the entire city, on
the same morning, with confident reasoning attached and a letter drafted for
each one. It would have been news about my own edit wearing the clothes of news
about a street.

Snapshots now carry a fingerprint of the question that produced them: radius,
both time windows, the severity vocabulary. The diff engine refuses to subtract
across a change in it. The cycle after I changed the radius wrote twenty five
journal entries that each said, in effect, *the query changed between these two
looks, so the arithmetic is meaningless*, and took no action at all.

That is in the journal. You can read it.

## What is not built

None of the Google Cloud integration is wired. Not Vertex, not Gemini, not Gemma,
not Firestore, not Pub/Sub, not Cloud Run. No cloud account has been created or
touched at any point.

Every one of them sits behind a protocol with a working local stand-in, and both
prompts are written in full with ten worked examples that the test suite parses
against the decision schema, so they cannot silently drift apart from the code.
Switching is a change at one wiring site. But it is not done, and the two tiers
in the current build are deterministic policy rather than models.

The important part is what the agent says about that. Every decision it records
now carries a line naming which tier was not a model.

That was not true until I checked. The caveat attached only to decisions a tier
had actually weighed, which sounds right and was: crediting a model for a rule's
work overstates things. But every decision in this journal was settled by a rule,
so not one of the first hundred and fifty carried any admission at all, while
four separate documents claimed they all did. The journal is append only, so
those entries cannot be given the line now. The page prints how many carry it.

## The number I am least proud of, printed largest

The restraint rate is a hundred percent, and directly under it the page says that
this is not yet impressive. Every one of those declines was settled by a rule.
Most observed that nothing had changed; twenty five refused a comparison outright
because I had changed the query underneath them. Not one was a tier weighing a
real change and choosing restraint. Right now that number measures a quiet city, not a careful agent, and
it would look exactly the same if both tiers were broken.

I would rather ship the sentence that says so than a number that flatters me. The
sentence is the product too.

**The ledger, every decision including all the nothings:
[`docs/ledger.html`](ledger.html)**
