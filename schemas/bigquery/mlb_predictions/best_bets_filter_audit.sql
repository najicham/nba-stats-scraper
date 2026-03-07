-- ============================================================================
-- MLB Best Bets Filter Audit Table Schema (v1)
-- ============================================================================
-- Dataset: mlb_predictions
-- Table: best_bets_filter_audit
-- Purpose: Audit trail for negative filter decisions on pitcher strikeout
--          best bets candidates. Records every filter evaluation (PASSED or
--          BLOCKED) for post-hoc analysis of filter effectiveness.
--          Modeled after nba_predictions.best_bets_filter_audit.
-- Created: 2026-03-06
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.best_bets_filter_audit` (
  -- Primary Keys
  game_date DATE NOT NULL,                      -- Game date (partition key)
  pitcher_lookup STRING NOT NULL,               -- Pitcher identifier
  system_id STRING NOT NULL,                    -- Model system_id

  -- Filter Decision
  filter_name STRING NOT NULL,                  -- Filter identifier (e.g., 'short_start_risk', 'bad_matchup')
  filter_result STRING NOT NULL,                -- 'PASSED' or 'BLOCKED'
  filter_reason STRING,                         -- Human-readable explanation when BLOCKED

  -- Context (optional, for deeper analysis)
  recommendation STRING,                        -- OVER/UNDER at time of filter evaluation
  edge FLOAT64,                                 -- Edge at time of filter evaluation
  line_value FLOAT64,                           -- Strikeout line at time of filter evaluation

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup, filter_name
OPTIONS (
  require_partition_filter=TRUE,
  description='Audit trail for MLB best bets filter decisions. Records PASSED/BLOCKED for every '
              'negative filter evaluated on pitcher strikeout candidates. Use for analyzing filter '
              'effectiveness: which filters block the most, which improve HR, which over-filter.'
);

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Filter effectiveness over last 7 days
-- SELECT
--   filter_name,
--   COUNTIF(filter_result = 'BLOCKED') as blocked,
--   COUNTIF(filter_result = 'PASSED') as passed,
--   ROUND(COUNTIF(filter_result = 'BLOCKED') * 100.0 /
--         NULLIF(COUNT(*), 0), 1) as block_rate_pct
-- FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY filter_name
-- ORDER BY blocked DESC;

-- Which pitchers are most frequently blocked?
-- SELECT
--   pitcher_lookup,
--   COUNT(DISTINCT filter_name) as unique_filters_hit,
--   COUNTIF(filter_result = 'BLOCKED') as total_blocks,
--   STRING_AGG(DISTINCT CASE WHEN filter_result = 'BLOCKED' THEN filter_name END, ', ') as blocking_filters
-- FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND filter_result = 'BLOCKED'
-- GROUP BY pitcher_lookup
-- ORDER BY total_blocks DESC;
