#!/bin/bash
# File: bin/processor_backfill/nbac_gamebook_backfill_monitor.sh

set -e

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
REGION=${REGION:-"us-west2"}
JOB_NAME="nbac-gamebook-backfill"  # Note: uses hyphens

echo "==========================================
NBA.com Gamebook Backfill Monitor
==========================================
"

# Get latest execution
EXECUTION_NAME=$(gcloud run jobs executions list \
  --job=${JOB_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --limit=1 \
  --format="value(name)")

if [ -z "$EXECUTION_NAME" ]; then
  echo "No executions found for job ${JOB_NAME}"
  exit 1
fi

echo "Latest execution: ${EXECUTION_NAME}"
echo ""

# Show execution details
echo "Execution Details:"
gcloud run jobs executions describe ${EXECUTION_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --format="yaml(status, spec.taskCount, spec.parallelism, status.completionTime, status.startTime)"

echo ""
echo "==========================================
Recent Logs (last 50 lines):
==========================================
"

# Show logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=${JOB_NAME} AND resource.labels.location=${REGION}" \
  --project=${PROJECT_ID} \
  --limit=50 \
  --format="table(timestamp, textPayload)"

echo ""
echo "==========================================
Data Quality Check:
==========================================
"

# Check BigQuery for recent data
bq query --use_legacy_sql=false --format=prettyjson <<SQL
SELECT 
  player_status,
  name_resolution_status,
  COUNT(*) as count
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
WHERE DATE(processed_at) = CURRENT_DATE()
GROUP BY player_status, name_resolution_status
ORDER BY player_status, name_resolution_status;
SQL

echo ""
echo "To stream logs in real-time:"
echo "gcloud run jobs executions logs ${EXECUTION_NAME} --region=${REGION} --tail"