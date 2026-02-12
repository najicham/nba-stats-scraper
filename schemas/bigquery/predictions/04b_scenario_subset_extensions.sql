-- ============================================================================
-- Scenario-Based Subset Extensions (Session 112)
-- ============================================================================
-- Purpose: Extend dynamic_subset_definitions to support scenario-based filtering
--
-- Session 111 discovered that optimal betting scenarios are defined by:
--   - Direction (OVER/UNDER)
--   - Vegas line ranges (low line OVERs, high line UNDERs)
--   - Edge thresholds
--   - Player blacklists (high-variance players to avoid for UNDER bets)
--   - Opponent risk (teams that allow breakout games)
--
-- This extension adds these capabilities to the existing subset system.
-- ============================================================================

-- ============================================================================
-- Step 1: Add columns to dynamic_subset_definitions
-- ============================================================================

-- Add recommendation filter (OVER, UNDER, or NULL for any)
ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS recommendation_filter STRING;

-- Add line value range filters
ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS line_min FLOAT64;

ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS line_max FLOAT64;

-- Add player blacklist (JSON array of player_lookup values)
ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS exclude_players STRING;  -- JSON array: ["lukadoncic", "julianrandle"]

-- Add opponent risk list (JSON array of team tricodes)
ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS exclude_opponents STRING;  -- JSON array: ["PHI", "MIN", "DET"]

-- Add scenario category for grouping
ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS scenario_category STRING;  -- 'optimal', 'anti_pattern', 'signal_based', 'custom'

-- Add expected hit rate and ROI for documentation
ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS expected_hit_rate FLOAT64;

ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS expected_roi FLOAT64;

-- Add validation metadata
ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS sample_size_source INT64;  -- Bets used to calculate expected rates

ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS validation_period STRING;  -- e.g., "2025-11-01 to 2026-02-02"

ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMP;

-- Session 209: Add quality filtering requirement
ALTER TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS require_quality_ready BOOLEAN;

-- ============================================================================
-- Step 2: Create supporting reference tables
-- ============================================================================

-- Player blacklist table for detailed tracking
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.player_betting_risk` (
  player_lookup STRING NOT NULL,
  player_name STRING NOT NULL,
  risk_type STRING NOT NULL,           -- 'under_blacklist', 'over_blacklist', 'high_variance'
  risk_reason STRING,                  -- Why this player is risky
  under_hit_rate FLOAT64,              -- Historical UNDER hit rate
  over_hit_rate FLOAT64,               -- Historical OVER hit rate
  avg_error FLOAT64,                   -- Average prediction error
  sample_size INT64,                   -- Number of bets in calculation
  validation_period STRING,            -- Date range used for calculation
  is_active BOOL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  created_by STRING DEFAULT 'system',
  notes STRING
);

-- Opponent risk table for teams that cause breakouts
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.opponent_betting_risk` (
  team_tricode STRING NOT NULL,        -- e.g., 'PHI', 'MIN', 'DET'
  team_name STRING,
  risk_type STRING NOT NULL,           -- 'under_risk', 'over_risk', 'pace_boost'
  risk_reason STRING,                  -- Why games against this team are risky
  under_hit_rate FLOAT64,              -- Historical UNDER hit rate vs this opponent
  over_hit_rate FLOAT64,               -- Historical OVER hit rate vs this opponent
  avg_actual_pts FLOAT64,              -- Average points scored against this team
  sample_size INT64,
  validation_period STRING,
  is_active BOOL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  notes STRING
);

-- ============================================================================
-- Step 3: Create performance tracking view
-- ============================================================================
-- @quality-filter: applied
-- Session 209: Filters by quality_alert_level = 'green' when require_quality_ready = TRUE
-- Quality filtering prevents contaminated metrics (12.1% vs 50.3% hit rate)

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_scenario_subset_performance` AS
WITH subset_defs AS (
  SELECT * FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
  WHERE is_active = TRUE
),
picks_with_results AS (
  SELECT
    pa.game_date,
    pa.player_lookup,
    pa.system_id,
    pa.recommendation,
    pa.line_value,
    pa.predicted_points,
    ABS(pa.predicted_points - pa.line_value) as edge,
    pa.confidence_score,
    pa.actual_points,
    pa.prediction_correct,
    pa.opponent_team_abbr as opponent_tricode,  -- Session 209: Normalize field name
    dps.daily_signal,
    dps.pct_over,
    COALESCE(fs.quality_alert_level, 'unknown') as quality_alert_level  -- Session 209: Quality filter
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  LEFT JOIN `nba-props-platform.nba_predictions.daily_prediction_signals` dps
    ON pa.game_date = dps.game_date AND pa.system_id = dps.system_id
  LEFT JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
    ON pa.player_lookup = fs.player_lookup
    AND pa.game_date = fs.game_date
  WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND pa.game_date < CURRENT_DATE()
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_value IS NOT NULL
)
SELECT
  d.subset_id,
  d.subset_name,
  d.scenario_category,
  d.recommendation_filter,
  d.min_edge,
  d.line_min,
  d.line_max,
  d.expected_hit_rate,
  d.expected_roi,
  COUNT(*) as actual_bets,
  SUM(CASE WHEN p.prediction_correct THEN 1 ELSE 0 END) as actual_wins,
  ROUND(100.0 * SUM(CASE WHEN p.prediction_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as actual_hit_rate,
  ROUND((100.0 * SUM(CASE WHEN p.prediction_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) - 52.38) / 52.38 * 100, 1) as actual_roi,
  d.sample_size_source,
  d.validation_period
FROM picks_with_results p
CROSS JOIN subset_defs d
WHERE
  -- System filter
  (d.system_id IS NULL OR p.system_id = d.system_id)
  -- Edge filter
  AND p.edge >= COALESCE(d.min_edge, 0)
  -- Confidence filter
  AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
  -- Recommendation filter (NEW)
  AND (d.recommendation_filter IS NULL OR p.recommendation = d.recommendation_filter)
  -- Line range filter (NEW)
  AND (d.line_min IS NULL OR p.line_value >= d.line_min)
  AND (d.line_max IS NULL OR p.line_value < d.line_max)
  -- Player blacklist filter (NEW) - uses JSON array
  AND (d.exclude_players IS NULL OR p.player_lookup NOT IN (
    SELECT JSON_VALUE(player) FROM UNNEST(JSON_QUERY_ARRAY(d.exclude_players)) AS player
  ))
  -- Opponent risk filter (NEW) - uses JSON array
  AND (d.exclude_opponents IS NULL OR p.opponent_tricode NOT IN (
    SELECT JSON_VALUE(opp) FROM UNNEST(JSON_QUERY_ARRAY(d.exclude_opponents)) AS opp
  ))
  -- Signal filter
  AND (
    d.signal_condition IS NULL OR d.signal_condition = 'ANY'
    OR (d.signal_condition = 'GREEN' AND p.daily_signal = 'GREEN')
    OR (d.signal_condition = 'GREEN_OR_YELLOW' AND p.daily_signal IN ('GREEN', 'YELLOW'))
    OR (d.signal_condition = 'RED' AND p.daily_signal = 'RED')
  )
  -- Session 209: Quality filter (12.1% vs 50.3% hit rate)
  AND (
    d.require_quality_ready IS NULL
    OR d.require_quality_ready = FALSE
    OR (d.require_quality_ready = TRUE AND p.quality_alert_level = 'green')
  )
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15
HAVING COUNT(*) >= 5
ORDER BY actual_hit_rate DESC;
