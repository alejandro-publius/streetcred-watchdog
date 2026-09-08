# GCP preconditions runbook

Everything that has to exist in Google Cloud before the first `gcloud run deploy`,
as a sequence an operator can work through in about ten minutes.

**Nothing in this document has been executed.** It was written by reading the
repository, not by running against a project. No Google Cloud account has been
created, authenticated to, or billed at any point in this project's life. Two
consequences follow and both matter:

- Every command below is **unverified against a live gcloud**. Flag names drift
  between releases. Run `gcloud <group> <command> --help` before pasting anything
  you have not used recently. Where a step is more likely to have moved, it says so.
- The verification block in step 9 is the thing to trust, not this prose. It reads
  state back out of the project and tells you what actually landed.

Run [`scripts/preflight_gcp.sh`](../scripts/preflight_gcp.sh) at the end. It is
read only and will tell you which of these steps took.

---

## What this costs while nothing is happening

**At idle, and at this project's volume, the expected monthly cost is $0.**

Every component lands inside a documented Always Free allowance. The table shows
the allowance beside what this agent would actually consume.

| Service | Always Free allowance | What the watchdog uses | Inside free tier |
| --- | --- | --- | --- |
| Cloud Run | 2,000,000 requests, 360,000 GB-seconds, 180,000 vCPU-seconds per month | roughly 5 to 30 invocations a day, scale to zero between | yes, by orders of magnitude |
| Firestore | 1 GiB storage, 50,000 reads / 20,000 writes / 20,000 deletes per day per project | 25 snapshot documents, a few hundred journal writes a day | yes |
| Pub/Sub | 10 GiB of messages per month | a handful of small JSON envelopes per cycle | yes |
| Secret Manager | 6 active secret versions, 10,000 access operations per month | 1 secret version, a few accesses per cycle | yes |
| Artifact Registry | 0.5 GB storage per month | one container image, roughly 200 to 300 MB per revision | **only for the first revision or two** |
| Cloud Scheduler | 3 jobs per month, per **billing account**, then $0.10 per job per month | 2 jobs | yes, unless that billing account already has jobs elsewhere |
| Vertex AI | none, usage based | see below | **not free, but near zero at the observed rate** |

Sources, all fetched 2026-08-20:

- Always Free allowances: <https://docs.cloud.google.com/free/docs/free-cloud-features>
- Cloud Scheduler pricing, 3 free jobs per billing account then $0.10 per job per month: <https://cloud.google.com/scheduler/pricing>
- Secret Manager, $0.06 per active secret version per month beyond the free 6: <https://cloud.google.com/secret-manager/pricing>
- Free trial, $300 in Welcome credit valid 90 days: <https://docs.cloud.google.com/free/docs/free-cloud-features>

### The three things that can actually cost money

1. **Artifact Registry storage.** The free 0.5 GB covers one image. Every
   `gcloud run deploy --source .` pushes a new revision, and they accumulate. The
   per-GB rate is **not quoted here because the pricing page would not render for
   verification**; check <https://cloud.google.com/artifact-registry/pricing>
   before assuming it is trivial, and set a cleanup policy early.
2. **Cloud Scheduler beyond 3 jobs.** The free tier is per billing account, not
   per project. If that account already runs scheduler jobs for something else,
   these two are billable at $0.10 each per month.
3. **Vertex AI.** The only usage-based cost with real blowup potential. Rates are
   deliberately not quoted here for the same reason they are not quoted in
   [`GEMINI_WIRING.md`](GEMINI_WIRING.md): a per-million figure recalled from
   memory is exactly the kind of plausible unverified number this project refuses.

   The measured shape of the demand, though, is real. Across the 175 evaluations
   in this repository's journal, **four** reached tier one and **zero** reached
   tier two. Per-call token counts are measured in `GEMINI_WIRING.md` section 4:
   about 265 prompt and 77 output tokens for triage, 402 and 184 for
   deliberation. Multiply by the current rate to get a real number.

---

## 1. Account and project

**FREE up to the point marked. Read the whole step before running any of it.**

```bash
gcloud auth login
gcloud components update
```

Create the project, or adopt one that already exists:

```bash
# New project
gcloud projects create streetcred-watchdog --name="Corner Watchdog"

# Or adopt an existing one, and confirm you have the right one
gcloud projects list --filter="projectId:streetcred-watchdog"
```

