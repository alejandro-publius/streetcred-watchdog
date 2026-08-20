# Contributing

The repository goes public at submission. If you want to change something, this
is what you need to know.

## Get it running

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
./tools/check.sh
```

`check.sh` runs everything a CI job would: lint, the 443 tests, and three checks a
linter cannot make. It needs no network, no credentials and no cloud account. If
it passes on your machine it passes on mine.

To watch the thing actually work:

```bash
python -m watchdog doctor            # 19 checks before you trust any output
python -m watchdog run --cycles 1    # a real sweep against live DataSF
python -m watchdog rehearse          # exercises the half a quiet city never does
open docs/ledger.html
```

## The one rule

**A number that is wrong must not be able to look like a number that is right.**

Everything else in this document follows from that. This repository exists
because a query filter named a category that did not exist, matched zero rows,
returned a clean zero on every corner on every sweep for a fortnight, and nothing
anywhere failed. There was no exception, no warning, no red. There was a number,
and the number was false.

So the standard for a change here is not "does it work". It is "when this is
wrong, how does anybody find out".

## What that means in practice

**Never coerce an unknown into a zero.** A count that cannot be parsed, a filter
that matched nothing, a fetch that failed, a baseline that will not load: none of
these are zero. They are unknown, and the code says so and refuses to compare.
`Snapshot.from_dict` raises rather than coercing. `_count_value` distinguishes an
absent key from an absent row, because the live API behaves differently for
`count(*)` and `sum()` and both mistakes are silent.

**Pin every literal that goes into a query.** Any enumerated value in a WHERE
clause has to appear in `vocabulary.py` with the row count it carried when it was
checked. The count is what makes it non-circular; comparing a list to a copy of
itself proves nothing. A cycle refuses to start if they disagree.

**Guard changes to the question, not just the answer.** If you change a radius, a
window, or a category list, you change every count at every corner at once.
`query_fingerprint` exists so that the delta engine refuses to subtract across
that change instead of reporting it as news about a street. If you add a
parameter that affects a count, add it to the fingerprint.

**Absence has to be legible.** A corner that dropped off the roster, a day with no
cycle, a run that stopped halfway, a tier that was never consulted: each gets an
entry or a visible mark. The failure this repo guards is not a crash, it is
silence that reads as calm.

**Write the caveat into the record, not the README.** Every entry produced while a
stand-in was running names which tier was not a model. Every rehearsal entry says
its baseline was constructed. Every injected failure says it was injected. A
footnote somebody has to go and find is not a disclosure.

## Tests

Every test in `tests/` should be able to answer "what confident lie does this
prevent". Look at the docstrings; that is what they are all doing.

Two habits worth copying:

- **Both halves.** A guard needs a fires-when-it-should test and a
  stays-silent-when-it-should test. With only the first, a function that returns
  True unconditionally passes.
- **Boundaries.** Thresholds get tested at N-1, N and N+1. An off-by-one in a
  comparison is invisible in every other kind of test: it runs, a number comes
  out, and the number is one escalation wrong per corner per day.

Tests must not touch the network. The fetcher is injected for exactly that
reason, so there is never a need for an `if testing` branch inside the decision
path.

## Style

`ruff` config is in `pyproject.toml` and the rule set is annotated with why each
group is there. Four of them are enabled because they found real bugs.

Formatting is deliberately **not** enforced. Do not run `ruff format` over this
repo: it reflows comment blocks that are laid out to be read, and here the
comments are half the artefact. Match the surrounding style by hand.

Two house rules, both checked by `tools/check.sh`:

- **No em dashes.** Anywhere. Prose, comments, commit messages.
- **No invented data.** Every number in a doc is measured, or labelled synthetic
  where it stands in for something. If you cannot source a figure, write that it
  is unknown. The prompt examples in `src/prompts/` use real corner records and
  label every constructed change as constructed.

Counts that move with every cycle are checked rather than trusted. After running
cycles, refresh the documents and read the diff:

```bash
python tools/check_numbers.py --fix
```

`check.sh` fails if a stated figure disagrees with the repository. Fix the
document, not the checker.

## What not to change without discussion

- **`delta.py`.** It is the deterministic floor everything else rests on, it has
  no cleverness in it on purpose, and its guards are the reason a failed fetch
  cannot manufacture a death.
- **`live.py`.** It refuses on every verb and reads no credential. Making it work
  is not a code change, it is the three blockers listed inside it, one of which is
  a human reading a full dry-run outbox.
- **The restraint rate arithmetic in `ledger.py`.** It is the one number this
  project asks to be trusted on, and it has already been wrong twice: once
  counting rule-settled declines as judgment, and once counting budget-blocked
  actions as restraint.

## Commits

One logical change per commit, with a message that says what shipped and, where
something was found by running the code, what it was. The commit log here is
meant to be readable as a narrative of what went wrong and what was done about
it, because that is the more useful half of the story.
