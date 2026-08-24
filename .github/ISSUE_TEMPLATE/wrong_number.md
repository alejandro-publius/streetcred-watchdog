---
name: A number looks wrong
about: The agent published a figure that does not match the record
title: "wrong number: "
labels: correctness
---

**This is the most important kind of issue this project can receive.** Every
serious bug so far has had the same shape: the code ran, a number came out, and
the number was false. Nothing failed, so nothing flagged it.

## The figure

Which corner, and what the agent said:

<!-- e.g. 6th and Mission, the ledger says 62 injury collisions over five years -->

What you believe it should be, and where you got that:

<!-- a DataSF query, StreetCred's own page, a news report, your own count -->

## The journal entry

Every published figure has a journal entry behind it. Open that entry's **The
full journal record** disclosure on the ledger and paste it here. Two fields
usually explain a discrepancy on their own:

- `cost.tiersConsulted` says whether anything actually weighed this.
- `degraded` says which tier was a stand-in rather than a model.

```json
paste the record here
```

## The query it came from

If you can, run this and paste the output. It is the first thing anyone
investigating will do.

```bash
python -m corner_watchdog doctor
```

The `query fingerprint` line names the radius and windows the figure was computed
under. Two corners are already known to disagree with StreetCred and are written
up in `DECISIONS.md`; worth checking there first in case it is one of them.
