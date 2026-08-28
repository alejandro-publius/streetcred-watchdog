# The agent that caught itself lying, in ten minutes

I built an autonomous agent for the All Things Agentic Hackathon that watches
twenty five San Francisco intersections every morning and mostly decides to do
nothing. This post is about the mornings it was wrong about itself, because
those turned out to be the interesting part.

## It ran on Google Cloud while insisting it had no credentials

The first time I deployed the thing, it worked. Cloud Run started it, Cloud
Scheduler woke it, it read the city's collision data, diffed twenty five
corners, wrote its decisions to Firestore and published them to a public page.
Every check was green.

It had also silently stopped using its models. Every journal entry it wrote that
morning carried a line saying tier one had run as deterministic rules, not
Gemma, because there were no Application Default Credentials on the machine.

The machine was a Cloud Run container. Its entire identity is a working Google
credential. What it does not have is a credentials *file*, because it has a
metadata server instead, and my preflight check tested for the file. So a
service whose credentials were fine reported that it had none, quietly ran the
deterministic stand-in, and produced output that looked exactly like the real
thing.

Nothing threw. No check failed. The only reason I found it inside ten minutes is
that the fallback is journaled on every single entry rather than logged once at
startup. I read the first entry of the first cloud run and the admission was
sitting in it.

I want to be precise about why that worked, because "we log our fallbacks" is
not the lesson. A startup log line would have scrolled past. The admission had
to travel *with each record*, so that reading any one decision meant reading
what produced it. The degradation is not metadata about the run. It is part of
the claim.

## The same bug, four more times

Once you go looking for output that is confidently wrong rather than loudly
broken, you find it everywhere in your own work.

**A counter read the wrong number and did not know.** A guard that keeps the
documentation honest ran `pytest --collect-only`, read the first integer, and
ignored the exit code. Under the wrong interpreter five files fail to import,
pytest prints "530 tests collected, 5 errors", and the guard cheerfully wrote
530 into the README where 661 was true. A partial collection is not a smaller
suite. It refuses now, and names the interpreter it could not collect under.

**A module was tested while production ran the part that was not.** I wrote a
new homepage component, gave it twenty three tests, watched them all pass, and
shipped a homepage that returned 404. The component was fine. The four lines
wiring it into the router were not, because my edit script had failed to match
and printed success anyway. The tests exercised the module directly; production
goes through the router; nothing tested the seam between them. Every test I had
was green and the page was down.

**A guard failed the build because I deleted the thing it was protecting.**
The repo has a check that pins certain claims to the one document that owns
them. I rewrote a disclosure section, cut a sentence about the agent framework
without noticing, and the build went red pointing at the exact missing phrase.
That is the check doing its whole job: I had not decided to remove the claim, I
had lost it while editing something else.

**A self-report would have inflated the headline number forever.** The agent
now reviews its own thresholds at the end of each cycle. My first version wrote
that review into the journal as an entry. A review entry has no actions and no
error, which is precisely the shape the ledger counts as *restraint*, the one
number this project asks to be judged on. One per cycle, forever, quietly
climbing. The containment tests caught it, and the review now rides in the run
report instead.

None of those five raised an exception. All of them produced something that
looked right.

## Two decisions I would make again

**Declining is a signed decision, because the decline is a required tool.** The
judgment tier is an Agent Development Kit agent with five registered tools:
four actions, and `decline`. It must call exactly one. Zero calls is an error
and two is an error. So "the agent left this corner alone" is never an absence
in the record; it is a tool call with reasoning attached, landing in the journal
in the same shape an action does, rendered at the same size on the public page.

This matters because the alternative is unfalsifiable. An agent that acts when
it has something to say and returns nothing otherwise produces an empty journal
on a quiet day and an empty journal when it is broken. Making the null result a
first-class signed output is what makes the quiet days evidence rather than
silence.

**Calibration only ever raises a threshold.** The agent tunes the bar its cheap
tier escalates on, and it can only move it up. The asymmetry is not caution, it
is what the data can support. When the expensive tier declines something the
cheap tier escalated, that is a false positive and both tiers left a record on
the same entry. When the cheap tier declines something that actually mattered,
that is a false negative and there is no record of it anywhere, because nothing
ever looked at it again. Evidence that exists can only ever argue for a higher
bar. A version that lowered thresholds on a good week would be inferring a
number from data that by construction cannot contain it.

And it refuses to retune at all below twenty outcomes. The real journal has
five. So every cycle it reads the evidence, declines to move anything, and says
why. That is the same argument the whole project makes about restraint, pointed
at its own knobs: doing nothing is a decision, and it has to be reported like
one.

## What I actually learned

The failure worth designing against is not the agent doing something wrong. It
is the agent producing output indistinguishable from correct while being wrong,
because that is the failure that survives your tests, your dashboards and your
demo, and surfaces in front of someone who trusted you.

Every defence that worked here has the same shape: something compares a claim to
the thing it is a claim about, automatically, and fails loudly when they
disagree. The degradation line beside each decision. The guard that fails the
build when the prose and the code drift. The counter that refuses rather than
guessing. Honesty is not a virtue you exercise while writing documentation. It
is a build step, or it decays the moment you are busy.

---

*This project was created for entering the All Things Agentic Hackathon.*
