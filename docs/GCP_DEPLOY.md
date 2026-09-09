# Running it on Google Cloud

Deployed and proven on 2026-08-25: two Cloud Run services, Firestore, Pub/Sub,
Secret Manager, Cloud Scheduler, and Gemini 3.5 Flash on Vertex AI at
`locations/global`. Resource names, URLs and a teardown command are in
[`HANDOFF.md`](../HANDOFF.md); the reasoning behind each step, including what every
API is for and what it costs, is in
[`docs/GCP_PRECONDITIONS.md`](GCP_PRECONDITIONS.md).

```bash
gcloud auth login && gcloud config set project YOUR_PROJECT
./scripts/preflight_gcp.sh              # read only, mutates nothing, names what is missing

# A budget before any API, because an alerts-only budget does not cap spend and
# you want to know that before you find out.
gcloud billing budgets create --billing-account=YOUR_BILLING_ID \
  --display-name="watchdog total" --budget-amount=450USD \
  --threshold-rule=percent=0.25 --threshold-rule=percent=0.50 --threshold-rule=percent=0.90 \
  --filter-projects=projects/YOUR_PROJECT_NUMBER

gcloud services enable run.googleapis.com firestore.googleapis.com pubsub.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com

# Named, not (default). The client library double-encodes the parentheses and
# every call against the default database is rejected. See HANDOFF.md.
gcloud firestore databases create --database=watchdog --location=us-central1

# Service accounts, secret, topic: docs/GCP_PRECONDITIONS.md steps 5 to 7 verbatim.

gcloud run deploy watchdog-observer --source . --region=us-central1 \
  --service-account=watchdog-observer@YOUR_PROJECT.iam.gserviceaccount.com \
  --no-allow-unauthenticated --min-instances=0 --max-instances=3 \
  --set-env-vars=SERVICE=observer,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=true,DECIDER=adk,FIRESTORE_DATABASE=watchdog,DAILY_ACTION_BUDGET=40,DAILY_TOKEN_BUDGET=200000

# The actor is the same command with SERVICE=actor, its own service account, and
# --set-secrets=WATCHDOG_INGEST_TOKEN=WATCHDOG_INGEST_TOKEN:latest

./scripts/preflight_gcp.sh              # every row should now pass
```

Read the service URL from `gcloud run services describe`, not from what
`gcloud run deploy` prints. They are different, and only one of them serves.

Prove it end to end:

```bash
URL=$(gcloud run services describe watchdog-observer --region=us-central1 --format='value(status.url)')
curl -s -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" $URL/status
curl -s -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" $URL/sweep
```

The first sweep against an empty Firestore records 25 first sightings and
escalates nothing, which is correct: there is nothing to compare against yet.
The second sweep is the one that can produce a delta.
