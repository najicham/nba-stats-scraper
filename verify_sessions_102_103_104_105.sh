#!/bin/bash

echo "========================================="
echo "Sessions 102, 103, 104 & 105 Verification Script"
echo "Run at: $(date -u)"
echo "========================================="

echo ""
echo "1️⃣  Verification 1: Coordinator Batch Loading"
echo "-----------------------------------------"
gcloud logging read \
  'resource.labels.service_name="prediction-coordinator" AND
   jsonPayload.message:"Batch" AND
   timestamp>="2026-01-18T23:00:00Z"' \
  --limit=5 \
  --format="value(jsonPayload.message)" | head -5

echo ""
echo "2️⃣  Verification 2: Model Version Fix"
echo "-----------------------------------------"
bq query --nouse_legacy_sql --format=prettyjson "
SELECT
  IFNULL(model_version, 'NULL') as model_version,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE created_at >= TIMESTAMP('2026-01-18 18:00:00 UTC')
GROUP BY model_version
ORDER BY predictions DESC
"

echo ""
echo "3️⃣  Verification 3: Metrics Count (All 7)"
echo "-----------------------------------------"
bq query --nouse_legacy_sql --format=prettyjson "
SELECT
  COUNT(*) as total_players,

  -- Session 103 metrics
  COUNTIF(pace_differential IS NOT NULL) as with_pace_diff,
  COUNTIF(opponent_pace_last_10 IS NOT NULL) as with_opp_pace,
  COUNTIF(opponent_ft_rate_allowed IS NOT NULL) as with_ft_rate,
  COUNTIF(opponent_def_rating_last_10 IS NOT NULL) as with_def_rating,

  -- Session 104 metrics
  COUNTIF(opponent_off_rating_last_10 IS NOT NULL) as with_off_rating,
  COUNTIF(opponent_rebounding_rate IS NOT NULL) as with_rebound_rate,

  -- Session 105 metric (NEW)
  COUNTIF(opponent_pace_variance IS NOT NULL) as with_pace_variance,

  ROUND(100.0 * COUNTIF(pace_differential IS NOT NULL) / COUNT(*), 2) as pct_populated
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date >= CURRENT_DATE()
"

echo ""
echo "3️⃣  Verification 3: Sample Metrics (All 7)"
echo "-----------------------------------------"
bq query --nouse_legacy_sql --format=prettyjson "
SELECT
    player_lookup,
    team_abbr,
    opponent_team_abbr,

    -- Session 103 metrics
    pace_differential,
    opponent_pace_last_10,
    opponent_ft_rate_allowed,
    opponent_def_rating_last_10,

    -- Session 104 metrics
    opponent_off_rating_last_10,
    opponent_rebounding_rate,

    -- Session 105 metric (NEW)
    opponent_pace_variance
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date >= CURRENT_DATE()
  AND pace_differential IS NOT NULL
LIMIT 5
"

echo ""
echo "========================================="
echo "Verification Complete!"
echo "========================================="
