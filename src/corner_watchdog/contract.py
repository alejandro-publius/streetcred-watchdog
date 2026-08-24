"""The decision schema both tiers must answer in, as typed code with a validator.

This file and the two prompt files under `src/prompts/` describe the same thing.
That duplication is the point of failure it is designed around: a prompt showing
one JSON shape while the parser expects another produces a model that is doing
its job and a system that discards the answer, and neither side logs anything
useful. So the examples inside the prompts are extracted and validated against
this module by the test suite, and the two cannot drift apart in silence.

Three design choices worth stating, because each one is a refusal:

  Unknown keys are rejected. A model that returns an extra field it invented
  gets an error, not a shrug. schema.py already says that a field which is not
  in the schema does not reach Firestore; this is the same rule one layer out,
  where the invention actually happens.

  Every verdict must justify itself in its own terms. Acting requires naming
  the published figure that is now wrong. Declining requires naming what is
  still accurate. Deferring requires naming what would resolve it. A schema
  that only demands prose gets prose; this one demands the specific claim that
  makes the verdict checkable by somebody who disagrees.

  Deferring exists. Without it a tier facing evidence it does not trust has two
  options, both bad: act on data it suspects, or decline and have that decline
  counted as restraint. A defer is a third thing and the ledger counts it as
  neither.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .schema import Tier1Verdict, Tier2Decision

TRIAGE_VERDICTS = ("escalate", "ignore", "defer")
DELIBERATION_VERDICTS = ("act", "decline", "defer")
ALLOWED_ACTIONS = ("rescore", "regenerate_letter", "reaudit_imagery", "flag")

TRIAGE_KEYS = {"verdict", "reason", "confidence"}
DELIBERATION_KEYS = {
    "verdict",
    "reasoning",
    "actions",
    "published_claim_now_wrong",
    "still_accurate",
    "what_would_resolve_it",
}

# Short enough to catch "ok" and "yes", long enough not to police style. The
# reason is published verbatim on a public page, so an empty one is a bug.
MIN_REASON_CHARS = 20

CONTRACT_VERSION = "decision-v1"


class ContractViolation(ValueError):
    """A model answer that cannot be trusted to mean what it appears to mean."""


def _require_text(d: dict[str, Any], key: str, verdict: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or len(value.strip()) < MIN_REASON_CHARS:
        raise ContractViolation(
            f"a {verdict!r} verdict requires {key!r} as at least {MIN_REASON_CHARS} characters "
            f"of plain sentence, got {value!r}"
        )
    return value.strip()


def _reject_unknown(d: dict[str, Any], allowed: set[str], what: str) -> None:
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise ContractViolation(
            f"{what} returned {len(unknown)} field(s) that are not in the schema: {unknown}. "
            "A field nobody defined is a field nobody validates, and it reads as a fact later."
        )


def _as_object(raw: Any, what: str) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ContractViolation(f"{what} did not return JSON: {e}") from None
    if not isinstance(raw, dict):
        raise ContractViolation(f"{what} must return a JSON object, got {type(raw).__name__}")
    return raw


# ------------------------------------------------------------------- tier one

@dataclass(frozen=True)
class TriageDecision:
    verdict: str
    reason: str
    confidence: float | None = None

    @property
    def escalates(self) -> bool:
        return self.verdict == "escalate"

    def to_tier1_verdict(self, *, basis: str | None = None) -> Tier1Verdict:
        """Into the shape the loop already runs on.

        A defer is not significant, because nothing should be spent on evidence
        the tier has just said it does not trust. It is also not an ordinary
        ignore, which is why the basis is carried separately.
        """
        return Tier1Verdict(
            significant=self.escalates,
            reason=self.reason,
            confidence=self.confidence,
            by_rule=False,
            basis=basis or ("triage_defer" if self.verdict == "defer" else "triage"),
        )


def parse_triage(raw: Any) -> TriageDecision:
    d = _as_object(raw, "triage")
    _reject_unknown(d, TRIAGE_KEYS, "triage")

    verdict = d.get("verdict")
    if verdict not in TRIAGE_VERDICTS:
        raise ContractViolation(
            f"triage verdict must be one of {list(TRIAGE_VERDICTS)}, got {verdict!r}"
        )

    reason = _require_text(d, "reason", verdict)

    confidence = d.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ContractViolation(f"confidence must be a number, got {confidence!r}")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ContractViolation(f"confidence must be between 0 and 1, got {confidence!r}")
        confidence = float(confidence)

    return TriageDecision(verdict=verdict, reason=reason, confidence=confidence)


# ------------------------------------------------------------------- tier two

@dataclass(frozen=True)
class DeliberationDecision:
    verdict: str
    reasoning: str
    actions: tuple[str, ...] = ()
    published_claim_now_wrong: str | None = None
    still_accurate: str | None = None
    what_would_resolve_it: str | None = None

    def to_tier2_decision(self) -> Tier2Decision:
        return Tier2Decision(reasoning=self.reasoning, actions=list(self.actions))  # type: ignore[arg-type]


def parse_deliberation(raw: Any) -> DeliberationDecision:
    d = _as_object(raw, "deliberation")
    _reject_unknown(d, DELIBERATION_KEYS, "deliberation")

    verdict = d.get("verdict")
    if verdict not in DELIBERATION_VERDICTS:
        raise ContractViolation(
            f"deliberation verdict must be one of {list(DELIBERATION_VERDICTS)}, got {verdict!r}"
        )

    reasoning = _require_text(d, "reasoning", verdict)

    actions = d.get("actions", [])
    if not isinstance(actions, list) or any(not isinstance(a, str) for a in actions):
        raise ContractViolation(f"actions must be a list of strings, got {actions!r}")
    unknown = [a for a in actions if a not in ALLOWED_ACTIONS]
    if unknown:
        raise ContractViolation(
            f"actions must come from {list(ALLOWED_ACTIONS)}, got {unknown}. An action with no "
            "verb behind it is a promise this system cannot keep."
        )
    if len(set(actions)) != len(actions):
        raise ContractViolation(f"actions must not repeat, got {actions}")

    # Each verdict has to justify itself in its own terms, and only its own.
    if verdict == "act":
        if not actions:
            raise ContractViolation(
                "an 'act' verdict with no actions is a decline wearing the wrong label"
            )
        _require_text(d, "published_claim_now_wrong", verdict)
    else:
        if actions:
            raise ContractViolation(
                f"a {verdict!r} verdict must not carry actions, got {actions}"
            )
        if verdict == "decline":
            _require_text(d, "still_accurate", verdict)
        else:
            _require_text(d, "what_would_resolve_it", verdict)

    return DeliberationDecision(
        verdict=verdict,
        reasoning=reasoning,
        actions=tuple(actions),
        published_claim_now_wrong=d.get("published_claim_now_wrong"),
        still_accurate=d.get("still_accurate"),
        what_would_resolve_it=d.get("what_would_resolve_it"),
    )


def triage_schema_block() -> str:
    """The exact text the prompt shows the model. One source, two readers."""
    return json.dumps(
        {
            "verdict": "escalate | ignore | defer",
            "reason": "one or two plain sentences, published verbatim",
            "confidence": "0.0 to 1.0, optional",
        },
        indent=2,
    )


def deliberation_schema_block() -> str:
    return json.dumps(
        {
            "verdict": "act | decline | defer",
            "reasoning": "two to four plain sentences, published verbatim",
            "actions": ["rescore | regenerate_letter | reaudit_imagery | flag"],
            "published_claim_now_wrong": "required when verdict is act",
            "still_accurate": "required when verdict is decline",
            "what_would_resolve_it": "required when verdict is defer",
        },
        indent=2,
    )
