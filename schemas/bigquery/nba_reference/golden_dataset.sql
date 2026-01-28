-- File: schemas/bigquery/nba_reference/golden_dataset.sql
-- Description: Golden dataset for rolling average verification
-- Created: 2026-01-27
-- Purpose: Manually verified player-date combinations for data quality testing

-- =============================================================================
-- Table: Golden Dataset - Manually Verified Rolling Averages
-- =============================================================================
-- This table contains manually verified player performance data for testing
-- the correctness of rolling average calculations (L5, L10, season averages).
--
-- Each record represents a player-date combination where the expected values
-- have been manually calculated from raw boxscore data and verified by a human.
--
-- Usage:
-- - Run verification scripts against this data daily/weekly
-- - Alert if calculated values differ from expected by > 0.1 points
-- - Gradually expand coverage to include more players and dates
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.golden_dataset` (
    -- =============================================================================
    -- PLAYER IDENTIFICATION
    -- =============================================================================

    player_id INT64 NOT NULL,                    -- Universal player ID (numeric)
    player_name STRING NOT NULL,                 -- Player's full name (e.g., "LeBron James")
    player_lookup STRING NOT NULL,               -- Normalized lookup key (e.g., "lebronjames")
    game_date DATE NOT NULL,                     -- Date of the game being verified

    -- =============================================================================
    -- EXPECTED VALUES (Manually Calculated/Verified)
    -- =============================================================================
    -- These values are manually calculated from raw boxscore data using the
    -- same logic as stats_aggregator.py. They serve as ground truth for testing.

    -- Points averaging
    expected_pts_l5 FLOAT64,                     -- Expected last 5 games points average
    expected_pts_l10 FLOAT64,                    -- Expected last 10 games points average
    expected_pts_season FLOAT64,                 -- Expected season average

    -- Rebounds averaging
    expected_reb_l5 FLOAT64,                     -- Expected last 5 games rebounds average
    expected_reb_l10 FLOAT64,                    -- Expected last 10 games rebounds average

    -- Assists averaging
    expected_ast_l5 FLOAT64,                     -- Expected last 5 games assists average
    expected_ast_l10 FLOAT64,                    -- Expected last 10 games assists average

    -- Minutes averaging
    expected_minutes_l10 FLOAT64,                -- Expected last 10 games minutes average

    -- Usage rate (advanced stat)
    expected_usage_rate_l10 FLOAT64,             -- Expected last 10 games usage rate

    -- =============================================================================
    -- METADATA
    -- =============================================================================

    verified_by STRING NOT NULL,                 -- Who verified this data (e.g., "manual", "script", username)
    verified_at TIMESTAMP NOT NULL,              -- When this record was verified
    notes STRING,                                -- Optional notes about this verification (e.g., "season opener", "injury return")
    is_active BOOLEAN DEFAULT TRUE,              -- Whether this record is currently used for validation

    -- =============================================================================
    -- AUDIT FIELDS
    -- =============================================================================

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY player_lookup, game_date
OPTIONS (
  description = "Golden dataset of manually verified player rolling averages for data quality testing"
);

-- =============================================================================
-- SAMPLE DATA INSERTION (Template)
-- =============================================================================
-- To add new golden dataset records, use this template:
--
-- INSERT INTO `nba-props-platform.nba_reference.golden_dataset`
--   (player_id, player_name, player_lookup, game_date,
--    expected_pts_l5, expected_pts_l10, expected_pts_season,
--    expected_reb_l5, expected_reb_l10,
--    expected_ast_l5, expected_ast_l10,
--    expected_minutes_l10, expected_usage_rate_l10,
--    verified_by, verified_at, notes, is_active)
-- VALUES
--   (2544, 'LeBron James', 'lebronjames', '2024-12-15',
--    25.4, 26.2, 27.1,
--    8.2, 7.9,
--    7.5, 7.8,
--    35.6, 28.3,
--    'manual', CURRENT_TIMESTAMP(), 'Mid-season check', TRUE);
--
-- =============================================================================

-- =============================================================================
-- RECOMMENDED QUERIES
-- =============================================================================

-- Get all active golden dataset records
-- SELECT
--   player_name,
--   game_date,
--   expected_pts_l5,
--   expected_pts_l10,
--   verified_by,
--   verified_at
-- FROM `nba-props-platform.nba_reference.golden_dataset`
-- WHERE is_active = TRUE
-- ORDER BY game_date DESC, player_name;

-- Compare golden dataset to actual cached values
-- SELECT
--   g.player_name,
--   g.game_date,
--   g.expected_pts_l5,
--   c.points_avg_last_5 as actual_pts_l5,
--   ABS(g.expected_pts_l5 - c.points_avg_last_5) as pts_l5_diff,
--   g.expected_pts_l10,
--   c.points_avg_last_10 as actual_pts_l10,
--   ABS(g.expected_pts_l10 - c.points_avg_last_10) as pts_l10_diff
-- FROM `nba-props-platform.nba_reference.golden_dataset` g
-- JOIN `nba-props-platform.nba_precompute.player_daily_cache` c
--   ON g.player_lookup = c.player_lookup
--   AND g.game_date = c.game_date
-- WHERE g.is_active = TRUE
--   AND (ABS(g.expected_pts_l5 - c.points_avg_last_5) > 0.1
--        OR ABS(g.expected_pts_l10 - c.points_avg_last_10) > 0.1)
-- ORDER BY pts_l5_diff DESC, pts_l10_diff DESC;

-- Get verification coverage statistics
-- SELECT
--   COUNT(*) as total_records,
--   COUNT(DISTINCT player_lookup) as unique_players,
--   MIN(game_date) as earliest_date,
--   MAX(game_date) as latest_date,
--   COUNTIF(is_active) as active_records,
--   MAX(verified_at) as most_recent_verification
-- FROM `nba-props-platform.nba_reference.golden_dataset`;

-- =============================================================================
-- DATA QUALITY NOTES
-- =============================================================================
--
-- Tolerance Recommendation: 0.1 points
-- - Rolling averages are rounded to 4 decimal places in calculation
-- - Display precision is typically 1 decimal place
-- - 0.1 point difference over 5 games = 0.02 ppg (negligible)
-- - Catches real calculation errors while avoiding false positives
--
-- Selection Criteria for Players:
-- - High-volume scorers (play most games, reliable data)
-- - High minutes (starters/stars)
-- - Mix of scoring styles (perimeter, paint, balanced)
-- - Consistent prop market availability
--
-- Recommended Initial Players:
-- - LeBron James (high-volume, consistent)
-- - Stephen Curry (high-volume, 3PT specialist)
-- - Luka Doncic (high usage, triple-double threat)
-- - Giannis Antetokounmpo (paint-heavy scorer)
-- - Joel Embiid (high-volume big man)
-- - Jayson Tatum (versatile scorer)
--
-- =============================================================================
