# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Seeded from `git log`
on 2026-09-07 and grouped by the date each batch of commits landed; the detail
underneath each date is in `git log` and, for what was found by running the
code rather than by writing it, in `LOG.md`.

## [Unreleased]

### 2026-09-06
- CI: ruff pinned in the workflow so an upstream linter release cannot redden
  an untouched tree.

### 2026-09-04
- CI actually runs on push and on pull requests for the first time: lint and
  the full test suite, plus a CI badge on the README.
- Dependabot watches the workflow actions.

### 2026-08-28
- Blog draft written, and two tests fixed that were measuring the calendar
  rather than the code they claimed to test.

### 2026-08-26
- Gemma wired as tier one; every journal entry now records which tier decided
  it (`tier1.decidedBy`).
- The actor publishes decisions to StreetCred's `/api/agent/report` and says
  so on the entry when a publish fails.
- Architecture diagram, requirements table, and `doctor` checks brought back
  in line with what is actually deployed, after an audit found each had
  drifted.
- Clean-clone quickstart figures in the README re-measured after the eval
  snapshots shipped.

### 2026-08-24
- ADK judgment agent (`adk_decider.py`) wired as tier two, with `decline` a
  required, signed tool call rather than silence.
- Guardrails implemented as ADK callbacks; triage and judgment joined into a
  two-agent `SequentialAgent` graph with a conditional edge.
- First deployment to Google Cloud: two Cloud Run services, Firestore,
  Pub/Sub with an OIDC push subscription, and Secret Manager.

### 2026-08-19 to 2026-08-20
- The whole loop built behind adapters: watched-set fetch, deterministic
  delta engine, dry-run outbox, a live path that implements the interface and
  refuses every verb, and the rendered ledger.
- The restraint rate given its breakdown, rule-settled declines counted
  separately from ones a tier actually weighed.
- The query radius corrected from a guessed 150 metres to a measured 80
  metres, verified against StreetCred's published scoreboard, with a query
  fingerprint added so the delta engine refuses to compare across the change.
- The `SEVERE_VALUES` filter bug found and fixed: DataSF's real category names
  did not match the filter's, so it matched zero rows for the life of the
  project without ever raising an error. Full account in `LOG.md`.
- Contributor scaffolding, ruff lint configuration, a documentation copy map,
  and the consistency checkers this repo runs on itself
  (`tools/check_numbers.py`, `check_adk_claims.py`, `check_diagram.py`,
  `check_copy_map.py`) added.

### 2026-08-18
- Initial scaffold: repository created, README pointed at the real clone URL.

[Unreleased]: https://github.com/alejandro-publius/streetcred-watchdog/commits/main
