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

TRIAGE_PROMPT_VERSION = "triage-v1"
DELIBERATION_PROMPT_VERSION = "deliberate-v1"

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

Return strict JSON only:
{{"significant": true or false, "reason": "one or two plain sentences", "confidence": 0.0 to 1.0}}

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

Return strict JSON only:
{{"actions": ["..."], "reasoning": "two to four plain sentences"}}

An empty actions list is a considered decline. Your reasoning is published verbatim on a
public page beside the actions, or beside the absence of them, so state plainly what you
weighed and why it did or did not clear the bar."""


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
