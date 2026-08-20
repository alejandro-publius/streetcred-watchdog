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
