# Handoff

What is deployed, where, and how to take it down. Written 2026-08-25.

Everything below was created by executing `docs/GCP_PRECONDITIONS.md` in order.
The runbook is the explanation; this file is the inventory.

## Identifiers

| | |
| --- | --- |
| Project | `streetcred-506117` |
| Project number | `1024958265893` |
| Billing account | `012FB0-DD6BF5-6E3D90` |
| Region | `us-central1` |
| Vertex location | `global`, because the Gemini 3.x family is served from the multi-region endpoint |
| Deliberation model | `gemini-3.5-flash` |

## Cloud Run

| Service | URL | Revision proven |
| --- | --- | --- |
| `watchdog-observer` | <https://watchdog-observer-bl5svvpbva-uc.a.run.app> | `watchdog-observer-00005-mqk` |
| `watchdog-actor` | <https://watchdog-actor-bl5svvpbva-uc.a.run.app> | `watchdog-actor-00005-zp6` |

Both private (`--no-allow-unauthenticated`), `minScale` unset so they scale to
zero, `maxScale=3`, 1 GiB, 1 vCPU. One image, two services: `SERVICE` picks the
half at boot.

**The URL `gcloud run deploy` prints is not the URL the service serves.** Deploy
reports `https://watchdog-observer-1024958265893.us-central1.run.app`, which
returns a generic Google 404. The canonical URL is the `bl5svvpbva-uc.a.run.app`
form above, from `gcloud run services describe --format='value(status.url)'`.
Read the URL from `describe`, never from the deploy output.

## Everything else

| Resource | Identifier |
| --- | --- |
| Firestore database | `watchdog` (**not** `(default)`, see below), Native, `us-central1` |
| Collections | `snapshots`, `journal`, `calibration` |
| Pub/Sub topic | `corner-deltas` |
| Push subscription | `corner-deltas-actor`, OIDC as `watchdog-pubsub-invoker`, ack 300s, retention 1d |
| Secret | `WATCHDOG_INGEST_TOKEN`, version 1, 64 bytes, accessor scoped to `watchdog-actor` only |
| Budget | `35b6b6e6-1b25-4143-a078-38a390c24789`, 450 USD, alerts at 25 / 50 / 90 percent |
| Artifact Registry | `cloud-run-source-deploy`, created implicitly by `--source` deploys |

### Service accounts, none with Editor or Owner

| Account | Roles |
| --- | --- |
| `watchdog-observer@` | `datastore.user`, `aiplatform.user`, `logging.logWriter`, `pubsub.publisher` **scoped to the one topic** |
| `watchdog-actor@` | `datastore.user`, `aiplatform.user`, `logging.logWriter`, `secretmanager.secretAccessor` **scoped to the one secret** |
| `watchdog-pubsub-invoker@` | `run.invoker` **scoped to `watchdog-actor` only** |
| `watchdog-scheduler-invoker@` | `run.invoker` **scoped to `watchdog-observer` only** |

`gcloud projects get-iam-policy` filtered to `watchdog-` and `roles/editor` or
`roles/owner` returns zero rows, and `scripts/preflight_gcp.sh` checks that on
every run.

## Cloud Scheduler, and which one is on

| Job | Schedule | Time zone | State |
| --- | --- | --- | --- |
| `watchdog-daily-cycle` | `0 7 * * *` | `America/Los_Angeles` | **ENABLED** |
| `watchdog-hourly-tick` | `30 * * * *` | `America/Los_Angeles` | **PAUSED** |

The daily job is enabled because autonomous operation is the point of the
project and one bounded cycle a morning is what that means. The hourly job is
paused, and the reason is not caution about spend: it is 125 unauthenticated
queries against San Francisco's open data portal every hour, 3,000 a day,
against a public service this repository deliberately rate-limits itself for
(`MAX_CONCURRENT_CORNERS = 5`, "nothing here is urgent enough to justify it").
It also proves nothing the daily job does not.

