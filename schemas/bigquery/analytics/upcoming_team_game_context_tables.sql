-- Path: schemas/bigquery/analytics/upcoming_team_game_context_tables.sql
-- Description: Phase 3 Analytics - Team-level game context with fatigue, betting, personnel tracking
-- Version: 2.0 - Added source tracking fields (Dependency Tracking v4.0)
-- Last Updated: November 2, 2025

-- ============================================================================
-- TABLE: nba_analytics.upcoming_team_game_context
-- ============================================================================
-- Purpose: Provide comprehensive team-level context for upcoming games including:
--   - Fatigue metrics (days rest, back-to-backs, games in windows)
--   - Betting context (spreads, totals, line movement)
--   - Personnel availability (injuries, questionable players)
--   - Recent performance (streaks, margins, momentum)
--   - Travel impact (miles traveled)
--
-- Granularity: 2 rows per game (home team view + away team view)
-- Update Frequency: Multiple times daily (after Phase 2 updates)
-- Data Window: Typically processes 7-14 days of upcoming games
--
-- Dependencies (Phase 2 Raw Tables):
--   1. nba_raw.nbac_schedule (CRITICAL) - Game schedule, matchups, results
--   2. nba_raw.odds_api_game_lines (OPTIONAL) - Betting lines (spreads/totals)
--   3. nba_raw.nbac_injury_report (OPTIONAL) - Player availability status
--
-- Consumers (Phase 4 Precompute):
--   - player_composite_factors - Uses fatigue, betting, personnel for player predictions
--   - team_matchup_analysis - Uses all context for team-level predictions
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba_analytics.upcoming_team_game_context` (
  
  -- =========================================================================
  -- BUSINESS KEYS (4 fields)
  -- =========================================================================
  team_abbr STRING NOT NULL,  -- Team for which this context applies (LAL, GSW, etc)
  game_id STRING NOT NULL,  -- NBA.com game ID (e.g., '0022400123')
  game_date DATE NOT NULL,  -- Eastern date of game (YYYY-MM-DD)
  season_year INT64 NOT NULL,  -- NBA season year (2024 = 2024-25 season)
  
  
  -- =========================================================================
  -- GAME CONTEXT (5 fields)
  -- =========================================================================
  opponent_team_abbr STRING NOT NULL,  -- Opposing team abbreviation
  home_game BOOLEAN NOT NULL,  -- TRUE if team is home, FALSE if away
  is_back_to_back BOOLEAN NOT NULL,  -- TRUE if game is on consecutive days
  days_since_last_game INT64,  -- Number of days since team's previous game (NULL if first game)
  game_number_in_season INT64,  -- Sequential game number for this team (1, 2, 3, ...)
  
  
  -- =========================================================================
  -- FATIGUE METRICS (4 fields)
  -- =========================================================================
  team_days_rest INT64,  -- Days of rest before this game (0 = back-to-back, NULL if first game)
  team_back_to_back BOOLEAN NOT NULL,  -- TRUE if this is 2nd game of back-to-back for team
  games_in_last_7_days INT64 NOT NULL,  -- Number of games played in previous 7 days
  games_in_last_14_days INT64 NOT NULL,  -- Number of games played in previous 14 days
  
  
  -- =========================================================================
  -- BETTING CONTEXT (7 fields)
  -- =========================================================================
  game_spread NUMERIC(5,2),  -- Point spread for team (negative = favored, positive = underdog, NULL if unavailable)
  game_total NUMERIC(5,1),  -- Over/under total points for game (NULL if unavailable)
  game_spread_source STRING,  -- Bookmaker providing spread (e.g., 'draftkings', 'fanduel', NULL if unavailable)
  game_total_source STRING,  -- Bookmaker providing total (e.g., 'draftkings', 'fanduel', NULL if unavailable)
  spread_movement NUMERIC(5,2),  -- Line movement from opening to current (positive = moved toward team, NULL if unavailable)
  total_movement NUMERIC(5,1),  -- Total movement from opening to current (positive = moved higher, NULL if unavailable)
  betting_lines_updated_at TIMESTAMP,  -- When betting lines were last updated (NULL if no lines available)
  
  
  -- =========================================================================
  -- PERSONNEL CONTEXT (2 fields)
  -- =========================================================================
  starters_out_count INT64 NOT NULL,  -- Number of expected starters with status='out' (processor defaults to 0)
  questionable_players_count INT64 NOT NULL,  -- Number of players with status='questionable' or 'doubtful' (processor defaults to 0)
  
  
  -- =========================================================================
  -- RECENT PERFORMANCE / MOMENTUM (4 fields)
  -- =========================================================================
  team_win_streak_entering INT64 NOT NULL,  -- Current winning streak (0 if not on streak, negative for losing streak) (processor defaults to 0)
  team_loss_streak_entering INT64 NOT NULL,  -- Current losing streak (0 if not on streak) (processor defaults to 0)
  last_game_margin INT64,  -- Point differential in team's last game (positive = win margin, negative = loss margin, NULL if first game)
  last_game_result STRING,  -- Result of team's last game ('W', 'L', NULL if first game)
  
  
  -- =========================================================================
  -- TRAVEL CONTEXT (1 field)
  -- =========================================================================
  travel_miles INT64 NOT NULL,  -- Miles traveled to this game from last game location (processor defaults to 0 for home games)
  
  
  -- =========================================================================
  -- SOURCE TRACKING: nba_raw.nbac_schedule (4 fields) - CRITICAL
  -- =========================================================================
  source_nbac_schedule_last_updated TIMESTAMP,  -- When nbac_schedule table was last processed (NULL if table missing)
  source_nbac_schedule_rows_found INT64,  -- Number of schedule records found in query (NULL if table missing, 0 if no data)
  source_nbac_schedule_completeness_pct NUMERIC(5,2),  -- Percentage of expected schedule records found (0-100, NULL if table missing)
  source_nbac_schedule_hash STRING,  -- Smart Idempotency: data_hash from nbac_schedule


  -- =========================================================================
  -- SOURCE TRACKING: nba_raw.odds_api_game_lines (4 fields) - OPTIONAL
  -- =========================================================================
  source_odds_lines_last_updated TIMESTAMP,  -- When odds_api_game_lines had latest snapshot (NULL if no betting data)
  source_odds_lines_rows_found INT64,  -- Number of betting line records found (NULL if no betting data, 0 if table empty)
  source_odds_lines_completeness_pct NUMERIC(5,2),  -- Percentage of expected betting lines found (0-100, NULL if no betting data)
  source_odds_lines_hash STRING,  -- Smart Idempotency: data_hash from odds_api_game_lines


  -- =========================================================================
  -- SOURCE TRACKING: nba_raw.nbac_injury_report (4 fields) - OPTIONAL
  -- =========================================================================
  source_injury_report_last_updated TIMESTAMP,  -- When injury report table was last processed (NULL if no injury data)
  source_injury_report_rows_found INT64,  -- Number of injury records found (NULL if no injury data, 0 if table empty)
  source_injury_report_completeness_pct NUMERIC(5,2),  -- Percentage of expected injury records found (0-100, NULL if no injury data)
  source_injury_report_hash STRING,  -- Smart Idempotency: data_hash from nbac_injury_report
  
  
  -- =========================================================================
  -- OPTIONAL TRACKING: Early Season Handling (2 fields)
  -- =========================================================================
  early_season_flag BOOLEAN,  -- TRUE if processed during early season with insufficient data
  insufficient_data_reason STRING,  -- Explanation of why data was insufficient (only populated when early_season_flag=TRUE)
  
  
  -- =========================================================================
  -- PROCESSING METADATA (2 fields)
  -- =========================================================================
  processed_at TIMESTAMP NOT NULL,  -- When this record was processed by upcoming_team_game_context processor
  created_at TIMESTAMP NOT NULL  -- When this record was first created (processor sets to CURRENT_TIMESTAMP)
)
PARTITION BY game_date
CLUSTER BY game_date, team_abbr, game_id;

-- ============================================================================
-- FIELD COUNT SUMMARY
-- ============================================================================
-- Business Keys:              4 fields
-- Game Context:               5 fields
-- Fatigue Metrics:            4 fields
-- Betting Context:            7 fields
-- Personnel Context:          2 fields
-- Recent Performance:         4 fields
-- Travel Context:             1 field
-- ─────────────────────────────────────
-- Business Fields Subtotal:  27 fields
--
-- Source Tracking (3 sources × 4 fields - includes smart idempotency hashes): 12 fields
-- Optional Early Season:                   2 fields
-- Processing Metadata:                     2 fields
-- ─────────────────────────────────────
-- Tracking Fields Subtotal:  16 fields
--
-- TOTAL:                     43 fields
-- ============================================================================

-- ============================================================================
-- IMPORTANT NOTE ABOUT DEFAULT VALUES
-- ============================================================================
-- BigQuery does NOT support DEFAULT values in CREATE TABLE statements.
-- All default values must be handled in the processor code:
--
-- Fields that should default to 0 in processor:
--   - starters_out_count (default: 0)
--   - questionable_players_count (default: 0)
--   - team_win_streak_entering (default: 0)
--   - team_loss_streak_entering (default: 0)
--   - travel_miles (default: 0)
--
-- Fields that should use CURRENT_TIMESTAMP in processor:
--   - processed_at (set on every insert/update)
--   - created_at (set on first insert only)
--
-- Fields that should be NULL when no data exists:
--   - All nullable fields (see schema above)
-- ============================================================================

-- ============================================================================
-- DEPENDENCY CONFIGURATION (for processor)
-- ============================================================================
-- The processor should implement get_dependencies() with these configs:
--
-- 1. nba_raw.nbac_schedule (CRITICAL):
--    - field_prefix: 'source_nbac_schedule'
--    - check_type: 'date_range'
--    - expected_count_min: 20 (typical 10 games × 2 teams)
--    - max_age_hours_warn: 12
--    - max_age_hours_fail: 36
--    - critical: True
--
-- 2. nba_raw.odds_api_game_lines (OPTIONAL):
--    - field_prefix: 'source_odds_lines'
--    - check_type: 'date_range'
--    - expected_count_min: 40 (multiple bookmakers × games)
--    - max_age_hours_warn: 4
--    - max_age_hours_fail: 12
--    - critical: False
--
-- 3. nba_raw.nbac_injury_report (OPTIONAL):
--    - field_prefix: 'source_injury_report'
--    - check_type: 'date_range'
--    - expected_count_min: 10 (variable by day)
--    - max_age_hours_warn: 8
--    - max_age_hours_fail: 24
--    - critical: False
-- ============================================================================

-- ============================================================================
-- USAGE EXAMPLES
-- ============================================================================

-- Example 1: Get today's games with full context
-- SELECT 
--   team_abbr,
--   opponent_team_abbr,
--   home_game,
--   team_days_rest,
--   team_back_to_back,
--   game_spread,
--   starters_out_count,
--   travel_miles,
--   source_nbac_schedule_completeness_pct,
--   source_odds_lines_completeness_pct
-- FROM `nba_analytics.upcoming_team_game_context`
-- WHERE game_date = CURRENT_DATE()
-- ORDER BY game_date, game_id, home_game DESC;

-- Example 2: Check data quality for recent games
-- SELECT 
--   game_date,
--   COUNT(*) as total_records,
--   AVG(source_nbac_schedule_completeness_pct) as avg_schedule_completeness,
--   AVG(source_odds_lines_completeness_pct) as avg_odds_completeness,
--   AVG(source_injury_report_completeness_pct) as avg_injury_completeness,
--   COUNT(CASE WHEN game_spread IS NULL THEN 1 END) as missing_spreads,
--   COUNT(CASE WHEN team_back_to_back THEN 1 END) as back_to_back_games
-- FROM `nba_analytics.upcoming_team_game_context`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY game_date
-- ORDER BY game_date DESC;

-- Example 3: Find games with stale data
-- SELECT 
--   game_date,
--   team_abbr,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_schedule_last_updated, HOUR) as schedule_age_hours,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_odds_lines_last_updated, HOUR) as odds_age_hours,
--   source_nbac_schedule_completeness_pct,
--   source_odds_lines_completeness_pct
-- FROM `nba_analytics.upcoming_team_game_context`
-- WHERE game_date >= CURRENT_DATE()
--   AND (
--     TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_schedule_last_updated, HOUR) > 36
--     OR TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_odds_lines_last_updated, HOUR) > 12
--   )
-- ORDER BY schedule_age_hours DESC;

-- Example 4: Identify data quality bottlenecks
-- SELECT 
--   game_date,
--   team_abbr,
--   CASE
--     WHEN source_nbac_schedule_completeness_pct < 85 THEN 'schedule'
--     WHEN source_odds_lines_completeness_pct < 85 THEN 'odds_lines'
--     WHEN source_injury_report_completeness_pct < 85 THEN 'injury_report'
--     ELSE 'all_good'
--   END as problem_source,
--   source_nbac_schedule_completeness_pct,
--   source_odds_lines_completeness_pct,
--   source_injury_report_completeness_pct
-- FROM `nba_analytics.upcoming_team_game_context`
-- WHERE game_date = CURRENT_DATE()
--   AND (
--     source_nbac_schedule_completeness_pct < 85
--     OR source_odds_lines_completeness_pct < 85
--     OR source_injury_report_completeness_pct < 85
--   );

-- ============================================================================
-- INDEXES / CLUSTERING
-- ============================================================================
-- Partitioned by: game_date (for efficient date range queries)
-- Clustered by: game_date, team_abbr, game_id
--   - Optimizes queries filtering by date + team
--   - Supports efficient Phase 4 lookups
--   - Reduces query costs for common access patterns

-- ============================================================================
-- MIGRATION NOTES
-- ============================================================================
-- Version 1.0 → 2.0 Changes:
--   + Added 9 source tracking fields (3 sources × 3 fields)
--   + Added 2 optional early season fields
--   + Added 2 processing metadata fields
--   Total: +13 fields (27 business → 40 total)
--
-- For existing table (if data exists):
--   ALTER TABLE `nba_analytics.upcoming_team_game_context`
--   ADD COLUMN IF NOT EXISTS source_nbac_schedule_last_updated TIMESTAMP,
--   ADD COLUMN IF NOT EXISTS source_nbac_schedule_rows_found INT64,
--   ADD COLUMN IF NOT EXISTS source_nbac_schedule_completeness_pct NUMERIC(5,2),
--   ADD COLUMN IF NOT EXISTS source_odds_lines_last_updated TIMESTAMP,
--   ADD COLUMN IF NOT EXISTS source_odds_lines_rows_found INT64,
--   ADD COLUMN IF NOT EXISTS source_odds_lines_completeness_pct NUMERIC(5,2),
--   ADD COLUMN IF NOT EXISTS source_injury_report_last_updated TIMESTAMP,
--   ADD COLUMN IF NOT EXISTS source_injury_report_rows_found INT64,
--   ADD COLUMN IF NOT EXISTS source_injury_report_completeness_pct NUMERIC(5,2),
--   ADD COLUMN IF NOT EXISTS early_season_flag BOOLEAN,
--   ADD COLUMN IF NOT EXISTS insufficient_data_reason STRING,
--   ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP,
--   ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;
--
-- Note: DEFAULT clauses in ALTER TABLE are supported, but we omit them here
--       for consistency. All defaults should be handled in processor code.
--
-- For new table (this script): Just run CREATE TABLE

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================