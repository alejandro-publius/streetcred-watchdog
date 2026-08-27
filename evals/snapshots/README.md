# The recordings the eval set was built from

Nine snapshots, copied verbatim out of `state/snapshots/` at the moment
`tools/build_evalset.py` last ran. Each one is a real reading of San Francisco's
open data taken by a real cycle on 2026-08-20, not a fixture written by hand.

They live here because `state/` is gitignored, so a clone had none of them, and
the test asserting that every eval case is built from a real recording was
asserting against an empty set. It passed on any machine that had ever run a
cycle and failed on every fresh clone, which is the wrong way round: the claim
is about the eval set, so the evidence for it has to travel with the eval set.

Do not edit these by hand. `python tools/build_evalset.py` rewrites them from
`state/snapshots/`, and `tests/test_decision_evals.py` fails if a case names a
corner that has no recording here.
