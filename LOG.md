# LOG

Working log. Newest entries at the bottom, except the pass summary which is at
the end.

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

---

## Overnight burn pass, 2026-08-20

One entry for the whole pass, as the standing rules require. 23 commits, all
inside the submission window. The gate held throughout: tests green at every
commit, `watchdog tick` runs under its lock, no Google account touched.

### Items completed

| Item | What shipped |
| --- | --- |
| carryover 0.1 | The restraint rate now says what it is made of: rule-settled versus actually weighed |
| carryover 0.2 | Radius corrected to 80 metres from measurement, guarded by a query fingerprint |
| carryover 0.3 | Watched set pinned by membership hash; leaving the roster is journaled |
| carryover 0.4 | `watchdog tick` under a cycle lock, plus launchd and cron config, installed nothing |
| A1, A3 | Every change class tested at its boundary; corrupt baselines quarantined |
| A2 | Every enumerated query value pinned against measured evidence, asserted before each cycle |
| A4 | Rehearsal isolation proved against the filesystem rather than by reading the code |
| B1, B2, B3 | Both prompts drafted in full against a decision contract that enforces them |
| B4 | `docs/GEMINI_WIRING.md` with measured token counts and deliberately blank prices |
| C1 | Streak header from journal timestamps, gaps drawn; full trace behind every entry |
| C2 | Empty, partial-cycle and source-down states designed and rendered to `docs/states/` |
| C3 | `watchdog ledger --corner <slug>`, one corner's history oldest first |
| D1 | `docs/architecture.mmd` and rendered SVG, two honest layers |
| D2 | README rewritten, every number measured, quick start verified in a clean clone |
| D3 | Demo script, every command checked to exist |
| D4 | Blog draft, 1,178 words |
| D5 | Social drafts plus the list of claims not to make |
| E1 | Token budget alongside the action budget; cost recorded on every entry as a projection |
| E2 | `watchdog doctor`, 19 checks, nonzero exit on failure |
| E3 | `--inject` for four failure modes, writing to its own state directory |
| F1 | `docs/FAQ.md`, nine judge questions |
| F2 | Lint clean under a chosen rule set, `tools/check.sh` |
| F3 | `CONTRIBUTING.md`, two issue templates, PR template |

### Items skipped, and why

None were skipped. Two deviations from the stated plan, both recorded here
rather than quietly absorbed:

- **A1 and A3 shipped in one commit.** They turned out to be the same change to
  the same files: A1's tests are what found the defect A3 exists to fix. The
  commit subject names both rather than faking a split.
- **Section E was built before D3, D4 and D5.** The demo script's kill-test beat
  depends on `--inject`, which is E3. Writing a demo script for a command that
  did not exist would have broken the no-invented-data rule, so the two sections
  were swapped.

The carryover items were numbered 0.1 through 0.4 rather than given letters,
because they came from the previous report's risk list rather than from the
lettered plan.

### What was found by running it, not by reading it

Seven defects, none of which raised an exception. In the order they were found:

1. **The radius was 150 metres and should have been 80.** Measured against
   StreetCred's published figures, exact on six of six corners. The repo had used
   150 on the strength of reading StreetCred's source rather than measuring its
   output.
2. **Fixing that would itself have produced the repo's signature failure.**
   Changing the radius invalidates every stored baseline, so the next sweep would
   have reported a 40 percent citywide collapse in collisions with confident
   reasoning attached. Snapshots now carry a query fingerprint and the delta
   engine refuses to subtract across a change in it.
3. **A renamed `count(*)` alias would parse as a clean zero.** Found by driving
   the fetch layer through a mock transport. Fixed using a distinction measured
   against the live API: `count(*)` over an empty set returns the key,
   `sum()` does not.
4. **A tie in the district group-by resolved to API order.** A corner on a
   district boundary would flip districts between sweeps and the agent would
   journal it as a real change.
5. **A corrupted stored count crashed the sweep**, taking out 24 healthy corners
   because one file was bad.
6. **A budget-blocked action counted as restraint.** Found by injecting a spent
   budget and reading what the ledger then claimed. An entry whose actions were
   all refused has an empty actions list, and the headline number was counting it
   as the agent choosing not to act. A journal of nothing but blocked entries read
   100 percent restraint before the fix and reads 0 percent after.
7. **The doctor reported healthy sources as failed.** It read timing off httpx's
   `.elapsed`, which raises unless the body has been read, inside a block that
   catches `Exception`.

### Where the numbers stand

Measured 2026-08-20 after the final cycle.

| | |
| --- | --- |
| Tests | 436, up from 76 at the start of the pass |
| Test files | 22, source modules 27 |
| Journal entries | 150 |
| Actions taken | 0 |
| Corners watched | 25 |
| City records covered per sweep | 5,905 |
| Google Cloud accounts touched | 0 |
