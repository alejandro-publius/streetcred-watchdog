#!/usr/bin/env bash
# Everything a CI job would run, in the order that fails fastest.
#
# No network, no credentials, no cloud. If this passes, the repo is in a state
# somebody else can clone and trust. If it fails, it says which of the four
# things broke rather than making you read a wall of output.
#
#   ./tools/check.sh
#
# There is deliberately no `ruff format` step. Formatting this repo would reflow
# comment blocks that are laid out to be read, and here the comments are half the
# artefact.

set -uo pipefail

PY="${PY:-./.venv/bin/python}"
failed=0

step() {
  printf '\n=== %s ===\n' "$1"
}

report() {
  if [ "$1" -eq 0 ]; then
    printf 'ok    %s\n' "$2"
  else
    printf 'FAIL  %s\n' "$2"
    failed=1
  fi
}

if [ ! -x "$PY" ]; then
  echo "No interpreter at $PY."
  echo "Create one with: python3 -m venv .venv && ./.venv/bin/pip install -e '.[dev]'"
  echo "Or point PY at another: PY=python3 ./tools/check.sh"
  exit 2
fi

step "lint"
"$PY" -m ruff check src tests
report $? "ruff"

step "tests"
"$PY" -m pytest -q
report $? "pytest"

step "import graph"
# The local loop must never import the one module that can POST. This is the
# guarantee behind "the agent has never posted anything anywhere", and it is
# cheap enough to check on every run rather than trusting a test to stay written.
if grep -REn 'from \.ingest|import ingest' src/watchdog/observer.py src/watchdog/actor.py \
     src/watchdog/runner.py src/watchdog/outbox.py src/watchdog/cli.py >/dev/null 2>&1; then
  report 1 "the local loop reaches ingest.py, which can POST"
else
  report 0 "the local loop does not import ingest.py"
fi

step "secrets"
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  report 1 ".env is tracked by git"
elif [ -n "$(git log --all --full-history --oneline -- .env 2>/dev/null)" ]; then
  report 1 ".env appears in git history"
else
  report 0 ".env is untracked and has never been committed"
fi

step "documentation numbers"
"$PY" tools/check_numbers.py
report $? "stated figures match the repository"

step "adk claims"
"$PY" tools/check_adk_claims.py
report $? "documentation matches what src/ imports"

step "copy map"
"$PY" tools/check_copy_map.py
report $? "each mapped block is in its one home"

step "prose"
# The house rule. Checked because it is the kind of thing that creeps back in one
# paste at a time.
if grep -rln '—' --include='*.md' --include='*.py' . \
     --exclude-dir=.venv --exclude-dir=.git --exclude-dir=state \
     --exclude-dir=state-rehearsal --exclude-dir=state-injected 2>/dev/null | grep -q .; then
  echo "em dashes found in:"
  grep -rln '—' --include='*.md' --include='*.py' . \
    --exclude-dir=.venv --exclude-dir=.git --exclude-dir=state \
    --exclude-dir=state-rehearsal --exclude-dir=state-injected 2>/dev/null
  report 1 "no em dashes"
else
  report 0 "no em dashes"
fi

printf '\n'
if [ "$failed" -eq 0 ]; then
  echo "All checks passed."
else
  echo "Something failed above. Nothing here needs network or credentials, so a"
  echo "failure is reproducible on any machine with the venv built."
fi
exit "$failed"
