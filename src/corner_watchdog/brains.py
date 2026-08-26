"""The two tiers, and what stands in for them when there is no Vertex project.

`RuleTriage` and `RuleDecider` are not simulations of Gemma and Gemini. They do
not pretend to reason and they never emit a sentence claiming a model wrote it.
They are the deterministic policy the models were going to be asked to apply,
written out longhand, so the loop around them can be run and criticised tonight.

Two things follow from that, and both matter more than the rules themselves:

  1. The degradation is journaled. Every entry produced while a stand-in was
     wired carries a `degraded` line naming which tier was not a model. An agent
     that quietly falls back produces output indistinguishable from the real
     thing, which is the failure mode this whole repo is written against.
  2. The seam is the real one. `judge` and `decide` take exactly what the
     versioned prompts in prompts.py take, so the model implementations fill the
     same signature rather than a convenient new one.

The prompts are still formatted for every call even though no model reads them
here. That is deliberate: it keeps prompts.py honest, and a prompt that has
never once been rendered against real data is a prompt that will fail the first
time it is.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import replace
from typing import Any

from .config import (
    decider_name,
    deliberation_model,
    triage_model,
    triage_name,
    vertex_location,
    vertex_project,
)
from .prompts import DELIBERATION_PROMPT_VERSION, TRIAGE_PROMPT_VERSION, deliberation_prompt, triage_prompt
from .schema import Calibration, Counts, Delta, Tier1Verdict, Tier2Decision


def vertex_is_configured() -> tuple[bool, str]:
    """Whether a real Vertex call could even be attempted.

    Checks configuration only. It deliberately does not try a call and time out,
    because a run that hangs for ninety seconds before falling back teaches the
    operator nothing that this cannot tell them immediately.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    adc = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
    if not project:
        return False, "GOOGLE_CLOUD_PROJECT is not set"
    if creds:
        return True, "configured, GOOGLE_APPLICATION_CREDENTIALS"
    if on_cloud_run():
        # The credential that matters here has no file and no environment
        # variable behind it. Cloud Run hands the service account to the process
        # through the metadata server, so both of the checks below are false on
        # a correctly configured production instance.
        #
        # This was found by deploying and reading the journal, not by reasoning
        # about it: the first cloud sweep wrote 25 entries every one of which
        # said "no Google application default credentials on this machine" while
        # sitting on a machine whose whole identity is an application default
        # credential. The tier silently degraded and only the degraded line,
        # which exists for exactly this, made it visible.
        return True, "configured, Cloud Run metadata server"
    if os.path.exists(adc):
        return True, "configured, local application default credentials"
    return False, "no Google application default credentials on this machine"


def on_cloud_run() -> bool:
    """Whether this process is a Cloud Run instance.

    K_SERVICE is injected by the runtime into every container it starts and is
    part of the documented contract, so it is a fact about the environment
    rather than a guess. Checked instead of calling the metadata server, because
    a network probe here would reintroduce the hang this function exists to
    avoid.
    """
    return bool(os.environ.get("K_SERVICE", "").strip())


# ------------------------------------------------------------------- tier one

