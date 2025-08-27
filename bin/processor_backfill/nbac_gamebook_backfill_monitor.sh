#!/bin/bash
# File: bin/processor_backfill/nbac_gamebook_backfill_monitor.sh
# Monitor NBA.com gamebook backfill job execution

set -e

# Configuration
PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
REGION=${REGION:-"us-west2"}
JOB_NAME="nbac-gamebook-backfill"  # Uses dashes for Cloud Run

echo "========================================"
echo "Monitoring NBA.com Gamebook Backfill Job"
echo "========================================"
echo "Job: ${JOB_NAME}"
echo "Region: ${REGION}"
echo "Project: ${PROJECT_ID}"
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
  echo "❌ No executions found for job ${JOB_NAME}"
  exit 1
fi

echo "✓ Found execution: ${EXECUTION_NAME}"
echo ""

# Show execution status
echo "📊 Execution Status:"
echo "===================="
gcloud run jobs executions describe ${EXECUTION_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --format="table(
    status.type:label='TYPE',
    status.conditions[0].status:label='STATUS',
    metadata.creationTimestamp:label='CREATION_TIMESTAMP',
    status.completionTime:label='COMPLETION_TIME'
  )"

# Check if still running
STATUS=$(gcloud run jobs executions describe ${EXECUTION_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --format="value(status.conditions[0].status)")

if [ "$STATUS" != "True" ]; then
  echo ""
  echo "⏳ Job is still running or failed"
fi

# Show recent logs
echo ""
echo "📜 Recent Logs (last 50 lines):"
echo "================================"
gcloud run jobs executions logs ${EXECUTION_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --limit=50 2>/dev/null || echo "No logs available yet"

# BigQuery statistics
echo ""
echo "📈 BigQuery Table Statistics:"
echo "=============================="

# Today's processing stats
echo "Today's Processing:"
bq query --use_legacy_sql=false --format=json <<SQL
SELECT 
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MIN(processed_at)) as started_at,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(processed_at)) as latest_at,
  COUNT(DISTINCT game_id) as games_processed,
  COUNT(*) as records_loaded_today,
  MIN(game_date) as earliest_game_date,
  MAX(game_date) as latest_game_date,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT CASE WHEN player_status = 'active' THEN player_lookup END) as active_players,
  COUNT(DISTINCT CASE WHEN player_status = 'inactive' AND name_resolution_status IN ('multiple_matches', 'not_found') THEN player_lookup END) as unresolved_names
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
WHERE DATE(processed_at) = CURRENT_DATE()
SQL

# Sample recent games
echo ""
echo "Recent Games Loaded:"
bq query --use_legacy_sql=false --format=json <<SQL
SELECT 
  game_date as date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT CASE WHEN player_status = 'active' THEN player_lookup END) as active_players,
  COUNT(DISTINCT CASE WHEN player_status = 'dnp' THEN player_lookup END) as dnp_players,
  COUNT(DISTINCT CASE WHEN player_status = 'inactive' THEN player_lookup END) as inactive_players,
  COUNT(*) as total_records
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 10
SQL

# Overall table stats
echo ""
echo "Overall Table Stats:"
bq query --use_legacy_sql=false --format=json <<SQL
SELECT 
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game,
  COUNT(DISTINCT game_id) as total_games,
  COUNT(DISTINCT player_lookup) as total_players,
  COUNT(*) as total_records,
  ROUND(COUNT(*) / COUNT(DISTINCT game_id), 1) as avg_records_per_game,
  COUNT(DISTINCT CASE WHEN name_resolution_status = 'not_found' THEN CONCAT(player_name_original, team_abbr) END) as unresolved_names
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
SQL

# Check for processing issues
echo ""
echo "🔍 Checking for Processing Issues:"
echo "==================================="

# Check for name resolution issues
RESOLUTION_ISSUES=$(bq query --use_legacy_sql=false --format=csv <<SQL | tail -n +2
SELECT COUNT(*)
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
WHERE player_status = 'inactive'
  AND name_resolution_status IN ('multiple_matches', 'not_found')
  AND DATE(processed_at) = CURRENT_DATE()
SQL
)

if [ "$RESOLUTION_ISSUES" -gt "0" ]; then
  echo "⚠️  Found $RESOLUTION_ISSUES name resolution issues today"
  echo "   Run this query to see details:"
  echo "   SELECT * FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_name_issues\` LIMIT 20"
else
  echo "✓ No name resolution issues found"
fi

# Check for missing data
echo ""
bq query --use_legacy_sql=false <<SQL
SELECT 
  CASE 
    WHEN COUNT(*) = 0 THEN '✓ No games with all NULL stats'
    ELSE CONCAT('⚠️  ', CAST(COUNT(*) AS STRING), ' games with all NULL stats')
  END as data_quality_check
FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
WHERE player_status = 'active'
  AND points IS NULL
  AND assists IS NULL
  AND total_rebounds IS NULL
SQL

echo ""
echo "💡 Useful Commands:"
echo "  Watch logs:    gcloud run jobs executions logs ${EXECUTION_NAME} --region=${REGION} --tail"
echo "  Full details:  gcloud run jobs executions describe ${EXECUTION_NAME} --region=${REGION}"
echo "  Job history:   gcloud run jobs executions list --job=${JOB_NAME} --region=${REGION}"
echo ""

if [ "$STATUS" = "True" ]; then
  echo "✅ Job completed successfully!"
else
  echo "🔄 Job is still in progress..."
fi