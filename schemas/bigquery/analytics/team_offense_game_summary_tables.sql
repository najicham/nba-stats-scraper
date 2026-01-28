-- Path: schemas/bigquery/analytics/team_offense_game_summary_schema.sql
-- Description: BigQuery table schema for team offensive game summary analytics
--
-- NBA Team Offense Game Summary Analytics
-- Complete team-level offensive performance with shot zone tracking and advanced metrics
-- Data Source: Aggregated from nba_raw.nbac_team_boxscore + nba_raw.nbac_play_by_play
-- Processing: TeamOffenseGameSummaryProcessor (Phase 3, MERGE_UPDATE strategy)
--
-- This table provides comprehensive offensive analytics for each team in each game:
-- - Basic stats (FG, 3PT, FT, AST, REB, TO)
-- - Shot zones (paint/mid-range/three) when play-by-play available
-- - Advanced metrics (offensive rating, pace, possessions, TS%)
-- - Game context (home/away, win/loss, OT periods)
-- - Source tracking for data quality monitoring

CREATE TABLE IF NOT EXISTS `nba_analytics.team_offense_game_summary` (
  -- ============================================================================
  -- CORE IDENTIFIERS (6 fields)
  -- ============================================================================
  game_id              STRING NOT NULL,    -- System format: "20250115_LAL_PHI" (YYYYMMDD_AWAY_HOME)
  nba_game_id          STRING,             -- NBA.com game ID: "0022400561" (for debugging/lookups)
  game_date            DATE NOT NULL,      -- Game date (partition key)
  team_abbr            STRING NOT NULL,    -- Team playing offense: "LAL", "PHI", "BOS", etc.
  opponent_team_abbr   STRING NOT NULL,    -- Opposing defensive team
  season_year          INT64 NOT NULL,     -- NBA season starting year (2024 for 2024-25 season)
  
  -- ============================================================================
  -- BASIC OFFENSIVE STATS (11 fields)
  -- ============================================================================
  points_scored        INT64,              -- Total points scored by team
  fg_attempts          INT64,              -- Total field goal attempts
  fg_makes             INT64,              -- Total field goal makes
  three_pt_attempts    INT64,              -- Three-point attempts
  three_pt_makes       INT64,              -- Three-point makes
  ft_attempts          INT64,              -- Free throw attempts
  ft_makes             INT64,              -- Free throw makes
  rebounds             INT64,              -- Total rebounds (offensive + defensive)
  assists              INT64,              -- Total assists
  turnovers            INT64,              -- Total turnovers
  personal_fouls       INT64,              -- Personal fouls committed
  
  -- ============================================================================
  -- TEAM SHOT ZONE PERFORMANCE (6 fields)
  -- Populated from play-by-play data when available
  -- NULL if play-by-play data not yet processed
  -- ============================================================================
  team_paint_attempts       INT64,         -- Paint shot attempts (≤8 feet)
  team_paint_makes          INT64,         -- Paint shot makes
  team_mid_range_attempts   INT64,         -- Mid-range attempts (9-23 feet, 2PT)
  team_mid_range_makes      INT64,         -- Mid-range makes
  points_in_paint_scored    INT64,         -- Points scored from paint shots
  second_chance_points_scored INT64,       -- Points immediately after offensive rebounds
  
  -- ============================================================================
  -- ADVANCED OFFENSIVE METRICS (4 fields)
  -- Calculated from basic stats
  -- ============================================================================
  offensive_rating     NUMERIC(6,2),       -- Points per 100 possessions
  pace                 NUMERIC(5,1),       -- Possessions per 48 minutes (normalized)
  possessions          INT64,              -- Estimated total possessions
  ts_pct               NUMERIC(5,3),       -- Team true shooting percentage
  
  -- ============================================================================
  -- GAME CONTEXT (4 fields)
  -- ============================================================================
  home_game            BOOLEAN NOT NULL,   -- Whether team was playing at home
  win_flag             BOOLEAN NOT NULL,   -- Whether team won the game
  margin_of_victory    INT64,              -- Point margin (positive = won, negative = lost)
  overtime_periods     INT64,              -- Number of overtime periods (0 = regulation)
  
  -- ============================================================================
  -- TEAM SITUATION CONTEXT (2 fields)
  -- Placeholders for future implementation
  -- ============================================================================
  players_inactive     INT64,              -- Number of players inactive/out (future)
  starters_inactive    INT64,              -- Number of regular starters inactive (future)
  
  -- ============================================================================
  -- REFEREE INTEGRATION (1 field)
  -- Placeholder for future implementation
  -- ============================================================================
  referee_crew_id      STRING,             -- Links to game_referees table (future)
  
  -- ============================================================================
  -- SOURCE TRACKING (8 fields = 2 sources × 4 fields)
  -- Per dependency tracking guide v4.0 + Smart Idempotency (Pattern #14)
  -- ============================================================================

  -- SOURCE 1: NBA.com Team Boxscore (PRIMARY - CRITICAL)
  -- nba_raw.nbac_team_boxscore
  source_nbac_boxscore_last_updated     TIMESTAMP,      -- When boxscore table was last processed
  source_nbac_boxscore_rows_found       INT64,          -- How many team records found for this date range
  source_nbac_boxscore_completeness_pct NUMERIC(5,2),   -- % of expected teams found
  source_nbac_boxscore_hash             STRING,         -- Smart Idempotency: data_hash from nbac_team_boxscore

  -- SOURCE 2: NBA.com Play-by-Play (ENHANCEMENT - OPTIONAL)
  -- nba_raw.nbac_play_by_play (falls back to bigdataball_play_by_play)
  source_play_by_play_last_updated      TIMESTAMP,      -- When play-by-play table was last processed
  source_play_by_play_rows_found        INT64,          -- How many play-by-play events found
  source_play_by_play_completeness_pct  NUMERIC(5,2),   -- % of expected shot events found
  source_play_by_play_hash              STRING,         -- Smart Idempotency: data_hash from nbac_play_by_play or bigdataball_play_by_play
  
  -- ============================================================================
  -- DATA QUALITY TRACKING (5 fields)
  -- ============================================================================
  data_quality_tier    STRING,            -- 'high', 'medium', 'low' based on source availability
  shot_zones_available BOOLEAN,           -- TRUE if play-by-play was processed
  shot_zones_source    STRING,            -- 'nbac_pbp', 'bigdataball', or NULL
  primary_source_used  STRING,            -- 'nbac_team_boxscore' (always)
  processed_with_issues BOOLEAN,          -- TRUE if validation issues logged

  -- ============================================================================
  -- PARTIAL GAME DATA DETECTION (3 fields)
  -- Added 2026-01-27: Flags incomplete data to help downstream processors
  -- Detection: game_status != 'Final' OR fg_attempts < 50
  -- ============================================================================
  is_partial_game_data BOOLEAN DEFAULT FALSE,  -- TRUE if game data was incomplete at processing time
  game_completeness_pct NUMERIC(5,2),          -- % of expected data available
  game_status_at_processing STRING,            -- 'scheduled', 'in_progress', 'final' at time of processing

  -- ============================================================================
  -- SMART REPROCESSING (1 field)
  -- Pattern #3: Phase 4 processors compare this hash to detect meaningful changes
  -- ============================================================================
  data_hash            STRING,                                 -- SHA256 hash (16 chars) of meaningful analytics output fields

  -- ============================================================================
  -- PROCESSING METADATA (2 fields)
  -- ============================================================================
  created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),  -- When record first created
  processed_at         TIMESTAMP                               -- When record last processed/updated
)
PARTITION BY game_date
CLUSTER BY team_abbr, game_date, home_game
OPTIONS (
  description = "Team offensive performance analytics with shot zone tracking and advanced metrics. Aggregated from NBA.com team boxscore and play-by-play data. Updated via MERGE_UPDATE strategy for shot zone backfilling. Smart idempotency tracks upstream Phase 2 data_hash values to skip reprocessing when source data unchanged.",
  require_partition_filter = true
);