class RuleTriage:
    """The Gemma stand-in.

    It only ever sees the ambiguous middle. Anything involving a death, a severe
    injury, an unreliable comparison or an empty delta was already settled by
    `rule_verdict` in delta.py before this is consulted, which is the same
    contract the real model runs under.
    """

    def __init__(self, why_degraded: str) -> None:
        self._why = why_degraded

    def describe(self) -> str:
        return f"RuleTriage, deterministic thresholds (stands in for Gemma, {TRIAGE_PROMPT_VERSION})"

    @property
    def degraded(self) -> str | None:
        return f"Tier one ran as deterministic rules, not Gemma: {self._why}."

    @property
    def decided_by(self) -> str:
        return f"RuleTriage, deterministic thresholds, no model ({TRIAGE_PROMPT_VERSION})"

    async def judge(self, delta: Delta, corner: dict[str, Any], calibration: Calibration) -> Tier1Verdict:
        # Stamped here rather than by the caller, so a verdict describes what
        # produced it wherever it is read from. A tier whose output only becomes
        # self-describing after the observer touches it is one that can be read
        # unlabelled by anything else, and the journal is not the only reader.
        return replace(
            await self._judge(delta, corner, calibration), decided_by=self.decided_by
        )

    async def _judge(self, delta: Delta, corner: dict[str, Any], calibration: Calibration) -> Tier1Verdict:
        # Rendered and discarded. See the module docstring.
        triage_prompt(
            name=delta.name,
            grade=corner.get("grade"),
            index=corner.get("index"),
            delta=delta.summary(),
            calibration=calibration,
        )

        if delta.new_collisions >= calibration.min_new_collisions:
            n = delta.new_collisions
            return Tier1Verdict(
                significant=True,
                reason=(
                    f"{n} new injury collision{'s' if n != 1 else ''} on the city's record here since "
                    f"the last look, at or above the current bar of {calibration.min_new_collisions}. "
                    "That is worth a closer look at what this corner's page says."
                ),
                confidence=None,
                by_rule=False,
            )

        if delta.district_changed:
            return Tier1Verdict(
                significant=True,
                reason=(
                    "The supervisor district this corner falls in changed, so the published page is "
                    "pointing residents at the wrong office. Worth a closer look."
                ),
                confidence=None,
                by_rule=False,
            )

        swing = abs(delta.reports_311_change)
        if swing >= calibration.reports_311_jump:
            direction = "rose" if delta.reports_311_change > 0 else "fell"
            return Tier1Verdict(
                significant=True,
                reason=(
                    f"Street-condition reports here {direction} by {swing} since the last look, past the "
                    f"current bar of {calibration.reports_311_jump}. A swing that size usually means "
                    "something at the corner actually changed."
                ),
                confidence=None,
                by_rule=False,
            )

        if delta.reports_311_change:
            direction = "rose" if delta.reports_311_change > 0 else "fell"
            return Tier1Verdict(
                significant=False,
                reason=(
                    f"Street-condition reports {direction} by {swing}, which is ordinary week-to-week "
                    "variance at a corner this busy. The bar for a closer look is "
                    f"{calibration.reports_311_jump}. "
                    "Nothing here changes what the record says about this crossing."
                ),
                confidence=None,
                by_rule=False,
            )

        return Tier1Verdict(
            significant=False,
            reason=(
                "What moved here does not change what the public record says about how dangerous this "
                "corner is, so it does not warrant the expensive look."
            ),
            confidence=None,
            by_rule=False,
        )



