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
"""

from __future__ import annotations

import os

DECIDER_IMPLEMENTATIONS = ("adk", "rule")
DEFAULT_DECIDER = "adk"

# The ADK's own built-in default at the version pinned here, and the oldest
# family the hackathon accepts. Overridden by DELIBERATION_MODEL.
DEFAULT_DELIBERATION_MODEL = "gemini-3.5-flash"
DEFAULT_TRIAGE_MODEL = "gemma-3-27b-it"

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
        f"decider={decider_name(env)}, deliberation model={deliberation_model(env)}, "
        f"location={vertex_location(env)}"
    )
