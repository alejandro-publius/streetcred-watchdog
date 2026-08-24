"""The copy map guard, and the drift it is supposed to stop.

Deduplicating prose once is easy. Keeping it deduplicated is not: the next person
to write a paragraph does not know the argument already exists two files away, and
until now nothing told them. That is how the degradation admission reached four
documents with every author doing something reasonable.

These tests drive the guard in both directions against a scratch tree. A guard
that passes on today's repository and would keep passing after somebody pastes
the thesis back into the FAQ is not a guard.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "check_copy_map.py"

THESIS = "An agent that only publishes its actions is showing you a highlight reel."
POINTER = 'The argument is in the README, under "Why the declines are the product".'


def load(repo_root: Path):
    spec = importlib.util.spec_from_file_location(f"copymap_{id(repo_root)}", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.REPO = repo_root
    return module


def build(tmp_path: Path, *, readme: str, faq: str = "", extra: dict[str, str] | None = None):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "src" / "corner_watchdog").mkdir(parents=True)
    (root / "README.md").write_text(readme)
    (root / "docs" / "FAQ.md").write_text(faq)
    (root / "docs" / "COPY_MAP.md").write_text("# Copy map\n")
    (root / "LOG.md").write_text(
        "Zero of 150 entries carried one. The cause was defensible: "
        "the caveat attached only to entries a tier had weighed, and "
        "every entry had been settled by a rule.\n"
    )
    (root / "src" / "corner_watchdog" / "ledger.py").write_text('X = "nothing here"\n')
    for name, body in (extra or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


FULL_README = (
    THESIS + " Anyone can build something that fires on every change. The hard part is\n"
    "the deciding not to.\n\n"
    "StreetCred predates this hackathon. It was built at a prior Build Club event. "
    "The Corner Watchdog is entirely new work.\n\n"
    "The Agent Development Kit is now genuinely in use: tier two is an `LlmAgent` "
    "with five registered tools.\n"
)


def test_the_deduplicated_repository_passes(tmp_path):
    root = build(tmp_path, readme=FULL_README, faq=POINTER)
    problems, _ = load(root).check()
    assert problems == []


def test_pasting_the_thesis_back_into_the_faq_fails(tmp_path):
    """The specific regression this exists to prevent."""
    root = build(tmp_path, readme=FULL_README,
                 faq=THESIS + " The hard part is the deciding not to.\n")
    problems, _ = load(root).check()
    assert any("restated in docs/FAQ.md" in p for p in problems)
    assert any("restraint thesis" in p for p in problems)


def test_a_pointer_that_also_re_argues_fails(tmp_path):
    """A pointer that restates the argument still makes a judge read it twice."""
    root = build(tmp_path, readme=FULL_README,
                 faq='See the README. ' + THESIS + " The hard part is the deciding not to.\n")
    problems, _ = load(root).check()
    assert any("restraint thesis" in p for p in problems)


def test_a_short_mention_is_allowed(tmp_path):
    """One distinctive phrase is within allowance. Pointers need to name things."""
    root = build(tmp_path, readme=FULL_README,
                 faq="Why the highlight reel framing matters is argued in the README.\n")
    problems, _ = load(root).check()
    assert problems == []


def test_losing_the_block_from_its_home_fails(tmp_path):
    """Deleting the canonical statement would otherwise silence the guard."""
    root = build(tmp_path, readme="A README with none of the mapped blocks in it.\n",
                 faq=POINTER)
    problems, _ = load(root).check()
    assert any("no longer contains any of its distinctive phrases" in p for p in problems)


def test_the_origin_disclosure_is_guarded_too(tmp_path):
    root = build(tmp_path, readme=FULL_README,
                 faq="StreetCred predates this hackathon, built at a prior Build Club event, "
                     "and the watchdog is entirely new work.\n")
    problems, _ = load(root).check()
    assert any("origin disclosure" in p for p in problems)


def test_the_adk_status_allows_no_restatement_anywhere(tmp_path):
    root = build(tmp_path, readme=FULL_README, faq=POINTER,
                 extra={"docs/GCP_PRECONDITIONS.md":
                        "Tier two is an `LlmAgent` with five registered tools.\n"})
    problems, _ = load(root).check()
    assert any("ADK status" in p for p in problems)


def test_the_history_story_may_not_leak_out_of_the_log(tmp_path):
    root = build(tmp_path, readme=FULL_README, faq=POINTER,
                 extra={"docs/architecture.md":
                        "Zero of 150 entries carried one.\n"})
    problems, _ = load(root).check()
    assert any("how it was false" in p and "architecture" in p for p in problems)


def test_exempt_documents_are_never_flagged(tmp_path):
    """Standalone artefacts are read alone and must restate what they need."""
    root = build(tmp_path, readme=FULL_README, faq=POINTER,
                 extra={"docs/blog_draft.md": THESIS + " the deciding not to\n",
                        "docs/demo_script.md": THESIS + " the deciding not to\n",
                        "docs/social_draft.md": THESIS + " the deciding not to\n",
                        "DECISIONS.md": THESIS + " the deciding not to\n",
                        "CONTRIBUTING.md": THESIS + " the deciding not to\n"})
    problems, _ = load(root).check()
    assert problems == []


def test_fenced_code_is_not_a_restatement(tmp_path):
    root = build(tmp_path, readme=FULL_README,
                 faq="```\n" + THESIS + " the deciding not to\n```\n")
    problems, _ = load(root).check()
    assert problems == []


def test_the_map_file_itself_may_name_every_block(tmp_path):
    root = build(tmp_path, readme=FULL_README, faq=POINTER)
    (root / "docs" / "COPY_MAP.md").write_text(
        THESIS + " the deciding not to. predates this hackathon. "
        "port is planned build-window work.\n"
    )
    problems, _ = load(root).check()
    assert problems == []


def test_a_missing_map_is_a_failure(tmp_path):
    root = build(tmp_path, readme=FULL_README, faq=POINTER)
    (root / "docs" / "COPY_MAP.md").unlink()
    problems, _ = load(root).check()
    assert any("COPY_MAP.md is missing" in p for p in problems)


# ------------------------------------------------ the repository as it stands

def test_the_real_repository_passes():
    import subprocess

    result = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "every mapped block is in its one home" in result.stdout


def test_the_map_document_exists_and_names_its_exemptions():
    text = (REPO / "docs" / "COPY_MAP.md").read_text()
    for exempt in ("DECISIONS.md", "LOG.md", "blog_draft", "demo_script", "social_draft"):
        assert exempt in text, f"{exempt} is exempt in code but not explained in the map"


def test_every_block_in_the_guard_appears_in_the_map():
    """The code and the contract must not drift apart."""
    tool = load(REPO)
    text = (REPO / "docs" / "COPY_MAP.md").read_text().lower()
    for block in tool.BLOCKS:
        stem = block.split(",")[0].strip().lower()
        assert stem in text, f"{block!r} is enforced but not written down in the map"
