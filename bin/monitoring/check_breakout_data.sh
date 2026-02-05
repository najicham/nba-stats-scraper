#!/bin/bash
# =============================================================================
# Breakout Detection Data Collection Monitor
# =============================================================================
# Purpose: Track progress of Feature 37-38 data collection for breakout model
#
# Features monitored:
#   - Feature 37: breakout_risk (role player scoring opportunity)
#   - Feature 38: composite_signal (breakout + matchup combined)
#   - injured_teammates_ppg: PPG of injured teammates creating opportunity
#
# Training readiness target: 2,000+ role player records (8-16 PPG average)
# =============================================================================

set -e

echo "========================================"
echo "Breakout Detection Data Collection Status"
echo "========================================"
echo ""

# 1. Overall record counts and date range
echo "1. Collection Overview"
echo "----------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as days_collected,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  COUNTIF(breakout_risk IS NOT NULL) as records_with_breakout_risk,
  COUNTIF(composite_signal IS NOT NULL) as records_with_composite_signal
FROM \`nba-props-platform.nba_predictions.prediction_features\`
WHERE game_date >= '2025-11-01'
"

# 2. Role player records (8-16 PPG - primary training cohort)
echo ""
echo "2. Role Player Records (8-16 PPG avg - Training Target)"
echo "--------------------------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as role_player_records,
  COUNT(DISTINCT player_id) as unique_role_players,
  COUNT(DISTINCT game_date) as days_with_role_players,
  ROUND(COUNT(*) / NULLIF(COUNT(DISTINCT game_date), 0), 1) as avg_per_day
FROM \`nba-props-platform.nba_predictions.prediction_features\`
WHERE game_date >= '2025-11-01'
  AND player_season_ppg BETWEEN 8 AND 16
  AND breakout_risk IS NOT NULL
"

# 3. Feature 37-38 value distributions
echo ""
echo "3. Feature Value Distributions"
echo "------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'breakout_risk' as feature,
  ROUND(AVG(breakout_risk), 4) as avg_value,
  ROUND(MIN(breakout_risk), 4) as min_value,
  ROUND(MAX(breakout_risk), 4) as max_value,
  ROUND(STDDEV(breakout_risk), 4) as stddev,
  COUNTIF(breakout_risk > 0) as non_zero_count
FROM \`nba-props-platform.nba_predictions.prediction_features\`
WHERE game_date >= '2025-11-01'
  AND breakout_risk IS NOT NULL

UNION ALL

SELECT
  'composite_signal' as feature,
  ROUND(AVG(composite_signal), 4) as avg_value,
  ROUND(MIN(composite_signal), 4) as min_value,
  ROUND(MAX(composite_signal), 4) as max_value,
  ROUND(STDDEV(composite_signal), 4) as stddev,
  COUNTIF(composite_signal > 0) as non_zero_count
FROM \`nba-props-platform.nba_predictions.prediction_features\`
WHERE game_date >= '2025-11-01'
  AND composite_signal IS NOT NULL
"

# 4. Injured teammates PPG validation
echo ""
echo "4. Injured Teammates PPG Validation"
echo "------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNTIF(injured_teammates_ppg > 0) as records_with_injuries,
  COUNTIF(injured_teammates_ppg = 0 OR injured_teammates_ppg IS NULL) as records_no_injuries,
  ROUND(100.0 * COUNTIF(injured_teammates_ppg > 0) / COUNT(*), 1) as pct_with_injuries,
  ROUND(AVG(CASE WHEN injured_teammates_ppg > 0 THEN injured_teammates_ppg END), 2) as avg_injured_ppg_when_present,
  ROUND(MAX(injured_teammates_ppg), 2) as max_injured_ppg
FROM \`nba-props-platform.nba_predictions.prediction_features\`
WHERE game_date >= '2025-11-01'
  AND breakout_risk IS NOT NULL
"

# 5. Daily collection trend (last 7 days)
echo ""
echo "5. Daily Collection Trend (Last 7 Days)"
echo "----------------------------------------"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(player_season_ppg BETWEEN 8 AND 16) as role_player_records,
  COUNTIF(breakout_risk > 0) as elevated_breakout_risk
FROM \`nba-props-platform.nba_predictions.prediction_features\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND breakout_risk IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC
"

# 6. Training readiness assessment
echo ""
echo "6. Training Readiness Assessment"
echo "---------------------------------"
bq query --use_legacy_sql=false --format=pretty "
WITH stats AS (
  SELECT
    COUNT(*) as role_player_records,
    COUNT(DISTINCT game_date) as days_collected
  FROM \`nba-props-platform.nba_predictions.prediction_features\`
  WHERE game_date >= '2025-11-01'
    AND player_season_ppg BETWEEN 8 AND 16
    AND breakout_risk IS NOT NULL
)
SELECT
  role_player_records,
  2000 as target_records,
  ROUND(100.0 * role_player_records / 2000, 1) as pct_complete,
  CASE
    WHEN role_player_records >= 2000 THEN 'READY FOR TRAINING'
    WHEN role_player_records >= 1500 THEN 'ALMOST READY (75%+)'
    WHEN role_player_records >= 1000 THEN 'HALFWAY THERE'
    ELSE CONCAT('COLLECTING (need ', 2000 - role_player_records, ' more)')
  END as status,
  days_collected,
  CASE
    WHEN role_player_records >= 2000 THEN 0
    ELSE CEIL((2000 - role_player_records) / NULLIF(role_player_records / days_collected, 0))
  END as estimated_days_remaining
FROM stats
"

echo ""
echo "========================================"
echo "Monitor complete"
echo "========================================"
