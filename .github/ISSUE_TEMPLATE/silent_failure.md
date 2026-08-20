---
name: Something failed quietly
about: The agent kept going when it should have refused, or said nothing when it should have
title: "silent failure: "
labels: correctness
---

The failure this project guards is not a crash. It is silence that reads as calm:
a corner that stopped being watched with no entry saying so, a comparison that
should have been refused and was not, a tier that was never consulted while the
page counted it as restraint.

## What the agent did

<!-- what it wrote, or what it did not write -->

## What it should have done instead

Usually one of these. Tick whichever fits:

- [ ] Refused to compare, because an input was partial, corrupt, or from a
      different query
- [ ] Written an entry saying it had stopped looking at something
- [ ] Marked an entry as degraded, deferred, or budget-blocked rather than as a
      decline
- [ ] Failed loudly rather than producing a number

## How you noticed

This matters more than usual here, because if the only way to notice was to
already know, that is the bug. What tipped you off?

## The record

```json
paste the journal entry, or say that there was not one
```

If there was no entry at all, that is the finding. Say which corner and which
cycle, and paste the surrounding entries so the gap is visible.
