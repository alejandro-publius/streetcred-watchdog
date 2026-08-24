"""The ADK guard, tested in both of its states.

The scaffold README called both services "ADK agent, Cloud Run" and told the
requirements table that "Both services are ADK agents with registered tools".
Neither was ever true. The failure is the one this whole repository is organised
around: a framework installed but never imported looks exactly like a framework
in use, so there was nothing to notice.

A guard for that is only worth having if it works in both directions. One that
passes today and silently keeps passing after somebody writes the real port is
not a guard, it is a comment. So these tests drive the checker through both
states by writing a throwaway repository on disk and pointing it there.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "check_adk_claims.py"


def load_tool(repo_root: Path):
    """Import the checker with REPO pointed at a scratch tree."""
    spec = importlib.util.spec_from_file_location(f"adk_tool_{id(repo_root)}", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.REPO = repo_root
    module.SRC = repo_root / "src"
    return module


def build(tmp_path: Path, *, imports_adk: bool, readme: str, pyproject: str) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "corner_watchdog").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text(readme)
    (root / "pyproject.toml").write_text(pyproject)

    body = "import google.adk\n" if imports_adk else "# no framework here\n"
    (root / "src" / "corner_watchdog" / "server.py").write_text(body)
    return root


NOT_BUILT_ROW = "| Agent Development Kit | not built | **no** |\n"
BUILT_ROW = "| Agent Development Kit | `server.py` | yes |\n"
PLANNED = "The Agent Development Kit port is planned build-window work: staged.\n"
STAGED = '# STAGED FOR THE ADK PORT, IMPORTED BY NOTHING YET\n"google-adk>=0.1.0",\n'
UNSTAGED = '"google-adk>=0.1.0",\n'


# ============================================================ state one: not in use

def test_the_honest_not_in_use_repository_passes(tmp_path):
    root = build(tmp_path, imports_adk=False,
                 readme=PLANNED + NOT_BUILT_ROW, pyproject=STAGED)
    problems, _ = load_tool(root).check()
    assert problems == []


def test_a_usage_claim_fails_while_nothing_imports_it(tmp_path):
    """The exact sentence the scaffold README carried."""
    root = build(tmp_path, imports_adk=False,
                 readme="OBSERVER  (ADK agent, Cloud Run)\n" + PLANNED + NOT_BUILT_ROW,
                 pyproject=STAGED)
    problems, _ = load_tool(root).check()
    assert any("claims the ADK is in use" in p for p in problems)


def test_the_other_scaffold_sentence_also_fails(tmp_path):
    root = build(tmp_path, imports_adk=False,
                 readme="Both services are ADK agents with registered tools.\n"
                        + PLANNED + NOT_BUILT_ROW,
                 pyproject=STAGED)
    problems, _ = load_tool(root).check()
    assert any("claims the ADK is in use" in p for p in problems)


@pytest.mark.parametrize("claim", [
    "The observer is built on ADK.",
    "Both services are powered by the ADK.",
    "This is an ADK-based agent.",
    "Written using the Agent Development Kit.",
])
def test_every_way_of_reasserting_the_claim_fails(tmp_path, claim):
    root = build(tmp_path, imports_adk=False,
                 readme=claim + "\n" + PLANNED + NOT_BUILT_ROW, pyproject=STAGED)
    problems, _ = load_tool(root).check()
    assert any("claims the ADK is in use" in p for p in problems), claim


def test_a_wired_yes_in_the_requirements_row_fails(tmp_path):
    root = build(tmp_path, imports_adk=False, readme=PLANNED + BUILT_ROW, pyproject=STAGED)
    problems, _ = load_tool(root).check()
    assert any("no module" in p and "requirements row" in p for p in problems)


def test_an_unstaged_dependency_fails(tmp_path):
    """A dependency in an extra with no explanation reads as one in use."""
    root = build(tmp_path, imports_adk=False,
                 readme=PLANNED + NOT_BUILT_ROW, pyproject=UNSTAGED)
    problems, _ = load_tool(root).check()
    assert any("no staged marker" in p for p in problems)


def test_removing_the_dependency_entirely_is_also_acceptable(tmp_path):
    """The instruction offered two remedies. The guard must accept both."""
    root = build(tmp_path, imports_adk=False,
                 readme=PLANNED + NOT_BUILT_ROW, pyproject='"httpx>=0.27.0",\n')
    problems, _ = load_tool(root).check()
    assert problems == []


def test_a_missing_requirements_row_is_not_a_pass(tmp_path):
    """Deleting the row would otherwise be the easiest way to silence the guard."""
    root = build(tmp_path, imports_adk=False, readme=PLANNED, pyproject=STAGED)
    problems, _ = load_tool(root).check()
    assert any("no 'Agent Development Kit' row" in p for p in problems)


# ================================================================ state two: in use

def test_the_claim_inverts_once_a_module_imports_it(tmp_path):
    """The whole point. A guard that only ever checks one direction is a comment."""
    root = build(tmp_path, imports_adk=True,
                 readme=PLANNED + NOT_BUILT_ROW, pyproject=STAGED)
    problems, _ = load_tool(root).check()

    assert any("requirements row still says" in p for p in problems)
    assert any("still carries the staged marker" in p for p in problems)
    assert any("still calls the ADK port planned work" in p for p in problems)


def test_the_honest_in_use_repository_passes(tmp_path):
    root = build(tmp_path, imports_adk=True, readme=BUILT_ROW, pyproject=UNSTAGED)
    problems, _ = load_tool(root).check()
    assert problems == []


def test_a_usage_claim_is_allowed_once_it_is_true(tmp_path):
    root = build(tmp_path, imports_adk=True,
                 readme="Both services are ADK agents with registered tools.\n" + BUILT_ROW,
                 pyproject=UNSTAGED)
    problems, _ = load_tool(root).check()
    assert problems == []


def test_importing_without_declaring_the_dependency_fails(tmp_path):
    root = build(tmp_path, imports_adk=True, readme=BUILT_ROW, pyproject='"httpx>=0.27.0",\n')
    problems, _ = load_tool(root).check()
    assert any("not declared in pyproject" in p for p in problems)


@pytest.mark.parametrize("statement", ["import google.adk", "from google.adk import Agent",
                                       "from google.adk.agents import LlmAgent"])
def test_every_import_form_is_detected(tmp_path, statement):
    root = build(tmp_path, imports_adk=False, readme=BUILT_ROW, pyproject=UNSTAGED)
    (root / "src" / "corner_watchdog" / "server.py").write_text(statement + "\n")
    assert load_tool(root).adk_importers(), statement


# ================================================================== not fooled by

def test_a_docstring_saying_it_is_not_imported_does_not_count_as_an_import(tmp_path):
    """This repository literally contains that sentence. A grep would invert the state."""
    root = build(tmp_path, imports_adk=False, readme=PLANNED + NOT_BUILT_ROW, pyproject=STAGED)
    (root / "src" / "corner_watchdog" / "notes.py").write_text(
        '"""google-adk is in the cloud extra and nothing imports google.adk."""\n'
    )
    tool = load_tool(root)
    assert tool.adk_importers() == []
    assert tool.check()[0] == []


def test_a_command_inside_a_fenced_block_is_not_a_claim(tmp_path):
    root = build(tmp_path, imports_adk=False,
                 readme="```bash\npip install google-adk  # ADK agents\n```\n"
                        + PLANNED + NOT_BUILT_ROW,
                 pyproject=STAGED)
    problems, _ = load_tool(root).check()
    assert problems == []


# ================================================ the repository as it stands today

def test_the_real_repository_passes_right_now():
    import subprocess

    result = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NOT IN USE" in result.stdout


def test_the_real_repository_has_no_adk_import():
    assert load_tool(REPO).adk_importers() == []


def test_the_scaffold_readme_would_have_failed_this_guard(tmp_path):
    """The claim that prompted all of this, run against the checker that now exists."""
    import subprocess

    scaffold = subprocess.run(
        ["git", "show", "33ac6f2:README.md"], capture_output=True, text=True, cwd=REPO
    ).stdout
    if not scaffold:
        pytest.skip("scaffold commit not available")

    root = build(tmp_path, imports_adk=False, readme=scaffold, pyproject=STAGED)
    problems, _ = load_tool(root).check()
    assert any("claims the ADK is in use" in p for p in problems), (
        "the guard does not catch the sentence it was written for"
    )