-- ============================================================================
-- FIELD COUNT SUMMARY
-- ============================================================================
-- Core identifiers:         6 fields
-- Basic offensive stats:   11 fields
-- Shot zones:               6 fields
-- Advanced metrics:         4 fields
-- Game context:             4 fields
-- Situation context:        2 fields
-- Referee:                  1 field
-- Source tracking:          8 fields (2 sources × 4 fields - includes smart idempotency hashes)
-- Data quality:             5 fields
-- Partial game detection:   3 fields (is_partial_game_data, game_completeness_pct, game_status_at_processing)
-- Processing metadata:      2 fields
-- -------------------------
-- TOTAL:                   52 fields

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
--    - 0 = source exists but query returned nothing
--    - Used for debugging data availability
--
-- 3. source_{prefix}_completeness_pct (NUMERIC(5,2))
--    - (rows_found / rows_expected) × 100, capped at 100%
--    - NULL = source doesn't exist (couldn't calculate)
--    - 0.0 = source exists, found 0% of expected data
--    - 100.0 = found all expected data (or more)
--    - Primary data quality metric

-- ============================================================================
-- DATA QUALITY TIER CALCULATION
-- ============================================================================
-- Quality tier assigned based on source availability and validation:
--
-- HIGH (best):
--   - Team boxscore present and complete (100% teams found)
--   - Play-by-play present (shot zones available)
--   - All validation checks passed
--   - No data quality issues logged
--
-- MEDIUM (good):
--   - Team boxscore present and complete
--   - Play-by-play missing (shot zones NULL)
--   - Basic validation passed
--   - Minor issues may be logged
--
-- LOW (needs attention):
--   - Team boxscore incomplete (<100% teams)
--   - Validation failures
--   - Missing opponent data
--   - Data quality issues logged

