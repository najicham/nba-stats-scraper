-- ============================================================================
-- NBA Props Platform - Player Game Summary Analytics Table
-- Complete player performance with shot zone tracking and multi-source fallback
-- File: schemas/bigquery/analytics/player_game_summary_tables.sql
-- ============================================================================
--
-- PHASE 3 ANALYTICS PROCESSOR
-- Data Sources: 6 Phase 2 raw tables with intelligent fallback logic
-- Processing: PlayerGameSummaryProcessor (MERGE_UPDATE strategy for multi-pass)
--
-- This table provides complete player game performance analytics combining:
-- - Core stats from NBA.com Gamebook (primary) → BDL fallback
-- - Shot zones from Big Ball Data → NBA.com PBP → Estimation fallback
-- - Prop lines from Odds API → BettingPros fallback
-- - Universal player identification via RegistryReader
--
-- Multi-Pass Processing Strategy:
-- Pass 1 (~1-2 hrs after game): Core stats (NBA.com/BDL)
-- Pass 2 (~4 hrs after game):   Shot zones (Big Ball Data/NBA.com PBP/estimation)
-- Pass 3 (anytime after game):  Prop results calculation
--
-- Key Phase 2 Dependencies (in priority order):
-- 1. nba_raw.nbac_gamebook_player_stats - PRIMARY stats (95% coverage, has plus_minus)
-- 2. nba_raw.bdl_player_boxscores - FALLBACK stats (100% coverage, no plus_minus)
-- 3. nba_raw.bigdataball_play_by_play - PREFERRED shot zones (variable coverage)
-- 4. nba_raw.nbac_play_by_play - BACKUP shot zones (95% coverage, unverified)
-- 5. nba_raw.odds_api_player_points_props - PRIMARY prop lines (60-70% players)
-- 6. nba_raw.bettingpros_player_points_props - BACKUP prop lines (60-70% players)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.player_game_summary` (
  -- ============================================================================
  -- CORE IDENTIFIERS (8 fields)
  -- ============================================================================
  player_lookup STRING NOT NULL,                    -- Normalized player identifier (join key)
  universal_player_id STRING,                       -- Universal player ID from registry (e.g., lebronjames_2024)
  player_full_name STRING,                          -- Display name for reports
  game_id STRING NOT NULL,                          -- Unique game identifier: "20250120_BKN_MIL"
  game_date DATE NOT NULL,                          -- Game date (partition key)
  team_abbr STRING NOT NULL,                        -- Player's team abbreviation
  opponent_team_abbr STRING NOT NULL,               -- Opposing team abbreviation
  season_year INT64 NOT NULL,                       -- Season year (2024 for 2024-25 season)
  
  -- ============================================================================
  -- BASIC PERFORMANCE STATS (16 fields)
  -- From NBA.com Gamebook (primary) or BDL Boxscores (fallback)
  -- ============================================================================
  points INT64,                                     -- Total points scored
  minutes_played NUMERIC(5,1),                      -- Minutes played (decimal format)
  assists INT64,                                    -- Total assists
  offensive_rebounds INT64,                         -- Offensive rebounds
  defensive_rebounds INT64,                         -- Defensive rebounds
  steals INT64,                                     -- Total steals
  blocks INT64,                                     -- Total blocks
  turnovers INT64,                                  -- Total turnovers
  fg_attempts INT64,                                -- Total field goal attempts
  fg_makes INT64,                                   -- Total field goal makes
  three_pt_attempts INT64,                          -- Three-point attempts
  three_pt_makes INT64,                             -- Three-point makes
  ft_attempts INT64,                                -- Free throw attempts
  ft_makes INT64,                                   -- Free throw makes
  plus_minus INT64,                                 -- Plus/minus (NBA.com only)
  personal_fouls INT64,                             -- Personal fouls committed
  
  -- ============================================================================
  -- SHOT ZONE PERFORMANCE (8 fields)
  -- From Big Ball Data (preferred) → NBA.com PBP (backup) → Estimation (fallback)
  -- ============================================================================
  paint_attempts INT64,                             -- Field goal attempts in paint (≤8 feet)
  paint_makes INT64,                                -- Field goal makes in paint
  mid_range_attempts INT64,                         -- Mid-range attempts (9-23 feet, 2PT)
  mid_range_makes INT64,                            -- Mid-range makes
  paint_blocks INT64,                               -- Blocks on paint shots (Big Ball Data only)
  mid_range_blocks INT64,                           -- Blocks on mid-range shots (Big Ball Data only)
  three_pt_blocks INT64,                            -- Blocks on three-point shots (Big Ball Data only)
  and1_count INT64,                                 -- Made FG + shooting foul drawn (Big Ball Data only)
  
  -- ============================================================================
  -- SHOT CREATION ANALYSIS (2 fields)
  -- From Big Ball Data play-by-play (when available)
  -- ============================================================================
  assisted_fg_makes INT64,                          -- Made FGs that were assisted
  unassisted_fg_makes INT64,                        -- Made FGs unassisted (shot creation)
  
  -- ============================================================================
  -- ADVANCED EFFICIENCY (5 fields)
  -- Calculated from basic stats
  -- ============================================================================
  usage_rate NUMERIC(5,2),                          -- Percentage of team plays used (future)
  ts_pct NUMERIC(5,3),                              -- True Shooting percentage
  efg_pct NUMERIC(5,3),                             -- Effective Field Goal percentage
  starter_flag BOOLEAN NOT NULL,                    -- Whether player started (minutes > 20)
  win_flag BOOLEAN NOT NULL,                        -- Whether player's team won
  
  -- ============================================================================
  -- PROP BETTING RESULTS (7 fields)
  -- From Odds API (primary) or BettingPros (backup)
  -- ============================================================================
  points_line NUMERIC(4,1),                         -- Betting line for points prop (closing)
  over_under_result STRING,                         -- 'OVER', 'UNDER', or NULL
  margin NUMERIC(6,2),                              -- Actual points minus line
  opening_line NUMERIC(4,1),                        -- Opening betting line
  line_movement NUMERIC(4,1),                       -- Line movement (closing - opening)
  points_line_source STRING,                        -- Source of closing line (e.g., 'draftkings')
  opening_line_source STRING,                       -- Source of opening line
  
  -- ============================================================================
  -- PLAYER AVAILABILITY (2 fields)
  -- From NBA.com Gamebook or BDL Boxscores
  -- ============================================================================
  is_active BOOLEAN NOT NULL,                       -- Whether player played
  player_status STRING,                             -- 'active', 'inactive', 'dnp', etc.
  
  -- ============================================================================
  -- PHASE 2 SOURCE TRACKING (24 fields = 6 sources × 4 fields each)
  -- Per dependency tracking guide v4.0 + Smart Idempotency (Pattern #14)
  -- ============================================================================
  
  -- SOURCE 1: NBA.com Gamebook Player Stats (PRIMARY - Critical)
  -- nba_raw.nbac_gamebook_player_stats
  source_nbac_last_updated TIMESTAMP,               -- When NBA.com gamebook was last processed
  source_nbac_rows_found INT64,                     -- How many NBA.com records found for this game
  source_nbac_completeness_pct NUMERIC(5,2),        -- % of expected active players found
  source_nbac_hash STRING,                          -- Smart Idempotency: data_hash from nbac_gamebook_player_stats

  -- SOURCE 2: Ball Don't Lie Player Boxscores (FALLBACK - Critical)
  -- nba_raw.bdl_player_boxscores
  source_bdl_last_updated TIMESTAMP,                -- When BDL table was last processed
  source_bdl_rows_found INT64,                      -- How many BDL records found for this game
  source_bdl_completeness_pct NUMERIC(5,2),         -- % of expected players found
  source_bdl_hash STRING,                           -- Smart Idempotency: data_hash from bdl_player_boxscores

  -- SOURCE 3: Big Ball Data Play-by-Play (OPTIONAL - Shot zones preferred)
  -- nba_raw.bigdataball_play_by_play
  source_bbd_last_updated TIMESTAMP,                -- When Big Ball Data was last processed
  source_bbd_rows_found INT64,                      -- How many shot events found for this player
  source_bbd_completeness_pct NUMERIC(5,2),         -- % of expected shot events found
  source_bbd_hash STRING,                           -- Smart Idempotency: data_hash from bigdataball_play_by_play

  -- SOURCE 4: NBA.com Play-by-Play (BACKUP - Shot zones unverified)
  -- nba_raw.nbac_play_by_play
  source_nbac_pbp_last_updated TIMESTAMP,           -- When NBA.com PBP was last processed
  source_nbac_pbp_rows_found INT64,                 -- How many PBP shot events found for this player
  source_nbac_pbp_completeness_pct NUMERIC(5,2),    -- % of expected shot events found
  source_nbac_pbp_hash STRING,                      -- Smart Idempotency: data_hash from nbac_play_by_play

  -- SOURCE 5: Odds API Player Props (OPTIONAL - Prop lines primary)
  -- nba_raw.odds_api_player_points_props
  source_odds_last_updated TIMESTAMP,               -- When Odds API was last processed
  source_odds_rows_found INT64,                     -- How many prop snapshots found for this player
  source_odds_completeness_pct NUMERIC(5,2),        -- % of expected bookmakers found
  source_odds_hash STRING,                          -- Smart Idempotency: data_hash from odds_api_player_points_props

  -- SOURCE 6: BettingPros Player Props (BACKUP - Prop lines backup)
  -- nba_raw.bettingpros_player_points_props
  source_bp_last_updated TIMESTAMP,                 -- When BettingPros was last processed
  source_bp_rows_found INT64,                       -- How many prop records found for this player
  source_bp_completeness_pct NUMERIC(5,2),          -- % of expected bookmakers found
  source_bp_hash STRING,                            -- Smart Idempotency: data_hash from bettingpros_player_points_props
  
  -- ============================================================================
  -- DATA QUALITY FLAGS (4 fields)
  -- ============================================================================
  data_quality_tier STRING,                         -- 'high', 'medium', 'low' (based on source availability)
  primary_source_used STRING,                       -- Primary data source: 'nbac_gamebook', 'bdl_boxscores', 'nbac_bdl_combined'
  processed_with_issues BOOLEAN,                    -- Quality issues flag
  shot_zones_estimated BOOLEAN,                     -- TRUE if shot zones estimated (no play-by-play data)
  
  -- ============================================================================
  -- SMART REPROCESSING (1 field)
  -- Pattern #3: Phase 4 processors compare this hash to detect meaningful changes
  -- ============================================================================
  data_hash STRING,                                 -- SHA256 hash (16 chars) of meaningful analytics output fields

  -- ============================================================================
  -- PROCESSING METADATA (2 fields)
  -- ============================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When record first created (Pass 1)
  processed_at TIMESTAMP                            -- When record last processed/updated (Pass 1/2/3)
)
PARTITION BY game_date
CLUSTER BY universal_player_id, player_lookup, team_abbr, game_date
OPTIONS(
  description="Player game performance with multi-source fallback logic: NBA.com/BDL for stats, Big Ball Data/NBA.com PBP/estimation for shot zones, Odds API/BettingPros for prop lines. Universal player ID enables stable cross-season identification. MERGE_UPDATE strategy allows multi-pass enrichment as data becomes available. Smart idempotency tracks upstream Phase 2 data_hash values to skip reprocessing when source data unchanged."
);

-- ============================================================================
-- FIELD COUNT SUMMARY
-- ============================================================================
-- Core identifiers:           8 fields
-- Basic stats:               16 fields
-- Shot zones:                 8 fields
-- Shot creation:              2 fields
-- Advanced efficiency:        5 fields
-- Prop betting:               7 fields
-- Player availability:        2 fields
-- Source tracking:           24 fields (6 sources × 4 fields - includes smart idempotency hashes)
-- Data quality:               4 fields
-- Smart reprocessing:         1 field  (data_hash for Phase 4 optimization)
-- Processing metadata:        2 fields
-- -------------------------
-- TOTAL:                     79 fields

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
--    - 0 = source exists but query returned nothing (player didn't play, no props)
--    - Used for debugging data availability
--
-- 3. source_{prefix}_completeness_pct (NUMERIC(5,2))
--    - (rows_found / rows_expected) × 100, capped at 100%
--    - NULL = source doesn't exist (couldn't calculate)
--    - 0.0 = source exists, found 0% of expected data
--    - 100.0 = found all expected data (or more)
--    - Primary data quality metric
--
-- Source Priority Fallback Logic:
-- - Core Stats: source_nbac_* (primary) → source_bdl_* (fallback)
-- - Shot Zones: source_bbd_* (tier 1) → source_nbac_pbp_* (tier 2) → estimation (tier 3)
-- - Prop Lines: source_odds_* (primary) → source_bp_* (backup)

-- ============================================================================
-- DATA QUALITY TIER CALCULATION
-- ============================================================================
-- Quality tier assigned based on source availability (score 0-10):
--
-- HIGH (score ≥ 9):
--   - NBA.com gamebook present (3 points) OR BDL present (2 points)
--   - Actual shot zones from Big Ball Data (3 points) or NBA.com PBP (2 points)
--   - Shot creation data present (1 point)
--   - Prop lines present (1 point)
--   - No processing issues
--   Example: NBA.com + Big Ball Data + shot creation + props = 3+3+1+1 = 8 (needs +1 for high)
--
-- MEDIUM (score 6-8):
--   - BDL + NBA.com present (5 points)
--   - Estimated shot zones (1 point) OR actual zones (2-3 points)
--   - May have prop lines (1 point)
--   - Minor issues may be logged
--   Example: BDL + estimated zones = 2+1 = 3 (actually low, this example needs work)
--
-- LOW (score < 6):
--   - BDL only (2 points)
--   - No NBA.com enhancements
--   - No shot zones or estimated only (1 point)
--   - Missing prop lines
--   Example: BDL + estimated zones + no props = 2+1+0 = 3

-- ============================================================================
-- MULTI-PASS PROCESSING STRATEGY
-- ============================================================================
-- This table uses MERGE_UPDATE strategy to allow progressive enhancement:
--
-- Pass 1 (Immediate, ~1-2 hours after game):
--   - Extract core stats from NBA.com Gamebook or BDL Boxscores
--   - Create initial record with universal_player_id via RegistryReader
--   - Set shot zone fields to NULL (will update later)
--   - Set prop result fields to NULL (will update later)
--   - Populate source_nbac_* and source_bdl_* tracking fields
--   - Action: INSERT new records
--
-- Pass 2 (Enhanced, ~4 hours after game):
--   - Try Big Ball Data for shot zones (preferred)
--   - Fall back to NBA.com PBP if Big Ball unavailable/incomplete
--   - Fall back to estimation if no play-by-play available
--   - Update paint/mid_range/three_pt fields
--   - Update assisted/unassisted field goal tracking
--   - Set shot_zones_estimated flag
--   - Populate source_bbd_* and source_nbac_pbp_* tracking fields
--   - Action: MERGE UPDATE existing records (preserves created_at)
--
-- Pass 3 (Final, anytime after game):
--   - Extract prop lines from Odds API or BettingPros
--   - Calculate over/under result and margin
--   - Track line movement (opening vs closing)
--   - Populate source_odds_* and source_bp_* tracking fields
--   - Action: MERGE UPDATE existing records
--
-- Each pass updates processed_at but preserves created_at timestamp.
-- MERGE keys: [player_lookup, game_id]

-- ============================================================================
-- DEFERRED FIELDS (FUTURE IMPLEMENTATION)
-- ============================================================================
-- The following fields are included in the schema but may return NULL
-- until their processing logic is fully implemented:
--
-- Shot Zone Blocks (3 fields):
--   - paint_blocks, mid_range_blocks, three_pt_blocks
--   - Requires Big Ball Data play-by-play with block events
--   - Currently returns NULL if data unavailable
--
-- Shot Creation (2 fields):
--   - assisted_fg_makes, unassisted_fg_makes
--   - Requires Big Ball Data with assist role tracking
--   - Currently returns NULL if data unavailable
--
-- And-1 Count (1 field):
--   - and1_count
--   - Requires Big Ball Data with shooting foul correlation
--   - Currently returns NULL
--
-- Usage Rate (1 field):
--   - usage_rate
--   - Requires team-level possession data
--   - Currently returns NULL
--   - Planned for Phase 3.1 when team context available

-- ============================================================================
-- USAGE NOTES
-- ============================================================================
--
-- Partition Requirement: ALL queries MUST include game_date filter
--   ❌ WRONG: SELECT * FROM player_game_summary WHERE player_lookup = 'lebronjames'
--   ✅ RIGHT: SELECT * FROM player_game_summary WHERE player_lookup = 'lebronjames' AND game_date >= '2024-01-01'
--
-- Clustering: Optimized for queries filtering/joining on:
--   1. universal_player_id (cross-season player matching)
--   2. player_lookup (most common - player-specific queries)
--   3. team_abbr (team-based analysis)
--   4. game_date (time-based analysis)
--
-- Processing Strategy: MERGE_UPDATE
--   - Merge keys: [player_lookup, game_id]
--   - Allows multi-pass enrichment as data becomes available
--   - Updates existing records rather than creating duplicates
--   - created_at preserved, processed_at updated each pass
--
-- Data Freshness:
--   - Pass 1: Available 1-2 hours after game completion
--   - Pass 2: Enhanced 4-6 hours after game completion
--   - Pass 3: Final results anytime after game completion
--
-- Related Tables (Phase 2 raw sources):
--   - nba_raw.nbac_gamebook_player_stats (PRIMARY stats)
--   - nba_raw.bdl_player_boxscores (FALLBACK stats)
--   - nba_raw.bigdataball_play_by_play (PREFERRED shot zones)
--   - nba_raw.nbac_play_by_play (BACKUP shot zones)
--   - nba_raw.odds_api_player_points_props (PRIMARY prop lines)
--   - nba_raw.bettingpros_player_points_props (BACKUP prop lines)
--
-- Related Tables (Phase 3 consumers):
--   - nba_analytics.upcoming_player_game_context (uses historical performance)
--
-- Related Tables (Phase 4 consumers):
--   - nba_precompute.player_shot_zone_analysis (aggregates shot zones)
--   - nba_precompute.player_composite_factors (uses recent performance)

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- Get player's recent games with shot zone breakdown
/*
SELECT 
  game_date,
  opponent_team_abbr,
  points,
  minutes_played,
  -- Shot zones
  paint_makes || '/' || paint_attempts as paint,
  mid_range_makes || '/' || mid_range_attempts as mid_range,
  three_pt_makes || '/' || three_pt_attempts as three_pt,
  -- Shot creation
  assisted_fg_makes,
  unassisted_fg_makes,
  -- Prop result
  points_line,
  over_under_result,
  margin,
  -- Quality
  data_quality_tier,
  shot_zones_estimated
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE player_lookup = 'lebronjames'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 DAY)
ORDER BY game_date DESC;
*/

-- Players with the most efficient shot selection (last 10 games)
/*
SELECT 
  player_lookup,
  universal_player_id,
  COUNT(*) as games,
  AVG(points) as avg_points,
  AVG(ts_pct) as avg_ts_pct,
  AVG(efg_pct) as avg_efg_pct,
  -- Shot zone efficiency
  SUM(paint_makes) * 100.0 / NULLIF(SUM(paint_attempts), 0) as paint_pct,
  SUM(mid_range_makes) * 100.0 / NULLIF(SUM(mid_range_attempts), 0) as mid_range_pct,
  SUM(three_pt_makes) * 100.0 / NULLIF(SUM(three_pt_attempts), 0) as three_pt_pct,
  -- Shot creation
  SUM(unassisted_fg_makes) * 100.0 / NULLIF(SUM(fg_makes), 0) as self_creation_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 DAY)
  AND shot_zones_estimated = FALSE  -- Only actual shot zones
  AND minutes_played >= 20  -- Starters/major rotation
GROUP BY player_lookup, universal_player_id
HAVING games >= 8
ORDER BY avg_ts_pct DESC
LIMIT 20;
*/

-- Prop betting analysis: Best over performers
/*
SELECT 
  player_lookup,
  team_abbr,
  COUNT(*) as games_with_props,
  AVG(points) as avg_points,
  AVG(points_line) as avg_line,
  SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) as overs,
  SUM(CASE WHEN over_under_result = 'UNDER' THEN 1 ELSE 0 END) as unders,
  ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as over_pct,
  AVG(margin) as avg_margin
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND points_line IS NOT NULL
GROUP BY player_lookup, team_abbr
HAVING games_with_props >= 10
ORDER BY over_pct DESC
LIMIT 20;
*/

-- Shot zone trends by home/away
/*
SELECT 
  player_lookup,
  CASE WHEN team_abbr = SPLIT(game_id, '_')[OFFSET(2)] THEN 'home' ELSE 'away' END as location,
  COUNT(*) as games,
  AVG(points) as avg_points,
  -- Paint efficiency
  SUM(paint_makes) * 100.0 / NULLIF(SUM(paint_attempts), 0) as paint_pct,
  -- Shot distribution
  SUM(paint_attempts) * 100.0 / NULLIF(SUM(fg_attempts), 0) as paint_freq_pct,
  SUM(mid_range_attempts) * 100.0 / NULLIF(SUM(fg_attempts), 0) as mid_range_freq_pct,
  SUM(three_pt_attempts) * 100.0 / NULLIF(SUM(fg_attempts), 0) as three_freq_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND shot_zones_estimated = FALSE
  AND player_lookup = 'lebronjames'
GROUP BY player_lookup, location
ORDER BY location;
*/

-- Games with significant line movement
/*
SELECT 
  game_date,
  player_lookup,
  team_abbr,
  opponent_team_abbr,
  opening_line,
  points_line,
  line_movement,
  points,
  over_under_result,
  margin,
  -- Context
  points_line_source,
  primary_source_used
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ABS(line_movement) >= 2.0  -- Line moved 2+ points
ORDER BY ABS(line_movement) DESC;
*/

-- Plus/minus leaders (NBA.com data only)
/*
SELECT 
  player_lookup,
  player_full_name,
  team_abbr,
  COUNT(*) as games,
  AVG(plus_minus) as avg_plus_minus,
  SUM(plus_minus) as total_plus_minus,
  AVG(points) as avg_points,
  AVG(minutes_played) as avg_minutes
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND plus_minus IS NOT NULL  -- Only NBA.com data has this
  AND minutes_played >= 20
GROUP BY player_lookup, player_full_name, team_abbr
HAVING games >= 10
ORDER BY avg_plus_minus DESC
LIMIT 20;
*/

-- ============================================================================
-- DATA QUALITY MONITORING QUERIES
-- ============================================================================

-- Check source freshness for recent games (calculate age on-demand)
/*
SELECT 
  game_date,
  COUNT(*) as total_players,
  -- Calculate source age in hours
  AVG(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_last_updated, HOUR)) as avg_nbac_age_hours,
  AVG(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_bdl_last_updated, HOUR)) as avg_bdl_age_hours,
  AVG(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_bbd_last_updated, HOUR)) as avg_bbd_age_hours,
  -- Source completeness
  AVG(source_nbac_completeness_pct) as avg_nbac_completeness,
  AVG(source_bdl_completeness_pct) as avg_bdl_completeness,
  AVG(source_bbd_completeness_pct) as avg_bbd_completeness,
  -- Quality tiers
  SUM(CASE WHEN data_quality_tier = 'high' THEN 1 ELSE 0 END) as high_quality,
  SUM(CASE WHEN data_quality_tier = 'medium' THEN 1 ELSE 0 END) as medium_quality,
  SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) as low_quality,
  -- Shot zones
  SUM(CASE WHEN shot_zones_estimated = TRUE THEN 1 ELSE 0 END) as estimated_zones,
  SUM(CASE WHEN shot_zones_estimated = FALSE THEN 1 ELSE 0 END) as actual_zones
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
*/

-- Identify games missing Big Ball Data (should have it by now)
/*
SELECT 
  game_date,
  game_id,
  COUNT(*) as players,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), processed_at, HOUR)) as hours_since_processed,
  -- Source availability
  SUM(CASE WHEN shot_zones_estimated = TRUE THEN 1 ELSE 0 END) as players_with_estimated_zones,
  SUM(CASE WHEN source_bbd_completeness_pct IS NOT NULL THEN 1 ELSE 0 END) as players_with_bbd_data
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND game_date < CURRENT_DATE()  -- Past games only
  AND shot_zones_estimated = TRUE  -- Should have actual zones by now
GROUP BY game_date, game_id
HAVING players_with_estimated_zones >= 8  -- At least one full team
ORDER BY game_date DESC;
*/

-- Check for processing issues
/*
SELECT 
  game_date,
  COUNT(*) as total_players,
  SUM(CASE WHEN processed_with_issues = TRUE THEN 1 ELSE 0 END) as players_with_issues,
  ROUND(SUM(CASE WHEN processed_with_issues = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as issue_pct,
  -- Common issues
  SUM(CASE WHEN points IS NULL THEN 1 ELSE 0 END) as missing_points,
  SUM(CASE WHEN fg_attempts IS NULL THEN 1 ELSE 0 END) as missing_fg_attempts,
  SUM(CASE WHEN plus_minus IS NULL THEN 1 ELSE 0 END) as missing_plus_minus
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
*/

-- Multi-source coverage analysis
/*
SELECT 
  game_date,
  -- Core stats coverage
  SUM(CASE WHEN source_nbac_completeness_pct >= 85 THEN 1 ELSE 0 END) as nbac_good,
  SUM(CASE WHEN source_bdl_completeness_pct >= 85 THEN 1 ELSE 0 END) as bdl_good,
  -- Shot zones coverage
  SUM(CASE WHEN source_bbd_completeness_pct >= 85 THEN 1 ELSE 0 END) as bbd_good,
  SUM(CASE WHEN source_nbac_pbp_completeness_pct >= 85 THEN 1 ELSE 0 END) as pbp_good,
  SUM(CASE WHEN shot_zones_estimated = TRUE THEN 1 ELSE 0 END) as estimated,
  -- Prop lines coverage
  SUM(CASE WHEN source_odds_completeness_pct IS NOT NULL THEN 1 ELSE 0 END) as has_odds_api,
  SUM(CASE WHEN source_bp_completeness_pct IS NOT NULL THEN 1 ELSE 0 END) as has_bettingpros,
  COUNT(*) as total_players
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
*/

-- ============================================================================
-- DATA VALIDATION QUERIES
-- ============================================================================

-- Validation 1: Check for statistical impossibilities
/*
SELECT game_date, player_lookup, team_abbr,
       fg_makes, fg_attempts, three_pt_makes, three_pt_attempts
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND (fg_makes > fg_attempts
       OR three_pt_makes > three_pt_attempts
       OR fg_makes < 0
       OR points < 0);
*/

-- Validation 2: Check shot zone totals match FGA
/*
SELECT game_date, player_lookup, team_abbr,
       fg_attempts,
       paint_attempts + mid_range_attempts + three_pt_attempts as zone_total,
       ABS(fg_attempts - (paint_attempts + mid_range_attempts + three_pt_attempts)) as diff
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND shot_zones_estimated = FALSE  -- Only check actual shot zones
  AND ABS(fg_attempts - (paint_attempts + mid_range_attempts + three_pt_attempts)) > 1;
*/

-- Validation 3: Check assisted tracking matches total FGM
/*
SELECT game_date, player_lookup, team_abbr,
       fg_makes,
       assisted_fg_makes + unassisted_fg_makes as tracking_total,
       fg_makes - (assisted_fg_makes + unassisted_fg_makes) as diff
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND assisted_fg_makes IS NOT NULL
  AND unassisted_fg_makes IS NOT NULL
  AND fg_makes != (assisted_fg_makes + unassisted_fg_makes);
*/

-- Validation 4: Check for extreme outliers
/*
SELECT game_date, player_lookup, team_abbr, points, minutes_played, fg_attempts
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND (points > 100 
       OR minutes_played > 60 
       OR fg_attempts > 50);
*/

-- ============================================================================
-- ALERT QUERIES (for monitoring system)
-- ============================================================================

-- Alert: Stale NBA.com data (>48 hours old)
/*
SELECT 
  'player_game_summary' as processor,
  game_date,
  COUNT(*) as affected_players,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_last_updated, HOUR)) as max_age_hours
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
HAVING MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_last_updated, HOUR)) > 48;
*/

-- Alert: Low completeness (<85%)
/*
SELECT 
  'player_game_summary' as processor,
  game_date,
  -- Find bottleneck source
  CASE 
    WHEN AVG(source_nbac_completeness_pct) < 85 THEN 'nbac'
    WHEN AVG(source_bdl_completeness_pct) < 85 THEN 'bdl'
    WHEN AVG(source_bbd_completeness_pct) < 85 THEN 'bbd'
    ELSE 'unknown'
  END as problem_source,
  AVG(source_nbac_completeness_pct) as avg_nbac_completeness,
  AVG(source_bdl_completeness_pct) as avg_bdl_completeness,
  AVG(source_bbd_completeness_pct) as avg_bbd_completeness
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
HAVING AVG(source_nbac_completeness_pct) < 85
    OR AVG(source_bdl_completeness_pct) < 85
    OR AVG(source_bbd_completeness_pct) < 85;
*/

-- Alert: High percentage of low quality data
/*
SELECT 
  'player_game_summary' as processor,
  game_date,
  COUNT(*) as total_players,
  SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) as low_quality_count,
  ROUND(SUM(CASE WHEN data_quality_tier = 'low' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as low_quality_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
HAVING low_quality_pct > 30;  -- Alert if >30% low quality
*/

-- Alert: Missing shot zones for old games
/*
SELECT 
  'player_game_summary' as processor,
  game_date,
  game_id,
  COUNT(*) as players_with_estimated_zones
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)  -- Games >24 hours old
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND shot_zones_estimated = TRUE
GROUP BY game_date, game_id
HAVING players_with_estimated_zones >= 8;  -- At least one full team
*/

-- ============================================================================
-- MAINTENANCE QUERIES
-- ============================================================================

-- Get table statistics
/*
SELECT 
  COUNT(*) as total_rows,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT universal_player_id) as unique_universal_ids,
  COUNT(DISTINCT game_id) as unique_games,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game,
  MAX(processed_at) as last_processed,
  -- Quality stats
  SUM(CASE WHEN data_quality_tier = 'high' THEN 1 ELSE 0 END) as high_quality_rows,
  SUM(CASE WHEN processed_with_issues THEN 1 ELSE 0 END) as rows_with_issues,
  SUM(CASE WHEN shot_zones_estimated = TRUE THEN 1 ELSE 0 END) as estimated_zones_rows,
  -- Source coverage
  SUM(CASE WHEN source_nbac_completeness_pct >= 85 THEN 1 ELSE 0 END) as nbac_good_coverage,
  SUM(CASE WHEN source_bbd_completeness_pct >= 85 THEN 1 ELSE 0 END) as bbd_good_coverage,
  SUM(CASE WHEN points_line IS NOT NULL THEN 1 ELSE 0 END) as games_with_props
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
*/

-- Check partition health
/*
SELECT 
  game_date,
  COUNT(*) as rows_per_partition,
  COUNT(DISTINCT game_id) as games_per_partition,
  AVG(CAST(LENGTH(TO_JSON_STRING(t)) AS INT64)) as avg_row_size_bytes
FROM `nba-props-platform.nba_analytics.player_game_summary` t
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
*/

-- ============================================================================
-- MIGRATION NOTES
-- ============================================================================
-- If table already exists with 66 fields (v3.0), add new source tracking fields:
/*
ALTER TABLE `nba-props-platform.nba_analytics.player_game_summary`

-- Source 5: NBA.com Play-by-Play (shot zones backup)
ADD COLUMN IF NOT EXISTS source_nbac_pbp_last_updated TIMESTAMP,
ADD COLUMN IF NOT EXISTS source_nbac_pbp_rows_found INT64,
ADD COLUMN IF NOT EXISTS source_nbac_pbp_completeness_pct NUMERIC(5,2),

-- Source 6: BettingPros (prop lines backup)
ADD COLUMN IF NOT EXISTS source_bp_last_updated TIMESTAMP,
ADD COLUMN IF NOT EXISTS source_bp_rows_found INT64,
ADD COLUMN IF NOT EXISTS source_bp_completeness_pct NUMERIC(5,2);
*/

-- ============================================================================
-- VERSION HISTORY
-- ============================================================================
-- v1.0 (Original):      Basic player game stats
-- v2.0 (+Shot Zones):   Added paint/mid-range/three shot zones
-- v3.0 (+Universal ID): Added universal_player_id for stable identification
-- v4.0 (+Tracking):     Added Phase 2 source tracking (12 fields, 4 sources)
-- v5.0 (+Full Sources): Added source_nbac_pbp_* and source_bp_* (18 fields, 6 sources)
--                       Updated to match v2.0 data mapping specification
--                       Added comprehensive documentation and monitoring queries
-- 
-- Last Updated: November 2025
-- Status: Production Ready - Matches v2.0 Data Mapping Document
-- Next: Implement multi-pass processing in processor
-- ============================================================================