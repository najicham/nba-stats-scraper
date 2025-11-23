-- ============================================================================
-- NBA Props Platform - Player Daily Cache Schema
-- Path: schemas/bigquery/precompute/player_daily_cache.sql
-- ============================================================================
-- Daily snapshot of player data that won't change during the day
-- Updated: Once daily at 12:00 AM (after Phase 4 processors complete)
-- Used by: Phase 5 prediction systems for fast re-prediction when lines change
-- Priority: MEDIUM - Optimization, not critical for Week 1
-- Purpose: Speeds up line change updates by caching stable data (2000x faster)
--
-- Cost Impact:
--   Without cache: ~$34/month (repeated queries throughout day)
--   With cache: ~$7/month (single nightly query)
--   Savings: $27/month (79% reduction)
--
-- Performance Impact:
--   BigQuery query: 2-3 seconds per update
--   Cache lookup: <1 millisecond per update
--   Speedup: 2000x faster for real-time updates
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.player_daily_cache` (
  -- ============================================================================
  -- IDENTIFIERS (3 fields)
  -- ============================================================================
  player_lookup STRING NOT NULL,                    -- Normalized player identifier
  universal_player_id STRING,                       -- Universal player ID (e.g., lebronjames_001)
  cache_date DATE NOT NULL,                         -- Date this cache represents (partition key)
  
  -- ============================================================================
  -- RECENT PERFORMANCE - Won't change during the day (8 fields)
  -- Source: nba_analytics.player_game_summary (aggregated)
  -- ============================================================================
  points_avg_last_5 NUMERIC(5,1),                   -- Average points over last 5 games
  points_avg_last_10 NUMERIC(5,1),                  -- Average points over last 10 games
  points_avg_season NUMERIC(5,1),                   -- Season average points
  points_std_last_10 NUMERIC(5,2),                  -- Standard deviation of points (volatility)
  minutes_avg_last_10 NUMERIC(5,1),                 -- Average minutes over last 10 games
  usage_rate_last_10 NUMERIC(5,2),                  -- Average usage rate over last 10 games
  ts_pct_last_10 NUMERIC(5,3),                      -- Average true shooting % over last 10 games
  games_played_season INT64,                        -- Total games played this season
  
  -- ============================================================================
  -- TEAM CONTEXT - Won't change during the day (3 fields)
  -- Source: nba_analytics.team_offense_game_summary + player_game_summary
  -- ============================================================================
  team_pace_last_10 NUMERIC(5,1),                   -- Team's recent pace (possessions per 48 min)
  team_off_rating_last_10 NUMERIC(6,2),             -- Team's offensive efficiency (points per 100 poss)
  player_usage_rate_season NUMERIC(5,2),            -- Season-long usage rate
  
  -- ============================================================================
  -- FATIGUE METRICS - Won't change during the day (7 fields)
  -- Source: nba_analytics.upcoming_player_game_context (direct copy!)
  -- Note: These are already calculated in Phase 3, just copy them
  -- ============================================================================
  games_in_last_7_days INT64,                       -- Games played in last 7 days
  games_in_last_14_days INT64,                      -- Games played in last 14 days
  minutes_in_last_7_days INT64,                     -- Total minutes in last 7 days
  minutes_in_last_14_days INT64,                    -- Total minutes in last 14 days
  back_to_backs_last_14_days INT64,                 -- Back-to-back games in last 14 days
  avg_minutes_per_game_last_7 NUMERIC(5,1),         -- Average minutes per game (last 7 days)
  fourth_quarter_minutes_last_7 INT64,              -- 4th quarter minutes (last 7 days)
  
  -- ============================================================================
  -- SHOT ZONE TENDENCIES - Won't change during the day (4 fields)
  -- Source: nba_precompute.player_shot_zone_analysis + player_game_summary
  -- ============================================================================
  primary_scoring_zone STRING,                      -- Primary scoring zone: 'paint', 'mid_range', '3pt'
  paint_rate_last_10 NUMERIC(5,2),                  -- % of shots from paint (last 10 games)
  three_pt_rate_last_10 NUMERIC(5,2),               -- % of shots from three (last 10 games)
  assisted_rate_last_10 NUMERIC(5,2),               -- % of made FGs that were assisted (last 10)
  
  -- ============================================================================
  -- PLAYER DEMOGRAPHICS (1 field)
  -- Source: nba_analytics.upcoming_player_game_context
  -- ============================================================================
  player_age INT64,                                 -- Player's current age
  
  -- ============================================================================
  -- SOURCE TRACKING: player_game_summary (3 fields)
  -- Dependency v4.0 tracking for performance and usage stats
  -- ============================================================================
  source_player_game_last_updated TIMESTAMP,        -- When player_game_summary was last updated
  source_player_game_rows_found INT64,              -- How many game records found for player
  source_player_game_completeness_pct NUMERIC(5,2), -- % of expected games found

  source_player_game_hash STRING,                   -- Hash from player_game_summary.data_hash
                                                     -- Used for smart reprocessing (Pattern #3)

  -- ============================================================================
  -- SOURCE TRACKING: team_offense_game_summary (3 fields)
  -- Dependency v4.0 tracking for team context stats
  -- ============================================================================
  source_team_offense_last_updated TIMESTAMP,       -- When team_offense_game_summary was last updated
  source_team_offense_rows_found INT64,             -- How many team games found
  source_team_offense_completeness_pct NUMERIC(5,2),-- % of expected team games found

  source_team_offense_hash STRING,                  -- Hash from team_offense_game_summary.data_hash
                                                     -- Used for smart reprocessing (Pattern #3)

  -- ============================================================================
  -- SOURCE TRACKING: upcoming_player_game_context (3 fields)
  -- Dependency v4.0 tracking for fatigue and context data
  -- ============================================================================
  source_upcoming_context_last_updated TIMESTAMP,   -- When upcoming_player_game_context was last updated
  source_upcoming_context_rows_found INT64,         -- Should be 1 (today's context record)
  source_upcoming_context_completeness_pct NUMERIC(5,2), -- Should be 100% (1 row expected)

  source_upcoming_context_hash STRING,              -- Hash from upcoming_player_game_context.data_hash
                                                     -- Used for smart reprocessing (Pattern #3)

  -- ============================================================================
  -- SOURCE TRACKING: player_shot_zone_analysis (3 fields)
  -- Dependency v4.0 tracking for shot zone tendencies
  -- ============================================================================
  source_shot_zone_last_updated TIMESTAMP,          -- When player_shot_zone_analysis was last updated
  source_shot_zone_rows_found INT64,                -- Should be 1 (today's analysis)
  source_shot_zone_completeness_pct NUMERIC(5,2),   -- Should be 100% (1 row expected)

  source_shot_zone_hash STRING,                     -- Hash from player_shot_zone_analysis.data_hash
                                                     -- Used for smart reprocessing (Pattern #3)
                                                     -- Note: This is a Phase 4 → Phase 4 dependency!

  -- ============================================================================
  -- SMART IDEMPOTENCY (Pattern #1) - 1 field
  -- ============================================================================
  data_hash STRING,                                 -- SHA256 hash of meaningful output fields
                                                     -- Computed from: all cached player data
                                                     -- Excludes: processed_at, created_at, source tracking
                                                     -- Used to detect if cached values changed
                                                     -- NULL = pattern not yet implemented

  -- ============================================================================
  -- SOURCE TRACKING: Optional fields (2 fields)
  -- Used when data is insufficient (early season, injuries, etc.)
  -- ============================================================================
  early_season_flag BOOLEAN,                        -- TRUE if player has < 10 games
  insufficient_data_reason STRING,                  -- Why data was insufficient (if early_season_flag = TRUE)

  -- ============================================================================
  -- HISTORICAL COMPLETENESS CHECKING (14 fields)
  -- Week 3 - Phase 4 Completeness Checking
  -- ============================================================================
  -- Completeness Metrics (4 fields)
  expected_games_count INT64,                       -- Games expected from schedule
  actual_games_count INT64,                         -- Games actually found in upstream table
  completeness_percentage FLOAT64,                  -- Completeness percentage 0-100%
  missing_games_count INT64,                        -- Number of games missing from upstream

  -- Production Readiness (2 fields)
  is_production_ready BOOLEAN,                      -- TRUE if completeness >= 90%
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

  -- ============================================================================
  -- MULTI-WINDOW COMPLETENESS (9 fields)
  -- Week 3 - Multi-Window Tracking (L5, L10, L7d, L14d)
  -- ALL windows must be 90% complete for production-ready status
  -- ============================================================================
  l5_completeness_pct FLOAT64,                      -- L5 games completeness percentage
  l5_is_complete BOOLEAN,                           -- TRUE if L5 >= 90% complete
  l10_completeness_pct FLOAT64,                     -- L10 games completeness percentage
  l10_is_complete BOOLEAN,                          -- TRUE if L10 >= 90% complete
  l7d_completeness_pct FLOAT64,                     -- L7 days completeness percentage
  l7d_is_complete BOOLEAN,                          -- TRUE if L7d >= 90% complete
  l14d_completeness_pct FLOAT64,                    -- L14 days completeness percentage
  l14d_is_complete BOOLEAN,                         -- TRUE if L14d >= 90% complete
  all_windows_complete BOOLEAN,                     -- TRUE if ALL windows >= 90% complete

  -- ============================================================================
  -- CACHE METADATA (3 fields)
  -- Version tracking and processing timestamps
  -- ============================================================================
  cache_version STRING,                             -- Version identifier: "v1", "v2", etc.
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When record was first created
  processed_at TIMESTAMP                            -- When this cache was generated
)
PARTITION BY cache_date
CLUSTER BY player_lookup, universal_player_id
OPTIONS(
  description="Daily snapshot of player data that won't change intraday. Updated once at 12 AM. Speeds up line change re-predictions by caching stable data. Sources: nba_analytics.player_game_summary, nba_analytics.team_offense_game_summary, nba_analytics.upcoming_player_game_context, nba_precompute.player_shot_zone_analysis. Cost savings: 79% reduction vs repeated queries. Performance: 2000x faster lookups.",
  partition_expiration_days=30
);

-- ============================================================================
-- INDEXES & PERFORMANCE NOTES
-- ============================================================================
-- Partition key: cache_date
--   - Enables efficient pruning by date
--   - Automatic partition expiration after 30 days
--   - Typical query: WHERE cache_date = CURRENT_DATE()
--
-- Cluster keys: player_lookup, universal_player_id
--   - Co-locates records for same player
--   - Optimizes Phase 5 lookups by player
--   - Typical query: WHERE player_lookup = 'lebronjames' AND cache_date = CURRENT_DATE()
--
-- Expected cardinality:
--   - ~450 rows per day (one per active player)
--   - ~13,500 rows per month (450 × 30 days)
--   - Auto-expires after 30 days to control costs
-- ============================================================================

-- ============================================================================
-- SAMPLE ROW (Normal Mid-Season Player)
-- ============================================================================
/*
{
  -- Identifiers
  "player_lookup": "lebronjames",
  "universal_player_id": "lebronjames_001",
  "cache_date": "2025-01-21",
  
  -- Recent Performance
  "points_avg_last_5": 27.6,
  "points_avg_last_10": 26.4,
  "points_avg_season": 25.8,
  "points_std_last_10": 3.42,
  "minutes_avg_last_10": 35.8,
  "usage_rate_last_10": 30.8,
  "ts_pct_last_10": 0.618,
  "games_played_season": 45,
  
  -- Team Context
  "team_pace_last_10": 103.2,
  "team_off_rating_last_10": 115.6,
  "player_usage_rate_season": 29.9,
  
  -- Fatigue Metrics
  "games_in_last_7_days": 3,
  "games_in_last_14_days": 5,
  "minutes_in_last_7_days": 108,
  "minutes_in_last_14_days": 176,
  "back_to_backs_last_14_days": 1,
  "avg_minutes_per_game_last_7": 36.0,
  "fourth_quarter_minutes_last_7": 28,
  
  -- Shot Zone Tendencies
  "primary_scoring_zone": "paint",
  "paint_rate_last_10": 48.3,
  "three_pt_rate_last_10": 31.2,
  "assisted_rate_last_10": 0.423,
  
  -- Demographics
  "player_age": 40,
  
  -- Source Tracking
  "source_player_game_last_updated": "2025-01-21T02:15:00Z",
  "source_player_game_rows_found": 45,
  "source_player_game_completeness_pct": 100.0,
  
  "source_team_offense_last_updated": "2025-01-21T02:20:00Z",
  "source_team_offense_rows_found": 10,
  "source_team_offense_completeness_pct": 100.0,
  
  "source_upcoming_context_last_updated": "2025-01-20T23:45:00Z",
  "source_upcoming_context_rows_found": 1,
  "source_upcoming_context_completeness_pct": 100.0,
  
  "source_shot_zone_last_updated": "2025-01-21T00:05:00Z",
  "source_shot_zone_rows_found": 1,
  "source_shot_zone_completeness_pct": 100.0,
  
  -- Early Season
  "early_season_flag": false,
  "insufficient_data_reason": null,
  
  -- Metadata
  "cache_version": "v1",
  "created_at": "2025-01-21T00:15:00Z",
  "processed_at": "2025-01-21T00:15:00Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Early Season Rookie - Limited Data)
-- ============================================================================
/*
{
  -- Identifiers
  "player_lookup": "victorwembanyama",
  "universal_player_id": "victorwembanyama_001",
  "cache_date": "2024-11-05",
  
  -- Recent Performance (only 7 games played)
  "points_avg_last_5": 23.4,
  "points_avg_last_10": 23.4,                       -- Only 7 games, so same as season
  "points_avg_season": 23.4,
  "points_std_last_10": 4.89,                       -- Higher volatility with small sample
  "minutes_avg_last_10": 31.2,
  "usage_rate_last_10": 28.5,
  "ts_pct_last_10": 0.571,
  "games_played_season": 7,                         -- Small sample size!
  
  -- Team Context (also limited data)
  "team_pace_last_10": 98.7,
  "team_off_rating_last_10": 112.3,
  "player_usage_rate_season": 28.5,
  
  -- Fatigue Metrics (copied from context)
  "games_in_last_7_days": 2,
  "games_in_last_14_days": 4,
  "minutes_in_last_7_days": 62,
  "minutes_in_last_14_days": 125,
  "back_to_backs_last_14_days": 0,
  "avg_minutes_per_game_last_7": 31.0,
  "fourth_quarter_minutes_last_7": 18,
  
  -- Shot Zone Tendencies
  "primary_scoring_zone": "paint",
  "paint_rate_last_10": 52.1,
  "three_pt_rate_last_10": 25.6,
  "assisted_rate_last_10": 0.615,                   -- Rookie, more assisted shots
  
  -- Demographics
  "player_age": 20,
  
  -- Source Tracking (all sources present but limited data)
  "source_player_game_last_updated": "2024-11-05T02:10:00Z",
  "source_player_game_rows_found": 7,               -- Only 7 games!
  "source_player_game_completeness_pct": 70.0,      -- 7/10 = 70%
  
  "source_team_offense_last_updated": "2024-11-05T02:18:00Z",
  "source_team_offense_rows_found": 7,
  "source_team_offense_completeness_pct": 70.0,
  
  "source_upcoming_context_last_updated": "2024-11-04T23:40:00Z",
  "source_upcoming_context_rows_found": 1,
  "source_upcoming_context_completeness_pct": 100.0,
  
  "source_shot_zone_last_updated": "2024-11-05T00:02:00Z",
  "source_shot_zone_rows_found": 1,
  "source_shot_zone_completeness_pct": 100.0,       -- Shot zones work with 7 games
  
  -- Early Season (flagged!)
  "early_season_flag": true,
  "insufficient_data_reason": "Only 7 games played, need 10 minimum",
  
  -- Metadata
  "cache_version": "v1",
  "created_at": "2024-11-05T00:17:00Z",
  "processed_at": "2024-11-05T00:17:00Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Injured Player Returning - Stale Data Warning)
-- ============================================================================
/*
{
  -- Identifiers
  "player_lookup": "kawhileonard",
  "universal_player_id": "kawhileonard_001",
  "cache_date": "2025-01-21",
  
  -- Recent Performance (hasn't played in 14 days)
  "points_avg_last_5": 24.8,                        -- From games 14-21 days ago
  "points_avg_last_10": 25.1,
  "points_avg_season": 24.9,
  "points_std_last_10": 3.21,
  "minutes_avg_last_10": 33.5,
  "usage_rate_last_10": 29.2,
  "ts_pct_last_10": 0.642,
  "games_played_season": 28,                        -- But last game was 14 days ago
  
  -- Team Context (current, but player wasn't playing)
  "team_pace_last_10": 101.8,
  "team_off_rating_last_10": 114.2,
  "player_usage_rate_season": 29.2,
  
  -- Fatigue Metrics (will show rested)
  "games_in_last_7_days": 0,                        -- Injured!
  "games_in_last_14_days": 0,                       -- No games
  "minutes_in_last_7_days": 0,
  "minutes_in_last_14_days": 0,
  "back_to_backs_last_14_days": 0,
  "avg_minutes_per_game_last_7": 0.0,
  "fourth_quarter_minutes_last_7": 0,
  
  -- Shot Zone Tendencies (from before injury)
  "primary_scoring_zone": "mid_range",
  "paint_rate_last_10": 35.2,
  "three_pt_rate_last_10": 38.4,
  "assisted_rate_last_10": 0.512,
  
  -- Demographics
  "player_age": 33,
  
  -- Source Tracking (player_game is stale!)
  "source_player_game_last_updated": "2025-01-07T02:15:00Z",  -- 14 days old!
  "source_player_game_rows_found": 28,
  "source_player_game_completeness_pct": 100.0,
  
  "source_team_offense_last_updated": "2025-01-21T02:20:00Z",  -- Current
  "source_team_offense_rows_found": 10,
  "source_team_offense_completeness_pct": 100.0,
  
  "source_upcoming_context_last_updated": "2025-01-20T23:45:00Z",  -- Current
  "source_upcoming_context_rows_found": 1,
  "source_upcoming_context_completeness_pct": 100.0,
  
  "source_shot_zone_last_updated": "2025-01-07T00:05:00Z",  -- 14 days old!
  "source_shot_zone_rows_found": 1,
  "source_shot_zone_completeness_pct": 100.0,
  
  -- Early Season
  "early_season_flag": false,
  "insufficient_data_reason": null,
  
  -- Metadata
  "cache_version": "v1",
  "created_at": "2025-01-21T00:15:00Z",
  "processed_at": "2025-01-21T00:15:00Z"
}
*/

-- ============================================================================
-- USAGE EXAMPLE: Phase 5 Morning Load (6 AM)
-- ============================================================================
-- Load all player cache data into memory at startup
-- SELECT * 
-- FROM `nba-props-platform.nba_precompute.player_daily_cache`
-- WHERE cache_date = CURRENT_DATE()
-- ORDER BY player_lookup;
--
-- This query runs ONCE at 6 AM and loads ~450 players into memory.
-- Phase 5 then reuses this cached data for all real-time updates during the day.
-- ============================================================================

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Check cache completeness for today
-- Expected: ~450 players (all with games today)
SELECT 
  cache_date,
  COUNT(DISTINCT player_lookup) as players_cached,
  COUNT(CASE WHEN early_season_flag = TRUE THEN 1 END) as early_season_count,
  
  -- Average completeness across all sources
  AVG(source_player_game_completeness_pct) as avg_player_game_completeness,
  AVG(source_team_offense_completeness_pct) as avg_team_offense_completeness,
  AVG(source_upcoming_context_completeness_pct) as avg_context_completeness,
  AVG(source_shot_zone_completeness_pct) as avg_shot_zone_completeness,
  
  -- Processing time
  MIN(processed_at) as first_processed,
  MAX(processed_at) as last_processed,
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE) as processing_duration_mins
  
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
GROUP BY cache_date;

-- Query 2: Check source data freshness
-- Expected: All sources <24 hours old
SELECT 
  cache_date,
  player_lookup,
  
  -- Calculate age for each source
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR) as player_game_age_hrs,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR) as team_offense_age_hrs,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR) as context_age_hrs,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR) as shot_zone_age_hrs,
  
  -- Identify stalest source
  GREATEST(
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)
  ) as stalest_source_age_hrs
  
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
  AND GREATEST(
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)
  ) > 24
ORDER BY stalest_source_age_hrs DESC;

-- Query 3: Find players with low data completeness
-- Expected: 0 rows (all players have complete data)
SELECT 
  cache_date,
  player_lookup,
  games_played_season,
  
  -- Completeness by source
  source_player_game_completeness_pct,
  source_team_offense_completeness_pct,
  source_upcoming_context_completeness_pct,
  source_shot_zone_completeness_pct,
  
  -- Identify bottleneck source
  CASE
    WHEN source_player_game_completeness_pct < 85 THEN 'player_game'
    WHEN source_team_offense_completeness_pct < 85 THEN 'team_offense'
    WHEN source_upcoming_context_completeness_pct < 85 THEN 'upcoming_context'
    WHEN source_shot_zone_completeness_pct < 85 THEN 'shot_zone'
    ELSE 'all_good'
  END as problem_source,
  
  early_season_flag,
  insufficient_data_reason
  
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
  AND (
    source_player_game_completeness_pct < 85 OR
    source_team_offense_completeness_pct < 85 OR
    source_upcoming_context_completeness_pct < 85 OR
    source_shot_zone_completeness_pct < 85
  )
ORDER BY 
  LEAST(
    source_player_game_completeness_pct,
    source_team_offense_completeness_pct,
    source_upcoming_context_completeness_pct,
    source_shot_zone_completeness_pct
  ) ASC;

-- Query 4: Find missing players (scheduled to play but no cache)
-- Expected: 0 rows (all scheduled players have cache)
SELECT 
  upg.player_lookup,
  upg.player_full_name,
  upg.team_abbr,
  upg.opponent_team_abbr,
  COUNT(DISTINCT pgs.game_id) as games_played_season,
  
  -- Why might they be missing?
  CASE 
    WHEN COUNT(DISTINCT pgs.game_id) < 5 THEN 'too_few_games'
    WHEN MAX(pgs.game_date) < DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY) THEN 'injured_recently'
    ELSE 'unknown'
  END as likely_reason
  
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context` upg
LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
  ON upg.player_lookup = pdc.player_lookup
  AND upg.game_date = pdc.cache_date
LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON upg.player_lookup = pgs.player_lookup
  AND pgs.season_year = EXTRACT(YEAR FROM upg.game_date)
WHERE upg.game_date = CURRENT_DATE()
  AND pdc.player_lookup IS NULL  -- Not in cache
GROUP BY 1, 2, 3, 4
ORDER BY 5 DESC;

-- Query 5: Distribution of key metrics
-- Shows typical values for cache data
SELECT 
  cache_date,
  
  -- Performance metrics distribution
  APPROX_QUANTILES(points_avg_season, 100)[OFFSET(25)] as points_p25,
  APPROX_QUANTILES(points_avg_season, 100)[OFFSET(50)] as points_median,
  APPROX_QUANTILES(points_avg_season, 100)[OFFSET(75)] as points_p75,
  
  -- Usage distribution
  APPROX_QUANTILES(usage_rate_last_10, 100)[OFFSET(25)] as usage_p25,
  APPROX_QUANTILES(usage_rate_last_10, 100)[OFFSET(50)] as usage_median,
  APPROX_QUANTILES(usage_rate_last_10, 100)[OFFSET(75)] as usage_p75,
  
  -- Minutes distribution
  APPROX_QUANTILES(minutes_avg_last_10, 100)[OFFSET(25)] as minutes_p25,
  APPROX_QUANTILES(minutes_avg_last_10, 100)[OFFSET(50)] as minutes_median,
  APPROX_QUANTILES(minutes_avg_last_10, 100)[OFFSET(75)] as minutes_p75,
  
  -- Fatigue metrics
  AVG(games_in_last_7_days) as avg_games_last_7,
  AVG(back_to_backs_last_14_days) as avg_back_to_backs,
  
  COUNT(*) as total_players
  
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND early_season_flag IS NULL
GROUP BY cache_date
ORDER BY cache_date DESC;

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Latest cache for today's games
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_latest_player_cache` AS
SELECT 
  player_lookup,
  universal_player_id,
  cache_date,
  
  -- Recent Performance
  points_avg_last_5,
  points_avg_last_10,
  points_avg_season,
  points_std_last_10,
  minutes_avg_last_10,
  usage_rate_last_10,
  ts_pct_last_10,
  games_played_season,
  
  -- Team Context
  team_pace_last_10,
  team_off_rating_last_10,
  player_usage_rate_season,
  
  -- Fatigue
  games_in_last_7_days,
  games_in_last_14_days,
  minutes_in_last_7_days,
  back_to_backs_last_14_days,
  
  -- Shot Zones
  primary_scoring_zone,
  paint_rate_last_10,
  three_pt_rate_last_10,
  assisted_rate_last_10,
  
  -- Quality
  early_season_flag,
  processed_at
  
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
  AND early_season_flag IS NULL
ORDER BY player_lookup;

-- View: Cache quality summary
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_cache_quality_summary` AS
SELECT 
  cache_date,
  COUNT(*) as total_players,
  
  -- Completeness
  AVG(source_player_game_completeness_pct) as avg_completeness_player_game,
  AVG(source_team_offense_completeness_pct) as avg_completeness_team_offense,
  AVG(source_upcoming_context_completeness_pct) as avg_completeness_context,
  AVG(source_shot_zone_completeness_pct) as avg_completeness_shot_zone,
  
  -- Minimum completeness (bottleneck)
  MIN(LEAST(
    source_player_game_completeness_pct,
    source_team_offense_completeness_pct,
    source_upcoming_context_completeness_pct,
    source_shot_zone_completeness_pct
  )) as min_completeness_any_source,
  
  -- Freshness
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR)) as max_age_player_game,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR)) as max_age_team_offense,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR)) as max_age_context,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)) as max_age_shot_zone,
  
  -- Flags
  SUM(CASE WHEN early_season_flag THEN 1 ELSE 0 END) as early_season_count,
  
  -- Processing
  MIN(processed_at) as first_processed,
  MAX(processed_at) as last_processed
  
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY cache_date
ORDER BY cache_date DESC;

