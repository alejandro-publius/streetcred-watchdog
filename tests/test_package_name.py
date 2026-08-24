"""The package name was taken, and the collision was invisible until it wasn't.

This package was called `watchdog` for the whole life of the project. That name
is also a very popular PyPI distribution, the file-system event library, and
`google-adk` depends on it: `google/adk/cli/fast_api.py` opens with
`from watchdog.observers import Observer`.

Two packages cannot share one import name. Whichever one wins, the other breaks,
and the way it breaks is the failure mode this repository is organised around:

    site-packages wins   `python -m watchdog` dies with "cannot be directly
                         executed", because it found the file-system library.
    src/ wins            `adk web` dies with "No module named
                         watchdog.observers", because it found this repository.

Neither is a crash in the thing you changed. Installing the ADK broke the
project's own entry point, and putting the project back on the path broke the
ADK's web console, and in both directions the error names a module nobody in
this repository wrote. So the package is `corner_watchdog` now, and this file
holds the two facts that made the rename necessary, so that a future reader who
wonders why the directory does not match the command has the answer here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_this_project_imports_as_corner_watchdog():
    import corner_watchdog

    assert Path(corner_watchdog.__file__).parent == REPO / "src" / "corner_watchdog"


def test_no_module_in_src_is_named_watchdog():
    """The directory is the claim. A stray re-add would resurrect the collision."""
    assert not (REPO / "src" / "watchdog").exists()


def test_the_third_party_watchdog_is_not_shadowed_by_this_repository():
    """The invariant `adk web` needs.

    Skipped rather than failed when the library is absent, because a clean
    `pip install -e ".[dev]"` has no reason to pull it in. The moment the ADK is
    installed it arrives, and from then on this is checked on every run.
    """
    if importlib.util.find_spec("watchdog") is None:
        pytest.skip("the third-party watchdog library is not installed here")

    import watchdog

    assert "site-packages" in str(Path(watchdog.__file__).resolve()), (
        f"`import watchdog` resolved to {watchdog.__file__}, which is not the "
        "file-system event library the ADK expects. `adk web` cannot boot in "
        "this state."
    )
    # The specific submodule the ADK reaches for, rather than the package alone.
    # A namespace package would satisfy the assertion above and still fail here.
    assert importlib.util.find_spec("watchdog.observers") is not None


def test_the_adk_web_console_can_still_import_its_reloader():
    """The end the rename was for, checked end to end rather than by proxy."""
    if importlib.util.find_spec("google.adk") is None:
        pytest.skip("google-adk is not installed here")

    # This is the import line that failed while this repository owned the name.
    from watchdog.observers import Observer  # noqa: F401

    assert importlib.util.find_spec("google.adk.cli.fast_api") is not None