-- ============================================================================
-- USAGE NOTES
-- ============================================================================
--
-- Partition Requirement: ALL queries MUST include game_date filter
--   ❌ WRONG: SELECT * FROM team_offense_game_summary WHERE team_abbr = 'LAL'
--   ✅ RIGHT: SELECT * FROM team_offense_game_summary WHERE team_abbr = 'LAL' AND game_date >= '2024-10-01'
--
-- Clustering: Optimized for queries filtering/joining on:
--   1. team_abbr (most common - team-specific queries)
--   2. game_date (time-based analysis)
--   3. home_game (home vs away splits)
--
-- Shot Zones: May be NULL if play-by-play data not yet available
--   - Initial processing: Shot zones NULL (team boxscore only)
--   - Re-processing: Shot zones populated when play-by-play arrives
--   - Check shot_zones_available flag to know if zones are present
--
-- Processing Strategy: MERGE_UPDATE
--   - Merge keys: [game_id, team_abbr]
--   - Allows re-processing to add shot zones later
--   - Updates existing records rather than creating duplicates
--
-- Related Tables:
--   - nba_raw.nbac_team_boxscore (source - team stats)
--   - nba_raw.nbac_play_by_play (source - shot zones)
--   - nba_raw.bigdataball_play_by_play (fallback - shot zones)
--   - nba_analytics.team_defense_game_summary (defensive counterpart)
--   - nba_precompute.* (downstream consumers)

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- Get team offensive stats for a specific game
-- SELECT *
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_id = '20250115_LAL_PHI'
--   AND game_date = '2025-01-15';
-- -- Returns: 2 rows (LAL and PHI)

-- Team's recent offensive performance
-- SELECT 
--   game_date,
--   opponent_team_abbr,
--   CASE WHEN home_game THEN 'vs' ELSE '@' END as location,
--   points_scored,
--   offensive_rating,
--   pace,
--   CASE WHEN win_flag THEN 'W' ELSE 'L' END as result,
--   margin_of_victory,
--   shot_zones_available
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE team_abbr = 'LAL'
--   AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- ORDER BY game_date DESC;

