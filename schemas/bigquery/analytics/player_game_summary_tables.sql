-- ============================================================================
-- NBA Props Platform - Player Game Summary Analytics Table
-- Pure performance results with shot zone tracking - no context duplication
-- Updated: Added universal_player_id + Phase 2 source tracking
-- File: schemas/bigquery/analytics/player_game_summary_tables.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.player_game_summary` (
  -- ============================================================================
  -- CORE IDENTIFIERS (8 fields)
  -- ============================================================================
  player_lookup STRING NOT NULL,                    -- Normalized player identifier
  universal_player_id STRING,                       -- Universal player ID from registry (e.g., lebronjames_2024)
  player_full_name STRING,                          -- Display name for reports
  game_id STRING NOT NULL,                          -- Unique game identifier (YYYYMMDD_AWAY_HOME)
  game_date DATE NOT NULL,                          -- Game date for partitioning
  team_abbr STRING NOT NULL,                        -- Player's team abbreviation
  opponent_team_abbr STRING NOT NULL,               -- Opposing team abbreviation
  season_year INT64 NOT NULL,                       -- Season year (2024 for 2024-25 season)
  
  -- ============================================================================
  -- BASIC PERFORMANCE STATS (16 fields)
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
  plus_minus INT64,                                 -- Plus/minus while on court
  personal_fouls INT64,                             -- Personal fouls committed
  
  -- ============================================================================
  -- SHOT ZONE PERFORMANCE (8 fields)
  -- ============================================================================
  paint_attempts INT64,                             -- Field goal attempts in paint (≤8 feet)
  paint_makes INT64,                                -- Field goal makes in paint
  mid_range_attempts INT64,                         -- Mid-range attempts (9-23 feet, 2PT)
  mid_range_makes INT64,                            -- Mid-range makes
  paint_blocks INT64,                               -- Blocks on paint shots
  mid_range_blocks INT64,                           -- Blocks on mid-range shots
  three_pt_blocks INT64,                            -- Blocks on three-point shots
  and1_count INT64,                                 -- Made FG + shooting foul drawn
  
  -- ============================================================================
  -- SHOT CREATION ANALYSIS (2 fields)
  -- ============================================================================
  assisted_fg_makes INT64,                          -- Made FGs that were assisted
  unassisted_fg_makes INT64,                        -- Made FGs unassisted (shot creation)
  
  -- ============================================================================
  -- ADVANCED EFFICIENCY (5 fields)
  -- ============================================================================
  usage_rate NUMERIC(5,2),                          -- Percentage of team plays used
  ts_pct NUMERIC(5,3),                              -- True Shooting percentage
  efg_pct NUMERIC(5,3),                             -- Effective Field Goal percentage
  starter_flag BOOLEAN NOT NULL,                    -- Whether player started
  win_flag BOOLEAN NOT NULL,                        -- Whether player's team won
  
  -- ============================================================================
  -- PROP BETTING RESULTS (7 fields)
  -- ============================================================================
  points_line NUMERIC(4,1),                         -- Betting line for points prop
  over_under_result STRING,                         -- 'OVER', 'UNDER', or NULL
  margin NUMERIC(6,2),                              -- Actual points minus line
  opening_line NUMERIC(4,1),                        -- Opening betting line
  line_movement NUMERIC(4,1),                       -- Line movement from open to close
  points_line_source STRING,                        -- Source of closing line (e.g., 'draftkings')
  opening_line_source STRING,                       -- Source of opening line
  
  -- ============================================================================
  -- PLAYER AVAILABILITY (2 fields)
  -- ============================================================================
  is_active BOOLEAN NOT NULL,                       -- Whether player played
  player_status STRING,                             -- 'active', 'injured', 'rest', 'dnp_coaches_decision', 'suspended', 'personal'
  
  -- ============================================================================
  -- PHASE 2 SOURCE TRACKING (12 fields - 4 sources × 3 fields each)
  -- ============================================================================
  -- These fields track data quality and lineage from Phase 2 raw tables
  -- Per dependency tracking guide v4.0
  
  -- SOURCE 1: Ball Don't Lie API (PRIMARY - Critical)
  -- nba_raw.bdl_player_boxscores
  source_bdl_last_updated TIMESTAMP,                -- When BDL table was last processed
  source_bdl_rows_found INT64,                      -- How many BDL records found for this game
  source_bdl_completeness_pct NUMERIC(5,2),         -- % of expected players found
  
  -- SOURCE 2: NBA.com Gamebook (ENHANCEMENT - Important)
  -- nba_raw.nbac_gamebook_player_stats
  source_nbac_last_updated TIMESTAMP,               -- When NBA.com gamebook was last processed
  source_nbac_rows_found INT64,                     -- How many NBA.com records found
  source_nbac_completeness_pct NUMERIC(5,2),        -- % of expected players found
  
  -- SOURCE 3: Big Ball Data Play-by-Play (OPTIONAL - Shot zones)
  -- nba_raw.bigdataball_play_by_play
  source_bbd_last_updated TIMESTAMP,                -- When Big Ball Data was last processed
  source_bbd_rows_found INT64,                      -- How many play-by-play events found
  source_bbd_completeness_pct NUMERIC(5,2),         -- % of expected shot events found
  
  -- SOURCE 4: The Odds API Player Props (OPTIONAL - Prop lines)
  -- nba_raw.odds_api_player_points_props
  source_odds_last_updated TIMESTAMP,               -- When Odds API was last processed
  source_odds_rows_found INT64,                     -- How many prop snapshots found
  source_odds_completeness_pct NUMERIC(5,2),        -- % of expected props found
  
  -- ============================================================================
  -- DATA QUALITY FLAGS (4 fields)
  -- ============================================================================
  data_quality_tier STRING,                         -- 'high', 'medium', 'low' (based on source availability)
  primary_source_used STRING,                       -- Primary data source (e.g., 'bdl_nbac_combined')
  processed_with_issues BOOLEAN,                    -- Quality issues flag
  shot_zones_estimated BOOLEAN,                     -- TRUE if shot zones estimated (no Big Ball Data)
  
  -- ============================================================================
  -- PROCESSING METADATA (2 fields)
  -- ============================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When record first created
  processed_at TIMESTAMP                            -- When record last processed/updated
)
PARTITION BY game_date
CLUSTER BY universal_player_id, player_lookup, team_abbr, game_date
OPTIONS(
  description="Player game performance with shot zone tracking and Phase 2 source tracking. Universal player ID enables stable cross-season identification. Source tracking fields monitor data quality from BDL, NBA.com, Big Ball Data, and Odds API."
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
-- Source tracking:           12 fields (4 sources × 3 fields)
-- Data quality:               4 fields
-- Processing metadata:        2 fields
-- -------------------------
-- TOTAL:                     66 fields

-- ============================================================================
-- SOURCE TRACKING FIELD SEMANTICS
-- ============================================================================
-- Per dependency tracking guide v4.0, each source has 3 fields:
--
-- 1. source_{prefix}_last_updated (TIMESTAMP)
--    - When the source table was last processed (from source's processed_at)
--    - NULL = source table doesn't exist
--    - Used to calculate data freshness/age
--
-- 2. source_{prefix}_rows_found (INT64)
--    - How many rows the extraction query returned
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
-- Quality tier assigned based on source availability:
--
-- HIGH (score ≥ 9):
--   - BDL data present (3 points)
--   - NBA.com gamebook present (2 points)
--   - Actual shot zones from Big Ball Data (3 points)
--   - Shot creation data present (1 point)
--   - Prop lines present (1 point)
--
-- MEDIUM (score 6-8):
--   - BDL + NBA.com present
--   - Estimated shot zones (no Big Ball Data)
--   - May have prop lines
--
-- LOW (score < 6):
--   - BDL only
--   - No NBA.com enhancements
--   - No shot zones or estimated only

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- Check source freshness (calculate age on-demand)
/*
SELECT 
  game_date,
  player_lookup,
  -- Calculate source age in hours
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_bdl_last_updated, HOUR) as bdl_age_hours,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_nbac_last_updated, HOUR) as nbac_age_hours,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_bbd_last_updated, HOUR) as bbd_age_hours,
  -- Source completeness
  source_bdl_completeness_pct,
  source_nbac_completeness_pct,
  source_bbd_completeness_pct,
  -- Data quality
  data_quality_tier,
  shot_zones_estimated
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND source_bdl_completeness_pct < 100.0  -- Find incomplete data
ORDER BY game_date DESC, source_bdl_completeness_pct ASC;
*/

-- Check games missing Big Ball Data (shot zones estimated)
/*
SELECT 
  game_date,
  game_id,
  COUNT(*) as players_with_estimated_zones,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), processed_at, HOUR)) as hours_since_processed
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE shot_zones_estimated = TRUE
  AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)  -- >24 hours old
GROUP BY game_date, game_id
HAVING players_with_estimated_zones >= 8  -- At least one full team
ORDER BY game_date DESC;
*/

-- Overall data quality summary
/*
SELECT 
  game_date,
  -- Source coverage
  AVG(source_bdl_completeness_pct) as avg_bdl_completeness,
  AVG(source_nbac_completeness_pct) as avg_nbac_completeness,
  AVG(source_bbd_completeness_pct) as avg_bbd_completeness,
  AVG(source_odds_completeness_pct) as avg_odds_completeness,
  -- Quality tiers
  COUNT(*) as total_player_games,
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

-- ============================================================================
-- MONITORING ALERTS
-- ============================================================================

-- Alert: Stale BDL data (>48 hours old)
/*
SELECT 
  'player_game_summary' as processor,
  game_date,
  COUNT(*) as affected_players,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_bdl_last_updated, HOUR)) as max_age_hours
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
HAVING MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_bdl_last_updated, HOUR)) > 48;
*/

-- Alert: Low completeness (<85%)
/*
SELECT 
  'player_game_summary' as processor,
  game_date,
  -- Find bottleneck source
  CASE 
    WHEN AVG(source_bdl_completeness_pct) < 85 THEN 'bdl'
    WHEN AVG(source_nbac_completeness_pct) < 85 THEN 'nbac'
    WHEN AVG(source_bbd_completeness_pct) < 85 THEN 'bbd'
    ELSE 'unknown'
  END as problem_source,
  AVG(source_bdl_completeness_pct) as avg_bdl_completeness,
  AVG(source_nbac_completeness_pct) as avg_nbac_completeness,
  AVG(source_bbd_completeness_pct) as avg_bbd_completeness
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date
HAVING AVG(source_bdl_completeness_pct) < 85
    OR AVG(source_nbac_completeness_pct) < 85
    OR AVG(source_bbd_completeness_pct) < 85;
*/

-- ============================================================================
-- MIGRATION NOTES
-- ============================================================================
-- If table already exists, add source tracking fields with:
/*
ALTER TABLE `nba-props-platform.nba_analytics.player_game_summary`

-- Source 1: BDL (Ball Don't Lie)
ADD COLUMN IF NOT EXISTS source_bdl_last_updated TIMESTAMP,
ADD COLUMN IF NOT EXISTS source_bdl_rows_found INT64,
ADD COLUMN IF NOT EXISTS source_bdl_completeness_pct NUMERIC(5,2),

-- Source 2: NBA.com Gamebook
ADD COLUMN IF NOT EXISTS source_nbac_last_updated TIMESTAMP,
ADD COLUMN IF NOT EXISTS source_nbac_rows_found INT64,
ADD COLUMN IF NOT EXISTS source_nbac_completeness_pct NUMERIC(5,2),

-- Source 3: Big Ball Data
ADD COLUMN IF NOT EXISTS source_bbd_last_updated TIMESTAMP,
ADD COLUMN IF NOT EXISTS source_bbd_rows_found INT64,
ADD COLUMN IF NOT EXISTS source_bbd_completeness_pct NUMERIC(5,2),

-- Source 4: Odds API
ADD COLUMN IF NOT EXISTS source_odds_last_updated TIMESTAMP,
ADD COLUMN IF NOT EXISTS source_odds_rows_found INT64,
ADD COLUMN IF NOT EXISTS source_odds_completeness_pct NUMERIC(5,2),

-- Data quality flag
ADD COLUMN IF NOT EXISTS shot_zones_estimated BOOLEAN;
*/

-- ============================================================================
-- VERSION HISTORY
-- ============================================================================
-- v1.0 (Original):      Basic player game stats
-- v2.0 (+Shot Zones):   Added paint/mid-range/three shot zones
-- v3.0 (+Universal ID): Added universal_player_id for stable identification
-- v4.0 (+Tracking):     Added Phase 2 source tracking (12 fields)
-- 
-- Last Updated: January 2025
-- Status: Ready for Implementation
-- ============================================================================