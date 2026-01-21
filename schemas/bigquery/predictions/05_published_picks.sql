-- ============================================================================
-- Published Picks Tracking Table
-- ============================================================================
-- Purpose: Track which picks were actually published/shown to users
--
-- This enables performance analysis of:
--   - Best bets shown on website
--   - Picks sent via notifications
--   - Promoted/featured picks
--
-- Grading: After games complete, this table is updated with actual results
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.published_picks` (
  -- Identification
  publication_id STRING NOT NULL,               -- UUID for this publication record
  prediction_id STRING NOT NULL,                -- Links to player_prop_predictions.prediction_id

  -- Context
  game_date DATE NOT NULL,                      -- Date of the game
  player_lookup STRING NOT NULL,                -- Player identifier
  game_id STRING NOT NULL,                      -- Game identifier
  system_id STRING NOT NULL,                    -- Prediction system (e.g., 'catboost_v8')

  -- Publication Details
  publication_type STRING NOT NULL,             -- 'best_bets', 'all_picks', 'notification', 'promoted'
  publication_channel STRING,                   -- 'website', 'email', 'push', 'twitter'
  rank INT64,                                   -- Position in list (1 = top pick)
  published_at TIMESTAMP NOT NULL,              -- When it was published

  -- Pick Details (snapshot at publication time)
  recommendation STRING NOT NULL,               -- 'OVER' or 'UNDER'
  line_value FLOAT64 NOT NULL,                  -- Prop line at publication
  predicted_points FLOAT64 NOT NULL,            -- Model prediction
  confidence_score FLOAT64 NOT NULL,            -- Model confidence (0-1)
  edge FLOAT64,                                 -- predicted_points - line_value
  composite_score FLOAT64,                      -- Ranking score used for selection

  -- Grading (filled after game completes)
  actual_points FLOAT64,                        -- Actual points scored
  prediction_correct BOOL,                      -- Did the pick win?
  absolute_error FLOAT64,                       -- |predicted - actual|
  graded_at TIMESTAMP,                          -- When grading occurred

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY publication_type, system_id
OPTIONS(
  require_partition_filter=TRUE
);

-- ============================================================================
-- Useful Views
-- ============================================================================

-- View: Published picks performance by type
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_published_picks_performance` AS
SELECT
  publication_type,
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
FROM `nba-props-platform.nba_predictions.published_picks`
WHERE graded_at IS NOT NULL
GROUP BY publication_type, week
ORDER BY week DESC, publication_type;

-- View: Best bets daily performance
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_best_bets_daily` AS
SELECT
  game_date,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error,
  STRING_AGG(
    CONCAT(player_lookup, ': ', recommendation, ' ',
           CASE WHEN prediction_correct THEN '✓' ELSE '✗' END),
    ', '
    ORDER BY rank
  ) as picks_summary
FROM `nba-props-platform.nba_predictions.published_picks`
WHERE publication_type = 'best_bets'
  AND graded_at IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC;
