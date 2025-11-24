#!/bin/bash
# ============================================================================
# Pub/Sub Flow Monitoring Script
# ============================================================================
# Purpose: Monitor Pub/Sub message flow Phase 3 → Phase 4 (NEW - 2025-11-23)
# Flow: Phase 3 publishes → nba-phase3-analytics-complete → Phase 4 processes
# Usage: ./bin/monitoring/check_pubsub_flow.sh
# ============================================================================

set -e

PROJECT_ID="nba-props-platform"

echo "=================================================="
echo "PUB/SUB FLOW MONITORING (Phase 3 → Phase 4)"
echo "=================================================="
echo ""

# 1. Check Pub/Sub topic and subscription
echo "1️⃣  Pub/Sub Infrastructure Status"
echo "--------------------------------------------------"
echo "Topic: nba-phase3-analytics-complete"
gcloud pubsub topics describe nba-phase3-analytics-complete \
  --project=$PROJECT_ID \
  --format="table(name.basename())"

echo ""
echo "Subscription: nba-phase3-analytics-complete-sub"
gcloud pubsub subscriptions describe nba-phase3-analytics-complete-sub \
  --project=$PROJECT_ID \
  --format="table(
    name.basename(),
    topic.basename(),
    pushConfig.pushEndpoint,
    ackDeadlineSeconds
  )"
echo ""

# 2. Check for message backlog
echo "2️⃣  Message Backlog"
echo "--------------------------------------------------"
BACKLOG=$(gcloud pubsub subscriptions describe nba-phase3-analytics-complete-sub \
  --project=$PROJECT_ID \
  --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")

echo "Undelivered messages: $BACKLOG"
if [ "$BACKLOG" -gt 0 ]; then
  echo "⚠️  WARNING: There are $BACKLOG undelivered messages!"
  echo "    This indicates Phase 4 may not be processing messages."
else
  echo "✅ No message backlog - healthy!"
fi
echo ""

# 3. Check Phase 3→4 latency (last 24 hours)
echo "3️⃣  Phase 3 → Phase 4 Processing Latency (Last 3 Days)"
echo "--------------------------------------------------"
bq query --use_legacy_sql=false --format=pretty --project_id=$PROJECT_ID "
WITH phase3_runs AS (
  SELECT
    'player_game_summary' as source_table,
    game_date,
    MAX(processed_at) as phase3_time
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date

  UNION ALL

  SELECT
    'team_defense_game_summary',
    game_date,
    MAX(processed_at)
  FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date

  UNION ALL

  SELECT
    'team_offense_game_summary',
    game_date,
    MAX(processed_at)
  FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date
),

phase4_runs AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    'team_defense_game_summary' as source_table,
    analysis_date as game_date,
    MAX(processed_at) as phase4_time
  FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY analysis_date

  UNION ALL

  SELECT
    'player_shot_zone_analysis',
    'team_offense_game_summary',
    analysis_date,
    MAX(processed_at)
  FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY analysis_date

  UNION ALL

  SELECT
    'player_daily_cache',
    'player_game_summary',
    cache_date,
    MAX(processed_at)
  FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
  WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY cache_date
)

SELECT
  p3.source_table,
  p3.game_date,
  FORMAT_TIMESTAMP('%H:%M:%S', p3.phase3_time, 'America/Los_Angeles') as phase3_completed_pt,
  p4.processor as phase4_processor,
  FORMAT_TIMESTAMP('%H:%M:%S', p4.phase4_time, 'America/Los_Angeles') as phase4_completed_pt,
  TIMESTAMP_DIFF(p4.phase4_time, p3.phase3_time, SECOND) as latency_seconds,
  CASE
    WHEN p4.phase4_time IS NULL THEN '❌ NOT PROCESSED'
    WHEN TIMESTAMP_DIFF(p4.phase4_time, p3.phase3_time, SECOND) < 300 THEN '✅ FAST (<5min)'
    WHEN TIMESTAMP_DIFF(p4.phase4_time, p3.phase3_time, SECOND) < 1800 THEN '✓ NORMAL (<30min)'
    ELSE '⚠ SLOW (>30min)'
  END as status
FROM phase3_runs p3
LEFT JOIN phase4_runs p4
  ON p3.source_table = p4.source_table
  AND p3.game_date = p4.game_date
ORDER BY p3.game_date DESC, p3.source_table;
"
echo ""

# 4. Check Cloud Run logs for Pub/Sub message handling
echo "4️⃣  Recent Phase 4 Pub/Sub Message Processing (Last 20)"
echo "--------------------------------------------------"
gcloud run services logs read nba-phase4-precompute-processors \
  --project=$PROJECT_ID \
  --region=us-west2 \
  --limit=20 \
  --format="table(
    time.format('%Y-%m-%d %H:%M:%S'),
    textPayload
  )" \
  2>/dev/null | grep -E "(Processing precompute|source_table|Successfully ran)" | head -20 || echo "No recent Pub/Sub messages found in logs"
echo ""

# 5. Summary
echo "5️⃣  Flow Health Summary"
echo "--------------------------------------------------"
echo "Phase 3 Analytics Processors:"
echo "  ✅ PlayerGameSummaryProcessor"
echo "  ✅ TeamOffenseGameSummaryProcessor"
echo "  ✅ TeamDefenseGameSummaryProcessor"
echo "  ✅ UpcomingPlayerGameContextProcessor"
echo "  ✅ UpcomingTeamGameContextProcessor"
echo ""
echo "All processors publish to: nba-phase3-analytics-complete"
echo ""
echo "Phase 4 Precompute Processors (Pub/Sub-triggered):"
echo "  ✅ PlayerDailyCacheProcessor (from player_game_summary)"
echo "  ✅ TeamDefenseZoneAnalysisProcessor (from team_defense_game_summary)"
echo "  ✅ PlayerShotZoneAnalysisProcessor (from team_offense_game_summary)"
echo ""

echo "=================================================="
echo "PUB/SUB FLOW MONITORING COMPLETE"
echo "=================================================="
echo ""
echo "📊 Interpretation:"
echo "  ✅ FAST:   Phase 4 processed within 5 minutes of Phase 3"
echo "  ✓  NORMAL: Phase 4 processed within 30 minutes of Phase 3"
echo "  ⚠  SLOW:   Phase 4 took >30 minutes (check Cloud Run logs)"
echo "  ❌ NOT PROCESSED: Phase 4 never ran (Pub/Sub issue)"
echo ""
echo "💡 What to do:"
echo "  - If latency is ✅ or ✓: Pub/Sub flow is working!"
echo "  - If ⚠ SLOW: Check Cloud Run cold starts or resource limits"
echo "  - If ❌ NOT PROCESSED: Check subscription and Cloud Run service"
echo "  - If message backlog >0: Phase 4 service may be down"
echo ""