-- View: Players with stale or incomplete data
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_cache_data_issues` AS
SELECT 
  cache_date,
  player_lookup,
  
  -- Issue classification
  CASE
    WHEN GREATEST(
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)
    ) > 48 THEN 'CRITICAL_STALE'
    WHEN GREATEST(
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)
    ) > 24 THEN 'WARNING_STALE'
    WHEN LEAST(
      source_player_game_completeness_pct,
      source_team_offense_completeness_pct,
      source_upcoming_context_completeness_pct,
      source_shot_zone_completeness_pct
    ) < 70 THEN 'CRITICAL_INCOMPLETE'
    WHEN LEAST(
      source_player_game_completeness_pct,
      source_team_offense_completeness_pct,
      source_upcoming_context_completeness_pct,
      source_shot_zone_completeness_pct
    ) < 85 THEN 'WARNING_INCOMPLETE'
    ELSE 'UNKNOWN'
  END as issue_type,
  
  -- Metrics
  LEAST(
    source_player_game_completeness_pct,
    source_team_offense_completeness_pct,
    source_upcoming_context_completeness_pct,
    source_shot_zone_completeness_pct
  ) as worst_completeness_pct,
  
  GREATEST(
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)
  ) as stalest_source_age_hrs,
  
  early_season_flag,
  insufficient_data_reason
  
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
  AND (
    GREATEST(
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR),
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)
    ) > 24
    OR LEAST(
      source_player_game_completeness_pct,
      source_team_offense_completeness_pct,
      source_upcoming_context_completeness_pct,
      source_shot_zone_completeness_pct
    ) < 85
  )
ORDER BY 
  CASE issue_type
    WHEN 'CRITICAL_STALE' THEN 1
    WHEN 'CRITICAL_INCOMPLETE' THEN 2
    WHEN 'WARNING_STALE' THEN 3
    WHEN 'WARNING_INCOMPLETE' THEN 4
    ELSE 5
  END,
  worst_completeness_pct ASC;

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Alert: Too few players cached (<400)
SELECT 
  'player_daily_cache' as processor,
  cache_date,
  COUNT(*) as players_cached
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
GROUP BY cache_date
HAVING COUNT(*) < 400;

-- Alert: Stale source data (>24 hours old)
SELECT 
  'player_daily_cache' as processor,
  cache_date,
  MAX(GREATEST(
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)
  )) as max_age_hours
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY cache_date
HAVING MAX(GREATEST(
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR)
)) > 24;

-- Alert: Low completeness (<85%)
SELECT 
  'player_daily_cache' as processor,
  cache_date,
  AVG(LEAST(
    source_player_game_completeness_pct,
    source_team_offense_completeness_pct,
    source_upcoming_context_completeness_pct,
    source_shot_zone_completeness_pct
  )) as avg_min_completeness,
  MIN(LEAST(
    source_player_game_completeness_pct,
    source_team_offense_completeness_pct,
    source_upcoming_context_completeness_pct,
    source_shot_zone_completeness_pct
  )) as worst_completeness
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY cache_date
HAVING MIN(LEAST(
  source_player_game_completeness_pct,
  source_team_offense_completeness_pct,
  source_upcoming_context_completeness_pct,
  source_shot_zone_completeness_pct
)) < 85;

-- Alert: Processing took too long (>15 minutes)
SELECT 
  'player_daily_cache' as processor,
  cache_date,
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE) as processing_duration_mins
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()
GROUP BY cache_date
HAVING TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE) > 15;

-- ============================================================================
-- USAGE IN PHASE 5 PREDICTIONS
-- ============================================================================
-- 
-- Morning Load (6 AM):
--   1. Load all cache records for today into memory (450 rows)
--   2. Convert to dictionary keyed by player_lookup
--   3. Keep in memory for entire day
--
-- Real-Time Updates (Throughout Day):
--   1. Prop line changes (10-50 times/day)
--   2. Lookup player in cached dict (<1ms)
--   3. Use cached recent performance, fatigue, shot zones
--   4. Only recalculate line-dependent factors
--   5. Generate updated prediction
--
-- Cache Miss Handling:
--   - If player not in cache, fall back to BigQuery query
--   - Log cache miss for monitoring
--   - Consider this player for next day's cache
--
-- Performance:
--   - Without cache: 2-3 seconds per update (BigQuery query)
--   - With cache: <100ms per update (in-memory lookup)
--   - Speedup: 20-30x faster
--
-- ============================================================================

-- ============================================================================
-- ALERT CONDITIONS
-- ============================================================================
-- Alert if:
-- 1. <400 players cached (should be ~450 on game days)
-- 2. Any source >24 hours old
-- 3. Minimum completeness <85%
-- 4. Processing duration >15 minutes
-- 5. >10% of players with early_season_flag
-- 6. Cache not rebuilt for 2+ days
-- ============================================================================

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create table in nba_precompute dataset
-- [ ] Verify schema matches processor expectations (43 fields total)
-- [ ] Set partition expiration (30 days)
-- [ ] Configure clustering (player_lookup, universal_player_id)
-- [ ] Test with sample data (10-20 players)
-- [ ] Validate all tracking fields populate correctly
-- [ ] Test early season handling (< 10 games)
-- [ ] Test injured player handling (stale data)
-- [ ] Enable monitoring queries
-- [ ] Create alert rules with thresholds
-- [ ] Create helper views (v_latest_player_cache, v_cache_quality_summary, v_cache_data_issues)
-- [ ] Document Phase 5 integration points
-- [ ] Test cache load performance at 6 AM
-- [ ] Verify cache miss handling works
-- [ ] Set up dashboard for cache health monitoring
-- ============================================================================

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Check cache completeness for today
-- SELECT 
--   COUNT(DISTINCT player_lookup) as players_cached,
--   AVG(source_player_game_completeness_pct) as avg_completeness,
--   SUM(CASE WHEN early_season_flag THEN 1 ELSE 0 END) as early_season_count,
--   MIN(processed_at) as first_processed,
--   MAX(processed_at) as last_processed
-- FROM `nba-props-platform.nba_precompute.player_daily_cache`
-- WHERE cache_date = CURRENT_DATE();

-- Check source freshness (all sources should be < 24 hours old)
-- SELECT 
--   player_lookup,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR) as player_game_age_hrs,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR) as team_offense_age_hrs,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR) as context_age_hrs,
--   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR) as shot_zone_age_hrs
-- FROM `nba-props-platform.nba_precompute.player_daily_cache`
-- WHERE cache_date = CURRENT_DATE()
--   AND (
--     TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_game_last_updated, HOUR) > 24 OR
--     TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_offense_last_updated, HOUR) > 24 OR
--     TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_context_last_updated, HOUR) > 24 OR
--     TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_shot_zone_last_updated, HOUR) > 24
--   )
-- ORDER BY player_game_age_hrs DESC;

-- Find players missing from cache (scheduled to play but no cache record)
-- SELECT 
--   upg.player_lookup,
--   upg.player_full_name,
--   upg.team_abbr,
--   upg.opponent_team_abbr,
--   COUNT(DISTINCT pgs.game_id) as games_played_season
-- FROM `nba-props-platform.nba_analytics.upcoming_player_game_context` upg
-- LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
--   ON upg.player_lookup = pdc.player_lookup
--   AND upg.game_date = pdc.cache_date
-- LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
--   ON upg.player_lookup = pgs.player_lookup
--   AND pgs.season_year = EXTRACT(YEAR FROM upg.game_date)
-- WHERE upg.game_date = CURRENT_DATE()
--   AND pdc.player_lookup IS NULL  -- Not in cache
-- GROUP BY 1, 2, 3, 4
-- ORDER BY 5 DESC;

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 43
--   Business fields: 26
--     - Identifiers: 3
--     - Recent performance: 8
--     - Team context: 3
--     - Fatigue metrics: 7
--     - Shot zones: 4
--     - Demographics: 1
--   
--   Tracking fields: 17
--     - Source tracking (4 sources × 3 fields): 12
--     - Optional tracking: 2
--     - Metadata: 3
-- ============================================================================

-- ============================================================================
-- DEPENDENCIES
-- ============================================================================
-- Phase 3 (CRITICAL):
--   1. nba_analytics.player_game_summary (performance stats)
--   2. nba_analytics.team_offense_game_summary (team context)
--   3. nba_analytics.upcoming_player_game_context (fatigue metrics)
--
-- Phase 4 (CRITICAL):
--   4. nba_precompute.player_shot_zone_analysis (shot zones)
--
-- Run Order:
--   Phase 3 → Complete by 11:45 PM
--   Phase 4 (player_shot_zone_analysis) → Complete by 11:55 PM
--   Phase 4 (player_daily_cache) → Runs at 12:00 AM
--   Phase 5 → Loads cache at 6:00 AM
-- ============================================================================

-- ============================================================================
-- CHANGE LOG
-- ============================================================================
-- 2025-11-22: Week 3 - Added completeness checking (23 fields)
--   - 14 standard completeness checking columns
--   - 9 multi-window completeness tracking columns (L5, L10, L7d, L14d)
--   - Total fields: 43 → 66
-- 2025-10-30: Initial schema creation
--   - 26 business fields for player performance caching
--   - 17 tracking fields for dependency monitoring (v4.0)
--   - Removed player_position (unreliable data source)
--   - Added source tracking for 4 upstream dependencies
--   - Optimized for Phase 5 real-time prediction updates
-- ============================================================================

-- ============================================================================
-- ALTER TABLE (For Adding Completeness Checking - Week 3)
-- ============================================================================
-- Run this to add completeness checking columns to existing table:

ALTER TABLE `nba-props-platform.nba_precompute.player_daily_cache`

-- Historical completeness checking (14 fields)
ADD COLUMN IF NOT EXISTS expected_games_count INT64
  OPTIONS (description='Games expected from schedule'),
ADD COLUMN IF NOT EXISTS actual_games_count INT64
  OPTIONS (description='Games actually found in upstream table'),
ADD COLUMN IF NOT EXISTS completeness_percentage FLOAT64
  OPTIONS (description='Completeness percentage 0-100%'),
ADD COLUMN IF NOT EXISTS missing_games_count INT64
  OPTIONS (description='Number of games missing from upstream'),

ADD COLUMN IF NOT EXISTS is_production_ready BOOLEAN
  OPTIONS (description='TRUE if completeness >= 90%'),
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

-- Multi-window completeness tracking (9 fields)
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
ADD COLUMN IF NOT EXISTS all_windows_complete BOOLEAN
  OPTIONS (description='TRUE if ALL windows >= 90% complete');

-- ============================================================================
-- Verify deployment:
-- ============================================================================
-- SELECT column_name, data_type, description
-- FROM `nba-props-platform.nba_precompute.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS`
-- WHERE table_name = 'player_daily_cache'
--   AND column_name IN ('completeness_percentage', 'is_production_ready', 'all_windows_complete')
-- ORDER BY column_name;
-- ============================================================================