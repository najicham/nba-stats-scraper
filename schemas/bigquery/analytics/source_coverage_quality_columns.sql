-- File: schemas/bigquery/analytics/source_coverage_quality_columns.sql
-- Description: Add source coverage quality tracking columns to Phase 3 analytics tables
-- Created: 2025-11-26
-- Purpose: Enable quality tracking and propagation through the analytics pipeline
--
-- Quality Column Reference:
--   quality_tier        - Categorical: 'gold', 'silver', 'bronze', 'poor', 'unusable'
--   quality_score       - Numeric: 0-100
--   quality_issues      - Array of specific problems: ['thin_sample:3/10', 'missing_optional:plus_minus']
--   data_sources        - Which sources were used: ['primary'], ['espn_backup'], ['reconstructed']
--   quality_sample_size - Number of games in sample (for rolling calculations)
--   quality_used_fallback    - TRUE if any fallback source was used
--   quality_reconstructed    - TRUE if data was reconstructed/derived
--   quality_calculated_at    - When quality was assessed (for staleness detection)
--   quality_metadata         - JSON for additional context not commonly queried

-- ============================================================================
-- PLAYER GAME SUMMARY
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_analytics.player_game_summary`
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS quality_score FLOAT64,
ADD COLUMN IF NOT EXISTS quality_issues ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS data_sources ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS quality_sample_size INT64,
ADD COLUMN IF NOT EXISTS quality_used_fallback BOOL,
ADD COLUMN IF NOT EXISTS quality_reconstructed BOOL,
ADD COLUMN IF NOT EXISTS quality_calculated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS quality_metadata JSON;


-- ============================================================================
-- TEAM OFFENSE GAME SUMMARY
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_analytics.team_offense_game_summary`
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS quality_score FLOAT64,
ADD COLUMN IF NOT EXISTS quality_issues ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS data_sources ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS quality_sample_size INT64,
ADD COLUMN IF NOT EXISTS quality_used_fallback BOOL,
ADD COLUMN IF NOT EXISTS quality_reconstructed BOOL,
ADD COLUMN IF NOT EXISTS quality_calculated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS quality_metadata JSON;


-- ============================================================================
-- TEAM DEFENSE GAME SUMMARY
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_analytics.team_defense_game_summary`
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS quality_score FLOAT64,
ADD COLUMN IF NOT EXISTS quality_issues ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS data_sources ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS quality_sample_size INT64,
ADD COLUMN IF NOT EXISTS quality_used_fallback BOOL,
ADD COLUMN IF NOT EXISTS quality_reconstructed BOOL,
ADD COLUMN IF NOT EXISTS quality_calculated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS quality_metadata JSON;


-- ============================================================================
-- UPCOMING PLAYER GAME CONTEXT
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_analytics.upcoming_player_game_context`
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS quality_score FLOAT64,
ADD COLUMN IF NOT EXISTS quality_issues ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS data_sources ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS quality_sample_size INT64,
ADD COLUMN IF NOT EXISTS quality_used_fallback BOOL,
ADD COLUMN IF NOT EXISTS quality_reconstructed BOOL,
ADD COLUMN IF NOT EXISTS quality_calculated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS quality_metadata JSON;