-- Season offensive averages for all teams
-- SELECT 
--   team_abbr,
--   COUNT(*) as games_played,
--   ROUND(AVG(points_scored), 1) as ppg,
--   ROUND(AVG(offensive_rating), 2) as avg_ortg,
--   ROUND(AVG(pace), 1) as avg_pace,
--   ROUND(AVG(CAST(assists AS FLOAT64)), 1) as apg,
--   ROUND(AVG(CAST(turnovers AS FLOAT64)), 1) as tpg,
--   ROUND(AVG(ts_pct) * 100, 1) as ts_pct,
--   -- Shot zone percentages (when available)
--   ROUND(AVG(CASE WHEN shot_zones_available THEN 
--     team_paint_attempts * 100.0 / (team_paint_attempts + team_mid_range_attempts + three_pt_attempts)
--   END), 1) as paint_rate
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE season_year = 2024
--   AND game_date >= '2024-10-01'
-- GROUP BY team_abbr
-- ORDER BY avg_ortg DESC;

-- Home vs away offensive performance
-- SELECT 
--   team_abbr,
--   home_game,
--   COUNT(*) as games,
--   ROUND(AVG(points_scored), 1) as ppg,
--   ROUND(AVG(offensive_rating), 2) as ortg,
--   ROUND(AVG(ts_pct) * 100, 1) as ts_pct,
--   SUM(CASE WHEN win_flag THEN 1 ELSE 0 END) as wins,
--   ROUND(SUM(CASE WHEN win_flag THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as win_pct
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE season_year = 2024
--   AND game_date >= '2024-10-01'
-- GROUP BY team_abbr, home_game
-- ORDER BY team_abbr, home_game DESC;

-- Shot zone analysis (when available)
-- SELECT 
--   team_abbr,
--   COUNT(*) as games_with_zones,
--   -- Paint
--   ROUND(AVG(team_paint_attempts), 1) as avg_paint_att,
--   ROUND(AVG(team_paint_makes * 100.0 / NULLIF(team_paint_attempts, 0)), 1) as paint_pct,
--   -- Mid-range
--   ROUND(AVG(team_mid_range_attempts), 1) as avg_mid_att,
--   ROUND(AVG(team_mid_range_makes * 100.0 / NULLIF(team_mid_range_attempts, 0)), 1) as mid_pct,
--   -- Three-point
--   ROUND(AVG(three_pt_attempts), 1) as avg_3pt_att,
--   ROUND(AVG(three_pt_makes * 100.0 / NULLIF(three_pt_attempts, 0)), 1) as three_pct
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE shot_zones_available = TRUE
--   AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- GROUP BY team_abbr
-- ORDER BY avg_paint_att DESC;

-- Overtime games analysis
-- SELECT 
--   game_date,
--   game_id,
--   team_abbr,
--   opponent_team_abbr,
--   overtime_periods,
--   points_scored,
--   pace,
--   CASE WHEN win_flag THEN 'W' ELSE 'L' END as result
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE overtime_periods > 0
--   AND game_date >= '2024-10-01'
-- ORDER BY game_date DESC, overtime_periods DESC;

-- ============================================================================
-- DATA QUALITY MONITORING QUERIES
-- ============================================================================

-- Check source freshness (calculate age on-demand)
-- SELECT 
--   game_date,
--   team_abbr,
--   -- Calculate source age in hours
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_boxscore_last_updated, HOUR) as boxscore_age_hours,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_play_by_play_last_updated, HOUR) as pbp_age_hours,
--   -- Completeness
--   source_nbac_boxscore_completeness_pct,
--   source_play_by_play_completeness_pct,
--   -- Quality
--   data_quality_tier,
--   shot_zones_available
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND (source_nbac_boxscore_completeness_pct < 100.0
--        OR TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_boxscore_last_updated, HOUR) > 48)
-- ORDER BY game_date DESC;

