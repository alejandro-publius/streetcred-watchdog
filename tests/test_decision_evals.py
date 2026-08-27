"""The ADK eval set, run against the graph in the test suite.

`evals/decisions.evalset.json` is a real `google.adk.evaluation.EvalSet` built by
`tools/build_evalset.py` from this repository's own recorded DataSF snapshots.
The same file is what `adk eval` reads against a live model.

What this file runs is the offline half, and it is worth being precise about what
that measures, because "eval" is a word that invites the wrong reading. It is not
a score for how well a model decides. Every case runs against the policy model in
tests/policy_model.py, which applies the deliberation prompt's policy rather than
reasoning about it, so what is under test is the graph:

    the routing        did the cheap tier settle it, or did it reach tier two
    the trajectory     did the deliberation end in exactly one tool, and that one
    the translation    did `re_audit` become `reaudit_imagery` in the journal, and
                       did `also` survive into the action list
    the contract       is a tool call held to the same rules JSON was
    the gates          did the budget stop it before the model, and did the
                       injection screen keep hostile text away from it

All of that is deterministic and none of it needs a network, which is why it can
live in a suite that runs offline in a second. The other half, whether a model
picks the right tool, needs the model and is reported separately.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from google.adk.evaluation.eval_set import EvalSet
from google.adk.runners import InMemoryRunner
from google.genai import types
from policy_model import PolicyModel

from corner_watchdog.adk_decider import AdkDecider, Guardrails
from corner_watchdog.adk_graph import build_graph
from corner_watchdog.budget import ActionBudget

REPO = Path(__file__).resolve().parents[1]
EVALSET = REPO / "evals" / "decisions.evalset.json"
# The recordings the cases were built from, shipped so the claim can be checked
# from a clone. state/ is gitignored and a clone has none of it.
SHIPPED = REPO / "evals" / "snapshots"

# The tool the model calls, and the action the journal stores.
EXPECTED_ACTION = {
    "flag": "flag",
    "rescore": "rescore",
    "regenerate_letter": "regenerate_letter",
    "re_audit": "reaudit_imagery",
}


def load() -> EvalSet:
    return EvalSet.model_validate(json.loads(EVALSET.read_text()))


def case_message(case) -> str:
    return case.conversation[0].user_content.parts[0].text


def expected_tools(case) -> list[str]:
    data = case.conversation[0].intermediate_data
    return [t.name for t in (data.tool_uses if data else [])]


def guard_of(case) -> str:
    state = case.session_input.state if case.session_input else {}
    return state.get("guard") or ""


def run_case(case) -> dict:
    """One eval case, through the same graph production runs."""
    guard = guard_of(case)
    budget = ActionBudget(limit=0 if guard == "budget" else 40)
    model = PolicyModel()
    decider = AdkDecider(model=model, guardrails=Guardrails(action_budget=budget))
    graph = build_graph(decider.agent)

    async def go():
        runner = InMemoryRunner(agent=graph, app_name="eval")
        session = await runner.session_service.create_session(app_name="eval", user_id="u")
        tools: list[str] = []
        async for event in runner.run_async(
            user_id="u",
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part(text=case_message(case))]
            ),
        ):
            for part in (event.content.parts if event.content else []) or []:
                if part.function_call:
                    tools.append(part.function_call.name)
        return tools

    tools = asyncio.run(go())
    return {
        "eval_id": case.eval_id,
        "guard": guard,
        "expected": expected_tools(case),
        "got": tools,
        "model_called": model.was_called,
        "decision": decider.outcome.decision,
        "intents": list(decider.outcome.intents),
    }


CASES = load().eval_cases
RESULTS: dict[str, dict] = {}


@pytest.fixture(scope="module", autouse=True)
def results_table():
    yield
    if not RESULTS:
        return
    rows = [RESULTS[c.eval_id] for c in CASES if c.eval_id in RESULTS]
    width = max(len(r["eval_id"]) for r in rows)
    print("\n\n  ADK decision eval set, offline against the policy model")
    print(f"  {'case':<{width}}  {'expected':<18} {'got':<18} {'model':<6} result")
    print(f"  {'-' * width}  {'-' * 18} {'-' * 18} {'-' * 6} ------")
    for r in rows:
        expected = ", ".join(r["expected"]) or "(no tool)"
        got = ", ".join(r["got"]) or "(no tool)"
        ok = "pass" if r["expected"] == r["got"] else "FAIL"
        print(
            f"  {r['eval_id']:<{width}}  {expected:<18} {got:<18} "
            f"{r['model_called']!s:<6} {ok}"
        )
    passed = sum(1 for r in rows if r["expected"] == r["got"])
    print(f"\n  {passed}/{len(rows)} cases matched their expected tool trajectory\n")


# ==================================================================== the trajectory

@pytest.mark.parametrize("case", CASES, ids=lambda c: c.eval_id)
def test_each_case_ends_in_the_tool_it_is_supposed_to(case):
    result = run_case(case)
    RESULTS[case.eval_id] = result

    assert result["got"] == result["expected"], (
        f"{case.eval_id} expected {result['expected']} and got {result['got']}"
    )


@pytest.mark.parametrize(
    "case", [c for c in CASES if not guard_of(c)], ids=lambda c: c.eval_id
)
def test_every_unguarded_case_signs_exactly_once(case):
    """Zero is an error and two is an error. Neither is a decline."""
    result = RESULTS.get(case.eval_id) or run_case(case)
    RESULTS[case.eval_id] = result

    assert len(result["got"]) == 1


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if expected_tools(c) and expected_tools(c) != ["decline"]],
    ids=lambda c: c.eval_id,
)
def test_an_action_case_lands_on_an_action_the_actuator_implements(case):
    result = RESULTS.get(case.eval_id) or run_case(case)
    RESULTS[case.eval_id] = result

    decision = result["decision"]
    assert decision is not None
    assert decision.actions[0] == EXPECTED_ACTION[result["expected"][0]]


@pytest.mark.parametrize(
    "case", [c for c in CASES if expected_tools(c) == ["decline"]], ids=lambda c: c.eval_id
)
def test_a_decline_case_carries_reasoning_and_no_actions(case):
    """The property the restraint rate depends on, checked case by case."""
    result = RESULTS.get(case.eval_id) or run_case(case)
    RESULTS[case.eval_id] = result

    decision = result["decision"]
    assert decision is not None
    assert decision.actions == []
    assert len(decision.reasoning) > 40, "a decline published verbatim needs to say something"


# ======================================================================== the gates

def test_the_budget_exhausted_case_never_reaches_the_model():
    case = next(c for c in CASES if guard_of(c) == "budget")
    result = RESULTS.get(case.eval_id) or run_case(case)
    RESULTS[case.eval_id] = result

    assert result["model_called"] is False
    assert result["got"] == []
    assert result["intents"] and "budget" in result["intents"][0]


def test_the_injection_case_never_reaches_the_model():
    case = next(c for c in CASES if guard_of(c) == "injection")
    result = RESULTS.get(case.eval_id) or run_case(case)
    RESULTS[case.eval_id] = result

    assert result["model_called"] is False
    assert result["got"] == []
    assert result["intents"] and "Screened" in result["intents"][0]


# ================================================================== the set itself

def test_the_eval_set_validates_against_the_adk_schema():
    """So `adk eval` reading it is a fact rather than a hope."""
    assert load().eval_set_id == "corner_watchdog_decisions"


def test_the_set_covers_every_action_tool_and_the_decline():
    covered = {t for c in CASES for t in expected_tools(c)}
    assert covered == {"flag", "rescore", "regenerate_letter", "re_audit", "decline"}


def test_the_set_has_at_least_eight_cases():
    assert len(CASES) >= 8


def test_every_case_is_built_from_a_real_recorded_snapshot():
    """No invented current record. The baseline is constructed; the reading is not.

    The recordings ship in `evals/snapshots/` rather than being read out of
    `state/`, which is gitignored. Reading `state/` meant this asserted against
    an empty set on every fresh clone while passing on any machine that had ever
    run a cycle, which is exactly backwards: the claim is about the eval set, so
    the evidence for it travels with the eval set.
    """
    shipped = {p.stem for p in SHIPPED.glob("*.json")}
    assert shipped, f"no recordings in {SHIPPED}, so this claim cannot be checked"
    for case in CASES:
        envelope = json.loads(case_message(case))
        assert envelope["corner"]["slug"] in shipped
        assert "constructed by offsetting the real record" in envelope["baselineNote"]


def test_the_shipped_recordings_are_readings_and_not_hand_written_fixtures():
    """A stub with the right filename would satisfy the check above.

    So the shape is checked too: a real reading carries the query fingerprint the
    fetcher stamps, a fetch timestamp, and a complete flag. None of those are
    things anyone would bother inventing, and all three are what makes the
    snapshot traceable back to a cycle.
    """
    for path in sorted(SHIPPED.glob("*.json")):
        snap = json.loads(path.read_text())
        assert snap["slug"] == path.stem
        assert snap["complete"] is True
        assert snap["query_fingerprint"].startswith("r=80m;collisions=5y")
        assert snap["fetched_at"].startswith("2026-"), "a reading carries when it was read"
        assert snap["counts"]["collisions_5y"] > 0


def test_every_case_uses_a_different_corner():
    """Nine cases on one corner would prove nine things about one record."""
    slugs = [json.loads(case_message(c))["corner"]["slug"] for c in CASES]
    assert len(set(slugs)) == len(slugs)