```bash
# Turn the hourly tick on, if you decide the DataSF load is acceptable
gcloud scheduler jobs resume watchdog-hourly-tick --location=us-central1 --project=streetcred-506117
# Turn the daily cycle off before leaving it unattended for a long time
gcloud scheduler jobs pause watchdog-daily-cycle --location=us-central1 --project=streetcred-506117
```

## Two findings that cost real time, recorded so they do not again

**Cloud Run's front end reserves `/healthz`.** It answers that path itself with
a generic Google 404 and never forwards it to the container. Every other path on
a private service returns 403. The symptom is one route 404ing while the
container is demonstrably healthy and serving. The status route is `/status`.

**The Firestore client double-encodes `(default)`.** Every call against the
default database fails with `InvalidArgument: 400 Invalid database id
%28default%29`; over REST the URL is visibly `.../databases/%2528default%2529/`.
Reproduced on a laptop and on a clean Cloud Run instance, on
google-cloud-firestore 2.22 and 2.29, on grpcio 1.76 and 1.83, and on both
transports. A hand-built REST call with a literal `(default)` in the path
succeeds against the same database with the same credentials. A **named**
database has no characters needing encoding and works on the ordinary gRPC
client, so the database is `watchdog`. `FIRESTORE_DATABASE` overrides it.

A third, caught only because the agent journals its own degradation:
`vertex_is_configured()` looked for a credential file, and Cloud Run has none
because the identity arrives through the metadata server. The first cloud sweep
wrote 25 entries saying it had no credentials while running on a machine whose
whole identity is one. `K_SERVICE` is checked now.

## Teardown

Deletes every resource this pass created. The Firestore database and its journal
go with it, so export first if the journal matters.

```bash
P=streetcred-506117; R=us-central1

# Stop the triggers first, so nothing fires mid-teardown
gcloud scheduler jobs delete watchdog-daily-cycle  --location=$R --project=$P --quiet
gcloud scheduler jobs delete watchdog-hourly-tick  --location=$R --project=$P --quiet

# Then the services, then the plumbing that points at them
gcloud run services delete watchdog-observer --region=$R --project=$P --quiet
gcloud run services delete watchdog-actor    --region=$R --project=$P --quiet
gcloud pubsub subscriptions delete corner-deltas-actor --project=$P --quiet
gcloud pubsub topics delete corner-deltas --project=$P --quiet

gcloud secrets delete WATCHDOG_INGEST_TOKEN --project=$P --quiet

for sa in watchdog-observer watchdog-actor watchdog-pubsub-invoker watchdog-scheduler-invoker; do
  gcloud iam service-accounts delete ${sa}@${P}.iam.gserviceaccount.com --project=$P --quiet
done

# Irreversible. The journal is in here.
gcloud firestore databases delete --database=watchdog --project=$P --quiet

# Images built by --source deploys
gcloud artifacts repositories delete cloud-run-source-deploy --location=$R --project=$P --quiet

# The budget is free and worth keeping. Delete only if you are done with the project.
# gcloud billing budgets delete 35b6b6e6-1b25-4143-a078-38a390c24789 \
#   --billing-account=012FB0-DD6BF5-6E3D90 --quiet
```

## Still outstanding

- **The observer posts nothing to StreetCred.** `ingest.py` exists and the actor
  holds the token, but no deployed path calls it. The live path still refuses
  every verb, and the disclosure in the README is still accurate about that.
- **Gemma is still not wired.** Tier one is `RuleTriage` in the cloud exactly as
  it is locally, and every journal entry says so in its `degraded` line.
- **The ledger is rendered from the local journal, not the Firestore one.**
  `ledger.py` reads a `LocalJsonStore`. Pointing it at `FirestoreStore` is a
  constructor change and a bounded read, and it has not been done.
- **The Vertex spend cap is not set.** The alerts-only budget exists and alerts
  do not cap anything. The spend cap is console-only: Billing, Budgets & alerts,
  Create budget, Spend cap enforcement, scope to Vertex AI.