-- ============================================================================
-- UPCOMING TEAM GAME CONTEXT
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_analytics.upcoming_team_game_context`
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS quality_score FLOAT64,
ADD COLUMN IF NOT EXISTS quality_issues ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS data_sources ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS quality_sample_size INT64,
ADD COLUMN IF NOT EXISTS quality_used_fallback BOOL,
ADD COLUMN IF NOT EXISTS quality_reconstructed BOOL,
ADD COLUMN IF NOT EXISTS quality_calculated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS quality_metadata JSON;


-- ============================================================================
-- HISTORICAL BACKFILL (Run once after columns are added)
-- ============================================================================
-- IMPORTANT: We use CONSERVATIVE defaults (silver, not gold) because:
-- 1. We cannot retroactively determine true source quality
-- 2. Claiming "gold" for unknown data creates false confidence
-- 3. Silver is honest: "data exists but quality is unverified"
--
-- Uncomment and run these statements to backfill existing data:
-- ============================================================================

/*
-- Backfill player_game_summary
UPDATE `nba-props-platform.nba_analytics.player_game_summary`
SET
    quality_tier = 'silver',
    quality_score = 80.0,
    quality_issues = ['historical_data'],
    data_sources = ['unknown'],
    quality_sample_size = NULL,
    quality_used_fallback = NULL,
    quality_reconstructed = NULL,
    quality_calculated_at = CURRENT_TIMESTAMP(),
    quality_metadata = JSON '{"backfilled": true, "backfill_date": "2025-11-26", "note": "Conservative default for historical data"}'
WHERE quality_tier IS NULL;

-- Backfill team_offense_game_summary
UPDATE `nba-props-platform.nba_analytics.team_offense_game_summary`
SET
    quality_tier = 'silver',
    quality_score = 80.0,
    quality_issues = ['historical_data'],
    data_sources = ['unknown'],
    quality_sample_size = NULL,
    quality_used_fallback = NULL,
    quality_reconstructed = NULL,
    quality_calculated_at = CURRENT_TIMESTAMP(),
    quality_metadata = JSON '{"backfilled": true, "backfill_date": "2025-11-26", "note": "Conservative default for historical data"}'
WHERE quality_tier IS NULL;

-- Backfill team_defense_game_summary
UPDATE `nba-props-platform.nba_analytics.team_defense_game_summary`
SET
    quality_tier = 'silver',
    quality_score = 80.0,
    quality_issues = ['historical_data'],
    data_sources = ['unknown'],
    quality_sample_size = NULL,
    quality_used_fallback = NULL,
    quality_reconstructed = NULL,
    quality_calculated_at = CURRENT_TIMESTAMP(),
    quality_metadata = JSON '{"backfilled": true, "backfill_date": "2025-11-26", "note": "Conservative default for historical data"}'
WHERE quality_tier IS NULL;

-- Backfill upcoming_player_game_context
UPDATE `nba-props-platform.nba_analytics.upcoming_player_game_context`
SET
    quality_tier = 'silver',
    quality_score = 80.0,
    quality_issues = ['historical_data'],
    data_sources = ['unknown'],
    quality_sample_size = NULL,
    quality_used_fallback = NULL,
    quality_reconstructed = NULL,
    quality_calculated_at = CURRENT_TIMESTAMP(),
    quality_metadata = JSON '{"backfilled": true, "backfill_date": "2025-11-26", "note": "Conservative default for historical data"}'
WHERE quality_tier IS NULL;

-- Backfill upcoming_team_game_context
UPDATE `nba-props-platform.nba_analytics.upcoming_team_game_context`
SET
    quality_tier = 'silver',
    quality_score = 80.0,
    quality_issues = ['historical_data'],
    data_sources = ['unknown'],
    quality_sample_size = NULL,
    quality_used_fallback = NULL,
    quality_reconstructed = NULL,
    quality_calculated_at = CURRENT_TIMESTAMP(),
    quality_metadata = JSON '{"backfilled": true, "backfill_date": "2025-11-26", "note": "Conservative default for historical data"}'
WHERE quality_tier IS NULL;
*/


-- ============================================================================
-- VERIFICATION QUERY
-- ============================================================================
-- Run after applying migrations to verify columns were added:
/*
SELECT
    'player_game_summary' as table_name,
    COUNT(*) as total_rows,
    COUNTIF(quality_tier IS NOT NULL) as rows_with_quality
FROM `nba-props-platform.nba_analytics.player_game_summary`
UNION ALL
SELECT
    'team_offense_game_summary',
    COUNT(*),
    COUNTIF(quality_tier IS NOT NULL)
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
UNION ALL
SELECT
    'team_defense_game_summary',
    COUNT(*),
    COUNTIF(quality_tier IS NOT NULL)
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
UNION ALL
SELECT
    'upcoming_player_game_context',
    COUNT(*),
    COUNTIF(quality_tier IS NOT NULL)
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
UNION ALL
SELECT
    'upcoming_team_game_context',
    COUNT(*),
    COUNTIF(quality_tier IS NOT NULL)
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`;
*/