Set it as the default so every later command inherits it:

```bash
gcloud config set project streetcred-watchdog
gcloud config list  # confirm before continuing
```

Capture the project number. Several later steps need it rather than the id:

```bash
gcloud projects describe streetcred-watchdog --format="value(projectNumber)"
```

Find your billing account id:

```bash
gcloud billing accounts list
```

> ### BILLABLE FROM HERE ON
>
> The next command attaches a payment method to this project. Everything before
> it is free and reversible. Everything after it can, in principle, charge you.
> Do step 2 before you do anything else in this section beyond the link itself.

```bash
gcloud billing projects link streetcred-watchdog \
  --billing-account=BILLING_ACCOUNT_ID   # <-- placeholder, from the list above
```

## 2. Budget guardrail, before any API

**FREE.** Do this immediately after linking billing and before enabling anything.

### Read this before you trust the budget

**An alerts-only budget does not cap spending.** Google's own documentation is
explicit: alerts-only budgets "don't automatically prevent the use or billing of
your services when the alerts-only budget amount or threshold rules are met or
exceeded" (<https://docs.cloud.google.com/billing/docs/how-to/budgets>). It emails
you. That is all it does.

There is a separate native feature, **spend cap budgets**, that does pause usage.
Its limits matter (<https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps>):

- scoped to a **single project and a single eligible service** per budget
- eligible services are Gemini API, Gemini Enterprise Agent Platform (Vertex AI),
  Cloud Run, and Cloud Run functions, so Firestore, Pub/Sub, Secret Manager and
  Artifact Registry **cannot be capped this way**
- enforcement uses estimated gross costs and is not instantaneous, so overages
  are still billed; set the cap below your real limit
- fixed costs from stored resources keep accruing after a cap trips

So do both, and know which one is doing what.

### The alerts-only budget, for the whole project

$300 trial credit plus $150 hackathon credit is $450. Alerts at 25, 50 and 90
percent give you three warnings before the credits are gone.

```bash
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="watchdog total" \
  --budget-amount=450USD \
  --threshold-rule=percent=0.25 \
  --threshold-rule=percent=0.50 \
  --threshold-rule=percent=0.90 \
  --filter-projects=projects/PROJECT_NUMBER
```

Placeholders: `BILLING_ACCOUNT_ID` from step 1, `PROJECT_NUMBER` from step 1.

This command surface has moved between `alpha`, `beta` and GA. If it errors, run
`gcloud billing budgets create --help` and match the flags rather than guessing.

### The spend cap, on the one service that can run away

Console only as far as the documentation shows, and it is worth the two minutes:

1. Billing, then **Budgets & alerts**, then **Create new budget**
2. Choose **Spend cap enforcement**, not Alerts only
3. Scope: project `streetcred-watchdog`, service **Vertex AI**
4. Set the amount below what you can actually absorb, because enforcement lags
5. Finish. Notifications at 50, 80 and 100 percent configure themselves.

Vertex is the right service to cap: it is the only usage-based cost here, and
everything else sits inside Always Free at this volume.

An alerts-only budget cannot be converted to a spend cap later. It is one way.

## 3. Enable APIs

**FREE to enable. Each becomes billable only on use.**

