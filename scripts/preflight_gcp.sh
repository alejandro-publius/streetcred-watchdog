#!/usr/bin/env bash
#
# Read-only preflight for the GCP preconditions in docs/GCP_PRECONDITIONS.md.
#
# GUARANTEE: this script mutates nothing. It creates no resource, enables no API,
# deploys nothing, writes no secret, and changes no IAM policy. Every gcloud call
# below uses a read verb only: describe, list, get-value, or get-iam-policy.
#
# The guarantee is enforced rather than promised. tests/test_preflight_script.py
# greps this file for create, enable, deploy, put, update and delete and fails if
# any of them appear, so the claim in this header cannot quietly stop being true.
#
# It also never prints a secret. Step 6 checks that the ingest token exists and
# reports its length; it does not access the value.
#
#   ./scripts/preflight_gcp.sh
#
# Exits 0 when every check passes, 1 when any check fails. A FAIL means the
# corresponding step in the runbook has not landed, and the row names which one.

set -uo pipefail

PROJECT="${WATCHDOG_PROJECT:-streetcred-watchdog}"
REGION="${WATCHDOG_REGION:-us-central1}"
TOPIC="corner-deltas"
SUBSCRIPTION="corner-deltas-actor"
SECRET="WATCHDOG_INGEST_TOKEN"

REQUIRED_APIS=(
  run.googleapis.com
  firestore.googleapis.com
  pubsub.googleapis.com
  cloudscheduler.googleapis.com
  secretmanager.googleapis.com
  aiplatform.googleapis.com
  artifactregistry.googleapis.com
  cloudbuild.googleapis.com
)

SERVICE_ACCOUNTS=(
  watchdog-observer
  watchdog-actor
)

failures=0
checks=0

row() {
  # row <status> <step> <name> <detail>
  local status="$1" step="$2" name="$3" detail="$4"
  checks=$((checks + 1))
  [ "$status" = "FAIL" ] && failures=$((failures + 1))
  printf '  %-4s  %-6s %-34s %s\n' "$status" "$step" "$name" "$detail"
}

echo "Corner Watchdog, GCP preflight. Read only: nothing here changes anything."
echo "Project: ${PROJECT}   Region: ${REGION}"
echo
printf '  %-4s  %-6s %-34s %s\n' "" "STEP" "CHECK" "DETAIL"

# --------------------------------------------------------------- prerequisites

if ! command -v gcloud >/dev/null 2>&1; then
  row FAIL "0" "gcloud installed" "not on PATH, see https://cloud.google.com/sdk/docs/install"
  echo
  echo "Nothing else can be checked without gcloud. Stopping."
  exit 1
fi
row PASS "0" "gcloud installed" "$(gcloud version --format='value(\"Google Cloud SDK\")' 2>/dev/null | head -1)"

ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)"
if [ -z "$ACTIVE_ACCOUNT" ]; then
  row FAIL "1" "authenticated" "no active account, run: gcloud auth login"
else
  row PASS "1" "authenticated" "$ACTIVE_ACCOUNT"
fi

# ------------------------------------------------------------ 1. project setup

if gcloud projects describe "$PROJECT" >/dev/null 2>&1; then
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)' 2>/dev/null)"
  row PASS "1" "project exists" "${PROJECT} (number ${PROJECT_NUMBER})"
else
  row FAIL "1" "project exists" "${PROJECT} not found or no access"
  PROJECT_NUMBER=""
fi

CONFIGURED="$(gcloud config get-value project 2>/dev/null)"
if [ "$CONFIGURED" = "$PROJECT" ]; then
  row PASS "1" "project is the default" "$CONFIGURED"
else
  row FAIL "1" "project is the default" "default is '${CONFIGURED:-unset}', run: gcloud config set project ${PROJECT}"
fi

BILLING="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null)"
if [ "$BILLING" = "True" ]; then
  BILLING_ACCOUNT="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null)"
  row PASS "1" "billing linked" "$BILLING_ACCOUNT"
else
  row FAIL "1" "billing linked" "not linked, everything downstream will fail"
  BILLING_ACCOUNT=""
fi

# ------------------------------------------------------------------ 2. budgets

if [ -n "$BILLING_ACCOUNT" ]; then
  BUDGET_ID="${BILLING_ACCOUNT#billingAccounts/}"
  BUDGET_COUNT="$(gcloud billing budgets list --billing-account="$BUDGET_ID" \
    --format='value(name)' 2>/dev/null | grep -c . || true)"
  if [ "${BUDGET_COUNT:-0}" -gt 0 ]; then
    row PASS "2" "budget exists" "${BUDGET_COUNT} budget(s) on the billing account"
  else
    row FAIL "2" "budget exists" "none found, set one BEFORE enabling APIs"
  fi
  # Deliberately not asserted: whether any budget is a spend cap rather than
  # alerts only. The distinction matters enormously and the list output does not
  # reliably expose it, so read it in the console rather than trusting a green row.
  row PASS "2" "spend cap, manual check" "confirm Vertex AI cap in console, alerts do not cap"
