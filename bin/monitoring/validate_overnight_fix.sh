#!/bin/bash
# Validation Script for Overnight Orchestration Fix
# Run this on Jan 1, 2026 after 8 AM ET to validate the fix worked
# Created: Dec 31, 2025

set -e

echo "=================================================="
echo "Overnight Orchestration Fix - Validation Report"
echo "=================================================="
echo ""
echo "Current Time: $(TZ=America/New_York date)"
echo ""

# 1. Check if schedulers executed
echo "1. SCHEDULER EXECUTION STATUS"
echo "------------------------------"
echo ""
echo "overnight-phase4 (expected: 6:00 AM ET):"
gcloud scheduler jobs describe overnight-phase4 --location=us-west2 \
  --format="value(lastAttemptTime,status.message)" | head -1 | \
  xargs -I {} date -d {} +'Last run: %Y-%m-%d %H:%M:%S %Z (ET: %I:%M %p)' 2>/dev/null || echo "Last run: Not available"

echo ""
echo "overnight-predictions (expected: 7:00 AM ET):"
gcloud scheduler jobs describe overnight-predictions --location=us-west2 \
  --format="value(lastAttemptTime,status.message)" | head -1 | \
  xargs -I {} date -d {} +'Last run: %Y-%m-%d %H:%M:%S %Z (ET: %I:%M %p)' 2>/dev/null || echo "Last run: Not available"

echo ""
echo ""

# 2. Check Phase 4 timing
echo "2. PHASE 4 EXECUTION TIME"
echo "-------------------------"
bq query --use_legacy_sql=false --format=prettyjson "
SELECT
  processor_name,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M ET', started_at, 'America/New_York') as run_time,
  status,
  record_count
FROM nba_reference.processor_run_history
WHERE processor_name LIKE '%FeatureStore%'
  AND DATE(started_at, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY started_at DESC
LIMIT 3" 2>/dev/null | jq -r '.[] | "Run: \(.run_time) | Status: \(.status) | Records: \(.record_count)"'

echo ""
echo ""

# 3. Check predictions timing
echo "3. PREDICTIONS CREATION TIME"
echo "----------------------------"
bq query --use_legacy_sql=false --format=csv "
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M ET', MIN(created_at), 'America/New_York') as first_created,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M ET', MAX(created_at), 'America/New_York') as last_created
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE('America/New_York')
  AND is_active = TRUE
GROUP BY game_date
ORDER BY game_date
LIMIT 3" 2>/dev/null

echo ""
echo ""

# 4. Cascade timing
echo "4. FULL CASCADE TIMING"
echo "----------------------"
bq query --use_legacy_sql=false < monitoring/queries/cascade_timing.sql 2>/dev/null | head -10

echo ""
echo ""

# 5. Success criteria
echo "5. SUCCESS CRITERIA CHECK"
echo "-------------------------"
echo ""
echo "✅ SUCCESS if:"
echo "   - overnight-phase4 ran between 6:00-6:30 AM ET"
echo "   - overnight-predictions ran between 7:00-7:30 AM ET"
echo "   - Predictions for today created around 7:00-7:30 AM ET"
echo "   - Total delay < 6 hours (vs 10+ hours before)"
echo ""
echo "⚠️  PARTIAL SUCCESS if:"
echo "   - Schedulers ran but predictions still created afternoon"
echo "   - Need to check logs for quality score issues"
echo ""
echo "❌ FAILURE if:"
echo "   - Schedulers didn't run (check lastAttemptTime above)"
echo "   - Predictions still created at 11:30 AM or later"
echo "   - Fallback schedulers (11 AM) were used instead"
echo ""

echo "=================================================="
echo "Validation Complete"
echo "=================================================="
