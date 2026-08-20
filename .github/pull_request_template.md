## What this changes

<!-- one paragraph, in plain sentences -->

## When this is wrong, how does anybody find out?

The one question this repository is organised around. A change that cannot fail
visibly is a change that will eventually fail invisibly.

<!-- name the guard, the test, or the journal field that would surface it -->

## Checklist

- [ ] `./tools/check.sh` passes: lint, tests, the import guard, the secrets
      check, and no em dashes
- [ ] Any new guard has both halves tested: it fires when it should **and** stays
      silent when it should
- [ ] No unknown is coerced into a zero. Unparseable, missing and failed all stay
      distinguishable from "nothing there"
- [ ] If a query parameter changed, `query_fingerprint` includes it, so stored
      snapshots taken under the old question are refused rather than subtracted
- [ ] If an enumerated value went into a query, it is pinned in `vocabulary.py`
      with the row count it carried when checked
- [ ] Every number added to a doc is measured, or labelled synthetic
- [ ] No em dashes

## Anything you found by running it

Optional, and the most valuable section in the template. Three of this project's
worst bugs were found by running the loop rather than by reading it, and the
commit log is meant to read as a narrative of what went wrong.