-- Overall data quality summary
-- SELECT 
--   game_date,
--   COUNT(*) as total_teams,
--   -- Source completeness
--   AVG(source_nbac_boxscore_completeness_pct) as avg_boxscore_completeness,
--   AVG(source_play_by_play_completeness_pct) as avg_pbp_completeness,
--   -- Quality tiers
--   SUM(CASE WHEN data_quality_tier = 'high' THEN 1 ELSE 0 END) as high_quality,
--   SUM(CASE WHEN data_quality_tier = 'medium' THEN 1 ELSE 0 END) as medium_quality,
--   SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) as low_quality,
--   -- Shot zones
--   SUM(CASE WHEN shot_zones_available THEN 1 ELSE 0 END) as teams_with_zones,
--   ROUND(SUM(CASE WHEN shot_zones_available THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as zone_coverage_pct
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- GROUP BY game_date
-- ORDER BY game_date DESC;

-- Games missing shot zones (need reprocessing)
-- SELECT 
--   game_date,
--   game_id,
--   COUNT(*) as teams_missing_zones,
--   ARRAY_AGG(team_abbr ORDER BY team_abbr) as affected_teams,
--   MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), processed_at, HOUR)) as hours_since_processed
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE shot_zones_available = FALSE
--   AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)  -- Games from yesterday or older
-- GROUP BY game_date, game_id
-- HAVING COUNT(*) >= 1
-- ORDER BY game_date DESC;

-- ============================================================================
-- DATA VALIDATION QUERIES
-- ============================================================================

-- Validation 1: Check for games with wrong number of teams
-- SELECT game_id, game_date, COUNT(*) as team_count
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= '2025-01-01'
-- GROUP BY game_id, game_date
-- HAVING COUNT(*) != 2;

-- Validation 2: Check points calculation
-- -- Points should equal: (FG2 × 2) + (3PT × 3) + FT
-- SELECT game_id, game_date, team_abbr, points_scored,
--        ((fg_makes - three_pt_makes) * 2) + (three_pt_makes * 3) + ft_makes as calculated_points,
--        points_scored - (((fg_makes - three_pt_makes) * 2) + (three_pt_makes * 3) + ft_makes) as diff
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= '2025-01-01'
--   AND points_scored != ((fg_makes - three_pt_makes) * 2) + (three_pt_makes * 3) + ft_makes;

-- Validation 3: Check field goal math
-- SELECT game_id, game_date, team_abbr,
--        fg_makes, fg_attempts, three_pt_makes, three_pt_attempts
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= '2025-01-01'
--   AND (fg_makes > fg_attempts 
--        OR three_pt_makes > three_pt_attempts
--        OR three_pt_makes > fg_makes);

-- Validation 4: Check reasonable stat ranges
-- SELECT game_id, game_date, team_abbr,
--        points_scored, offensive_rating, pace, possessions
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= '2025-01-01'
--   AND (points_scored < 50 OR points_scored > 200
--        OR offensive_rating < 70 OR offensive_rating > 150
--        OR pace < 80 OR pace > 120
--        OR possessions < 80 OR possessions > 120);

-- Validation 5: Check win/loss consistency per game
-- -- One team should win, one should lose (no ties)
-- SELECT t1.game_id, t1.game_date,
--        t1.team_abbr as team1, t1.points_scored as team1_points, t1.win_flag as team1_won,
--        t2.team_abbr as team2, t2.points_scored as team2_points, t2.win_flag as team2_won
-- FROM `nba_analytics.team_offense_game_summary` t1
-- JOIN `nba_analytics.team_offense_game_summary` t2
--   ON t1.game_id = t2.game_id
--   AND t1.game_date = t2.game_date
--   AND t1.team_abbr < t2.team_abbr  -- Avoid duplicates
-- WHERE t1.game_date >= '2025-01-01'
--   AND (t1.win_flag = t2.win_flag  -- Both won or both lost (impossible!)
--        OR (t1.points_scored > t2.points_scored AND NOT t1.win_flag)  -- Inconsistent
--        OR (t2.points_scored > t1.points_scored AND NOT t2.win_flag)); -- Inconsistent

-- Validation 6: Check home/away balance per game
-- -- Each game should have 1 home and 1 away team
-- SELECT game_id, game_date,
--        SUM(CASE WHEN home_game THEN 1 ELSE 0 END) as home_count,
--        SUM(CASE WHEN NOT home_game THEN 1 ELSE 0 END) as away_count
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= '2025-01-01'
-- GROUP BY game_id, game_date
-- HAVING home_count != 1 OR away_count != 1;