class GemmaTriage:
    """Tier one, as Gemma on Vertex.

    Reaches the model through the same Application Default Credentials the
    judgment tier already uses, which on Cloud Run is the metadata server and on
    a laptop is `gcloud auth application-default login`. No key, no secret, and
    no second authentication path to keep working.

    Two findings from probing this are worth carrying in the code rather than in
    a commit message, because both look like bugs in this file when they are not.

    **The model name is not the obvious one.** Gemma reaches Vertex as a managed
    service, `google/gemma-4-26b-a4b-it-maas`, served only from the global
    endpoint. The name AI Studio uses, `gemma-3-27b-it`, answers on Vertex with a
    404 against a publisher path, which reads as a permissions problem and is
    not one.

    **A 429 here is capacity, not quota.** The managed pool is shared, and about
    one call in three came back `RESOURCE_EXHAUSTED, the request queue is full`
    during the probe. That is backpressure and it clears on a retry, so it is
    retried a bounded number of times. What it must never do is silently become
    a decline: a corner that nobody looked at is not a corner judged unimportant,
    and the two are the same shape in a journal unless something says otherwise.

    So the fallback is per call and it is labelled per call. When Gemma answers,
    the entry records Gemma. When it does not, the entry records the rule that
    stood in and why, and `basis` still says `triage` because a tier was
    consulted. A reader can tell the difference; a run-level degradation note
    could not, because it would be identical on both.
    """

    RETRYABLE = ("RESOURCE_EXHAUSTED", "429", "UNAVAILABLE", "503")

    def __init__(
        self,
        *,
        model: str | None = None,
        location: str | None = None,
        project: str | None = None,
        client: Any = None,
        attempts: int = 3,
        base_delay_s: float = 1.0,
        sleep: Any = None,
    ) -> None:
        self.model = model or triage_model()
        self.location = location or vertex_location()
        self.project = project or vertex_project()
        self.attempts = attempts
        self.base_delay_s = base_delay_s
        self._client = client
        self._sleep = sleep or asyncio.sleep
        # The floor this falls back to. Constructed with the reason a fallback
        # would be happening rather than a generic one, so the sentence it writes
        # is about this call and not about the build.
        self._floor = RuleTriage("Gemma was consulted and did not answer")

    def describe(self) -> str:
        return f"GemmaTriage, {self.model} on Vertex {self.location} ({TRIAGE_PROMPT_VERSION})"

    @property
    def degraded(self) -> str | None:
        # Tier one is a model in this wiring. A call that falls back says so on
        # its own entry, which is the only place the claim is true or false.
        return None

    @property
    def decided_by(self) -> str:
        return f"Gemma, {self.model}, Vertex {self.location} ({TRIAGE_PROMPT_VERSION})"

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
        return self._client

    async def judge(self, delta: Delta, corner: dict[str, Any], calibration: Calibration) -> Tier1Verdict:
        prompt = triage_prompt(
            name=delta.name,
            grade=corner.get("grade"),
            index=corner.get("index"),
            delta=delta.summary(),
            calibration=calibration,
        )

        why = ""
        for attempt in range(1, self.attempts + 1):
            try:
                raw = await self._call(prompt)
            except Exception as e:  # noqa: BLE001 - the reason is recorded, not swallowed
                why = f"{type(e).__name__}: {str(e)[:160]}"
                if attempt < self.attempts and any(m in str(e) for m in self.RETRYABLE):
                    # Queue-full backpressure clears in about a second. Bounded
                    # deliberately: tier one runs on every corner in the sweep,
                    # so a generous backoff here is multiplied by the size of the
                    # watched set and turns a daily cron into a timeout.
                    await self._sleep(self.base_delay_s * (2 ** (attempt - 1)))
                    continue
                break

            parsed = self._parse(raw)
            if parsed is not None:
                return parsed
            # A model that answered in prose is a real answer to the wrong
            # question. Retrying is cheap and the floor is still there.
            why = f"the reply did not parse as the schema the prompt asks for: {raw[:120]!r}"
            if attempt < self.attempts:
                continue
            break

        fallen = await self._floor.judge(delta, corner, calibration)
        return replace(
            fallen,
            decided_by=(
                f"RuleTriage, deterministic thresholds, because Gemma did not answer "
                f"after {self.attempts} attempt(s): {why}"
            ),
        )

    async def _call(self, prompt: str) -> str:
        client = self._get_client()
        response = await asyncio.to_thread(
            client.models.generate_content, model=self.model, contents=prompt
        )
        return (getattr(response, "text", "") or "").strip()

    def _parse(self, raw: str) -> Tier1Verdict | None:
        """The prompt asks for strict JSON. Read it, or say it was not there."""
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None

        verdict = str(data.get("verdict", "")).strip().lower()
        reason = str(data.get("reason", "")).strip()
        if verdict not in ("escalate", "ignore", "defer") or not reason:
            return None

        confidence = data.get("confidence")
        confidence = float(confidence) if isinstance(confidence, (int, float)) else None

        return Tier1Verdict(
            significant=verdict == "escalate",
            reason=reason,
            confidence=confidence,
            by_rule=False,
            # A defer is not an ignore. The vocabulary already carries the
            # distinction and losing it here would flatten "I cannot tell" into
            # "this does not matter", which are opposite claims about evidence.
            basis="triage_defer" if verdict == "defer" else "triage",
            decided_by=self.decided_by,
        )


# ------------------------------------------------------------------- tier two

