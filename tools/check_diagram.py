"""The architecture diagram exists in three places, so hold them together.

There is one source, `docs/architecture.mmd`, and three renderings of it: a PNG,
and an inline copy in each of the two READMEs. Three copies of one drawing is the
same drift surface as three copies of one number, and this repository already
learned what happens to those. The version that stood here until 2026-08-26 was a
week stale and still said no Google Cloud account had been touched.

So the READMEs are generated from the source rather than edited beside it, and
this fails the build when they disagree.

    python tools/check_diagram.py          check
    python tools/check_diagram.py --fix    rewrite the README blocks from source

The sibling repository is checked only when it is where it usually is. A skip is
printed as a skip: a guard that quietly passes because it could not find its
subject is worse than no guard, because it reports the same word either way.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "docs" / "architecture.mmd"
SIBLING = REPO.parent / "streetcred" / "README.md"

# The inline copies drop the render-time config and the comments about how to
# render. What is left is the structure, which is the part that must not drift.
INLINE_INIT = (
    '%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 45, '
    '"rankSpacing": 55, "padding": 14, "wrappingWidth": 460}}}%%'
)

MARKER = "The escalation path"  # picks this diagram out of a README holding others


def expected_block() -> str:
    lines = SOURCE.read_text().splitlines()
    body = [ln for ln in lines[1:] if not ln.strip().startswith("%%")]
    while body and not body[0].strip():
        body.pop(0)
    return "```mermaid\n" + INLINE_INIT + "\n" + "\n".join(body).rstrip() + "\n```"


def check_one(path: Path, want: str, fix: bool) -> str | None:
    text = path.read_text()
    blocks = [m for m in re.finditer(r"```mermaid\n.*?\n```", text, re.S) if MARKER in m.group(0)]
    if len(blocks) != 1:
        return f"{path}: found {len(blocks)} inlined architecture diagrams, expected exactly 1"
    if blocks[0].group(0) == want:
        return None
    if fix:
        path.write_text(text[: blocks[0].start()] + want + text[blocks[0].end() :])
        return None
    return f"{path}: the inlined diagram does not match docs/architecture.mmd"


def main(fix: bool = False) -> int:
    if not SOURCE.exists():
        print(f"missing {SOURCE}")
        return 1

    want = expected_block()
    problems = [p for p in (check_one(REPO / "README.md", want, fix),) if p]

    if SIBLING.exists():
        found = check_one(SIBLING, want, fix)
        if found:
            problems.append(found)
        print(f"checked 2 inlined copies against {SOURCE.relative_to(REPO)}")
    else:
        print(
            f"checked 1 inlined copy against {SOURCE.relative_to(REPO)}. "
            f"SKIPPED {SIBLING}, which is not present on this machine."
        )

    if problems:
        print()
        for p in problems:
            print(f"  {p}")
        print()
        print("Run `python tools/check_diagram.py --fix`, then re-render:")
        print("  npx @mermaid-js/mermaid-cli -i docs/architecture.mmd -o docs/architecture.png "
              "-w 1920 -H 1080 -b white -s 2")
        return 1

    print("every inlined diagram matches its source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(fix="--fix" in sys.argv))
