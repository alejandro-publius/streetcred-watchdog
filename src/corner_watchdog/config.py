"""Which implementation of each seam is wired, read from the environment.

`ports.py` names the seams and `runner.py` wires them. This file is the one
place that decides *which* side of a seam a given run gets, so that changing the
answer is an environment variable rather than an edit.

There is exactly one rule in here worth stating: an unrecognised value is an
error, never a silent fallback to the default. `DECIDER=adkk` quietly running the
deterministic stand-in, while the operator believes a model is deliberating, is
the failure this repository is written against, wearing a typo as a disguise.

    DECIDER=adk     the ADK judgment agent. The default.
    DECIDER=rule    the deterministic stand-in, kept selectable for comparison.
    TRIAGE=gemma    Gemma on Vertex. The default.
    TRIAGE=rule     the deterministic stand-in, kept selectable for comparison.
"""

from __future__ import annotations

import os

DECIDER_IMPLEMENTATIONS = ("adk", "rule")
DEFAULT_DECIDER = "adk"

TRIAGE_IMPLEMENTATIONS = ("gemma", "rule")
DEFAULT_TRIAGE = "gemma"

# The ADK's own built-in default at the version pinned here, and the oldest
# family the hackathon accepts. Overridden by DELIBERATION_MODEL.
DEFAULT_DELIBERATION_MODEL = "gemini-3.5-flash"
# Gemma reaches Vertex as a managed service rather than as an ordinary publisher
# model, and the name carries both the vendor prefix and the -maas suffix. The
# obvious name, `gemma-3-27b-it`, is what AI Studio serves and what Vertex
# answers with a 404 that reads like a permissions problem. Probed on 2026-08-26
# against both, and the finding is written up in docs/GEMINI_WIRING.md.
DEFAULT_TRIAGE_MODEL = "google/gemma-4-26b-a4b-it-maas"

# Vertex serves the 3.x family from the multi-region endpoint. A regional
# location that does not carry the model fails at call time with a 404 naming a
# publisher path, which reads as a permissions problem and is not one.
DEFAULT_LOCATION = "global"


class ConfigError(ValueError):
    """An environment that does not describe a runnable wiring."""


def decider_name(env: dict[str, str] | None = None) -> str:
    """Which Decider implementation this run gets."""
    source = os.environ if env is None else env
    # Stripped before the fallback, not after. `DECIDER=` and `DECIDER="  "` in a
    # .env file both mean the operator left it blank, which is unset, not a typo.
    raw = (source.get("DECIDER") or "").strip().lower() or DEFAULT_DECIDER
    if raw not in DECIDER_IMPLEMENTATIONS:
        raise ConfigError(
            f"DECIDER={raw!r} is not one of {list(DECIDER_IMPLEMENTATIONS)}. Refusing to "
            "guess, because falling back to the deterministic stand-in while the operator "
            "believes a model is deliberating is the exact failure this repository exists "
            "to prevent."
        )
    return raw


def triage_name(env: dict[str, str] | None = None) -> str:
    """Which Triage implementation this run gets.

    Same rule as decider_name, and for the same reason: tier one running as a
    rule while the operator believes Gemma is judging is the failure this file
    exists to prevent, and a typo is the likeliest way to cause it.
    """
    source = os.environ if env is None else env
    raw = (source.get("TRIAGE") or "").strip().lower() or DEFAULT_TRIAGE
    if raw not in TRIAGE_IMPLEMENTATIONS:
        raise ConfigError(
            f"TRIAGE={raw!r} is not one of {list(TRIAGE_IMPLEMENTATIONS)}. Refusing to guess."
        )
    return raw


def deliberation_model(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return (source.get("DELIBERATION_MODEL") or DEFAULT_DELIBERATION_MODEL).strip()


def triage_model(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return (source.get("TRIAGE_MODEL") or DEFAULT_TRIAGE_MODEL).strip()


def vertex_location(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return (source.get("GOOGLE_CLOUD_LOCATION") or DEFAULT_LOCATION).strip()


def vertex_project(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return (source.get("GOOGLE_CLOUD_PROJECT") or "").strip()


def describe(env: dict[str, str] | None = None) -> str:
    """One line for the cycle report, so a run says which wiring it had."""
    return (
        f"triage={triage_name(env)}, triage model={triage_model(env)}, "
        f"decider={decider_name(env)}, deliberation model={deliberation_model(env)}, "
        f"location={vertex_location(env)}"
    )