class RuleDecider:
    """The Gemini stand-in. Runs only on escalations, sees the full record."""

    def __init__(self, why_degraded: str) -> None:
        self._why = why_degraded

    def describe(self) -> str:
        return f"RuleDecider, deterministic policy (stands in for Gemini, {DELIBERATION_PROMPT_VERSION})"

    @property
    def degraded(self) -> str | None:
        return f"Tier two ran as deterministic policy, not Gemini: {self._why}."

    async def decide(
        self, delta: Delta, corner: dict[str, Any], counts: Counts, escalation_reason: str
    ) -> Tier2Decision:
        deliberation_prompt(
            name=delta.name,
            grade=corner.get("grade"),
            index=corner.get("index"),
            delta=delta.summary(),
            escalation_reason=escalation_reason,
            counts=counts,
        )

        actions: list[str] = []
        because: list[str] = []

        # The letter cites collision figures in so many words, so any movement in
        # them makes a sentence in the published letter untrue.
        if delta.new_fatal or delta.new_severe or delta.new_collisions:
            actions.append("rescore")
            actions.append("regenerate_letter")
            because.append(
                "The letter on this corner's page states its collision figures outright, and those "
                "figures moved, so both the score inputs and the letter's own sentences are now behind "
                "the city's record."
            )

        if delta.new_fatal:
            actions.append("flag")
            because.append(
                "A new fatality is not something to leave to an automated redraft alone, so a human is "
                "flagged as well."
            )

        if delta.district_changed:
            actions.append("regenerate_letter")
            because.append(
                "The letter is addressed to a supervisor, and the district under this corner changed, so "
                "the address line is wrong."
            )

        if abs(delta.reports_311_change) >= 15 and not delta.new_collisions:
            actions.append("reaudit_imagery")
            because.append(
                "A street-condition swing this size with no new collisions points at something visible "
                "at the corner rather than at the crash record, so the imagery is what to look at."
            )

        # De-duplicate while holding the order the reasoning explains them in.
        ordered = list(dict.fromkeys(actions))

        if not ordered:
            return Tier2Decision(
                reasoning=(
                    "Tier one was right to send this up, and having looked at the corner's full record "
                    "there is still nothing here that makes a published figure wrong. The score inputs "
                    "did not move and the letter's stated numbers are all still accurate. Acting anyway "
                    "would churn the page without correcting anything, so this is a decline."
                ),
                actions=[],
            )

        return Tier2Decision(reasoning=" ".join(because), actions=ordered)  # type: ignore[arg-type]


def select_brains() -> tuple[Any, Any, str | None]:
    """Wire the tiers, and say plainly which ones are real.

    Returns the two tiers plus a single degradation line for the journal, or
    None when both tiers were genuinely models.

    `TRIAGE` chooses tier one and `DECIDER` chooses tier two. Both default to a
    model; `rule` keeps the deterministic stand-in selectable on either, so the
    two can be compared on the same journal rather than by argument. An
    unrecognised value raises rather than falling back, which is `config.py`'s
    rule and the reason it exists.

    There is one fallback here and it is loud. `DECIDER=adk` on a machine with no
    Vertex project cannot call a model, so it runs the stand-in and says so on
    every entry it writes. That is the same admission this module has always
    made; what it must never become is silence, because an agent that quietly
    degrades produces output indistinguishable from the real thing.

    Tier one now has the same shape, with one difference worth naming: Gemma can
    fail a single call and succeed on the next, so its fallback is per entry
    rather than per run and is recorded on the entry. The note returned from here
    covers only what is true for the whole run.
    """
    wanted = decider_name()
    wanted_triage = triage_name()
    ok, why = vertex_is_configured()

    triage: Any
    if wanted_triage == "rule":
        triage = RuleTriage(
            "TRIAGE=rule was selected, not because a model was unavailable"
        )
    elif ok:
        triage = GemmaTriage()
    else:
        triage = RuleTriage(why)

    # Joined rather than interpolated. Tier one's note is None when Gemma is
    # wired, and an f-string would have written the word "None" onto every entry
    # in the journal, which is worse than saying nothing because it looks like a
    # value.
    def note_with(tier_two: str) -> str:
        return " ".join(p for p in (triage.degraded, tier_two) if p)

    if wanted == "rule":
        decider = RuleDecider(why)
        return triage, decider, note_with(
            "Tier two ran as deterministic policy because DECIDER=rule was selected, not "
            "because a model was unavailable."
        )

    if not ok:
        decider = RuleDecider(why)
        return triage, decider, note_with(
            f"DECIDER=adk was requested but no model could be called: {why}. Tier two ran as "
            "deterministic policy instead. Nothing on this entry was decided by a model."
        )

    from .adk_decider import AdkDecider

    decider = AdkDecider(model=deliberation_model())
    # Both tiers are models in the default wiring, so there is nothing to admit
    # at the run level and the note is None. A tier one call that falls back is
    # recorded on the entry it happened to, not here.
    return triage, decider, triage.degraded