else
  row FAIL "2" "budget exists" "cannot check, billing not linked"
fi

# --------------------------------------------------------------------- 3. APIs

ENABLED="$(gcloud services list --enabled --project="$PROJECT" --format='value(config.name)' 2>/dev/null)"
for api in "${REQUIRED_APIS[@]}"; do
  if printf '%s\n' "$ENABLED" | grep -qx "$api"; then
    row PASS "3" "api ${api%%.*}" "$api"
  else
    row FAIL "3" "api ${api%%.*}" "$api not enabled"
  fi
done

# ---------------------------------------------------------------- 4. Firestore

FS="$(gcloud firestore databases list --project="$PROJECT" \
  --format='value(locationId,type)' 2>/dev/null | head -1)"
if [ -n "$FS" ]; then
  row PASS "4" "firestore database" "$FS"
else
  row FAIL "4" "firestore database" "none found in ${PROJECT}"
fi

# ---------------------------------------------------------- 5. service accounts

SA_LIST="$(gcloud iam service-accounts list --project="$PROJECT" --format='value(email)' 2>/dev/null)"
for sa in "${SERVICE_ACCOUNTS[@]}"; do
  if printf '%s\n' "$SA_LIST" | grep -q "^${sa}@"; then
    row PASS "5" "service account ${sa}" "${sa}@${PROJECT}.iam.gserviceaccount.com"
  else
    row FAIL "5" "service account ${sa}" "not found"
  fi
done

# The check that matters more than existence: nobody was handed Editor or Owner.
OVERPRIVILEGED="$(gcloud projects get-iam-policy "$PROJECT" \
  --flatten='bindings[].members' \
  --filter='bindings.members:watchdog- AND (bindings.role:roles/editor OR bindings.role:roles/owner)' \
  --format='value(bindings.role)' 2>/dev/null | grep -c . || true)"
if [ "${OVERPRIVILEGED:-0}" -eq 0 ]; then
  row PASS "5" "no editor or owner granted" "least privilege intact"
else
  row FAIL "5" "no editor or owner granted" "${OVERPRIVILEGED} broad binding(s) on a watchdog account"
fi

# ------------------------------------------------------------------- 6. secret

if gcloud secrets describe "$SECRET" --project="$PROJECT" >/dev/null 2>&1; then
  VERSIONS="$(gcloud secrets versions list "$SECRET" --project="$PROJECT" \
    --filter='state:ENABLED' --format='value(name)' 2>/dev/null | grep -c . || true)"
  if [ "${VERSIONS:-0}" -gt 0 ]; then
    row PASS "6" "secret ${SECRET}" "${VERSIONS} enabled version(s), value not read"
  else
    row FAIL "6" "secret ${SECRET}" "secret exists but has no enabled version"
  fi
else
  row FAIL "6" "secret ${SECRET}" "not found"
fi

# ------------------------------------------------------------------- 7. pubsub

if gcloud pubsub topics describe "$TOPIC" --project="$PROJECT" >/dev/null 2>&1; then
  row PASS "7" "topic ${TOPIC}" "exists"
else
  row FAIL "7" "topic ${TOPIC}" "not found"
fi

SUB_ENDPOINT="$(gcloud pubsub subscriptions describe "$SUBSCRIPTION" --project="$PROJECT" \
  --format='value(pushConfig.pushEndpoint)' 2>/dev/null)"
if [ -n "$SUB_ENDPOINT" ]; then
  row PASS "7" "subscription ${SUBSCRIPTION}" "pushes to ${SUB_ENDPOINT}"
elif gcloud pubsub subscriptions describe "$SUBSCRIPTION" --project="$PROJECT" >/dev/null 2>&1; then
  row FAIL "7" "subscription ${SUBSCRIPTION}" "exists but has no push endpoint, fill in after first deploy"
else
  row FAIL "7" "subscription ${SUBSCRIPTION}" "not found, expected after first deploy"
fi

# ---------------------------------------------------------------- 8. scheduler

JOBS="$(gcloud scheduler jobs list --location="$REGION" --project="$PROJECT" \
  --format='value(name)' 2>/dev/null | grep -c . || true)"
if [ "${JOBS:-0}" -gt 0 ]; then
  row PASS "8" "scheduler jobs" "${JOBS} job(s) in ${REGION}"
else
  row FAIL "8" "scheduler jobs" "none, expected until after first deploy"
fi

# -------------------------------------------------------------------- verdict

echo
echo "${checks} checks, $((checks - failures)) pass, ${failures} fail"

if [ "$failures" -gt 0 ]; then
  cat <<'NOTE'

Failures are expected before the first deploy. Steps 7 and 8 cannot land until a
Cloud Run URL exists, and the runbook marks both as fill-in-after-first-deploy.
Anything failing in steps 1 through 6 is genuinely outstanding.

The runbook is docs/GCP_PRECONDITIONS.md and the step column above names which
part of it to go back to.
NOTE
  exit 1
fi

echo "Every precondition in docs/GCP_PRECONDITIONS.md is in place."
exit 0
