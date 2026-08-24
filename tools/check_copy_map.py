"""Keep each mapped block in the one home docs/COPY_MAP.md gives it.

Deduplicating prose once is easy. Keeping it deduplicated is not, because the
next person to write a paragraph does not know the argument already exists two
files away, and nothing tells them. That is how the degradation admission ended
up in four documents while each author was doing something reasonable.

So the map becomes a check, the same way figures did in check_numbers.py and the
ADK claim did in check_adk_claims.py. A block reappearing outside its canonical
home fails the build.

    python tools/check_copy_map.py

The fingerprint for each block is a set of distinctive phrases from its full
statement. A pointer is expected to name the block and say where it lives, so
short mentions are fine; what fails is a document restating enough of the
argument to make a reader who has already read the canonical home feel they are
reading it twice.

Exemptions are in the map and repeated here so the reason travels with the code:
DECISIONS.md and LOG.md are append-only records, and the blog, demo script and
social drafts are standalone artefacts that are read alone and must restate what
they need.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Documents a judge traverses in order. These are the ones that must not repeat
# each other.
TRAVERSED = [
    "README.md",
    "docs/FAQ.md",
    "docs/architecture.md",
    "docs/GEMINI_WIRING.md",
    "docs/GCP_PRECONDITIONS.md",
    "docs/COPY_MAP.md",
    "LEDGER_TEMPLATE",  # the page chrome in src/corner_watchdog/ledger.py
]

# Never checked, and why. See docs/COPY_MAP.md.
EXEMPT = {
    "DECISIONS.md": "append-only record",
    "LOG.md": "append-only record",
    "docs/blog_draft.md": "standalone artefact",
    "docs/demo_script.md": "standalone artefact",
    "docs/social_draft.md": "standalone artefact",
    "CONTRIBUTING.md": "read by contributors, outside the judge traversal",
}

# block -> (canonical home, phrases that only the full statement would contain,
#           how many of them may appear elsewhere before it counts as a restatement)
BLOCKS: dict[str, tuple[str, tuple[str, ...], int]] = {
    "restraint thesis": (
        "README.md",
        ("only publishes its actions", "highlight reel", "the deciding not to"),
        1,
    ),
    "origin disclosure": (
        "README.md",
        ("predates this hackathon", "prior Build Club event", "entirely new work"),
        1,
    ),
    "degradation, how it was false": (
        "LOG.md",
        ("Zero of 150 entries carried one", "the caveat attached only to entries",
         "every entry had been settled by a rule"),
        0,
    ),
    "ADK status": (
        "README.md",
        ("port is planned build-window work", "staged in the `cloud` extra"),
        0,
    ),
}

# The map file names every block, so it is allowed to mention all of them.
ALWAYS_ALLOWED = {"docs/COPY_MAP.md"}


def ledger_chrome() -> str:
    """Prose from the ledger page template, which is chrome rather than data."""
    src = (REPO / "src" / "corner_watchdog" / "ledger.py").read_text()
    blocks = re.findall(r'"""(.*?)"""', src, flags=re.S)
    html = "\n".join(b for b in blocks if "<" in b)
    html += "\n" + "\n".join(re.findall(r'"([^"\n]{40,})"', src))
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def prose(name: str) -> str:
    if name == "LEDGER_TEMPLATE":
        return ledger_chrome()
    path = REPO / name
    if not path.exists():
        return ""
    text = path.read_text()
    text = re.sub(r"```.*?```", " ", text, flags=re.S)   # fenced code is not prose
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return text


def check() -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    documents = {name: prose(name) for name in TRAVERSED}

    for block, (home, phrases, allowance) in BLOCKS.items():
        home_text = prose(home)
        present_at_home = sum(1 for p in phrases if p.lower() in home_text.lower())

        if home not in EXEMPT and present_at_home == 0:
            problems.append(
                f"{block!r}: its canonical home {home} no longer contains any of its "
                f"distinctive phrases. Either it moved without the map being updated, "
                f"or it was deleted."
            )
        notes.append(f"{block:<30} home {home:<18} {present_at_home}/{len(phrases)} phrases")

        for name, text in documents.items():
            if name == home or name in ALWAYS_ALLOWED:
                continue
            hits = [p for p in phrases if p.lower() in text.lower()]
            if len(hits) > allowance:
                problems.append(
                    f"{block!r} is restated in {name}: {len(hits)} distinctive phrase(s) "
                    f"{hits}, allowance {allowance}. Its home is {home}. Replace the "
                    f"restatement with one line and a pointer, or move the home in "
                    f"docs/COPY_MAP.md and update this rule in the same commit."
                )

    if not (REPO / "docs" / "COPY_MAP.md").exists():
        problems.append("docs/COPY_MAP.md is missing, and it is the contract this enforces.")

    return problems, notes


def main() -> int:
    problems, notes = check()
    for note in notes:
        print(note)
    print(f"{len(BLOCKS)} mapped blocks across {len(TRAVERSED)} traversed documents, "
          f"{len(EXEMPT)} exempt")

    if problems:
        print()
        print("Copy has drifted from docs/COPY_MAP.md:")
        for p in problems:
            print(f"  {p}")
        print()
        print("A judge reading these in order should meet each argument once. Fix the")
        print("document, or move the home in the map and this rule together.")
        return 1

    print("every mapped block is in its one home")
    return 0


if __name__ == "__main__":
    sys.exit(main())
