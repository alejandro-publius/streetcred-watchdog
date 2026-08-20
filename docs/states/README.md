# Ledger states

Rendered fixtures of the states the ledger can be in, so they can be reviewed before
they happen for real. Regenerate with `python tools/render_states.py`.

- `empty.html` no cycle has run yet
- `partial-cycle.html` a cycle that stopped halfway
- `source-down.html` a source was unavailable

Every page carries a banner saying it is a fixture. The corner names and counts
in them are real; the failures are constructed.
