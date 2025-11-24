#!/bin/bash
# ============================================================================
# CASCADE Scheduler Monitoring Script
# ============================================================================
# Purpose: Monitor CASCADE scheduler job execution (NEW - 2025-11-23)
# Jobs: player-composite-factors-daily (11 PM), ml-feature-store-daily (11:30 PM)
# Usage: ./bin/monitoring/check_cascade_schedulers.sh
# ============================================================================

set -e

PROJECT_ID="nba-props-platform"
LOCATION="us-west2"

echo "=================================================="
echo "CASCADE SCHEDULER MONITORING"
echo "=================================================="
echo ""

# 1. Check Cloud Scheduler job status
echo "1️⃣  Cloud Scheduler Jobs Status"
echo "--------------------------------------------------"
gcloud scheduler jobs list \
  --project=$PROJECT_ID \
  --location=$LOCATION \
  --filter="name:player-composite OR name:ml-feature" \
  --format="table(
    name.basename(),
    schedule,
    state,
    lastAttemptTime,
    status.code
  )"
echo ""

# 2. Check player_composite_factors output
echo "2️⃣  player_composite_factors - Last 3 Days"
echo "--------------------------------------------------"
bq query --use_legacy_sql=false --format=pretty --project_id=$PROJECT_ID "
SELECT
  game_date,
  COUNT(*) as total_entities,
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as production_ready,
  ROUND(AVG(completeness_percentage), 1) as avg_completeness_pct,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(processed_at), 'America/Los_Angeles') as last_run_pt,
  CASE
    WHEN SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*) >= 0.95 THEN '✅ EXCELLENT'
    WHEN SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*) >= 0.90 THEN '✓ GOOD'
    WHEN SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*) >= 0.80 THEN '⚠ WARNING'
    ELSE '❌ CRITICAL'
  END as status
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
"
echo ""

# 3. Check ml_feature_store output
echo "3️⃣  ml_feature_store - Last 3 Days"
echo "--------------------------------------------------"
bq query --use_legacy_sql=false --format=pretty --project_id=$PROJECT_ID "
SELECT
  game_date,
  COUNT(*) as total_entities,
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as production_ready,
  ROUND(AVG(completeness_percentage), 1) as avg_completeness_pct,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(processed_at), 'America/Los_Angeles') as last_run_pt,
  CASE
    WHEN SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*) >= 0.95 THEN '✅ EXCELLENT'
    WHEN SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*) >= 0.90 THEN '✓ GOOD'
    WHEN SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*) >= 0.80 THEN '⚠ WARNING'
    ELSE '❌ CRITICAL'
  END as status
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
"
echo ""

# 4. Check for data quality issues
echo "4️⃣  Data Quality Issues (if any)"
echo "--------------------------------------------------"
bq query --use_legacy_sql=false --format=pretty --project_id=$PROJECT_ID --max_rows=10 "
SELECT
  'player_composite_factors' as processor,
  game_date,
  ARRAY_TO_STRING(data_quality_issues, ', ') as issues,
  COUNT(*) as affected_entities
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND ARRAY_LENGTH(data_quality_issues) > 0
GROUP BY game_date, ARRAY_TO_STRING(data_quality_issues, ', ')

UNION ALL

SELECT
  'ml_feature_store',
  game_date,
  ARRAY_TO_STRING(data_quality_issues, ', '),
  COUNT(*)
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND ARRAY_LENGTH(data_quality_issues) > 0
GROUP BY game_date, ARRAY_TO_STRING(data_quality_issues, ', ')

ORDER BY game_date DESC;
"
echo ""

# 5. Today's run status
echo "5️⃣  Expected Run Times (Pacific Time)"
echo "--------------------------------------------------"
echo "player-composite-factors-daily: 11:00 PM PT daily"
echo "ml-feature-store-daily:         11:30 PM PT daily"
echo ""
echo "Current time (PT): $(TZ='America/Los_Angeles' date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# 6. Next run information
echo "6️⃣  Next Scheduled Runs"
echo "--------------------------------------------------"
gcloud scheduler jobs describe player-composite-factors-daily \
  --project=$PROJECT_ID \
  --location=$LOCATION \
  --format="value(schedule)" | \
  awk '{print "player-composite-factors: Next run scheduled per: " $0}'

gcloud scheduler jobs describe ml-feature-store-daily \
  --project=$PROJECT_ID \
  --location=$LOCATION \
  --format="value(schedule)" | \
  awk '{print "ml-feature-store: Next run scheduled per: " $0}'
echo ""

echo "=================================================="
echo "CASCADE MONITORING COMPLETE"
echo "=================================================="
echo ""
echo "📊 Interpretation:"
echo "  ✅ EXCELLENT: ≥95% production ready"
echo "  ✓  GOOD:      ≥90% production ready"
echo "  ⚠  WARNING:   ≥80% production ready"
echo "  ❌ CRITICAL:  <80% production ready"
echo ""
echo "💡 What to do:"
echo "  - If yesterday's data shows '✅' or '✓': All good!"
echo "  - If '⚠' or '❌': Check data quality issues above"
echo "  - If no data for yesterday: Jobs may not have run yet (check schedule)"
echo ""