-- Validation 7: Check overtime period consistency
-- -- OT periods should match for both teams in same game
-- SELECT t1.game_id, t1.game_date,
--        t1.team_abbr, t1.overtime_periods as ot1,
--        t2.team_abbr, t2.overtime_periods as ot2
-- FROM `nba_analytics.team_offense_game_summary` t1
-- JOIN `nba_analytics.team_offense_game_summary` t2
--   ON t1.game_id = t2.game_id
--   AND t1.game_date = t2.game_date
--   AND t1.team_abbr < t2.team_abbr
-- WHERE t1.game_date >= '2025-01-01'
--   AND t1.overtime_periods != t2.overtime_periods;

-- ============================================================================
-- ALERT QUERIES (for monitoring system)
-- ============================================================================

-- Alert: Stale team boxscore data (>48 hours old)
-- SELECT 
--   'team_offense_game_summary' as processor,
--   game_date,
--   COUNT(*) as affected_teams,
--   MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_boxscore_last_updated, HOUR)) as max_age_hours
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
-- GROUP BY game_date
-- HAVING MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_boxscore_last_updated, HOUR)) > 48;

-- Alert: Low completeness (<85%)
-- SELECT 
--   'team_offense_game_summary' as processor,
--   game_date,
--   AVG(source_nbac_boxscore_completeness_pct) as avg_completeness,
--   MIN(source_nbac_boxscore_completeness_pct) as min_completeness,
--   COUNT(*) as total_teams
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
-- GROUP BY game_date
-- HAVING MIN(source_nbac_boxscore_completeness_pct) < 85;

-- Alert: High percentage of low quality data
-- SELECT 
--   game_date,
--   COUNT(*) as total_teams,
--   SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) as low_quality_count,
--   ROUND(SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as low_quality_pct
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
-- GROUP BY game_date
-- HAVING low_quality_pct > 20;  -- Alert if >20% low quality

-- Alert: Missing shot zones for old games (>3 days)
-- SELECT 
--   game_date,
--   COUNT(*) as teams_missing_zones,
--   ARRAY_AGG(DISTINCT game_id) as affected_games
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE shot_zones_available = FALSE
--   AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
-- GROUP BY game_date
-- HAVING COUNT(*) > 0
-- ORDER BY game_date DESC;

-- ============================================================================
-- MAINTENANCE QUERIES
-- ============================================================================

-- Get table statistics
-- SELECT 
--   COUNT(*) as total_rows,
--   COUNT(DISTINCT game_id) as unique_games,
--   COUNT(DISTINCT team_abbr) as unique_teams,
--   COUNT(DISTINCT season_year) as seasons,
--   MIN(game_date) as earliest_game,
--   MAX(game_date) as latest_game,
--   MAX(processed_at) as last_processed,
--   -- Quality stats
--   SUM(CASE WHEN shot_zones_available THEN 1 ELSE 0 END) as rows_with_zones,
--   ROUND(SUM(CASE WHEN shot_zones_available THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as zone_coverage_pct,
--   SUM(CASE WHEN data_quality_tier = 'high' THEN 1 ELSE 0 END) as high_quality_rows,
--   SUM(CASE WHEN processed_with_issues THEN 1 ELSE 0 END) as rows_with_issues
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE game_date >= '2024-10-01';

-- Get processing status by date
-- SELECT 
--   DATE(processed_at) as process_date,
--   COUNT(*) as records_processed,
--   COUNT(DISTINCT game_id) as unique_games,
--   AVG(source_nbac_boxscore_completeness_pct) as avg_completeness
-- FROM `nba_analytics.team_offense_game_summary`
-- WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY process_date
-- ORDER BY process_date DESC;

-- ============================================================================
-- VERSION HISTORY
-- ============================================================================
-- v1.0 (Initial):       Complete schema design with source tracking
-- v1.1 (+nba_game_id):  Added nba_game_id field for NBA.com API lookups
-- 
-- Last Updated: January 2025
-- Status: Ready for Implementation
-- Next: Implement TeamOffenseGameSummaryProcessor
-- ============================================================================