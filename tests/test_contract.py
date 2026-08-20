"""The decision contract, and the guarantee that the prompts still match it.

Two files describe this schema: `contract.py` enforces it and the markdown under
`src/prompts/` shows it to a model. That duplication is the failure this suite is
built around. A prompt teaching one JSON shape while the parser expects another
produces a model doing its job perfectly and a system throwing the answer away,
and neither side logs anything that would explain it.

So every fenced JSON block in both prompt files is extracted and pushed through
the real parser. Editing an example into a shape the code rejects fails here,
and so does tightening the code past what the examples teach.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from watchdog.contract import (
    ALLOWED_ACTIONS,
    DELIBERATION_KEYS,
    DELIBERATION_VERDICTS,
    MIN_REASON_CHARS,
    TRIAGE_KEYS,
    TRIAGE_VERDICTS,
    ContractViolation,
    deliberation_schema_block,
    parse_deliberation,
    parse_triage,
    triage_schema_block,
)

PROMPTS = Path(__file__).resolve().parents[1] / "src" / "prompts"
TRIAGE_MD = PROMPTS / "triage.md"
DELIBERATION_MD = PROMPTS / "deliberation.md"

FENCE = re.compile(r"```json\n(.*?)```", re.S)


def json_blocks(path: Path) -> list[dict]:
    """Every fenced JSON block in a prompt file, in order."""
    out = []
    for raw in FENCE.findall(path.read_text()):
        out.append(json.loads(raw))
    return out


def examples(path: Path) -> list[dict]:
    """The worked examples: every block except the schema declaration itself.

    The schema block is the one whose values are type descriptions rather than
    answers, and it is always the first block in the file.
    """
    return json_blocks(path)[1:]


# ------------------------------------------------------- the files are there

def test_both_prompt_files_exist():
    assert TRIAGE_MD.exists()
    assert DELIBERATION_MD.exists()


def _keys_declared_in(prompt_text: str) -> set[str]:
    """The JSON field names a rendered prompt actually shows the model."""
    unescaped = prompt_text.replace("{{", "{").replace("}}", "}")
    return set(re.findall(r'"(\w+)":', unescaped))


def test_the_python_triage_prompt_declares_the_schema_the_code_enforces():
    """The gap that let a real drift through.

    This suite originally checked only the markdown under src/prompts/, so
    prompts.py went on teaching the pre-contract shape, `{"significant": ...}`,
    while the parser had moved to `{"verdict": ...}`. A model following that
    prompt perfectly would have had every answer rejected, and nothing on either
    side would have logged why.
    """
    from watchdog.prompts import TRIAGE_PROMPT

    assert _keys_declared_in(TRIAGE_PROMPT) == TRIAGE_KEYS


def test_the_python_deliberation_prompt_declares_the_schema_the_code_enforces():
    from watchdog.prompts import DELIBERATION_PROMPT

    assert _keys_declared_in(DELIBERATION_PROMPT) == DELIBERATION_KEYS


def test_the_python_prompts_and_the_markdown_agree_on_the_verdicts():
    from watchdog.prompts import DELIBERATION_PROMPT, TRIAGE_PROMPT

    for verdict in TRIAGE_VERDICTS:
        assert verdict in TRIAGE_PROMPT, f"triage prompt never mentions {verdict!r}"
    for verdict in DELIBERATION_VERDICTS:
        assert verdict in DELIBERATION_PROMPT, f"deliberation prompt never mentions {verdict!r}"


def test_a_rendered_triage_prompt_still_declares_the_schema():
    """Rendered, not just the template, so a format() bug cannot hide it."""
    from watchdog.prompts import triage_prompt
    from watchdog.schema import Calibration

    rendered = triage_prompt(
        name="6th and Mission", grade="F", index=99,
        delta="3 new injury collisions.", calibration=Calibration(),
    )
    assert _keys_declared_in(rendered) == TRIAGE_KEYS


def test_the_triage_prompt_declares_the_schema_the_code_enforces():
    declared = json_blocks(TRIAGE_MD)[0]
    assert set(declared) == set(json.loads(triage_schema_block()))


def test_the_deliberation_prompt_declares_the_schema_the_code_enforces():
    declared = json_blocks(DELIBERATION_MD)[0]
    assert set(declared) == set(json.loads(deliberation_schema_block()))


# ------------------------------------- every worked example survives the parser

def test_the_triage_prompt_has_the_six_examples_it_promises():
    assert len(examples(TRIAGE_MD)) == 6


def test_the_deliberation_prompt_has_the_four_examples_it_promises():
    assert len(examples(DELIBERATION_MD)) == 4


@pytest.mark.parametrize("example", examples(TRIAGE_MD))
def test_every_triage_example_parses(example):
    decision = parse_triage(example)
    assert decision.verdict in TRIAGE_VERDICTS
    assert len(decision.reason) >= MIN_REASON_CHARS


@pytest.mark.parametrize("example", examples(DELIBERATION_MD))
def test_every_deliberation_example_parses(example):
    decision = parse_deliberation(example)
    assert decision.verdict in DELIBERATION_VERDICTS
    assert all(a in ALLOWED_ACTIONS for a in decision.actions)


def test_the_triage_examples_cover_all_three_verdicts():
    """An example set that never shows a verdict does not teach it."""
    seen = {parse_triage(e).verdict for e in examples(TRIAGE_MD)}
    assert seen == set(TRIAGE_VERDICTS)


def test_the_deliberation_examples_cover_all_three_verdicts():
    seen = {parse_deliberation(e).verdict for e in examples(DELIBERATION_MD)}
    assert seen == set(DELIBERATION_VERDICTS)


def test_a_fatality_example_flags_a_human():
    """Rule 5 in the prompt. An example that contradicted it would teach the opposite."""
    acted = [parse_deliberation(e) for e in examples(DELIBERATION_MD)
             if parse_deliberation(e).verdict == "act"]
    fatal = [d for d in acted if "killed" in d.reasoning or "died" in d.reasoning]
    assert fatal, "no worked example covers a fatality"
    assert all("flag" in d.actions for d in fatal)


def test_the_decline_example_names_what_is_still_accurate():
    declines = [parse_deliberation(e) for e in examples(DELIBERATION_MD)
                if parse_deliberation(e).verdict == "decline"]
    assert declines
    assert all(d.still_accurate for d in declines)


def test_the_defer_example_names_what_would_resolve_it():
    defers = [parse_deliberation(e) for e in examples(DELIBERATION_MD)
              if parse_deliberation(e).verdict == "defer"]
    assert defers
    assert all(d.what_would_resolve_it for d in defers)


def test_the_prompts_label_which_numbers_are_synthetic():
    """The house rule: no invented data presented as real."""
    for path in (TRIAGE_MD, DELIBERATION_MD):
        text = path.read_text()
        assert "synthetic" in text.lower()
        assert "2026-08-20" in text  # the date the real figures were read


# ------------------------------------------------------------ triage parsing

def test_a_verdict_outside_the_set_is_refused():
    with pytest.raises(ContractViolation) as e:
        parse_triage({"verdict": "maybe", "reason": "a" * 30})
    assert "must be one of" in str(e.value)


def test_a_missing_verdict_is_refused():
    with pytest.raises(ContractViolation):
        parse_triage({"reason": "a" * 30})


def test_an_empty_reason_is_refused():
    """It is published verbatim on a public page."""
    with pytest.raises(ContractViolation):
        parse_triage({"verdict": "ignore", "reason": ""})


def test_a_one_word_reason_is_refused():
    with pytest.raises(ContractViolation):
        parse_triage({"verdict": "ignore", "reason": "noise"})


def test_an_invented_field_is_refused():
    """A field nobody defined is a field nobody validates."""
    with pytest.raises(ContractViolation) as e:
        parse_triage({"verdict": "ignore", "reason": "a" * 30, "urgency": "high"})
    assert "urgency" in str(e.value)


@pytest.mark.parametrize("bad", [-0.1, 1.1, "high", True])
def test_a_confidence_outside_zero_to_one_is_refused(bad):
    with pytest.raises(ContractViolation):
        parse_triage({"verdict": "ignore", "reason": "a" * 30, "confidence": bad})


def test_confidence_is_optional():
    assert parse_triage({"verdict": "ignore", "reason": "a" * 30}).confidence is None


def test_a_json_string_is_accepted_as_well_as_an_object():
    """Models return text. The parser should not need a wrapper to say so."""
    d = parse_triage(json.dumps({"verdict": "escalate", "reason": "a" * 30}))
    assert d.escalates is True


def test_prose_around_the_json_is_refused_rather_than_salvaged():
    with pytest.raises(ContractViolation) as e:
        parse_triage('Sure! Here is my answer:\n{"verdict": "ignore"}')
    assert "did not return JSON" in str(e.value)


def test_a_defer_becomes_a_non_significant_verdict_with_its_own_basis():
    """Nothing should be spent on evidence the tier just said it does not trust."""
    v = parse_triage({"verdict": "defer", "reason": "a" * 30}).to_tier1_verdict()
    assert v.significant is False
    assert v.basis == "triage_defer"
    assert v.by_rule is False


def test_an_ignore_and_a_defer_are_not_the_same_basis():
    ignore = parse_triage({"verdict": "ignore", "reason": "a" * 30}).to_tier1_verdict()
    defer = parse_triage({"verdict": "defer", "reason": "a" * 30}).to_tier1_verdict()
    assert ignore.basis != defer.basis


# ------------------------------------------------------ deliberation parsing

def base_act(**over):
    d = {
        "verdict": "act",
        "reasoning": "a" * 40,
        "actions": ["rescore"],
        "published_claim_now_wrong": "b" * 40,
    }
    d.update(over)
    return d


def test_an_act_with_no_actions_is_refused():
    with pytest.raises(ContractViolation) as e:
        parse_deliberation(base_act(actions=[]))
    assert "decline wearing the wrong label" in str(e.value)


def test_an_act_without_naming_the_wrong_claim_is_refused():
    """The trace-before-action contract, enforced rather than requested."""
    d = base_act()
    del d["published_claim_now_wrong"]
    with pytest.raises(ContractViolation) as e:
        parse_deliberation(d)
    assert "published_claim_now_wrong" in str(e.value)


def test_a_decline_carrying_actions_is_refused():
    with pytest.raises(ContractViolation) as e:
        parse_deliberation({"verdict": "decline", "reasoning": "a" * 40,
                            "actions": ["rescore"], "still_accurate": "b" * 40})
    assert "must not carry actions" in str(e.value)


def test_a_decline_without_naming_what_is_still_accurate_is_refused():
    with pytest.raises(ContractViolation):
        parse_deliberation({"verdict": "decline", "reasoning": "a" * 40})


def test_a_defer_without_naming_what_would_resolve_it_is_refused():
    with pytest.raises(ContractViolation):
        parse_deliberation({"verdict": "defer", "reasoning": "a" * 40})


def test_an_invented_action_verb_is_refused():
    with pytest.raises(ContractViolation) as e:
        parse_deliberation(base_act(actions=["rescore", "tweet_about_it"]))
    assert "tweet_about_it" in str(e.value)
    assert "promise this system cannot keep" in str(e.value)


def test_a_repeated_action_is_refused():
    with pytest.raises(ContractViolation):
        parse_deliberation(base_act(actions=["rescore", "rescore"]))


def test_actions_must_be_a_list_of_strings():
    with pytest.raises(ContractViolation):
        parse_deliberation(base_act(actions="rescore"))


def test_a_valid_act_converts_into_the_internal_decision():
    d = parse_deliberation(base_act(actions=["rescore", "flag"]))
    tier2 = d.to_tier2_decision()
    assert tier2.actions == ["rescore", "flag"]
    assert tier2.reasoning == "a" * 40


def test_a_defer_converts_into_a_decision_with_no_actions():
    d = parse_deliberation({"verdict": "defer", "reasoning": "a" * 40,
                            "what_would_resolve_it": "b" * 40})
    assert d.to_tier2_decision().actions == []


def test_every_allowed_action_is_actually_accepted():
    """A verb the prompt teaches but the parser rejects is a trap."""
    for verb in ALLOWED_ACTIONS:
        assert parse_deliberation(base_act(actions=[verb])).actions == (verb,)
