# Considered and rejected

Fuller versions in [`DECISIONS.md`](../DECISIONS.md).

- **Calling a small local model so the demo could say a model ran.** Buys a sentence in a
  pitch, costs the one property this project is about.
- **Mutating real snapshots to force an interesting delta for the demo.** The rehearsal
  constructs the *past* instead, never the present, and every entry it writes says so.
- **A hash for the query fingerprint.** The journal entry that refuses a comparison prints
  it, and `r=80m;collisions=5y;...` tells a reader what happened where `a3f19c` does
  not. No entry ever printed `r=150m`: the old baselines predated the field, so the
  refusals read `not recorded then r=80m...`, which is itself the right answer.
- **Coercing a corrupted stored count to zero.** That is the SEVERE_VALUES failure with a
  different mask. It refuses to load and the file is quarantined instead.
- **Leaving the live path unwritten, or callable behind a flag.** Unwritten hides whether
  the interface fits until the worst moment; callable is how a dry run becomes a live send
  by way of one wrong argument.
- **Quoting Vertex prices from memory in the cost estimate.** Token counts are measured;
  the rates are left blank with the arithmetic beside them.

