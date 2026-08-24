"""A model that answers from a script, so the graph can be tested without a network.

This is not a simulation of Gemini and it does not pretend to reason. It replays
a list of turns that a test wrote down, which is the only way to assert on what
the *graph* does: whether the budget gate fires before the model is reached,
whether a run without a tool call becomes an error, whether a decline is
journaled in the same shape as an action. None of those are facts about the
model, and testing them against a real one would make them non-deterministic
facts about the weather.

What it does faithfully reproduce is the shape of a model turn: a `BaseLlm`
yielding `LlmResponse` objects, so the ADK's own flow, tool executor and
callbacks all run exactly as they do in production. A fake at the decider's
boundary would have proved nothing about the ADK; this one sits under it.

It also records every request it was asked to serve, which is how a test proves
a guardrail short-circuited before the model rather than after it. A model that
was never called leaves an empty list, and that empty list is the assertion.
"""

from __future__ import annotations

from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field


def call(name: str, **args: Any) -> types.Part:
    """One scripted tool call."""
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def text(body: str) -> types.Part:
    """One scripted prose turn. The thing that must not be read as a decline."""
    return types.Part(text=body)


class ScriptedModel(BaseLlm):
    """Replays `turns` one per model call, then repeats the last one.

    Repeating rather than raising on exhaustion is deliberate. After a tool runs,
    the ADK calls the model again to close the turn, and a test that had to count
    those follow-up calls exactly would be asserting on ADK internals rather than
    on this repository's behaviour.
    """

    model: str = "scripted-test-model"
    # default_factory rather than a bare [], so two ScriptedModels never share
    # one recorder. A test asserting "the model was never called" against a list
    # another test had already appended to would pass for the wrong reason.
    turns: list[list[types.Part]] = Field(default_factory=list)
    seen: list[LlmRequest] = Field(default_factory=list)

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        self.seen.append(llm_request)
        if not self.turns:
            parts = [text("no script was provided")]
        else:
            index = min(len(self.seen) - 1, len(self.turns) - 1)
            parts = self.turns[index]
        yield LlmResponse(content=types.Content(role="model", parts=list(parts)))

    @property
    def call_count(self) -> int:
        return len(self.seen)

    @property
    def was_called(self) -> bool:
        return bool(self.seen)

    def prompts_seen(self) -> list[str]:
        """Every piece of text this model was actually shown.

        Used by the injection tests: the assertion is that the hostile string
        never appears in here, which is a stronger claim than the screen having
        returned True.
        """
        out: list[str] = []
        for request in self.seen:
            config = getattr(request, "config", None)
            instruction = getattr(config, "system_instruction", None)
            if isinstance(instruction, str):
                out.append(instruction)
            for content in request.contents or []:
                for part in content.parts or []:
                    if part.text:
                        out.append(part.text)
        return out


def scripted(*turns: list[types.Part]) -> ScriptedModel:
    return ScriptedModel(turns=list(turns), seen=[])
