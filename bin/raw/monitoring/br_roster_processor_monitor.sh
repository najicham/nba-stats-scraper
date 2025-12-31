#!/bin/bash
# File: bin/raw/monitoring/br_roster_processor_monitor.sh
# Purpose: Monitor Basketball Reference roster processor job executions
# Usage: ./bin/raw/monitoring/br_roster_processor_monitor.sh [--logs N]

set -e

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
REGION=${REGION:-"us-west2"}
JOB_NAME="br-roster-processor"

# Parse arguments
LOGS_LIMIT=50
while [[ $# -gt 0 ]]; do
    case "$1" in
        --logs)
            LOGS_LIMIT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--logs N]"
            echo ""
            echo "Options:"
            echo "  --logs N    Show last N log entries (default: 50)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Basketball Reference Roster Processor Monitor"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Job: $JOB_NAME"
echo ""

# Get latest execution
echo "Fetching latest execution..."
EXECUTION_NAME=$(gcloud run jobs executions list \
  --job=${JOB_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --limit=1 \
  --format="value(name)" 2>/dev/null || echo "")

if [ -z "$EXECUTION_NAME" ]; then
  echo "No executions found for job ${JOB_NAME}"
  echo ""
  echo "Checking if job exists..."
  gcloud run jobs describe ${JOB_NAME} \
    --region=${REGION} \
    --project=${PROJECT_ID} \
    --format="value(name)" 2>/dev/null || echo "Job not found: ${JOB_NAME}"
  exit 1
fi

echo "Latest execution: ${EXECUTION_NAME}"
echo ""

# Show execution details
echo "Execution Details:"
echo "------------------------------------------"
gcloud run jobs executions describe ${EXECUTION_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --format="yaml(status, spec.taskCount, spec.parallelism, status.completionTime, status.startTime)"

echo ""
echo "=========================================="
echo "Recent Logs (last ${LOGS_LIMIT} lines):"
echo "=========================================="

# Show logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=${JOB_NAME} AND resource.labels.location=${REGION}" \
  --project=${PROJECT_ID} \
  --limit=${LOGS_LIMIT} \
  --format="table(timestamp, textPayload)"

echo ""
echo "=========================================="
echo "Data Quality Check (BigQuery):"
echo "=========================================="

# Check BigQuery for roster data
bq query --use_legacy_sql=false --format=prettyjson <<SQL
SELECT
  season_year,
  COUNT(DISTINCT team_abbrev) as teams_count,
  COUNT(*) as total_players,
  MAX(updated_at) as last_update
FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
GROUP BY season_year
ORDER BY season_year DESC
LIMIT 5;
SQL

echo ""
echo "=========================================="
echo "Recent Processing Activity:"
echo "=========================================="

bq query --use_legacy_sql=false --format=prettyjson <<SQL
SELECT
  DATE(processed_at) as process_date,
  COUNT(DISTINCT team_abbrev) as teams_processed,
  COUNT(*) as records_updated,
  MAX(processed_at) as last_update
FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY process_date
ORDER BY process_date DESC;
SQL

echo ""
echo "To stream logs in real-time:"
echo "gcloud run jobs executions logs ${EXECUTION_NAME} --region=${REGION} --tail"
