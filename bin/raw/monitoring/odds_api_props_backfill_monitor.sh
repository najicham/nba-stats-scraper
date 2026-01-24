pl#!/bin/bash
# File: bin/processor_backfill/odds_api_props_backfill_monitor.sh
#
# Monitor the Odds API Props Processor Backfill Job
# Follows same pattern as br_roster_processor_monitor.sh

set -euo pipefail

# Configuration
PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
REGION=${REGION:-"us-west2"}
JOB_NAME="odds-api-props-backfill"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Monitoring Odds API Props Backfill Job${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Job: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo ""

# Get latest execution
echo "📋 Getting latest execution..."
EXECUTION_NAME=$(gcloud run jobs executions list \
  --job=${JOB_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --limit=1 \
  --format="value(name)")

if [ -z "$EXECUTION_NAME" ]; then
  echo -e "${RED}❌ No executions found for job ${JOB_NAME}${NC}"
  echo ""
  echo "To start a new execution:"
  echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION}"
  exit 1
fi

echo -e "${GREEN}✓${NC} Found execution: ${EXECUTION_NAME}"
echo ""

# Get execution status
echo "📊 Execution Status:"
echo "===================="
gcloud run jobs executions describe ${EXECUTION_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --format="table(
    status.conditions[0].type,
    status.conditions[0].status,
    metadata.creationTimestamp,
    status.completionTime
  )"

echo ""

# Check if job is still running
STATUS=$(gcloud run jobs executions describe ${EXECUTION_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --format="value(status.conditions[0].status)")

if [ "$STATUS" == "True" ]; then
  echo -e "${GREEN}✓ Job completed successfully${NC}"
else
  echo -e "${YELLOW}⏳ Job is still running or failed${NC}"
fi

echo ""

# Stream recent logs
echo "📜 Recent Logs (last 50 lines):"
echo "================================"
gcloud logging read "resource.type=\"cloud_run_job\" 
  AND resource.labels.job_name=\"${JOB_NAME}\" 
  AND labels.execution_name=\"${EXECUTION_NAME}\"" \
  --project=${PROJECT_ID} \
  --limit=50 \
  --format="table(timestamp, jsonPayload.message)" \
  --order="desc" | tac

echo ""

# Monitor BigQuery table growth
echo "📈 BigQuery Table Statistics:"
echo "=============================="

# Today's processing stats
echo -e "${BLUE}Today's Processing:${NC}"
bq query --use_legacy_sql=false --format=prettyjson --project_id=${PROJECT_ID} <<SQL
SELECT
  COUNT(*) as records_loaded_today,
  COUNT(DISTINCT game_id) as games_processed,
  COUNT(DISTINCT player_name) as unique_players,
  COUNT(DISTINCT bookmaker) as bookmakers,
  MIN(game_date) as earliest_game_date,
  MAX(game_date) as latest_game_date,
  MIN(processing_timestamp) as started_at,
  MAX(processing_timestamp) as latest_at
FROM \`${PROJECT_ID}.nba_raw.odds_api_player_points_props\`
WHERE DATE(processing_timestamp) = CURRENT_DATE()
SQL

echo ""
echo -e "${BLUE}Recent Daily Loads:${NC}"
bq query --use_legacy_sql=false --format=prettyjson --project_id=${PROJECT_ID} <<SQL
SELECT
  DATE(game_date) as date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_name) as players,
  COUNT(*) as total_props,
  MIN(minutes_before_tipoff) as closest_to_tipoff,
  MAX(minutes_before_tipoff) as furthest_from_tipoff
FROM \`${PROJECT_ID}.nba_raw.odds_api_player_points_props\`
WHERE DATE(processing_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY date
ORDER BY date DESC
LIMIT 10
SQL

echo ""
echo -e "${BLUE}Overall Table Stats:${NC}"
bq query --use_legacy_sql=false --format=prettyjson --project_id=${PROJECT_ID} <<SQL
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as total_games,
  COUNT(DISTINCT player_name) as total_players,
  COUNT(DISTINCT bookmaker) as total_bookmakers,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game,
  ROUND(COUNT(*) / COUNT(DISTINCT game_id), 2) as avg_props_per_game
FROM \`${PROJECT_ID}.nba_raw.odds_api_player_points_props\`
SQL

echo ""

# Check for any errors in processing
echo "🔍 Checking for Processing Issues:"
echo "==================================="

# Count of recent errors in logs
ERROR_COUNT=$(gcloud logging read "resource.type=\"cloud_run_job\" 
  AND resource.labels.job_name=\"${JOB_NAME}\" 
  AND labels.execution_name=\"${EXECUTION_NAME}\"
  AND severity=\"ERROR\"" \
  --project=${PROJECT_ID} \
  --limit=10 \
  --format="value(jsonPayload.message)" | wc -l)

if [ "$ERROR_COUNT" -gt 0 ]; then
  echo -e "${RED}⚠️  Found $ERROR_COUNT error messages in logs${NC}"
  echo "Recent errors:"
  gcloud logging read "resource.type=\"cloud_run_job\" 
    AND resource.labels.job_name=\"${JOB_NAME}\" 
    AND labels.execution_name=\"${EXECUTION_NAME}\"
    AND severity=\"ERROR\"" \
    --project=${PROJECT_ID} \
    --limit=5 \
    --format="table(timestamp, jsonPayload.message)"
else
  echo -e "${GREEN}✓ No errors found in recent logs${NC}"
fi

echo ""

# Show how to tail logs live
echo "💡 To watch logs in real-time:"
echo "   gcloud run jobs executions logs ${EXECUTION_NAME} --region=${REGION} --tail"
echo ""
echo "📊 To see full execution details:"
echo "   gcloud run jobs executions describe ${EXECUTION_NAME} --region=${REGION}"
echo ""
echo "🔄 To check job history:"
echo "   gcloud run jobs executions list --job=${JOB_NAME} --region=${REGION}"
echo ""

# Calculate estimated completion
if [ "$STATUS" != "True" ]; then
  echo "⏱️  Estimating completion time..."
  
  # Get processed count
  PROCESSED=$(bq query --use_legacy_sql=false --format=csv --project_id=${PROJECT_ID} \
    "SELECT COUNT(DISTINCT game_date) FROM \`${PROJECT_ID}.nba_raw.odds_api_player_points_props\` 
     WHERE DATE(processing_timestamp) = CURRENT_DATE()" | tail -n 1)
  
  # Rough estimate: ~730 days total
  TOTAL_DAYS=730
  
  if [ -n "$PROCESSED" ] && [ "$PROCESSED" -gt 0 ]; then
    PERCENT=$((PROCESSED * 100 / TOTAL_DAYS))
    echo -e "${YELLOW}Progress: Approximately ${PERCENT}% complete (${PROCESSED}/${TOTAL_DAYS} days)${NC}"
  fi
fi

echo ""
echo "✅ Monitoring complete!"