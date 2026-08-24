"""A model that applies the deliberation policy, for running the eval set offline.

This is the piece that needs its limits stated, because it would be easy to
mistake for something it is not.

It is **not** a stand-in for Gemini's judgment, and the offline eval table is not
a measurement of how well a model decides. It reads the delta out of the request
it is given and applies the policy the deliberation prompt describes, in so many
words:

    a new fatality            flag, and redraft and rescore alongside it, because
                              a death is never left to an automated redraft alone
    a new severe injury       rescore, and redraft, because the score inputs moved
    new injury collisions     redraft, and rescore, because the letter states the
                              figure that moved
    a large 311 swing with    re-audit the imagery, because a swing that size with
    no new collisions         no crash record points at something visible
    anything else             decline, and name what is still accurate

What the eval set then measures is whether the *graph* carries that decision
through intact: whether the tool call becomes the right journal action, whether
`also` survives, whether the contract's requirements are enforced on a tool call
as they were on JSON, whether the budget gate fires before the model, and whether
the injection screen keeps hostile text away from it. Every one of those is a
property of this repository rather than of a model, and every one of them is
deterministic, so it belongs in a test suite that runs offline in a second.

The same eval set run through `adk eval` against a real model measures the other
thing, and the two are reported separately rather than added together.

It reads the envelope out of the request rather than the prose the decider is
shown. The original user message is still in the conversation the sub-agent
receives, and parsing JSON is exact where parsing "311 street-condition reports
rose by 16" out of a sentence is a second implementation of the delta engine
waiting to disagree with the first.
"""

from __future__ import annotations

import json
import re
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

# The bar above which a street-condition swing stops being weekly variance and
# starts implying something physically changed at the corner. Higher than the
# RuleDecider stand-in's 15, deliberately: the stand-in re-audits any swing past
# its tier-one threshold, which acts on ordinary movement.
LARGE_SWING = 40


def _find_envelope(llm_request: LlmRequest) -> dict[str, Any] | None:
    for content in reversed(llm_request.contents or []):
        for part in content.parts or []:
            if not part.text:
                continue
            match = re.search(r"\{.*\}", part.text, re.S)
            if not match:
                continue
            try:
                loaded = json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict) and "delta" in loaded:
                return loaded
    return None


def decide(envelope: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The policy, as a tool name and its arguments."""
    delta = envelope.get("delta") or {}
    counts = envelope.get("counts") or {}
    name = (envelope.get("corner") or {}).get("name", "this corner")
    summary = envelope.get("delta_summary", "")

    fatal = int(delta.get("new_fatal") or 0)
    severe = int(delta.get("new_severe") or 0)
    collisions = int(delta.get("new_collisions") or 0)
    swing = int(delta.get("reports_311_change") or 0)

    if fatal:
        return "flag", {
            "reasoning": (
                f"The city's record now shows a new fatal collision at {name}. A death changes "
                "what the published page says about how dangerous this crossing is, and it is "
                "not something to leave to an automated redraft alone, so a person is put in "
                "front of it as well as the score and the letter being corrected."
            ),
            "published_claim_now_wrong": (
                f"The letter states {counts.get('fatal_5y', 0) - fatal} fatal collisions in five "
                f"years at {name}; the record now shows {counts.get('fatal_5y', 0)}."
            ),
            "also": ["rescore", "regenerate_letter"],
        }

    if severe:
        return "rescore", {
            "reasoning": (
                f"A new severe injury collision is on the city's record at {name}. Severe "
                "injuries are an input to the Danger Index, so the published score is now "
                "computed from figures the record has moved past, and the letter states the "
                "same figure in so many words."
            ),
            "published_claim_now_wrong": (
                f"The published score and letter use {counts.get('severe_5y', 0) - severe} "
                f"severe injuries over five years; the record now shows "
                f"{counts.get('severe_5y', 0)}."
            ),
            "also": ["regenerate_letter"],
        }

    if collisions:
        return "regenerate_letter", {
            "reasoning": (
                f"{summary} The letter on this corner's page states its collision count "
                "outright, so that sentence is now behind the city's own record, and the score "
                "is computed from the same number."
            ),
            "published_claim_now_wrong": (
                f"The letter states {counts.get('collisions_5y', 0) - collisions} injury "
                f"collisions in five years; the record now shows "
                f"{counts.get('collisions_5y', 0)}."
            ),
            "also": ["rescore"],
        }

    if swing >= LARGE_SWING:
        return "re_audit", {
            "reasoning": (
                f"{summary} A street-condition swing that size with no new collisions at all "
                "points at something visible at the corner rather than at the crash record, so "
                "the imagery is the thing to look at rather than the score."
            ),
            "published_claim_now_wrong": (
                "The published imagery audit predates a street-condition swing of "
                f"{swing} reports, so what the page shows of this corner may no longer be what "
                "is there."
            ),
            "also": [],
        }

    return "decline", {
        "reasoning": (
            f"{summary} Nothing in that moves a figure this page publishes. The collision, "
            "fatality and severe injury counts the score and the letter are built from are "
            "unchanged, and acting would churn the page without correcting anything."
        ),
        "still_accurate": (
            f"The letter's stated {counts.get('collisions_5y', 0)} injury collisions, "
            f"{counts.get('fatal_5y', 0)} fatalities and {counts.get('severe_5y', 0)} severe "
            "injuries over five years are all still exactly what the city's record says."
        ),
    }


class PolicyModel(BaseLlm):
    """Applies the policy above, then closes the turn."""

    model: str = "deliberation-policy"
    seen: list[LlmRequest] = Field(default_factory=list)
    signed: list[str] = Field(default_factory=list)

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        self.seen.append(llm_request)

        # A second call in one deliberation is the ADK closing the turn after the
        # tool ran. Answering with another tool call there would sign twice, which
        # this repository treats as an error.
        if self.signed:
            yield LlmResponse(
                content=types.Content(
                    role="model", parts=[types.Part(text="Decision recorded.")]
                )
            )
            return

        envelope = _find_envelope(llm_request)
        if envelope is None:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="No delta envelope was present in this request.")],
                )
            )
            return

        tool, args = decide(envelope)
        self.signed.append(tool)
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(function_call=types.FunctionCall(name=tool, args=args))],
            )
        )

    @property
    def was_called(self) -> bool:
        return bool(self.seen)