```bash
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

### Which component needs each one

Derived from the repository, not from memory. The derivation is worth stating
plainly, because it is weaker than it looks: **no Google client library is
imported anywhere in `src/`**. The only Google-aware code is
`brains.vertex_is_configured()`, which reads two environment variables and checks
for a credentials file. So this mapping comes from the declared `cloud` extra in
`pyproject.toml`, the protocols in `ports.py`, and the `Dockerfile`, and it is a
statement of intent rather than an observation of running code.

| API | Needed by | Evidence in the repo |
| --- | --- | --- |
| `run.googleapis.com` | Both services. The observer sweep and the actor. | `Dockerfile` boots `uvicorn corner_watchdog.server:app` and switches on `SERVICE=observer` or `actor`; `fastapi` and `uvicorn` are in the `cloud` extra. **`corner_watchdog/server.py` does not exist yet**, so nothing is deployable today. |
| `firestore.googleapis.com` | The `Store` protocol in `ports.py`, today `LocalJsonStore` | `google-cloud-firestore` in the `cloud` extra; `store.py` docstring names the three collections it stands in for |
| `pubsub.googleapis.com` | The `Bus` protocol, today `DirectBus` | `google-cloud-pubsub` in the `cloud` extra; `bus.py` round-trips payloads through JSON precisely so Pub/Sub can carry them |
| `secretmanager.googleapis.com` | `ingest.py`, which reads `WATCHDOG_INGEST_TOKEN` from the environment | `google-cloud-secret-manager` in the `cloud` extra; `ingest.py:48` |
| `aiplatform.googleapis.com` | The `Triage` and `Decider` protocols, today `RuleTriage` and `RuleDecider` | `google-genai` in the `cloud` extra; `brains.vertex_is_configured()` checks `GOOGLE_CLOUD_PROJECT` and ADC |
| `cloudscheduler.googleapis.com` | The timed trigger, today `launchd` or `cron` via `schedule.py` | `ops/dev.watchdog.cycle.plist` is the local stand-in; the README architecture names Cloud Scheduler |
| `artifactregistry.googleapis.com` | Deploy only. `gcloud run deploy --source .` pushes the image here. | The README's deploy section uses `--source .` |
| `cloudbuild.googleapis.com` | Deploy only. `--source .` builds remotely. | Same |

`google-adk` is in the `cloud` extra and needs no API enabled. Its status is
stated once, in the README disclosure and requirements row, and enforced by
`tools/check_adk_claims.py`.

## 4. Firestore

**FREE within 1 GiB and the daily operation allowances.**

Native mode, in the region `.env.example` already names as
`GOOGLE_CLOUD_LOCATION`:

```bash
gcloud firestore databases create --database=watchdog --location=us-central1 --type=firestore-native
```

**Correction, added after the deploy this runbook led to.** The command above
now names the database explicitly. It did not when this runbook was written,
which creates the project's `(default)` database, and the client library
double-encodes that name so every call against it is rejected. `HANDOFF.md`
has the full account; `FIRESTORE_DATABASE=watchdog` is what the deployed
services actually run with.

There is one database per project and the location cannot be changed afterwards.
`us-central1` matches the Vertex region in `.env.example`, which keeps the
Firestore and model calls in the same region.

The schema is already written down, in `src/corner_watchdog/schema.py`: three
collections, `snapshots/{slug}`, `journal/{entry_id}` and `calibration/state`.
Nothing needs creating; Firestore makes collections on first write.

## 5. Service accounts

**FREE.** No Editor, no Owner, no Project role anywhere below.

```bash
gcloud iam service-accounts create watchdog-observer \
  --display-name="Corner Watchdog observer"
gcloud iam service-accounts create watchdog-actor \
  --display-name="Corner Watchdog actor"
```

### Observer, least privilege

It reads DataSF over the public internet, writes Firestore, publishes to Pub/Sub,
and would call Gemma. It does **not** post to StreetCred, so it gets no secret.

```bash
PROJECT=streetcred-watchdog
OBS=watchdog-observer@${PROJECT}.iam.gserviceaccount.com

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${OBS}" --role="roles/datastore.user"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${OBS}" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${OBS}" --role="roles/logging.logWriter"

# Publisher scoped to the one topic, not project wide. Run after step 7.
gcloud pubsub topics add-iam-policy-binding corner-deltas \
  --member="serviceAccount:${OBS}" --role="roles/pubsub.publisher"
```

### Actor, least privilege

It receives a push, writes Firestore, would call Gemini, and reads the one secret
so it can POST to StreetCred.

```bash
ACT=watchdog-actor@${PROJECT}.iam.gserviceaccount.com

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${ACT}" --role="roles/datastore.user"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${ACT}" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${ACT}" --role="roles/logging.logWriter"

# Secret access scoped to the one secret, not project wide. Run after step 6.
gcloud secrets add-iam-policy-binding WATCHDOG_INGEST_TOKEN \
  --member="serviceAccount:${ACT}" --role="roles/secretmanager.secretAccessor"
```

### The two plumbing identities

Push subscriptions and scheduler jobs need to invoke private Cloud Run services.
Give each its own invoker rather than making the services public.

```bash
gcloud iam service-accounts create watchdog-pubsub-invoker \
  --display-name="Pub/Sub push to actor"
gcloud iam service-accounts create watchdog-scheduler-invoker \
  --display-name="Scheduler trigger for observer"
