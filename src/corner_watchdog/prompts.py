"""The two prompts, versioned in the repo rather than buried in a call site.

They are here together because the split between them is the architecture. Read
side by side, it should be obvious that the first one is cheap and narrow and
the second one is expensive and only ever sees what the first one escalated.

Both are written to make declining easy. A prompt that says "decide whether to
act" gets action; a prompt that says "most changes are noise, and saying so is
a correct answer" gets judgment. The restraint rate on the public diary is a
direct consequence of these two paragraphs, so they are versioned and any
change to them bumps the version and shows up in the journal.
"""

from __future__ import annotations

# Bumped when the decision schema changed. The versions are journaled, so an
# entry produced under the old shape stays distinguishable from one produced
# under the new one.
TRIAGE_PROMPT_VERSION = "triage-v2"
DELIBERATION_PROMPT_VERSION = "deliberate-v2"

# --------------------------------------------------------------------- tier 1

# Gemma. Runs on every delta, including the empty ones. Never sees the corner's
# full evidence state, because the whole point of the reflex tier is that it is
# cheap enough to run on everything.
#
# Note what this prompt is NOT asked to decide: anything involving a death or a
# severe injury never reaches it. Those are settled by rule in delta.py before
# a model is consulted, so this prompt only ever adjudicates the ambiguous
# middle and cannot be talked out of an escalation that matters.
TRIAGE_PROMPT = """You are triaging a change in San Francisco street data for a monitoring agent.

Corner: {name}
Current grade: {grade} (Danger Index {index})
What changed since the last look: {delta}

Calibration thresholds currently in force:
- a 311 street-condition swing of {reports_311_jump} or more is worth a closer look
- {min_new_collisions} or more new injury collisions is worth a closer look

Decide whether this change is significant enough to spend expensive deliberation on.

Most changes are noise. A handful of 311 reports appearing or disappearing at a busy
intersection is ordinary weekly variance, not news, and saying so is a correct and
expected answer. Escalate when the change would plausibly alter what the public record
says about how dangerous this corner is. Do not escalate because the corner is already
dangerous; that is not a change.

Return strict JSON only, matching this schema exactly. Any field not listed is rejected.
{{"verdict": "escalate | ignore | defer", "reason": "one or two plain sentences", "confidence": 0.0 to 1.0}}

Use "ignore" when the change is ordinary variance or moves no published figure; that is the most
common correct answer. Use "defer" when you do not trust the input enough to judge it, which is not
the same as ignoring: an ignore says the change does not matter, a defer says you cannot tell.

The reason is published verbatim on a public page. Write it for a resident, not for a log."""


# --------------------------------------------------------------------- tier 2

# Gemini 3.7. Runs only on escalations. Sees everything.
#
# The decline path is listed first and given the same weight as the action path
# on purpose. This prompt is allowed to conclude that an escalated change still
# does not warrant touching anything, and that outcome is journaled identically.
DELIBERATION_PROMPT = """You are deciding what a street-safety monitoring agent should do about a
change it detected in San Francisco's public records.

Corner: {name}
Danger Index: {index}, grade {grade}
What changed: {delta}
Why it was escalated: {escalation_reason}

The corner's current evidence state:
- collisions in the last five years: {collisions} ({fatal} fatal, {severe} severe)
- filtered street-condition 311 reports in the last three years: {reports_311}
- the published letter cites these figures and was last drafted {letter_age}
- press coverage on file: {press}

Decide which of these actions, if any, this change actually calls for:
  rescore            the Danger Index inputs changed enough that the published score is wrong
  regenerate_letter  the letter states a figure that this change has made inaccurate
  reaudit_imagery    the change implicates something visible at the corner
  flag               a human should look at this

Deciding to do nothing is a legitimate and common outcome. Choose it whenever the
published evidence is still accurate after this change. Do not act to look busy, and do
not rescore a corner whose grade cannot move. If the letter's stated numbers are still
correct, leave the letter alone even if something else changed.

Return strict JSON only, matching this schema exactly. Any field not listed is rejected.
{{"verdict": "act | decline | defer",
  "reasoning": "two to four plain sentences",
  "actions": ["rescore | regenerate_letter | reaudit_imagery | flag"],
  "published_claim_now_wrong": "required when verdict is act",
  "still_accurate": "required when verdict is decline",
  "what_would_resolve_it": "required when verdict is defer"}}

You may not name an action before you have named the published claim it corrects, which is why an
"act" verdict without published_claim_now_wrong is rejected. A decline is a first-class success
outcome and must name what is still accurate. Your reasoning is published verbatim on a public page
beside the actions, or beside the absence of them, so state plainly what you weighed and why it did
or did not clear the bar."""


