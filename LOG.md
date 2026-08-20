# LOG

Working log for the local build night of 2026-08-19. Newest entries at the bottom.

## Phase 1: hackathon window verification (2026-08-19, 21:58 PDT)

Source: https://allthingsagentichackathon.devpost.com/details/dates, fetched 2026-08-19
evening PDT. The dates page prints times without a year; the hackathon front page states
the deadline as "Aug 31, 2026 @ 5:00pm PDT", which pins the year.

| Event | Date |
| --- | --- |
| Submission period opens | August 4, 2026, 7:45am PDT |
| Submission deadline | August 31, 2026, 5:00pm PDT |
| Judging period | September 1, 9:00am PDT through September 24, 5:00pm PDT |
| Winners announced | October 8, 2026, 12:00pm PDT |
| First commit in this repo | 33ac6f2, "watchdog scaffold", 2026-08-18, 08:40:19 PDT |
| Second commit in this repo | a66acd2, "readme: real clone url", 2026-08-18, 11:07:01 PDT |

Verdict, stated plainly: both existing commits landed fourteen days after the submission
period opened and thirteen days before it closes. They are inside the window. Tonight's
work, 2026-08-19, is also inside the window, with twelve days of margin before the
deadline.

## Phase 2: inventory, scaffold versus implementation (2026-08-19)

Ten lines, one per finding:

1. Implemented and tested: schema.py, the whole Firestore document contract (Snapshot, Delta, Tier1Verdict, Tier2Decision, JournalEntry, bounded Calibration).
2. Implemented and tested: delta.py, diff_snapshots with its three guards (first sighting, incomplete fetch, withdrawn record) plus the deterministic rule floor.
3. Implemented but never exercised: datasf.py, five SoQL lanes per corner copied from StreetCred, async httpx, marks partial fetches incomplete; no caller exists.
4. Implemented but never exercised: ingest.py, StreetCredClient covering journal, rescore, letter, flag, and the public board read; token comes from env only.
5. Prose only: prompts.py holds both versioned model prompts, and nothing imports it anywhere.
6. Missing entirely: watchdog/server.py, which the Dockerfile boots; there is no ADK agent, no FastAPI app, and no entrypoint of any kind.
7. Missing entirely: the loop itself; no observer sweep, no actor, no journal writer, no budget enforcement, no calibration persistence, no CLI.
8. Tests: 21 pass in 0.02s offline (13 for delta and the rule floor, 8 for calibration and journal serialisation); they import only schema and delta.
9. Toolchain drift: pyproject requires Python 3.11 or newer, but .venv is Python 3.9 carrying only pytest; the declared Google dependencies are not installed.
10. Secrets: .env exists locally, is matched by .gitignore line 1 (verified with git check-ignore), and git log --all --full-history -- .env returns nothing, so it has never been committed.

## The severity filter matched nothing, on every sweep, from the first commit

Found by running, not by reading. The first pair of live cycles returned
`severe_5y = 0` for all 25 corners, while StreetCred's own board shows severe
counts of 9 and 6 at two of those same corners. Asking the dataset directly:

    $ curl -sG https://data.sfgov.org/resource/ubvf-ztfx.json \
        --data-urlencode '$select=collision_severity,count(*)' \
        --data-urlencode '$group=collision_severity'
    Fatal                        622
    Injury (Complaint of Pain) 41829
    Injury (Other Visible)     18715
    Injury (Severe)             4638

`SEVERE_VALUES` held `("Severe Injury", "Suspected Serious Injury")`. Those are
CHP SWITRS category names, not what DataSF publishes. The query was valid, matched
no rows, and returned a clean zero every time, which made the rule "any new severe
injury is significant by rule" a rule that could never fire. Nothing logged a
warning, because nothing was wrong as far as the code could tell.

Fixed to `("Injury (Severe)",)`. The dataset's four real categories are now pinned
in `datasf.py` as `KNOWN_SEVERITY_VALUES` next to the command that produced them,
and `tests/test_datasf_queries.py` asserts the filter only ever names categories
that exist. The same check was run against the nine-entry 311 `SERVICE_NAMES`
allow list: all nine match real service names, so that query was sound.

The two cycles run before the fix were archived to `state-precheck-broken-severe/`
rather than deleted, and the gate cycles below were run again from an empty state
directory. A journal computed from a query known to be broken should not be
rendered as the product, and it should not be quietly discarded either.

## The rehearsal announced a fatality it had not constructed

The first rehearsal run printed "6th and Mission: a new fatality" and produced no
fatality. 6th and Mission has `fatal_5y = 0`, so subtracting one floored at zero,
the baseline matched the current reading, and the fatality path never ran while
the output claimed it had. Fixed: a corner is now only eligible for a scenario
whose subtraction its real record can absorb, and any scenario that cannot be
built is printed as NOT REHEARSED instead of silently swapped for another.

## Gate run, 2026-08-19 22:22 PDT

Two full cycles, 25 corners each, live DataSF reads, no Google account touched.

| | cycle 1 | cycle 2 |
| --- | --- | --- |
| corners looked at | 25 | 25 |
| escalated to deliberation | 0 | 0 |
| declined at triage | 25 | 25 |
| first sightings | 25 | 0 |
| incomplete fetches | 0 | 0 |
| actions taken | 0 | 0 |

Cycle 1 declined all 25 by the first-sighting rule: no baseline exists, so there is
nothing to compare. Cycle 2 declined all 25 because nothing at any of these corners
changed in the six minutes between sweeps, which is the honest and expected result
and not a demonstration of anything. Restraint rate 100 percent over 50 evaluations.

Because two cycles minutes apart cannot exercise the expensive half of the loop, the
deliberation tier, the budget and the letter renderer were run separately by
`watchdog rehearse` against constructed baselines, kept in their own state directory,
excluded from the restraint rate, and labelled on every entry. That run produced 4
escalations, 4 deliberations, 7 actions and 8 dry-run artefacts.
