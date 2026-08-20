"""Verify that the numbers in the documentation still match the repository.

Added after the documentation drifted from the code within a single working day.
Three files quoted an evaluation count and a test count that had been true when
written and were stale by the time anyone read them. Nothing failed, nothing
warned, and the numbers were wrong on exactly the pages that ask to be trusted.

That is the same failure this whole project is written against, committed by the
project itself, which is why it is now a build step rather than a resolution.

    python tools/check_numbers.py

Facts are read from the repository, never asserted here. Each rule names a
regular expression whose first group must equal the live value. If a document
legitimately needs to quote a stale figure, it should say the date it was true
and use wording the pattern does not match, rather than this file gaining an
exception.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def live_facts() -> dict[str, int]:
    """What is actually true, counted now."""
    journal = REPO / "state" / "journal.jsonl"
    entries = 0
    if journal.exists():
        entries = sum(1 for line in journal.read_text().splitlines() if line.strip())

    watched = REPO / "data" / "watched.json"
    corners = 0
    if watched.exists():
        corners = len(json.loads(watched.read_text()).get("corners") or [])

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    found = re.search(r"(\d+) tests collected", collected)
    tests = int(found.group(1)) if found else 0

    return {"entries": entries, "corners": corners, "tests": tests}


# (document, fact, pattern). The pattern's first group is compared to the fact.
# Every occurrence must match; a document quoting the same fact twice with two
# different numbers is the exact drift this catches.
RULES = [
    ("README.md", "tests", r"\|\s*Tests\s*\|\s*([\d,]+),"),
    ("README.md", "tests", r"#\s*([\d,]+) tests, no network"),
    ("README.md", "tests", r"all ([\d,]+) tests green"),
    ("README.md", "tests", r"\|\s*`tests/`\s*\|\s*([\d,]+) of them"),
    ("README.md", "entries", r"\|\s*Evaluations journaled\s*\|\s*([\d,]+)\s*\|"),
    ("README.md", "entries", r"Across ([\d,]+) real evaluations"),
    ("README.md", "corners", r"\|\s*Corners watched\s*\|\s*([\d,]+)\s*\|"),
    ("docs/FAQ.md", "entries", r"Every one of the ([\d,]+) declines"),
    ("docs/social_draft.md", "entries", r"It has made ([\d,]+) decisions"),
    ("docs/social_draft.md", "entries", r"intersections\. ([\d,]+) decisions so far"),
    ("CONTRIBUTING.md", "tests", r"lint, the ([\d,]+) tests"),
    ("docs/blog_draft.md", "entries", r"It has made ([\d,]+) decisions"),
]


def main(fix: bool = False) -> int:
    """Check every stated figure, or rewrite them to match.

    `--fix` exists because the journal grows on every cycle, so any count pinned
    in prose is stale within hours. Leaving that to be noticed by hand is how the
    drift happened in the first place. Refreshing is one command, and the check
    then holds the result.
    """
    facts = live_facts()
    problems: list[str] = []
    fixed = 0
    checked = 0

    for filename, fact, pattern in RULES:
        path = REPO / filename
        if not path.exists():
            problems.append(f"{filename}: missing, but a rule points at it")
            continue
        text = path.read_text()
        matches = re.findall(pattern, text)
        if not matches:
            problems.append(
                f"{filename}: no match for {fact} pattern {pattern!r}. Either the wording "
                "changed and the rule needs updating, or the figure was dropped."
            )
            continue

        if fix:
            def replace(match: re.Match[str], fact: str = fact) -> str:
                whole, stated = match.group(0), match.group(1)
                return whole.replace(stated, f"{facts[fact]:,}" if "," in stated else str(facts[fact]))

            updated = re.sub(pattern, replace, text)
            if updated != text:
                path.write_text(updated)
                fixed += 1
            continue

        for raw in matches:
            checked += 1
            stated = int(raw.replace(",", ""))
            if stated != facts[fact]:
                problems.append(
                    f"{filename}: says {fact} is {stated}, repository says {facts[fact]}"
                )

    print(f"live facts: {facts}")

    if fix:
        print(f"rewrote figures in {fixed} document(s)")
        return 0

    print(f"{checked} stated figures checked across {len({r[0] for r in RULES})} documents")

    if problems:
        print()
        print("Documentation disagrees with the repository:")
        for p in problems:
            print(f"  {p}")
        print()
        print("Run `python tools/check_numbers.py --fix` to refresh them, then read the diff.")
        print("A number on a page that asks to be trusted is the last place a stale figure")
        print("should be allowed to sit.")
        return 1

    print("every stated figure matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(fix="--fix" in sys.argv))
