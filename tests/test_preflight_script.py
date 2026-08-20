"""The preflight script promises it mutates nothing. This makes that enforceable.

A comment at the top of a shell script saying "read only" is worth exactly as
much as the last person who edited it below the comment. The script is going to
be run by an operator against a live billing account, probably in a hurry, on a
morning when something else is on fire. It has to be true.

So the guarantee is a test rather than a sentence: the file is scanned for the
verbs that change state, and any of them appearing fails the build. That is the
same move as everything else here, which is to turn a claim somebody has to trust
into one a machine checks.

This file also carries the one deviation in the pass that produced it. The
instruction said not to modify `tests/`, and also said to add this test. Adding a
new file rather than editing an existing one is the reading that satisfies both:
no existing test changed, no agent behaviour changed.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preflight_gcp.sh"

# Verbs that create, bill, or destroy. If one of these reaches the script,
# somebody has turned a preflight into a deployment.
FORBIDDEN_VERBS = ("create", "enable", "deploy", "put", "update", "delete")

# The only gcloud verbs a read-only script needs. Anything else is a new
# capability and should be a deliberate decision, not a drive-by edit.
ALLOWED_GCLOUD_VERBS = {
    "describe", "list", "get-value", "get-iam-policy", "version", "auth",
}


def script_text() -> str:
    return SCRIPT.read_text()


SUBSTITUTION = re.compile(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
QUOTED = re.compile(r"""(?:"[^"]*")|(?:'[^']*')""")


def code_lines() -> list[tuple[int, str]]:
    """The parts of each line that bash would execute.

    Three passes, and the order matters. Comments go first, because they explain
    the ban and are allowed to name the verbs it bans. Then command substitutions
    are pulled out and kept, because `"$(gcloud ... )"` sits inside a quoted string
    and is still a real call. Only then are the remaining quoted literals dropped,
    because a FAIL message that says "fill in after first deploy" is prose, not a
    deployment.

    Getting this wrong in the permissive direction would hide a real mutation, so
    the substitution pass exists specifically to stop the quote stripping from
    swallowing one.
    """
    out: list[tuple[int, str]] = []
    heredoc_end: str | None = None

    for n, raw in enumerate(script_text().splitlines(), start=1):
        line = raw.strip()

        # A heredoc body is text the script prints, not code it runs. The closing
        # marker is matched before anything else so the terminator itself is not
        # mistaken for a command.
        if heredoc_end is not None:
            if line == heredoc_end:
                heredoc_end = None
            continue
        opener = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?", line)
        if opener:
            heredoc_end = opener.group(1)
            continue

        if not line or line.startswith("#"):
            continue

        fragments = [m.group(1) for m in SUBSTITUTION.finditer(line)]
        bare = QUOTED.sub(" ", SUBSTITUTION.sub(" ", line))
        for fragment in [*fragments, bare]:
            if fragment.strip():
                out.append((n, fragment))
    return out


# ------------------------------------------------------------------- it exists

def test_the_script_exists_and_is_executable():
    assert SCRIPT.exists(), "scripts/preflight_gcp.sh is missing"
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "not executable, chmod +x scripts/preflight_gcp.sh"


def test_the_header_states_the_guarantee():
    """If the promise is removed, the reason for this test file goes with it."""
    head = "\n".join(script_text().splitlines()[:20])
    assert "mutates nothing" in head
    assert "read verb only" in head or "read verb" in head


# ------------------------------------------------------ nothing that changes state

@pytest.mark.parametrize("verb", FORBIDDEN_VERBS)
def test_no_state_changing_verb_appears_in_executable_code(verb):
    """The whole point of the file. Comments are exempt; code is not."""
    offenders = [
        (n, line.strip())
        for n, line in code_lines()
        if re.search(rf"\b{verb}\b", line)
    ]
    assert offenders == [], (
        f"{verb!r} appears in executable lines of preflight_gcp.sh: {offenders}. "
        "This script is run against a live billing account and must not change anything."
    )


def test_every_gcloud_invocation_uses_a_read_verb():
    """Belt and braces: catch a mutating verb the blocklist did not anticipate."""
    unexpected: list[tuple[int, str]] = []
    for n, line in code_lines():
        for match in re.finditer(r"gcloud\s+([a-z-]+(?:\s+[a-z-]+)*)", line):
            words = match.group(1).split()
            verb = next((w for w in reversed(words) if w in ALLOWED_GCLOUD_VERBS), None)
            if verb is None:
                unexpected.append((n, line.strip()[:90]))
    assert unexpected == [], (
        f"gcloud calls whose verb is not in the read-only allow list: {unexpected}"
    )


def test_it_does_not_pipe_into_anything_that_writes():
    """A read verb piped into a write is still a write."""
    for n, line in code_lines():
        assert not re.search(r"\|\s*gcloud\s+\S+\s+(create|add|set|update)", line), (
            f"line {n} pipes into a mutating gcloud call: {line.strip()}"
        )


def test_it_never_accesses_the_secret_value():
    """It checks the token exists. Printing it would defeat the point of having it."""
    text = script_text()
    assert "versions access" not in text, "the script would read the secret value"
    assert "value not read" in text, "the secret check should say it did not read the value"


# ------------------------------------------------------------------ it is usable

def test_it_is_valid_bash():
    import subprocess

    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, f"syntax error: {result.stderr}"


def test_it_checks_every_api_the_runbook_enables():
    """The script and the runbook must not drift apart on the API list."""
    runbook = (SCRIPT.parents[1] / "docs" / "GCP_PRECONDITIONS.md").read_text()
    apis = re.findall(r"([a-z]+\.googleapis\.com)", script_text())
    assert len(set(apis)) == 8, f"expected 8 APIs in the script, found {sorted(set(apis))}"
    for api in set(apis):
        assert api in runbook, f"{api} is checked by the script but not enabled by the runbook"


def test_it_exits_nonzero_on_failure():
    text = script_text()
    assert "exit 1" in text
    assert "exit 0" in text


def test_it_names_the_runbook_step_for_every_check():
    """A FAIL is only useful if it says which step to go back to."""
    rows = re.findall(r'row (?:PASS|FAIL) "(\d)"', script_text())
    assert rows, "no step numbers on any row"
    assert set(rows) <= {"0", "1", "2", "3", "4", "5", "6", "7", "8"}


def test_the_runbook_points_at_the_script():
    runbook = (SCRIPT.parents[1] / "docs" / "GCP_PRECONDITIONS.md").read_text()
    assert "preflight_gcp.sh" in runbook