```

Their `roles/run.invoker` bindings are scoped to a specific service and therefore
**cannot be granted until after the first deploy**. They are in step 8.

The Pub/Sub service agent also needs to mint tokens for the push identity:

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format="value(projectNumber)")
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

### One open question, stated rather than assumed

`ingest.py` exposes a `journal()` method as well as `rescore()`, `letter()` and
`flag()`. If the deployed observer is meant to post its declines to StreetCred
directly rather than only writing Firestore, it will also need
`roles/secretmanager.secretAccessor` on the token. As the code stands the local
observer posts nothing at all, so this grants it nothing. Decide when
`server.py` is written, and widen the grant then rather than pre-emptively now.

## 6. Secret Manager

**FREE for the first 6 active secret versions.** This uses one.

Create the secret, then add the value from `.env` **without printing it**, the
same no-echo pattern used when the token was rotated:

```bash
gcloud secrets create WATCHDOG_INGEST_TOKEN --replication-policy=automatic

grep '^WATCHDOG_INGEST_TOKEN=' .env | cut -d= -f2- | tr -d '\n' \
  | gcloud secrets versions add WATCHDOG_INGEST_TOKEN --data-file=-
```

`tr -d '\n'` is not optional. Without it the trailing newline becomes part of the
secret, StreetCred's bearer comparison fails, and the failure looks like an auth
problem rather than a whitespace problem.

Confirm without revealing it:

```bash
gcloud secrets versions list WATCHDOG_INGEST_TOKEN
gcloud secrets versions access latest --secret=WATCHDOG_INGEST_TOKEN | wc -c   # expect 64
```

### Every other variable the code reads

Only the token is a secret. The rest are plain configuration and belong in Cloud
Run environment variables, not in Secret Manager.

| Variable | Read by code | Where it belongs in production |
| --- | --- | --- |
| `WATCHDOG_INGEST_TOKEN` | yes, `ingest.py` | **Secret Manager** |
| `GOOGLE_CLOUD_PROJECT` | yes, `brains.py` | Cloud Run env var, or inherited |
| `STREETCRED_ORIGIN` | yes, `ingest.py` | Cloud Run env var |
| `DAILY_ACTION_BUDGET` | yes, `budget.py` | Cloud Run env var |
| `DAILY_TOKEN_BUDGET` | yes, `budget.py` | Cloud Run env var |
| `GOOGLE_APPLICATION_CREDENTIALS` | yes, `brains.py` | **do not set on Cloud Run.** ADC comes from the metadata server; setting this points at a key file that should not exist |

Three discrepancies between `.env.example` and the code, found while writing this
and left alone because this pass does not modify the repository's behaviour:

- `DAILY_TOKEN_BUDGET` is read by `budget.py` but is **not** in `.env.example`.
- `DAILY_IMAGE_BUDGET` is in `.env.example` and is read by nothing.
- `TRIAGE_MODEL`, `DELIBERATION_MODEL`, `GOOGLE_CLOUD_LOCATION`, `DELTA_TOPIC`
  and `DELTA_SUBSCRIPTION` are in `.env.example` and read by nothing, because the
  cloud adapters are not built. `GEMINI_WIRING.md` treats reading them as work
  still to do, which is consistent.

## 7. Pub/Sub

**FREE within 10 GiB of messages per month.**

```bash
gcloud pubsub topics create corner-deltas
```

The topic name matches `DELTA_TOPIC` in `.env.example`. The subscription name
below matches `DELTA_SUBSCRIPTION`.

The push subscription needs the actor's URL, which does not exist until the first
deploy. Create the topic now and **come back for this**:

```bash
# FILL IN AFTER FIRST DEPLOY. ACTOR_URL comes from:
#   gcloud run services describe watchdog-actor --region=us-central1 --format="value(status.url)"

gcloud pubsub subscriptions create corner-deltas-actor \
  --topic=corner-deltas \
  --push-endpoint=ACTOR_URL \
  --push-auth-service-account=watchdog-pubsub-invoker@streetcred-watchdog.iam.gserviceaccount.com \
  --ack-deadline=60
