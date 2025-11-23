-- ============================================================================
-- NBA Props Platform - Upcoming Player Game Context Analytics Table
-- Complete pre-game context for player similarity matching and predictions
-- File: schemas/bigquery/analytics/upcoming_player_game_context_tables.sql
-- ============================================================================
--
-- PHASE 3 ANALYTICS PROCESSOR
-- Data Sources: Phase 2 raw tables only (no Phase 3 dependencies)
-- Processing: UpcomingPlayerGameContextProcessor (MERGE_UPDATE strategy)
--
-- This table provides comprehensive pre-game context for every player with a
-- points prop bet available. It combines:
-- - Historical performance (last 30 days from boxscores)
-- - Fatigue analysis (rest days, back-to-backs, minutes load)
-- - Prop betting context (current/opening lines, movement)
-- - Game situation (spreads, totals, pace expectations)
-- - Injury status and team context
--
-- Key dependencies (all Phase 2 raw tables):
-- 1. nba_raw.odds_api_player_points_props - DRIVER (which players to process)
-- 2. nba_raw.bdl_player_boxscores - Historical performance (PRIMARY)
-- 3. nba_raw.nbac_schedule - Game timing and context
-- 4. nba_raw.odds_api_game_lines - Game spreads and totals
--
-- Optional sources (enhance quality if available):
-- 5. nba_raw.espn_team_rosters - Current team verification
-- 6. nba_raw.nbac_injury_report - Injury status
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.upcoming_player_game_context` (
  -- ============================================================================
  -- CORE IDENTIFIERS (6 fields)
  -- ============================================================================
  player_lookup STRING NOT NULL,                    -- Normalized player identifier (join key)
  universal_player_id STRING,                       -- Universal player ID from registry (e.g., lebronjames_001)
  game_id STRING NOT NULL,                          -- Unique game identifier: "20250120_LAL_BOS"
  game_date DATE NOT NULL,                          -- Game date (partition key)
  team_abbr STRING NOT NULL,                        -- Player's team abbreviation
  opponent_team_abbr STRING NOT NULL,               -- Opposing team abbreviation
  
  -- ============================================================================
  -- PLAYER PROP BETTING CONTEXT (5 fields)
  -- From nba_raw.odds_api_player_points_props
  -- ============================================================================
  current_points_line NUMERIC(4,1),                 -- Most recent player points line
  opening_points_line NUMERIC(4,1),                 -- Opening player points line
  line_movement NUMERIC(4,1),                       -- Current line - opening line
  current_points_line_source STRING,                -- Source of current line (bookmaker(s))
  opening_points_line_source STRING,                -- Source of opening line (bookmaker(s))
  
  -- ============================================================================
  -- GAME SPREAD CONTEXT (5 fields)
  -- From nba_raw.odds_api_game_lines (market_key='spreads')
  -- ============================================================================
  game_spread NUMERIC(4,1),                         -- Current point spread (consensus across bookmakers)
  opening_spread NUMERIC(4,1),                      -- Opening point spread
  spread_movement NUMERIC(4,1),                     -- Current spread - opening spread
  game_spread_source STRING,                        -- Source of current spread (bookmaker(s))
  spread_public_betting_pct NUMERIC(5,2),           -- % of public bets on favorite (future)
  
  -- ============================================================================
  -- GAME TOTAL CONTEXT (5 fields)
  -- From nba_raw.odds_api_game_lines (market_key='totals')
  -- ============================================================================
  game_total NUMERIC(5,1),                          -- Current over/under total points
  opening_total NUMERIC(5,1),                       -- Opening total
  total_movement NUMERIC(4,1),                      -- Current total - opening total
  game_total_source STRING,                         -- Source of current total (bookmaker(s))
  total_public_betting_pct NUMERIC(5,2),            -- % of public bets on OVER (future)
  
  -- ============================================================================
  -- PRE-GAME CONTEXT (8 fields)
  -- Calculated from schedule and historical data
  -- ============================================================================
  pace_differential NUMERIC(5,1),                   -- Team vs opponent pace (future)
  opponent_pace_last_10 NUMERIC(5,1),               -- Opponent recent pace (future)
  game_start_time_local STRING,                     -- Game start time in local timezone (e.g., "7:30 PM ET") - FIXED: Changed from TIME to STRING
  opponent_ft_rate_allowed NUMERIC(5,3),            -- FT opportunities (future)
  home_game BOOLEAN,                                -- Home vs away
  back_to_back BOOLEAN,                             -- Back-to-back flag
  season_phase STRING,                              -- 'early', 'mid', 'late', 'playoffs'
  projected_usage_rate NUMERIC(5,2),                -- Expected usage based on available players (future)
  
  -- ============================================================================
  -- PLAYER FATIGUE ANALYSIS (12 fields)
  -- Calculated from nba_raw.bdl_player_boxscores + schedule
  -- ============================================================================
  days_rest INT64,                                  -- Rest days since last game
  days_rest_before_last_game INT64,                 -- Previous rest (fatigue trend)
  days_since_2_plus_days_rest INT64,                -- Time since real rest
  games_in_last_7_days INT64,                       -- Weekly load
  games_in_last_14_days INT64,                      -- Bi-weekly load
  minutes_in_last_7_days INT64,                     -- Weekly minutes
  minutes_in_last_14_days INT64,                    -- Bi-weekly minutes
  avg_minutes_per_game_last_7 NUMERIC(5,1),         -- Recent intensity
  back_to_backs_last_14_days INT64,                 -- Recent compression
  avg_usage_rate_last_7_games NUMERIC(5,2),         -- Usage intensity (future)
  fourth_quarter_minutes_last_7 INT64,              -- Crunch time load (future)
  clutch_minutes_last_7_games INT64,                -- High-stress minutes (future)
  
  -- ============================================================================
  -- TRAVEL CONTEXT (5 fields)
  -- Calculated from schedule (future implementation)
  -- ============================================================================
  travel_miles INT64,                               -- Travel distance (future)
  time_zone_changes INT64,                          -- Time zones crossed (future)
  consecutive_road_games INT64,                     -- Road trip length (future)
  miles_traveled_last_14_days INT64,                -- Cumulative travel (future)
  time_zones_crossed_last_14_days INT64,            -- Jet lag factor (future)
  
  -- ============================================================================
  -- PLAYER CHARACTERISTICS (1 field)
  -- From nba_raw.espn_team_rosters (optional)
  -- ============================================================================
  player_age INT64,                                 -- Current age for fatigue analysis
  
  -- ============================================================================
  -- RECENT PERFORMANCE CONTEXT (8 fields)
  -- Calculated from nba_raw.bdl_player_boxscores
  -- ============================================================================
  points_avg_last_5 NUMERIC(5,1),                   -- Recent form
  points_avg_last_10 NUMERIC(5,1),                  -- Broader trend
  prop_over_streak INT64,                           -- Current over streak
  prop_under_streak INT64,                          -- Current under streak
  star_teammates_out INT64,                         -- Key players out (future)
  opponent_def_rating_last_10 NUMERIC(6,2),         -- Opponent defense (future)
  shooting_pct_decline_last_5 NUMERIC(5,3),         -- Performance decline signal (future)
  fourth_quarter_production_last_7 NUMERIC(5,1),    -- Late-game energy (future)
  
  -- ============================================================================
  -- FORWARD-LOOKING SCHEDULE CONTEXT (4 fields)
  -- TODO: Returns 0/NULL for now, implement in future iteration
  -- ============================================================================
  next_game_days_rest INT64,                        -- Days until player's next game
  games_in_next_7_days INT64,                       -- Player's upcoming game density
  next_opponent_win_pct NUMERIC(5,3),               -- Win percentage of player's next opponent
  next_game_is_primetime BOOLEAN,                   -- Whether player's next game is nationally televised
  
  -- ============================================================================
  -- OPPONENT ASYMMETRY CONTEXT (3 fields)
  -- TODO: Implement fully after team context processor is stable
  -- ============================================================================
  opponent_days_rest INT64,                         -- Current opponent's rest before this game
  opponent_games_in_next_7_days INT64,              -- Current opponent's upcoming schedule density
  opponent_next_game_days_rest INT64,               -- Current opponent's rest after this game
  
  -- ============================================================================
  -- REAL-TIME UPDATES (4 fields)
  -- From nba_raw.nbac_injury_report (optional)
  -- ============================================================================
  player_status STRING,                             -- Injury report status: 'out', 'questionable', 'doubtful', 'probable', 'available'
  injury_report STRING,                             -- Detailed injury info
  questionable_teammates INT64,                     -- Questionable players on team
  probable_teammates INT64,                         -- Probable players on team
  
  -- ============================================================================
  -- SOURCE TRACKING (16 fields = 4 sources × 4 fields)
  -- Per dependency tracking guide v4.0 + Smart Idempotency (Pattern #14)
  -- ============================================================================

  -- SOURCE 1: Player Boxscores (PRIMARY - CRITICAL)
  -- nba_raw.bdl_player_boxscores (fallback: nbac_player_boxscores)
  source_boxscore_last_updated TIMESTAMP,           -- When boxscore table was last processed
  source_boxscore_rows_found INT64,                 -- How many player games found (last 30 days)
  source_boxscore_completeness_pct NUMERIC(5,2),    -- % of expected games found
  source_boxscore_hash STRING,                      -- Smart Idempotency: data_hash from bdl_player_boxscores

  -- SOURCE 2: Schedule (CRITICAL)
  -- nba_raw.nbac_schedule
  source_schedule_last_updated TIMESTAMP,           -- When schedule table was last processed
  source_schedule_rows_found INT64,                 -- How many game records found
  source_schedule_completeness_pct NUMERIC(5,2),    -- % of expected schedule data found
  source_schedule_hash STRING,                      -- Smart Idempotency: data_hash from nbac_schedule

  -- SOURCE 3: Player Props (DRIVER - CRITICAL)
  -- nba_raw.odds_api_player_points_props
  source_props_last_updated TIMESTAMP,              -- When props table was last processed
  source_props_rows_found INT64,                    -- How many prop records found
  source_props_completeness_pct NUMERIC(5,2),       -- % of expected props found
  source_props_hash STRING,                         -- Smart Idempotency: data_hash from odds_api_player_points_props

  -- SOURCE 4: Game Lines (CRITICAL)
  -- nba_raw.odds_api_game_lines
  source_game_lines_last_updated TIMESTAMP,         -- When game lines table was last processed
  source_game_lines_rows_found INT64,               -- How many line records found
  source_game_lines_completeness_pct NUMERIC(5,2),  -- % of expected lines found
  source_game_lines_hash STRING,                    -- Smart Idempotency: data_hash from odds_api_game_lines
  
  -- ============================================================================
  -- DATA QUALITY TRACKING (3 fields)
  -- ============================================================================
  data_quality_tier STRING,                         -- 'high', 'medium', 'low' based on sample size
  primary_source_used STRING,                       -- Which boxscore source: 'bdl_player_boxscores', 'nbac_player_boxscores', 'nbac_gamebook'
  processed_with_issues BOOLEAN,                    -- Issues flag (missing lines, <3 bookmakers, etc.)
  
  -- ============================================================================
  -- COMPLETENESS CHECKING METADATA (25 fields) - Added Week 5
  -- ============================================================================

  -- Completeness Metrics (4 fields)
  expected_games_count INT64,                       -- Games expected from schedule
  actual_games_count INT64,                         -- Games actually found in upstream table
  completeness_percentage FLOAT64,                  -- Completeness percentage 0-100%
  missing_games_count INT64,                        -- Number of games missing from upstream

  -- Production Readiness (2 fields)
  is_production_ready BOOLEAN,                      -- TRUE if all windows >= 90% complete
  data_quality_issues ARRAY<STRING>,                -- Specific quality issues found

  -- Circuit Breaker (4 fields)
  last_reprocess_attempt_at TIMESTAMP,              -- When reprocessing was last attempted
  reprocess_attempt_count INT64,                    -- Number of reprocess attempts
  circuit_breaker_active BOOLEAN,                   -- TRUE if max reprocess attempts reached
  circuit_breaker_until TIMESTAMP,                  -- When circuit breaker expires (7 days from last attempt)

  -- Bootstrap/Override (4 fields)
  manual_override_required BOOLEAN,                 -- TRUE if manual intervention needed
  season_boundary_detected BOOLEAN,                 -- TRUE if date near season start/end
  backfill_bootstrap_mode BOOLEAN,                  -- TRUE if first 30 days of season/backfill
  processing_decision_reason STRING,                -- Why record was processed or skipped

  -- Multi-Window Completeness (11 fields - 5 windows × 2 + 1 all_windows)
  l5_completeness_pct FLOAT64,                      -- L5 games completeness percentage
  l5_is_complete BOOLEAN,                           -- TRUE if L5 >= 90% complete
  l10_completeness_pct FLOAT64,                     -- L10 games completeness percentage
  l10_is_complete BOOLEAN,                          -- TRUE if L10 >= 90% complete
  l7d_completeness_pct FLOAT64,                     -- L7 days completeness percentage
  l7d_is_complete BOOLEAN,                          -- TRUE if L7d >= 90% complete
  l14d_completeness_pct FLOAT64,                    -- L14 days completeness percentage
  l14d_is_complete BOOLEAN,                         -- TRUE if L14d >= 90% complete
  l30d_completeness_pct FLOAT64,                    -- L30 days completeness percentage
  l30d_is_complete BOOLEAN,                         -- TRUE if L30d >= 90% complete
  all_windows_complete BOOLEAN,                     -- TRUE if ALL windows >= 90% complete

  -- ============================================================================
  -- UPDATE TRACKING (3 fields)
  -- ============================================================================
  context_version INT64,                            -- Update counter (for intraday updates)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, universal_player_id, game_date
OPTIONS(
  description="Complete pre-game context for player predictions with universal player identification. Aggregated from Phase 2 raw tables: player boxscores, schedule, props, and game lines. Forward-looking schedule fields and opponent asymmetry fields are placeholders for future implementation. Smart idempotency tracks upstream Phase 2 data_hash values to skip reprocessing when source data unchanged."
);

-- ============================================================================
-- FIELD COUNT SUMMARY
-- ============================================================================
-- Core identifiers:          6 fields
-- Prop betting context:      5 fields
-- Game spread context:       5 fields
-- Game total context:        5 fields
-- Pre-game context:          8 fields
-- Player fatigue:           12 fields
-- Travel context:            5 fields
-- Player characteristics:    1 field
-- Recent performance:        8 fields
-- Forward-looking schedule:  4 fields (deferred)
-- Opponent asymmetry:        3 fields (deferred)
-- Real-time updates:         4 fields
-- Source tracking:          16 fields (4 sources × 4 fields - includes smart idempotency hashes)
-- Data quality:              3 fields
-- Completeness checking:    25 fields (14 standard + 11 multi-window)
-- Update tracking:           3 fields
-- -------------------------
-- TOTAL:                   113 fields (updated Week 5)

-- ============================================================================
-- CHANGE LOG
-- ============================================================================
-- v1.0 (Initial):       Complete schema design with Phase 2 source tracking
-- v1.1 (+source_track): Added 4 Phase 2 sources × 3 fields = 12 tracking fields
-- v1.2 (+docs):         Added comprehensive documentation and example queries
-- v1.3 (data_type):     Changed game_start_time_local from TIME to STRING
-- 
-- Last Updated: November 2025
-- Status: Production Ready
-- ============================================================================

-- ============================================================================
-- SOURCE TRACKING FIELD SEMANTICS
-- ============================================================================
-- Per dependency tracking guide v4.0, each source has 3 fields:
--
-- 1. source_{prefix}_last_updated (TIMESTAMP)
--    - When the source table was last processed (from source's processed_at)
--    - NULL = source table doesn't exist or wasn't checked
--    - Used to calculate data freshness/age on-demand
--
-- 2. source_{prefix}_rows_found (INT64)
--    - How many rows the extraction query returned from source
--    - NULL = source table doesn't exist
--    - 0 = source exists but query returned nothing (player has no history)
--    - Used for debugging data availability
--
-- 3. source_{prefix}_completeness_pct (NUMERIC(5,2))
--    - (rows_found / rows_expected) × 100, capped at 100%
--    - NULL = source doesn't exist (couldn't calculate)
--    - 0.0 = source exists, found 0% of expected data (rookie/new player)
--    - 100.0 = found all expected data (or more)
--    - Primary data quality metric

-- ============================================================================
-- DATA QUALITY TIER CALCULATION
-- ============================================================================
-- Quality tier assigned based on historical sample size:
--
-- HIGH (best):
--   - Player has 10+ games in last 30 days
--   - All critical sources present and complete
--   - Recent averages are reliable
--   - No processing issues
--
-- MEDIUM (good):
--   - Player has 5-9 games in last 30 days
--   - Critical sources present (may have minor gaps)
--   - Recent averages have moderate confidence
--   - Minor issues may be logged
--
-- LOW (needs attention):
--   - Player has <5 games in last 30 days (rookie, returning from injury, etc.)
--   - Limited historical context
--   - Recent averages have low confidence
--   - Use with caution for predictions

-- ============================================================================
-- DEFERRED FIELDS (FUTURE IMPLEMENTATION)
-- ============================================================================
-- The following fields are included in the schema but return default values
-- until their processing logic is fully implemented:
--
-- Forward-Looking Schedule (4 fields):
--   - next_game_days_rest, games_in_next_7_days, next_opponent_win_pct, next_game_is_primetime
--   - Currently returns 0/NULL/FALSE
--   - Requires forward schedule analysis from schedule table
--
-- Opponent Asymmetry (3 fields):
--   - opponent_days_rest, opponent_games_in_next_7_days, opponent_next_game_days_rest
--   - Currently returns 0/NULL
--   - Can be calculated from schedule once implemented
--
-- Advanced Fatigue (3 fields):
--   - avg_usage_rate_last_7_games, fourth_quarter_minutes_last_7, clutch_minutes_last_7_games
--   - Currently returns NULL
--   - Requires play-by-play data for crunch time analysis
--
-- Travel Context (5 fields):
--   - All travel fields return NULL for now
--   - Requires travel distance calculations between cities
--   - Requires timezone mapping for arenas
--
-- Performance Signals (4 fields):
--   - star_teammates_out, opponent_def_rating_last_10, shooting_pct_decline_last_5, fourth_quarter_production_last_7
--   - Currently returns NULL/0
--   - Requires additional analytics tables
--
-- Pre-game Context (4 fields):
--   - pace_differential, opponent_pace_last_10, opponent_ft_rate_allowed, projected_usage_rate
--   - Currently returns NULL
--   - Requires team analytics tables
--
-- Public Betting (2 fields):
--   - spread_public_betting_pct, total_public_betting_pct
--   - Currently returns NULL
--   - Requires public betting percentage data source
-- ============================================================================

-- ============================================================================
-- USAGE NOTES
-- ============================================================================
--
-- Partition Requirement: ALL queries MUST include game_date filter
--   ❌ WRONG: SELECT * FROM upcoming_player_game_context WHERE player_lookup = 'lebronjames'
--   ✅ RIGHT: SELECT * FROM upcoming_player_game_context WHERE player_lookup = 'lebronjames' AND game_date >= CURRENT_DATE()
--
-- Clustering: Optimized for queries filtering/joining on:
--   1. player_lookup (most common - player-specific queries)
--   2. universal_player_id (cross-source player matching)
--   3. game_date (time-based analysis)
--
-- Processing Strategy: MERGE_UPDATE
--   - Merge keys: [player_lookup, game_id]
--   - Allows intraday updates as props/lines change
--   - Updates existing records rather than creating duplicates
--   - context_version tracks number of updates
--
-- Data Freshness:
--   - Reprocessed multiple times per day as data updates:
--     - Morning: Initial context for today's games
--     - Throughout day: As props/injuries change
--     - Pre-game: Final update before tipoff
--
-- Related Tables (Phase 2 raw sources):
--   - nba_raw.odds_api_player_points_props (DRIVER - which players to process)
--   - nba_raw.bdl_player_boxscores (PRIMARY - historical performance)
--   - nba_raw.nbac_schedule (game timing and context)
--   - nba_raw.odds_api_game_lines (game spreads/totals)
--   - nba_raw.espn_team_rosters (optional - current team)
--   - nba_raw.nbac_injury_report (optional - injury status)
--
-- Related Tables (Phase 4 consumers):
--   - nba_precompute.player_composite_factors (uses this as input)
--   - nba_precompute.player_daily_cache (uses this as input)
--
-- Deferred Fields:
--   - Many fields in schema return NULL/0/FALSE for now
--   - Schema is future-ready for when we implement those features
--   - Check field comments for "(future)" markers

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- Get pre-game context for a specific player today
-- SELECT *
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE player_lookup = 'lebronjames'
--   AND game_date = CURRENT_DATE();

-- Get all players with props for today
-- SELECT 
--   player_lookup,
--   universal_player_id,
--   team_abbr,
--   opponent_team_abbr,
--   current_points_line,
--   line_movement,
--   points_avg_last_5,
--   points_avg_last_10,
--   days_rest,
--   games_in_last_7_days,
--   data_quality_tier,
--   CASE WHEN home_game THEN 'vs' ELSE '@' END as location
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
-- ORDER BY current_points_line DESC;

-- Players with significant line movement today
-- SELECT 
--   player_lookup,
--   team_abbr,
--   current_points_line,
--   opening_points_line,
--   line_movement,
--   points_avg_last_10,
--   -- Line position vs average
--   current_points_line - points_avg_last_10 as line_vs_avg
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
--   AND ABS(line_movement) >= 1.5  -- Line moved 1.5+ points
-- ORDER BY ABS(line_movement) DESC;

-- Fatigued players (back-to-back or heavy minutes)
-- SELECT 
--   player_lookup,
--   team_abbr,
--   opponent_team_abbr,
--   back_to_back,
--   days_rest,
--   games_in_last_7_days,
--   minutes_in_last_7_days,
--   avg_minutes_per_game_last_7,
--   points_avg_last_5,
--   current_points_line
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
--   AND (back_to_back = TRUE 
--        OR games_in_last_7_days >= 4
--        OR minutes_in_last_7_days >= 140)
-- ORDER BY minutes_in_last_7_days DESC;

-- Players with limited data (rookies, injuries)
-- SELECT 
--   player_lookup,
--   team_abbr,
--   data_quality_tier,
--   source_boxscore_rows_found as games_in_last_30,
--   points_avg_last_5,
--   points_avg_last_10,
--   current_points_line
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
--   AND data_quality_tier = 'low'
-- ORDER BY source_boxscore_rows_found ASC;

-- Game situation analysis
-- SELECT 
--   player_lookup,
--   team_abbr,
--   opponent_team_abbr,
--   current_points_line,
--   game_spread,
--   game_total,
--   home_game,
--   -- Expected competitiveness
--   CASE 
--     WHEN ABS(game_spread) <= 3 THEN 'close'
--     WHEN ABS(game_spread) <= 7 THEN 'moderate'
--     ELSE 'blowout_risk'
--   END as game_competitiveness,
--   -- Expected pace
--   CASE
--     WHEN game_total >= 230 THEN 'high'
--     WHEN game_total >= 220 THEN 'medium'
--     ELSE 'low'
--   END as expected_pace
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
-- ORDER BY game_total DESC;

-- Recent performance trends
-- SELECT 
--   player_lookup,
--   team_abbr,
--   current_points_line,
--   points_avg_last_5,
--   points_avg_last_10,
--   -- Form indicator
--   points_avg_last_5 - points_avg_last_10 as recent_form_change,
--   prop_over_streak,
--   prop_under_streak,
--   -- Consistency check
--   CASE
--     WHEN points_avg_last_5 > current_points_line + 2 THEN 'line_low'
--     WHEN points_avg_last_5 < current_points_line - 2 THEN 'line_high'
--     ELSE 'line_neutral'
--   END as line_position
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
-- ORDER BY ABS(points_avg_last_5 - current_points_line) DESC;

-- ============================================================================
-- DATA QUALITY MONITORING QUERIES
-- ============================================================================

-- Check source freshness (calculate age on-demand)
-- SELECT 
--   game_date,
--   player_lookup,
--   -- Calculate source age in hours
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_boxscore_last_updated, HOUR) as boxscore_age_hours,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_schedule_last_updated, HOUR) as schedule_age_hours,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_props_last_updated, HOUR) as props_age_hours,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_game_lines_last_updated, HOUR) as lines_age_hours,
--   -- Completeness
--   source_boxscore_completeness_pct,
--   source_props_completeness_pct,
--   source_game_lines_completeness_pct,
--   -- Quality
--   data_quality_tier,
--   processed_with_issues
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
--   AND (source_boxscore_completeness_pct < 85
--        OR TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_props_last_updated, HOUR) > 24)
-- ORDER BY source_boxscore_completeness_pct ASC;

-- Overall data quality summary by date
-- SELECT 
--   game_date,
--   COUNT(*) as total_players,
--   -- Source completeness
--   AVG(source_boxscore_completeness_pct) as avg_boxscore_completeness,
--   AVG(source_props_completeness_pct) as avg_props_completeness,
--   AVG(source_game_lines_completeness_pct) as avg_lines_completeness,
--   -- Quality tiers
--   SUM(CASE WHEN data_quality_tier = 'high' THEN 1 ELSE 0 END) as high_quality,
--   SUM(CASE WHEN data_quality_tier = 'medium' THEN 1 ELSE 0 END) as medium_quality,
--   SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) as low_quality,
--   -- Issues
--   SUM(CASE WHEN processed_with_issues THEN 1 ELSE 0 END) as players_with_issues,
--   ROUND(SUM(CASE WHEN processed_with_issues THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as issue_pct
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY game_date
-- ORDER BY game_date DESC;

-- Missing or incomplete data
-- SELECT 
--   game_date,
--   player_lookup,
--   team_abbr,
--   data_quality_tier,
--   source_boxscore_rows_found as games_found,
--   CASE
--     WHEN source_boxscore_rows_found IS NULL THEN 'source_missing'
--     WHEN source_boxscore_rows_found = 0 THEN 'no_history'
--     WHEN source_boxscore_rows_found < 5 THEN 'limited_history'
--     WHEN game_spread IS NULL THEN 'missing_game_lines'
--     WHEN current_points_line IS NULL THEN 'missing_prop_line'
--     ELSE 'other'
--   END as issue_category,
--   processed_with_issues
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
--   AND (processed_with_issues = TRUE
--        OR source_boxscore_completeness_pct < 85
--        OR data_quality_tier = 'low')
-- ORDER BY data_quality_tier, source_boxscore_rows_found;

-- ============================================================================
-- DATA VALIDATION QUERIES
-- ============================================================================

-- Validation 1: Check for negative days_rest
-- SELECT game_date, player_lookup, days_rest
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date >= CURRENT_DATE()
--   AND days_rest < 0;

-- Validation 2: Check unreasonable point lines
-- SELECT game_date, player_lookup, current_points_line
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date >= CURRENT_DATE()
--   AND (current_points_line < 5.0 OR current_points_line > 50.0);

-- Validation 3: Check missing critical fields
-- SELECT game_date, player_lookup, team_abbr,
--        current_points_line, game_id
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date >= CURRENT_DATE()
--   AND (player_lookup IS NULL 
--        OR team_abbr IS NULL 
--        OR game_id IS NULL);

-- Validation 4: Check extreme line movements
-- SELECT game_date, player_lookup, team_abbr,
--        opening_points_line, current_points_line, line_movement
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date >= CURRENT_DATE()
--   AND ABS(line_movement) > 5.0;

-- ============================================================================
-- ALERT QUERIES (for monitoring system)
-- ============================================================================

-- Alert: Stale props data (>24 hours old)
-- SELECT 
--   'upcoming_player_game_context' as processor,
--   game_date,
--   COUNT(*) as affected_players,
--   MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_props_last_updated, HOUR)) as max_age_hours
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
-- GROUP BY game_date
-- HAVING MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_props_last_updated, HOUR)) > 24;

-- Alert: Low completeness (<85%)
-- SELECT 
--   'upcoming_player_game_context' as processor,
--   game_date,
--   AVG(source_boxscore_completeness_pct) as avg_completeness,
--   MIN(source_boxscore_completeness_pct) as min_completeness,
--   COUNT(*) as total_players
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
-- GROUP BY game_date
-- HAVING MIN(source_boxscore_completeness_pct) < 85;

-- Alert: High percentage of low quality data
-- SELECT 
--   game_date,
--   COUNT(*) as total_players,
--   SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) as low_quality_count,`
--   ROUND(SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as low_quality_pct
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date = CURRENT_DATE()
-- GROUP BY game_date
-- HAVING low_quality_pct > 30;  -- Alert if >30% low quality

-- ============================================================================
-- MAINTENANCE QUERIES
-- ============================================================================

-- Get table statistics
-- SELECT 
--   COUNT(*) as total_rows,
--   COUNT(DISTINCT player_lookup) as unique_players,
--   COUNT(DISTINCT game_id) as unique_games,
--   MIN(game_date) as earliest_game,
--   MAX(game_date) as latest_game,
--   MAX(processed_at) as last_processed,
--   -- Quality stats
--   SUM(CASE WHEN data_quality_tier = 'high' THEN 1 ELSE 0 END) as high_quality_rows,
--   SUM(CASE WHEN processed_with_issues THEN 1 ELSE 0 END) as rows_with_issues,
--   -- Average sample sizes
--   AVG(source_boxscore_rows_found) as avg_games_per_player
-- FROM `nba_analytics.upcoming_player_game_context`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- ============================================================================
-- DEPLOYMENT: Add completeness checking columns (Week 5)
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_analytics.upcoming_player_game_context`
ADD COLUMN IF NOT EXISTS expected_games_count INT64
  OPTIONS (description='Games expected from schedule'),
ADD COLUMN IF NOT EXISTS actual_games_count INT64
  OPTIONS (description='Games actually found in upstream table'),
ADD COLUMN IF NOT EXISTS completeness_percentage FLOAT64
  OPTIONS (description='Completeness percentage 0-100%'),
ADD COLUMN IF NOT EXISTS missing_games_count INT64
  OPTIONS (description='Number of games missing from upstream'),

ADD COLUMN IF NOT EXISTS is_production_ready BOOLEAN
  OPTIONS (description='TRUE if all windows >= 90% complete'),
ADD COLUMN IF NOT EXISTS data_quality_issues ARRAY<STRING>
  OPTIONS (description='Specific quality issues found'),

ADD COLUMN IF NOT EXISTS last_reprocess_attempt_at TIMESTAMP
  OPTIONS (description='When reprocessing was last attempted'),
ADD COLUMN IF NOT EXISTS reprocess_attempt_count INT64
  OPTIONS (description='Number of reprocess attempts'),
ADD COLUMN IF NOT EXISTS circuit_breaker_active BOOLEAN
  OPTIONS (description='TRUE if max reprocess attempts reached'),
ADD COLUMN IF NOT EXISTS circuit_breaker_until TIMESTAMP
  OPTIONS (description='When circuit breaker expires (7 days from last attempt)'),

ADD COLUMN IF NOT EXISTS manual_override_required BOOLEAN
  OPTIONS (description='TRUE if manual intervention needed'),
ADD COLUMN IF NOT EXISTS season_boundary_detected BOOLEAN
  OPTIONS (description='TRUE if date near season start/end'),
ADD COLUMN IF NOT EXISTS backfill_bootstrap_mode BOOLEAN
  OPTIONS (description='TRUE if first 30 days of season/backfill'),
ADD COLUMN IF NOT EXISTS processing_decision_reason STRING
  OPTIONS (description='Why record was processed or skipped'),

ADD COLUMN IF NOT EXISTS l5_completeness_pct FLOAT64
  OPTIONS (description='L5 games completeness percentage'),
ADD COLUMN IF NOT EXISTS l5_is_complete BOOLEAN
  OPTIONS (description='TRUE if L5 >= 90% complete'),
ADD COLUMN IF NOT EXISTS l10_completeness_pct FLOAT64
  OPTIONS (description='L10 games completeness percentage'),
ADD COLUMN IF NOT EXISTS l10_is_complete BOOLEAN
  OPTIONS (description='TRUE if L10 >= 90% complete'),
ADD COLUMN IF NOT EXISTS l7d_completeness_pct FLOAT64
  OPTIONS (description='L7 days completeness percentage'),
ADD COLUMN IF NOT EXISTS l7d_is_complete BOOLEAN
  OPTIONS (description='TRUE if L7d >= 90% complete'),
ADD COLUMN IF NOT EXISTS l14d_completeness_pct FLOAT64
  OPTIONS (description='L14 days completeness percentage'),
ADD COLUMN IF NOT EXISTS l14d_is_complete BOOLEAN
  OPTIONS (description='TRUE if L14d >= 90% complete'),
ADD COLUMN IF NOT EXISTS l30d_completeness_pct FLOAT64
  OPTIONS (description='L30 days completeness percentage'),
ADD COLUMN IF NOT EXISTS l30d_is_complete BOOLEAN
  OPTIONS (description='TRUE if L30d >= 90% complete'),
ADD COLUMN IF NOT EXISTS all_windows_complete BOOLEAN
  OPTIONS (description='TRUE if ALL windows >= 90% complete');

-- ============================================================================
-- VERSION HISTORY
-- ============================================================================
-- v1.0 (Initial):       Complete schema design with Phase 2 source tracking
-- v1.1 (+source_track): Added 4 Phase 2 sources × 3 fields = 12 tracking fields
-- v1.2 (+docs):         Added comprehensive documentation and example queries
-- v1.3 (+completeness): Added 25 completeness checking columns (Week 5)
--
-- Last Updated: November 2025
-- Status: Ready for Implementation
-- Next: Implement UpcomingPlayerGameContextProcessor
-- ============================================================================