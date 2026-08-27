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

    # A partial collection is not a smaller suite, it is a broken interpreter,
    # and the difference is invisible in the output. Run under the wrong python
    # and five files fail to import: pytest prints "530 tests collected, 5 errors"
    # and exits non-zero, and a version of this function that read only the first
    # number wrote 530 into the README where 661 was true. Refuse instead. A
    # figure this file cannot stand behind must not be published as one.
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only"],
        capture_output=True, text=True, cwd=REPO,
    )
    found = re.search(r"(\d+) tests collected", run.stdout)
    if run.returncode != 0 or not found:
        raise SystemExit(
            f"pytest could not collect the suite under {sys.executable}.\n"
            f"{run.stdout.strip().splitlines()[-1] if run.stdout.strip() else run.stderr.strip()}\n"
            "Run this through the project venv, .venv/bin/python, as tools/check.sh does. "
            "A count taken from a failed collection is a smaller number, not a smaller suite."
        )
    tests = int(found.group(1))

    return {"entries": entries, "corners": corners, "tests": tests}


# (document, fact, pattern). The pattern's first group is compared to the fact.
# Every occurrence must match; a document quoting the same fact twice with two
# different numbers is the exact drift this catches.
RULES = [
    ("README.md", "tests", r"\|\s*Tests\s*\|\s*([\d,]+),"),
    # Repointed 2026-08-26. The quick-start comment used to carry the full suite
    # count beside `pip install -e ".[dev]"`, which does not install the Google
    # client libraries, so a judge following it saw 652 next to a promise of 678.
    # The pinned figure moved to the line that describes the full install; the
    # documented path now states its own number, which this rule leaves alone
    # because it is a different fact.
    ("README.md", "tests", r"then pytest -q reports the full ([\d,]+)"),
    ("README.md", "tests", r"all ([\d,]+) tests green"),
    ("README.md", "tests", r"\|\s*`tests/`\s*\|\s*([\d,]+) of them"),
    ("README.md", "entries", r"\|\s*Evaluations journaled\s*\|\s*([\d,]+)\s*\|"),
    ("README.md", "entries", r"Across ([\d,]+) real evaluations"),
    ("README.md", "corners", r"\|\s*Corners watched\s*\|\s*([\d,]+)\s*\|"),
    ("docs/FAQ.md", "entries", r"Almost\. 171 of the ([\d,]+) declines"),
    ("docs/social_draft.md", "entries", r"It has made ([\d,]+) decisions"),
    ("docs/social_draft.md", "entries", r"intersections\. ([\d,]+) decisions so far"),
    # CONTRIBUTING.md used to pin the test count here. docs/COPY_MAP.md moved it
    # to a relative reference, "the full test suite", so there is no figure left
    # to check. The rule is removed rather than loosened: a pattern that matches
    # nothing would report a missing figure forever.
    ("docs/blog_draft.md", "entries", r"It has made ([\d,]+) decisions"),
    # The Devpost write-up quotes the suite size. Pinned for the same reason the
    # README's copy is: it is the figure a reader is most likely to check, and
    # the write-up is the document least likely to be reread before submission.
    ("docs/SUBMISSION.md", "tests", r"([\d,]+) on the agent in"),
]



# ---------------------------------------------------------------- the scoreboard

# docs/PROGRESS.md prints a bar chart above four checklists, and the chart was
# wrong: it claimed 30 of 40 items at 75 percent while its own tables held 43
# rows and 29 done. Nobody noticed because the header and the evidence for it are
# four screens apart, which is the same distance that let every other figure in
# this repository drift. So the chart is rendered from the rows rather than
# written next to them, and this holds the two together.

PROGRESS = "docs/PROGRESS.md"

AXES = [
    ("Innovation and utility (40%)", "## Innovation and utility, 40 percent"),
    ("Architecture (30%)", "## Architecture, 30 percent"),
    ("Demo readiness (30%)", "## Demo readiness, 30 percent"),
    ("Bonuses", "## Bonuses"),
]


def _tally(block: str) -> tuple[int, int]:
    rows = [ln for ln in block.splitlines() if ln.startswith(("| done |", "| **not** |"))]
    return sum(1 for ln in rows if ln.startswith("| done |")), len(rows)


def progress_counts(text: str) -> list[tuple[str, int, int]]:
    """Each axis, counted from the checklist under it."""
    starts = [text.index(h) for _, h in AXES]
    ends = [*starts[1:], text.index("## What moves the number most")]
    return [
        (label, *_tally(text[a:b]))
        for (label, _), a, b in zip(AXES, starts, ends, strict=True)
    ]


def render_chart(text: str) -> str:
    """The bar chart, from the rows. The needs-line is prose and is preserved."""
    counts = progress_counts(text)
    old = {}
    for line in text[text.index("```") : text.index("```", text.index("```") + 3)].splitlines():
        if "needs:" in line:
            old[line.split("[")[0].strip()] = "   needs:" + line.split("needs:")[1]
        elif "nothing outstanding" in line:
            old[line.split("[")[0].strip()] = "   nothing outstanding"

    lines = []
    for label, done, total in counts:
        pct = round(100 * done / total) if total else 0
        bar = "#" * round(pct / 5) + "-" * (20 - round(pct / 5))
        lines.append(f"{label:<30}[{bar}] {pct:>3}%{old.get(label, '')}")
    lines.append("-" * 78)
    d = sum(c[1] for c in counts)
    t = sum(c[2] for c in counts)
    pct = round(100 * d / t)
    bar = "#" * round(pct / 5) + "-" * (20 - round(pct / 5))
    lines.append(f"{'OVERALL':<30}[{bar}] {pct:>3}%   {d} of {t} items")
    return "```\n" + "\n".join(lines) + "\n```"


def check_progress(fix: bool) -> list[str]:
    path = REPO / PROGRESS
    if not path.exists():
        return [f"{PROGRESS}: missing, but the scoreboard rule points at it"]
    text = path.read_text()
    start = text.index("```")
    end = text.index("```", start + 3) + 3
    want = render_chart(text)
    if text[start:end] == want:
        return []
    if fix:
        path.write_text(text[:start] + want + text[end:])
        return []
    return [f"{PROGRESS}: the bar chart disagrees with the checklists under it"]


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

    problems += check_progress(fix)

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