```

The ack deadline is worth a thought rather than a default. A deliberation that
calls Gemini can take longer than 10 seconds, and an expired ack redelivers the
message, which means the actor deliberates twice on the same delta and can act
twice. Whatever you set, the actor needs to be idempotent before this matters.

## 8. Cloud Scheduler

**FREE for the first 3 jobs per billing account, then $0.10 per job per month.**
These are 2 jobs.

> ### DO NOT CREATE UNTIL FIRST DEPLOY
>
> Both commands need the observer's URL and both fail without it. They are
> rendered here so the schedule is decided now and typed later.

First, the invoker bindings that could not be made in step 5:

```bash
OBS_URL=$(gcloud run services describe watchdog-observer \
  --region=us-central1 --format="value(status.url)")

gcloud run services add-iam-policy-binding watchdog-observer \
  --region=us-central1 \
  --member="serviceAccount:watchdog-scheduler-invoker@streetcred-watchdog.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

gcloud run services add-iam-policy-binding watchdog-actor \
  --region=us-central1 \
  --member="serviceAccount:watchdog-pubsub-invoker@streetcred-watchdog.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

The daily sweep, 06:40 Pacific:

```bash
gcloud scheduler jobs create http watchdog-daily \
  --location=us-central1 \
  --schedule="40 6 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="${OBS_URL}/sweep" \
  --http-method=POST \
  --oidc-service-account-email=watchdog-scheduler-invoker@streetcred-watchdog.iam.gserviceaccount.com \
  --attempt-deadline=600s
```

The hourly light tick:

```bash
gcloud scheduler jobs create http watchdog-hourly \
  --location=us-central1 \
  --schedule="0 * * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="${OBS_URL}/tick" \
  --http-method=POST \
  --oidc-service-account-email=watchdog-scheduler-invoker@streetcred-watchdog.iam.gserviceaccount.com \
  --attempt-deadline=300s
```

`America/Los_Angeles` rather than a fixed offset, so 06:40 stays 06:40 across
daylight saving. The window arithmetic inside the agent is UTC regardless, which
is deliberate and tested.

The paths `/sweep` and `/tick` are **assumed**. `corner_watchdog/server.py` does not
exist, so no route is defined anywhere in the repository. Whoever writes it
decides these, and these two commands change to match.

## 9. Verification

**FREE. Everything here is read only.** Run
[`scripts/preflight_gcp.sh`](../scripts/preflight_gcp.sh) for all of it as a
pass/fail table, or run the pieces by hand:

```bash
# 1. account and project
gcloud auth list
gcloud config get-value project
gcloud projects describe streetcred-watchdog

# 1. billing linked
gcloud billing projects describe streetcred-watchdog

# 2. budgets exist
gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID

# 3. APIs enabled
gcloud services list --enabled --filter="config.name:(run.googleapis.com OR \
  firestore.googleapis.com OR pubsub.googleapis.com OR cloudscheduler.googleapis.com OR \
  secretmanager.googleapis.com OR aiplatform.googleapis.com OR \
  artifactregistry.googleapis.com OR cloudbuild.googleapis.com)"

# 4. Firestore
gcloud firestore databases list

# 5. service accounts and their roles
gcloud iam service-accounts list
gcloud projects get-iam-policy streetcred-watchdog \
  --flatten="bindings[].members" \
  --filter="bindings.members:watchdog-" \
  --format="table(bindings.role, bindings.members)"

# 6. secret exists, without revealing it
gcloud secrets versions list WATCHDOG_INGEST_TOKEN

# 7. topic and subscription
gcloud pubsub topics list
gcloud pubsub subscriptions describe corner-deltas-actor

# 8. scheduler jobs
gcloud scheduler jobs list --location=us-central1
```

The IAM check is the one to read carefully. If `roles/editor` or `roles/owner`
appears against any `watchdog-` account, something granted more than this runbook
asked for, and least privilege is the entire point of step 5.

## What is still missing after all of this

Finishing this runbook makes the project deployable. It does not make it
deployed, and two things block that:

1. **`src/corner_watchdog/server.py` does not exist.** The `Dockerfile` boots
   `uvicorn corner_watchdog.server:app`. There is no FastAPI app, no `/sweep` route, no
   `/tick` route, and no push handler. `gcloud run deploy` will build an image
   that crashes on start.
2. **No Vertex client is written.** `select_brains()` returns the deterministic
   stand-ins. Enabling `aiplatform.googleapis.com` changes nothing on its own.
   The plan is [`GEMINI_WIRING.md`](GEMINI_WIRING.md).

Both are code, not configuration, and neither is in this runbook's scope.
