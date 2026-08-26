# Demo script, four minutes, hard stop

Supersedes [`demo_script_v1_three_minutes.md`](demo_script_v1_three_minutes.md),
a three minute script written before anything was deployed, whose disclosure card
is now false in every clause. It is kept as a record; do not film from it. It was
renamed rather than replaced in place because this filesystem is case insensitive,
so `DEMO_SCRIPT.md` and `demo_script.md` are one file, and writing the new script
silently overwrote the old one.

Every screen named here exists and is reachable today. Timings are cumulative
and the last beat ends at 3:56, which leaves four seconds of slack and no more.
If a beat runs long, cut the beat, not the disclosure.

**Two rules for the recording.**

1. **Do not narrate a capability you are not showing on screen.**
2. **Do not present a replay as live.** Every beat below is marked
   **[LIVE]** or **[RECORDED]**. A recorded beat carries a small persistent
   corner label reading `recorded <date>`. The reason is not modesty: this
   project's entire argument is that its claims can be checked, and a cloud
   sweep replayed as though it were happening now is the exact category of
   claim it exists to refuse.

**Why anything is recorded at all.** A live sweep reads twenty five corners and
takes about thirty seconds, and on a quiet morning it finds nothing, which is
the honest result and terrible footage. Vertex has also refused on quota twice
during this build. So the sweep is recorded and labelled, and everything that is
a page or a stored record is live, because those cannot fail on camera.

---

## The disclosure card, verbatim

On screen at 0:15. Say it out loud. Do not paraphrase, do not shorten.

> StreetCred, the page this agent publishes to, was built at an earlier event.
> The Corner Watchdog is entirely new work for this hackathon. It runs on Google
> Cloud, both of its model tiers are Google models, and one box in the diagram is
> still a stand-in: when Gemma's shared pool refuses a call, a deterministic rule
> answers instead, and the entry says which one decided it.

---

## 0:00 to 0:15 &middot; Cold open **[RECORDED]**

**Screen:** terminal, the final line of a real cloud sweep.

```
looked at 25, escalated 0, declined 25, acted 0
```

**Say:**

> This agent watched the twenty five most dangerous intersections in San
> Francisco this morning, on its own schedule, and decided to do nothing at all.
> That is the product.

Hold the line for two full seconds after you stop talking. Let it be boring on
purpose.

## 0:15 to 0:30 &middot; The disclosure **[LIVE]**

**Screen:** the card above, plain text, no animation.

**Say:** the disclosure sentence, verbatim.

It goes at fifteen seconds rather than at the end. A caveat at the end reads as
a hedge; a caveat at the start reads as the frame.

## 0:30 to 1:00 &middot; Where the decisions land **[LIVE]**

**Screen:** <https://streetcred.thealexschroeder.workers.dev/watchdog>, scrolled
slowly from the top.

**Say:**

> Everything it decides is here, on a public page, including the mornings it
> decided nothing. Each entry carries the reasoning it wrote at the time and a
> link to the raw record. Nobody has to be told where to look, and nothing here
> was written by hand.

Scroll past at least three declines. Do not scroll to find an action. There
aren't any, and hunting for one on camera says more than the page does.

## 1:00 to 1:35 &middot; The shape **[LIVE]**

**Screen:** `docs/architecture.png`, full frame. Do not zoom around; the diagram
is sized to be read whole at this resolution.

**Say:**

> Cloud Scheduler wakes an observer on Cloud Run. It reads the city's open data,
> diffs each corner against the snapshot it stored in Firestore, and runs a
> deterministic floor first: a new death escalates by rule, before any model is
> consulted, so no model can be talked out of the one thing that matters most.
> What is left goes to Gemma. Only what Gemma escalates reaches Pub/Sub, and only
> that reaches the second service, where an Agent Development Kit agent runs
> Gemini with five tools.

Point at the two green boxes as you name them. They are the only two green boxes.

## 1:35 to 2:05 &middot; The edge that is the architecture **[RECORDED]**

**Screen:** `adk web`, the reasoning trace of one escalation, tier one visible
declining and tier two never entered.

**Say:**

> The gate between the tiers is the whole design. A sequential agent runs its
> children unconditionally, so the obvious build lets the expensive tier start
> and return early on a quiet corner. That version writes the same journal and
> bills a model every morning on every corner. Ours checks before the second
> agent is entered at all. Across a hundred and seventy five real evaluations,
> four reached tier two.

## 2:05 to 2:35 &middot; Doing nothing, signed **[LIVE]**

**Screen:** split. Left, `src/corner_watchdog/adk_decider.py` with the five tool
definitions visible and `decline` among them. Right, the diary entry that
decline produced.

**Say:**

> Deciding to do nothing is not the absence of a decision here. It is a tool
> call named decline, it carries its reasoning, and it lands in the journal in
> exactly the same shape an action does. Zero tool calls is an error. Two is an
> error.

## 2:35 to 3:05 &middot; The gate refusing our own agent **[LIVE]**

**Screen:** the rejected-ingest section of `/watchdog`, on the entry reading
`claimed consequence this site cannot verify`.

**Say:**

> The first real deliberation this thing ran in the cloud claimed it had
> redrafted a letter. The site holds no letter for that corner, because the
> actuator is a dry run. So it refused to publish the claim, and the refusal is
> on the page with its reason. That is the best thing that happened all week. A
> gate whose refusals are invisible is the same as no gate.

Do not apologise for this beat. Do not call it a bug.

## 3:05 to 3:35 &middot; The number, and why it is defensible **[LIVE]**

**Screen:** the top of `/watchdog`, restraint rate and the breakdown under it.

**Say:**

> The headline is a restraint rate, and a restraint rate is trivially gamed:
> decline everything and score a hundred percent. So three things are kept out of
> it. An entry that errored. An entry where the agent wanted to act and the budget
> stopped it. And a decline where a rule just observed there was nothing to
> compare. That last split is the one that matters, because a rate that hides it
> describes a quiet city while reading as a careful agent.

## 3:35 to 3:56 &middot; Close **[LIVE]**

**Screen:** back to `/watchdog`, top of the page, still.

**Say:**

> The city publishes all of this already. Nobody reads it. This reads it every
> morning, tells you honestly when nothing changed, and shows its work when
> something did, so that the morning it says something you have a reason to
> believe it.

Stop. Do not add a thank-you beat. **Hard stop at 4:00.**

---

## The filming list

Every screen above, in the order the recording needs them.

| # | Screen | Live or recorded | Where it is |
| --- | --- | --- | --- |
| 1 | Cloud sweep final line | recorded | `POST /sweep` on `watchdog-observer` |
| 2 | Disclosure card | live | this file |
| 3 | Public diary | live | `/watchdog` |
| 4 | Architecture diagram | live | `docs/architecture.png` |
| 5 | `adk web` reasoning trace | recorded | `adk web`, local |
| 6 | Five tools, `decline` among them | live | `src/corner_watchdog/adk_decider.py` |
| 7 | A decline entry | live | `/watchdog` |
| 8 | The refused ingest | live | `/watchdog`, rejected section |
| 9 | Restraint rate and its breakdown | live | `/watchdog`, top |

## Before you record

- Run `python -m corner_watchdog doctor` and read it. If the publish check is
  failing, the diary and the journal disagree and beat 3 will show it.
- Confirm the refused-ingest entry is still on `/watchdog`. Beat 8 has no
  fallback and the page is the only place that entry lives.
- Have the recorded beats already cut, labelled, and to length. Recording them
  during the take is how four minutes becomes six.
