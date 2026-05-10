#!/bin/bash
# verify-pipeline-state.sh — end-to-end check of the pipeline-state-redesign.
#
# Runs through the full system in <60 seconds. Use before any demo or after
# any infrastructure change. Exits 0 if healthy, non-zero if anything broken.
#
# Pipeline-state-redesign Phase L.

set -uo pipefail

PROJECT_ID="nba-props-platform"
EXIT_CODE=0

green() { printf '\e[32m%s\e[0m\n' "$1"; }
red()   { printf '\e[31m%s\e[0m\n' "$1"; }
yellow(){ printf '\e[33m%s\e[0m\n' "$1"; }

check() {
  local name="$1"; local cmd="$2"; local expected="$3"
  local got
  got=$(eval "${cmd}" 2>&1) || true
  if echo "${got}" | grep -qE "${expected}"; then
    green "  ✓ ${name}"
  else
    red "  ✗ ${name}"
    echo "      expected pattern: ${expected}"
    echo "      got: $(echo "${got}" | head -1)"
    EXIT_CODE=1
  fi
}

echo "==> 1. BigQuery tables exist"
check "halt_state" \
  "bq show --project_id=${PROJECT_ID} ${PROJECT_ID}:nba_orchestration.halt_state 2>&1" \
  "halt_state"
check "expected_outputs" \
  "bq show --project_id=${PROJECT_ID} ${PROJECT_ID}:nba_orchestration.expected_outputs 2>&1" \
  "expected_outputs"
check "expected_outputs_gaps view" \
  "bq show --project_id=${PROJECT_ID} ${PROJECT_ID}:nba_orchestration.expected_outputs_gaps 2>&1" \
  "expected_outputs_gaps"
check "expected_outputs_coverage view" \
  "bq show --project_id=${PROJECT_ID} ${PROJECT_ID}:nba_orchestration.expected_outputs_coverage 2>&1" \
  "expected_outputs_coverage"

echo
echo "==> 2. halt_state has today's row, written by the CF"
TODAY=$(date +%Y-%m-%d)
check "halt_state today (NBA)" \
  "bq query --project_id=${PROJECT_ID} --use_legacy_sql=false --format=csv --headless 'SELECT source FROM \`${PROJECT_ID}.nba_orchestration.halt_state\` WHERE effective_date = CURRENT_DATE() AND sport = \"nba\"' 2>&1" \
  "halt_state_writer_cf"
check "halt_state today (MLB)" \
  "bq query --project_id=${PROJECT_ID} --use_legacy_sql=false --format=csv --headless 'SELECT source FROM \`${PROJECT_ID}.nba_orchestration.halt_state\` WHERE effective_date = CURRENT_DATE() AND sport = \"mlb\"' 2>&1" \
  "halt_state_writer_cf"

echo
echo "==> 3. expected_outputs is populated"
check "expected_outputs has rows" \
  "bq query --project_id=${PROJECT_ID} --use_legacy_sql=false --format=csv --headless 'SELECT COUNT(*) > 1000 FROM \`${PROJECT_ID}.nba_orchestration.expected_outputs\`' 2>&1" \
  "true"

echo
echo "==> 4. Cloud Functions are ACTIVE"
for cf in halt-state-writer expected-outputs-planner phase-completion-reconciler gap-detector backfill-pubsub-subscriber; do
  check "CF: ${cf}" \
    "gcloud functions describe ${cf} --gen2 --region=us-west2 --project=${PROJECT_ID} --format='value(state)' 2>&1" \
    "ACTIVE"
done

echo
echo "==> 4b. Subscriber IAM (the bug that hit on 2026-05-10 morning)"
# EventArc-invoked subscriber must have run.invoker granted to both the
# trigger SA and the broad-default compute SA. Without these, every
# Pub/Sub message returns 403 and the system silently doesn't backfill.
check "Subscriber has gap-detector invoker" \
  "gcloud run services get-iam-policy backfill-pubsub-subscriber --region=us-west2 --project=${PROJECT_ID} --format=json 2>&1" \
  "gap-detector@nba-props-platform.iam.gserviceaccount.com"
check "Subscriber EventArc trigger exists" \
  "gcloud eventarc triggers list --location=us-west2 --project=${PROJECT_ID} --format='value(name)' 2>&1 | grep backfill-pubsub-subscriber" \
  "backfill-pubsub-subscriber"

echo
echo "==> 5. Schedulers are ENABLED"
for sched in halt-state-writer-daily expected-outputs-planner-nightly phase-completion-reconciler-30min gap-detector-30min; do
  check "Scheduler: ${sched}" \
    "gcloud scheduler jobs describe ${sched} --location=us-west2 --project=${PROJECT_ID} --format='value(state)' 2>&1" \
    "ENABLED"
done

echo
echo "==> 6. Pub/Sub topic exists"
check "Topic: nba-backfill-trigger" \
  "gcloud pubsub topics describe nba-backfill-trigger --project=${PROJECT_ID} --format='value(name)' 2>&1" \
  "nba-backfill-trigger"

echo
echo "==> 7. Frontend uptime checks exist"
for check_name in playerprops-root playerprops-mlb playerprops-nba-best-bets; do
  check "Uptime: ${check_name}" \
    "gcloud monitoring uptime list-configs --project=${PROJECT_ID} --filter='displayName ~ ${check_name}' --format='value(displayName)' 2>&1" \
    "${check_name}"
done

echo
echo "==> 8. Dashboard exists"
check "Dashboard: NBA Pipeline Health" \
  "gcloud monitoring dashboards list --project=${PROJECT_ID} --filter='displayName=\"NBA Pipeline Health\"' --format='value(displayName)' 2>&1" \
  "NBA Pipeline Health"

echo
echo "==> 9. Coverage summary"
bq query --project_id=${PROJECT_ID} --use_legacy_sql=false --format=pretty \
  "SELECT sport, status, COUNT(*) AS n
   FROM \`${PROJECT_ID}.nba_orchestration.expected_outputs\`
   GROUP BY sport, status
   ORDER BY sport, status" 2>&1 | tail -15

echo
if [ ${EXIT_CODE} -eq 0 ]; then
  green "==> ALL CHECKS PASSED"
else
  red "==> SOME CHECKS FAILED — see ✗ markers above"
fi
exit ${EXIT_CODE}