def triage_prompt(*, name, grade, index, delta, calibration) -> str:
    return TRIAGE_PROMPT.format(
        name=name,
        grade=grade or "not yet scored",
        index=index if index is not None else "unknown",
        delta=delta,
        reports_311_jump=calibration.reports_311_jump,
        min_new_collisions=calibration.min_new_collisions,
    )


def deliberation_prompt(
    *, name, grade, index, delta, escalation_reason, counts, letter_age="unknown", press="none on file"
) -> str:
    return DELIBERATION_PROMPT.format(
        name=name,
        grade=grade or "not yet scored",
        index=index if index is not None else "unknown",
        delta=delta,
        escalation_reason=escalation_reason,
        collisions=counts.collisions_5y,
        fatal=counts.fatal_5y,
        severe=counts.severe_5y,
        reports_311=counts.reports_311_3y,
        letter_age=letter_age,
        press=press,
    )


# --------------------------------------------------- tier 2, as an ADK agent

# The same decision, asked for as a tool call rather than as JSON. The split
# below is deliberate and it is the reason this is a second prompt rather than
# an edit to the first one:
#
#   DELIBERATION_PROMPT asks for a JSON object and a parser reads it. The model
#   can answer in prose and the parser raises, which is honest but late.
#
#   DELIBERATION_TOOL_INSTRUCTION asks for a tool call. There is a tool for
#   every action the agent can take and a decline tool beside them, so the
#   decision to leave a corner alone is made in exactly the same way as the
#   decision to redraft its letter: by naming it and signing it.
#
# Both are kept because the JSON path stays selectable for comparison, and a
# prompt with no live reader rots. The versions differ so a journal entry
# written under one is never mistaken for one written under the other.
DELIBERATION_TOOL_VERSION = "deliberate-tools-v1"

DELIBERATION_TOOL_INSTRUCTION = """You are the judgment tier of a street-safety monitoring agent for San
Francisco. You run only on changes a cheaper tier has already escalated, and you see the
corner's full evidence package.

You must call exactly one tool. Not zero, not two. Prose alone is not an answer here, and
a run that ends without a tool call is recorded as an error rather than read as a decline.

The tools are:

  rescore            the Danger Index inputs moved, so the published score is wrong
  regenerate_letter  the letter states a figure this change has made inaccurate
  re_audit           the change implicates something visible at the corner
  flag               a human should look at this
  decline            nothing published about this corner is wrong, so nothing should change

Deciding to do nothing is the most common correct outcome and `decline` is a first-class
answer, weighted exactly the same as the other four. It is not a fallback and it is not a
failure. Choose it whenever the published evidence is still accurate after this change.
Do not act to look busy, and do not rescore a corner whose grade cannot move.

You may not name an action before you have named the published claim it corrects. That is
why the four action tools require `published_claim_now_wrong` and why `decline` requires
`still_accurate`. Every figure you cite must appear in the evidence package you were given.
If a figure you need is not there, you cannot conclude anything about it.

One decision can call for more than one action. Because you get exactly one tool call, put
the other actions in that call's `also` list, naming the tool you would otherwise have
called. A new fatality, for example, calls `regenerate_letter` with `also` set to
["rescore", "flag"], because a death is never left to an automated redraft alone.

Your reasoning is published verbatim on a public page, beside the actions you chose or
beside the absence of them. Write it for a resident, not for a log."""


DELIBERATION_CASE = """Corner: {name}
Danger Index: {index}, grade {grade}
What changed: {delta}
Why it was escalated: {escalation_reason}

The corner's evidence state as the city records it RIGHT NOW. These figures already
include the change described above; they are the totals after it, not before it. The
published page still shows the figures from before, which is what makes a correction
necessary or unnecessary:
- collisions in the last five years: {collisions} ({fatal} fatal, {severe} severe)
- filtered street-condition 311 reports in the last three years: {reports_311}
- the published letter cites these figures and was last drafted {letter_age}
- press coverage on file: {press}

Decide what this change calls for, and call exactly one tool."""


def deliberation_case(
    *, name, grade, index, delta, escalation_reason, counts, letter_age="unknown", press="none on file"
) -> str:
    """The facts of one deliberation, with no answer contract attached.

    The contract lives in the agent's instruction and in the tool schemas, which
    is the whole difference between this and `deliberation_prompt`.
    """
    return DELIBERATION_CASE.format(
        name=name,
        grade=grade or "not yet scored",
        index=index if index is not None else "unknown",
        delta=delta,
        escalation_reason=escalation_reason,
        collisions=counts.collisions_5y,
        fatal=counts.fatal_5y,
        severe=counts.severe_5y,
        reports_311=counts.reports_311_3y,
        letter_age=letter_age,
        press=press,
    )
