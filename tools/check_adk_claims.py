"""Hold the documentation's ADK claims to what the source actually imports.

The scaffold README said, of both services, "ADK agent, Cloud Run", and the
requirements table said "Both services are ADK agents with registered tools".
Neither was true on the day it was written and neither ever became true. Nothing
caught it, because a framework you have installed but never import looks exactly
like a framework you are using, right up until somebody greps for the import.

So this is the same move as tools/check_numbers.py, applied to a claim rather
than a figure. Reality is read from the source tree, never asserted here, and the
documents are held to it.

    python tools/check_adk_claims.py

The check has two states and flips between them on its own.

    no module under src/ imports the ADK
        the docs may not claim it runs. The requirements row must read "not
        built". The staged marker in pyproject.toml is required, because a
        dependency sitting in an extra with no explanation reads as one in use.

    some module under src/ imports the ADK
        the claim inverts. The requirements row may no longer say "not built",
        the disclosure sentence calling the port planned work must go, and the
        staged marker must go, because by then every one of them is false.

Nobody has to remember to flip it. The first real `import google.adk` does it,
and the build fails until the prose catches up.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

# The distribution is google-adk; the import package is google.adk.
IMPORT_ROOTS = ("google.adk", "google_adk")
DISTRIBUTION = "google-adk"

STAGED_MARKER = "STAGED FOR THE ADK PORT, IMPORTED BY NOTHING YET"

# Phrasings that assert the framework is in use. Each one was either in the
# scaffold README or is the obvious way somebody would reintroduce the claim.
# Matched case insensitively against prose, not against code.
USAGE_CLAIMS = (
    r"ADK agents?\b",
    r"\bare ADK\b",
    r"built (?:on|with) (?:the )?ADK\b",
    r"powered by (?:the )?ADK\b",
    r"\bADK-based\b",
    r"using the Agent Development Kit\b",
    r"registered tools\b",
)

# Files whose ADK claims are checked. The historical record is deliberately not
# in here: LOG.md and DECISIONS.md describe what was true on a given day, and
# rewriting them to match today would be the opposite of a decision journal.
CHECKED_DOCS = (
    "README.md",
    "docs/architecture.md",
    "docs/architecture.mmd",
    "docs/FAQ.md",
    "docs/blog_draft.md",
    "docs/social_draft.md",
    "docs/demo_script.md",
)

REQUIREMENTS_ROW = re.compile(
    r"^\|\s*Agent Development Kit\s*\|\s*(?P<where>[^|]*?)\s*\|\s*(?P<wired>[^|]*?)\s*\|",
    re.M,
)


def adk_importers() -> list[str]:
    """Every module under src/ that imports the ADK, by AST rather than by grep.

    AST because a grep would match the word inside a docstring explaining that
    the ADK is not imported, which is a sentence this repository actually
    contains and would otherwise flip the check into its opposite state.
    """
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if any(name == root or name.startswith(root + ".") for root in IMPORT_ROOTS):
                    found.append(f"{path.relative_to(REPO)}: {name}")
    return found


def prose_lines(path: Path) -> list[tuple[int, str]]:
    """Lines outside fenced code blocks. A command is not a claim."""
    out: list[tuple[int, str]] = []
    fenced = False
    for n, line in enumerate(path.read_text().splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append((n, line))
    return out


def check() -> tuple[list[str], list[str]]:
    """Returns (problems, notes)."""
    importers = adk_importers()
    in_use = bool(importers)
    problems: list[str] = []
    notes: list[str] = [
        f"ADK imports found in src/: {importers if importers else 'none'}",
        f"state: {'IN USE' if in_use else 'NOT IN USE'}",
    ]

    # ---------------------------------------------------------- the prose claims
    for name in CHECKED_DOCS:
        path = REPO / name
        if not path.exists():
            continue
        for n, line in prose_lines(path):
            for pattern in USAGE_CLAIMS:
                if re.search(pattern, line, re.I):
                    if not in_use:
                        problems.append(
                            f"{name}:{n} claims the ADK is in use, and no module under src/ "
                            f"imports it: {line.strip()[:100]!r}"
                        )
                    break

    # ------------------------------------------------------- the requirements row
    readme = (REPO / "README.md").read_text()
    row = REQUIREMENTS_ROW.search(readme)
    if not row:
        problems.append(
            "README.md has no 'Agent Development Kit' row in the requirements table. "
            "That row is where the claim is made, so its absence is not a pass."
        )
    else:
        wired = row.group("wired").lower()
        says_no = "no" in wired
        if in_use and says_no:
            problems.append(
                f"README.md requirements row still says {row.group('wired')!r}, but "
                f"{len(importers)} module(s) now import the ADK. The claim inverted."
            )
        if not in_use and not says_no:
            problems.append(
                f"README.md requirements row says {row.group('wired')!r}, but no module "
                "under src/ imports the ADK."
            )

    # --------------------------------------------------------- the staged marker
    pyproject = (REPO / "pyproject.toml").read_text()
    declared = DISTRIBUTION in pyproject
    marked = STAGED_MARKER in pyproject

    if declared and not in_use and not marked:
        problems.append(
            f"pyproject.toml declares {DISTRIBUTION} but nothing imports it and it carries "
            f"no staged marker. Either remove it from the extra or annotate it with "
            f"'{STAGED_MARKER}', so its presence is not read as evidence of use."
        )
    if in_use and marked:
        problems.append(
            f"pyproject.toml still carries the staged marker while {len(importers)} module(s) "
            "import the ADK. The marker says it is imported by nothing, which is now false."
        )
    if not declared and in_use:
        problems.append(
            f"src/ imports the ADK but {DISTRIBUTION} is not declared in pyproject.toml."
        )

    # ------------------------------------------- the disclosure sentence, once used
    planned = "Agent Development Kit port is planned build-window work" in readme
    if in_use and planned:
        problems.append(
            "README.md still calls the ADK port planned work while src/ imports it."
        )
    if not in_use and not planned:
        notes.append(
            "note: the README does not call the ADK port planned work. Not required, "
            "but the disclosure is where a reader looks for it."
        )

    return problems, notes


def main() -> int:
    problems, notes = check()
    for note in notes:
        print(note)

    if problems:
        print()
        print("Documentation disagrees with the source about the ADK:")
        for p in problems:
            print(f"  {p}")
        print()
        print("Fix the document or the dependency, not this file. A framework that is")
        print("installed but never imported looks exactly like one that is in use.")
        return 1

    print("every ADK claim matches what src/ imports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
