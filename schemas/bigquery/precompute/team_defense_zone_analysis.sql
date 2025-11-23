-- ============================================================================
-- NBA Props Platform - Team Defense Zone Analysis Schema
-- Phase 4 Precompute Table with v4.0 Dependency Tracking
-- ============================================================================
-- Table: nba_precompute.team_defense_zone_analysis
-- Purpose: Team defensive performance by shot zone (last 15 games rolling)
-- Update: Nightly at 11:00 PM (before player processors)
-- Retention: 90 days
-- 
-- Version: 1.0 (with v4.0 dependency tracking)
-- Date: January 2025
-- Status: Production-Ready
--
-- Related Documents:
-- - team-defense-zone-analysis-implementation-v4.md (full implementation guide)
-- - dependency-tracking-design-v4.0-streamlined.md (tracking design)
-- ============================================================================

-- ============================================================================
-- TABLE DEFINITION
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.team_defense_zone_analysis` (
  -- ============================================================================
  -- IDENTIFIERS (2 fields)
  -- ============================================================================
  team_abbr STRING NOT NULL,                        -- NBA team abbreviation (LAL, GSW, etc.)
  analysis_date DATE NOT NULL,                      -- Date this analysis represents (partition key)
  
  -- ============================================================================
  -- PAINT DEFENSE - Last 15 games (5 fields)
  -- ============================================================================
  paint_pct_allowed_last_15 NUMERIC(5,3),           -- FG% allowed in paint (≤8 feet)
                                                     -- Range: 0.400-0.700
                                                     -- Example: 0.610 = 61.0%
  
  paint_attempts_allowed_per_game NUMERIC(5,1),     -- Paint shot attempts allowed per game
                                                     -- Range: 25.0-50.0
                                                     -- Example: 38.2
  
  paint_points_allowed_per_game NUMERIC(5,1),       -- Paint points allowed per game
                                                     -- Range: 30.0-70.0
                                                     -- Example: 48.8
  
  paint_blocks_per_game NUMERIC(4,1),               -- Paint blocks per game
                                                     -- Range: 1.0-8.0
                                                     -- Example: 3.2
  
  paint_defense_vs_league_avg NUMERIC(5,2),         -- Percentage points vs league average
                                                     -- Positive = worse defense (allowing more)
                                                     -- Negative = better defense (allowing less)
                                                     -- Range: -10.00 to +10.00
                                                     -- Example: +3.00 (3 pp worse than league)
  
  -- ============================================================================
  -- MID-RANGE DEFENSE - Last 15 games (4 fields)
  -- ============================================================================
  mid_range_pct_allowed_last_15 NUMERIC(5,3),       -- FG% allowed mid-range (9+ feet, 2PT)
                                                     -- Range: 0.300-0.550
                                                     -- Example: 0.429 = 42.9%
  
  mid_range_attempts_allowed_per_game NUMERIC(5,1), -- Mid-range attempts allowed per game
                                                     -- Range: 10.0-25.0
                                                     -- Example: 15.9
  
  mid_range_blocks_per_game NUMERIC(4,1),           -- Mid-range blocks per game
                                                     -- Range: 0.0-3.0
                                                     -- Example: 0.8
  
  mid_range_defense_vs_league_avg NUMERIC(5,2),     -- Percentage points vs league average
                                                     -- Range: -10.00 to +10.00
                                                     -- Example: -1.20 (1.2 pp better than league)
  
  -- ============================================================================
  -- THREE-POINT DEFENSE - Last 15 games (4 fields)
  -- ============================================================================
  three_pt_pct_allowed_last_15 NUMERIC(5,3),        -- 3PT% allowed
                                                     -- Range: 0.280-0.420
                                                     -- Example: 0.351 = 35.1%
  
  three_pt_attempts_allowed_per_game NUMERIC(5,1),  -- Three-point attempts allowed per game
                                                     -- Range: 28.0-42.0
                                                     -- Example: 37.0
  
  three_pt_blocks_per_game NUMERIC(4,1),            -- Three-point blocks per game (rare)
                                                     -- Range: 0.0-1.0
                                                     -- Example: 0.1
  
  three_pt_defense_vs_league_avg NUMERIC(5,2),      -- Percentage points vs league average
                                                     -- Range: -10.00 to +10.00
                                                     -- Example: +0.50 (0.5 pp worse than league)
  
  -- ============================================================================
  -- OVERALL DEFENSIVE METRICS - Last 15 games (4 fields)
  -- ============================================================================
  defensive_rating_last_15 NUMERIC(6,2),            -- Points allowed per 100 possessions
                                                     -- Range: 100.00-120.00
                                                     -- Example: 112.30
  
  opponent_points_per_game NUMERIC(5,1),            -- Total points allowed per game
                                                     -- Range: 100.0-125.0
                                                     -- Example: 114.8
  
  opponent_pace NUMERIC(5,1),                       -- Pace allowed to opponents
                                                     -- Range: 95.0-105.0
                                                     -- Example: 99.7
  
  games_in_sample INT64,                            -- Number of games in sample
                                                     -- Expected: 15 (mid-season)
                                                     -- Early season: <15
                                                     -- Example: 15
  
  -- ============================================================================
  -- DEFENSIVE STRENGTHS/WEAKNESSES (2 fields)
  -- ============================================================================
  strongest_zone STRING,                            -- Best defensive zone
                                                     -- Values: 'paint', 'mid_range', 'perimeter'
                                                     -- Based on most negative vs_league_avg
                                                     -- Example: 'mid_range'
  
  weakest_zone STRING,                              -- Worst defensive zone
                                                     -- Values: 'paint', 'mid_range', 'perimeter'
                                                     -- Based on most positive vs_league_avg
                                                     -- Example: 'paint'
  
  -- ============================================================================
  -- DATA QUALITY (2 fields)
  -- ============================================================================
  data_quality_tier STRING,                         -- Overall data quality assessment
                                                     -- Values: 'high' (≥15 games), 
                                                     --         'medium' (10-14 games),
                                                     --         'low' (<10 games)
                                                     -- Example: 'high'
  
  calculation_notes STRING,                         -- Issues or warnings during calculation
                                                     -- NULL if no issues
                                                     -- Example: "No mid-range attempts"
  
  -- ============================================================================
  -- SOURCE TRACKING (v4.0) - 3 fields per source
  -- ============================================================================
  -- These fields track the upstream data source quality and freshness
  -- Source: nba_analytics.team_defense_game_summary
  
  source_team_defense_last_updated TIMESTAMP,       -- When source table was last processed
                                                     -- NULL = source doesn't exist
                                                     -- Example: '2025-01-27T23:05:00Z'
  
  source_team_defense_rows_found INT64,             -- Rows returned from source query
                                                     -- NULL = source doesn't exist
                                                     -- 0 = source exists but empty
                                                     -- Example: 450 (30 teams × 15 games)
  
  source_team_defense_completeness_pct NUMERIC(5,2), -- Percentage of expected rows found
                                                     -- Calculation: (rows_found / rows_expected) × 100
                                                     -- NULL = source doesn't exist
                                                     -- 100.0 = all expected data present
                                                     -- Range: 0.00-100.00
                                                     -- Example: 100.00

  source_team_defense_hash STRING,                  -- Hash from team_defense_game_summary.data_hash
                                                     -- Used for smart reprocessing (Pattern #3)
                                                     -- NULL = source has no hash or doesn't exist
                                                     -- Example: 'a3b4c5d6e7f8...'

  -- ============================================================================
  -- SMART IDEMPOTENCY (Pattern #1) - 1 field
  -- ============================================================================
  -- This field enables skipping duplicate BigQuery writes when output unchanged

  data_hash STRING,                                 -- SHA256 hash of meaningful output fields
                                                     -- Computed from: all defense metrics + quality fields
                                                     -- Excludes: processed_at, created_at, source tracking
                                                     -- Used to detect if calculated values changed
                                                     -- NULL = pattern not yet implemented
                                                     -- Example: '1a2b3c4d5e6f...'

  -- ============================================================================
  -- OPTIONAL: EARLY SEASON FIELDS (2 fields)
  -- ============================================================================
  -- These fields are set when insufficient data exists for calculation

  early_season_flag BOOLEAN,                        -- TRUE = insufficient data for calculation
                                                     -- Set when games_in_sample < min_games_required
                                                     -- NULL or FALSE = normal processing
                                                     -- Example: TRUE (first 2 weeks of season)

  insufficient_data_reason STRING,                  -- Why data was insufficient
                                                     -- Only set when early_season_flag = TRUE
                                                     -- Example: "Only 3 games available, need 15"

  -- ============================================================================
  -- HISTORICAL COMPLETENESS CHECKING (14 fields)
  -- ============================================================================
  -- These fields track whether all required historical data is present
  -- Used during backfill to identify records that need reprocessing

  -- Completeness Metrics (4 fields)
  expected_games_count INT64,                       -- Games expected from schedule
                                                     -- NULL = completeness not checked
                                                     -- Example: 17 (team played 17 games)

  actual_games_count INT64,                         -- Games actually found in upstream
                                                     -- NULL = completeness not checked
                                                     -- Example: 15 (missing 2 games)

  completeness_percentage FLOAT64,                  -- Completeness (0-100%)
                                                     -- Calculation: (actual / expected) × 100
                                                     -- NULL = completeness not checked
                                                     -- Range: 0.0-100.0
                                                     -- Example: 88.2 (15/17 games)

  missing_games_count INT64,                        -- Games missing from upstream
                                                     -- Calculation: expected - actual
                                                     -- NULL = completeness not checked
                                                     -- Example: 2

  -- Production Readiness (2 fields)
  is_production_ready BOOLEAN,                      -- Ready for production use?
                                                     -- TRUE = completeness_pct >= 90%
                                                     -- FALSE = incomplete data, may need reprocessing
                                                     -- NULL = completeness not checked
                                                     -- Example: FALSE (only 88.2% complete)

  data_quality_issues ARRAY<STRING>,                -- Specific quality issues found
                                                     -- NULL or [] = no issues
                                                     -- Example: ["missing_game_2024-11-05", "missing_game_2024-11-12"]

  -- Circuit Breaker (4 fields)
  last_reprocess_attempt_at TIMESTAMP,              -- When reprocessing was last attempted
                                                     -- NULL = never reprocessed
                                                     -- Example: '2025-01-27T23:00:00Z'

  reprocess_attempt_count INT64,                    -- Number of reprocess attempts
                                                     -- NULL or 0 = never reprocessed
                                                     -- Max: 3 (circuit breaker trips at 3)
                                                     -- Example: 2

  circuit_breaker_active BOOLEAN,                   -- Circuit breaker tripped?
                                                     -- TRUE = max attempts reached (3)
                                                     -- FALSE = can still retry
                                                     -- NULL = never reprocessed
                                                     -- Example: FALSE

  circuit_breaker_until TIMESTAMP,                  -- When circuit breaker expires
                                                     -- NULL = circuit breaker not active
                                                     -- Set to: last_attempt + 7 days
                                                     -- Example: '2025-02-03T23:00:00Z'

  -- Bootstrap/Override (4 fields)
  manual_override_required BOOLEAN,                 -- Manual intervention needed?
                                                     -- TRUE = circuit breaker tripped, manual fix required
                                                     -- FALSE = automatic retry allowed
                                                     -- NULL = no issues
                                                     -- Example: FALSE

  season_boundary_detected BOOLEAN,                 -- Date near season start/end?
                                                     -- TRUE = Oct-Nov or April (expected gaps)
                                                     -- FALSE = mid-season
                                                     -- Used to prevent false alerts
                                                     -- Example: FALSE

  backfill_bootstrap_mode BOOLEAN,                  -- In bootstrap mode?
                                                     -- TRUE = first 30 days of season/backfill
                                                     -- FALSE = normal operation
                                                     -- Allows partial data during early dates
                                                     -- Example: FALSE

  processing_decision_reason STRING,                -- Why processed or skipped?
                                                     -- Values: 'processed_successfully',
                                                     --         'incomplete_upstream_data',
                                                     --         'circuit_breaker_active',
                                                     --         'early_season_placeholder'
                                                     -- Example: 'incomplete_upstream_data'

  -- ============================================================================
  -- PROCESSING METADATA (2 fields)
  -- ============================================================================
  processed_at TIMESTAMP NOT NULL,                  -- When this calculation was performed
                                                     -- Example: '2025-01-27T23:10:00Z'

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()  -- Row creation timestamp
)
PARTITION BY analysis_date
CLUSTER BY team_abbr, analysis_date
OPTIONS(
  description="Team defensive performance by shot zone (last 15 games rolling). Source: nba_analytics.team_defense_game_summary. Uses v4.0 dependency tracking (3 fields per source). Updated nightly at 11:00 PM.",
  partition_expiration_days=90
);

-- ============================================================================
-- SCHEMA UPDATES (If Table Already Exists)
-- ============================================================================
-- Run these ALTER TABLE statements to add v4.0 dependency tracking fields
-- to an existing table

ALTER TABLE `nba-props-platform.nba_precompute.team_defense_zone_analysis`

-- v4.0 Source tracking (3 fields)
ADD COLUMN IF NOT EXISTS source_team_defense_last_updated TIMESTAMP
  OPTIONS (description="When source team_defense_game_summary was last processed"),
ADD COLUMN IF NOT EXISTS source_team_defense_rows_found INT64
  OPTIONS (description="Rows returned from team_defense_game_summary query"),
ADD COLUMN IF NOT EXISTS source_team_defense_completeness_pct NUMERIC(5,2)
  OPTIONS (description="Percentage of expected rows found (0-100)"),

-- Smart patterns (2 fields)
ADD COLUMN IF NOT EXISTS source_team_defense_hash STRING
  OPTIONS (description="Hash from team_defense_game_summary for smart reprocessing"),
ADD COLUMN IF NOT EXISTS data_hash STRING
  OPTIONS (description="SHA256 hash of output for smart idempotency"),

-- Early season fields (2 fields)
ADD COLUMN IF NOT EXISTS early_season_flag BOOLEAN
  OPTIONS (description="TRUE when insufficient games for calculation"),
ADD COLUMN IF NOT EXISTS insufficient_data_reason STRING
  OPTIONS (description="Explanation of why data was insufficient"),

-- Historical completeness checking (14 fields)
ADD COLUMN IF NOT EXISTS expected_games_count INT64
  OPTIONS (description="Games expected from schedule"),
ADD COLUMN IF NOT EXISTS actual_games_count INT64
  OPTIONS (description="Games actually found in upstream table"),
ADD COLUMN IF NOT EXISTS completeness_percentage FLOAT64
  OPTIONS (description="Completeness percentage 0-100%"),
ADD COLUMN IF NOT EXISTS missing_games_count INT64
  OPTIONS (description="Number of games missing from upstream"),
ADD COLUMN IF NOT EXISTS is_production_ready BOOLEAN
  OPTIONS (description="TRUE if completeness >= 90%"),
ADD COLUMN IF NOT EXISTS data_quality_issues ARRAY<STRING>
  OPTIONS (description="Specific quality issues found"),
ADD COLUMN IF NOT EXISTS last_reprocess_attempt_at TIMESTAMP
  OPTIONS (description="When reprocessing was last attempted"),
ADD COLUMN IF NOT EXISTS reprocess_attempt_count INT64
  OPTIONS (description="Number of reprocess attempts"),
ADD COLUMN IF NOT EXISTS circuit_breaker_active BOOLEAN
  OPTIONS (description="TRUE if max reprocess attempts reached"),
ADD COLUMN IF NOT EXISTS circuit_breaker_until TIMESTAMP
  OPTIONS (description="When circuit breaker expires (7 days from last attempt)"),
ADD COLUMN IF NOT EXISTS manual_override_required BOOLEAN
  OPTIONS (description="TRUE if manual intervention needed"),
ADD COLUMN IF NOT EXISTS season_boundary_detected BOOLEAN
  OPTIONS (description="TRUE if date near season start/end"),
ADD COLUMN IF NOT EXISTS backfill_bootstrap_mode BOOLEAN
  OPTIONS (description="TRUE if first 30 days of season/backfill"),
ADD COLUMN IF NOT EXISTS processing_decision_reason STRING
  OPTIONS (description="Why record was processed or skipped");

-- ============================================================================
-- FIELD SUMMARY
-- ============================================================================
-- Total fields: 48
--   - Identifiers: 2
--   - Paint defense: 5
--   - Mid-range defense: 4
--   - Three-point defense: 4
--   - Overall metrics: 4
--   - Strengths/weaknesses: 2
--   - Data quality: 2
--   - Source tracking (v4.0): 4 (including hash)
--   - Smart patterns (hash columns): 1
--   - Early season (optional): 2
--   - Historical completeness checking: 14
--   - Processing metadata: 2

-- ============================================================================
-- SAMPLE ROW (Normal Season - Real Data)
-- ============================================================================
/*
{
  -- Identifiers
  "team_abbr": "LAL",
  "analysis_date": "2025-01-27",
  
  -- Paint defense
  "paint_pct_allowed_last_15": 0.610,
  "paint_attempts_allowed_per_game": 38.2,
  "paint_points_allowed_per_game": 48.8,
  "paint_blocks_per_game": 3.2,
  "paint_defense_vs_league_avg": 3.00,
  
  -- Mid-range defense
  "mid_range_pct_allowed_last_15": 0.429,
  "mid_range_attempts_allowed_per_game": 15.9,
  "mid_range_blocks_per_game": 0.8,
  "mid_range_defense_vs_league_avg": -1.20,
  
  -- Three-point defense
  "three_pt_pct_allowed_last_15": 0.351,
  "three_pt_attempts_allowed_per_game": 37.0,
  "three_pt_blocks_per_game": 0.1,
  "three_pt_defense_vs_league_avg": 0.50,
  
  -- Overall metrics
  "defensive_rating_last_15": 112.30,
  "opponent_points_per_game": 114.8,
  "opponent_pace": 99.7,
  "games_in_sample": 15,
  
  -- Strengths/weaknesses
  "strongest_zone": "mid_range",
  "weakest_zone": "paint",
  
  -- Data quality
  "data_quality_tier": "high",
  "calculation_notes": null,
  
  -- Source tracking (v4.0)
  "source_team_defense_last_updated": "2025-01-27T23:05:00Z",
  "source_team_defense_rows_found": 450,
  "source_team_defense_completeness_pct": 100.00,
  "source_team_defense_hash": "a3b4c5d6e7f89a0b1c2d3e4f567890ab",

  -- Smart patterns
  "data_hash": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d",

  -- Early season (not set for normal season)
  "early_season_flag": null,
  "insufficient_data_reason": null,

  -- Processing metadata
  "processed_at": "2025-01-27T23:10:00Z",
  "created_at": "2025-01-27T23:10:15Z"
}
*/

-- ============================================================================
-- SAMPLE ROW (Early Season - Placeholder)
-- ============================================================================
/*
{
  -- Identifiers
  "team_abbr": "LAL",
  "analysis_date": "2024-10-28",
  
  -- Paint defense (all NULL)
  "paint_pct_allowed_last_15": null,
  "paint_attempts_allowed_per_game": null,
  "paint_points_allowed_per_game": null,
  "paint_blocks_per_game": null,
  "paint_defense_vs_league_avg": null,
  
  -- Mid-range defense (all NULL)
  "mid_range_pct_allowed_last_15": null,
  "mid_range_attempts_allowed_per_game": null,
  "mid_range_blocks_per_game": null,
  "mid_range_defense_vs_league_avg": null,
  
  -- Three-point defense (all NULL)
  "three_pt_pct_allowed_last_15": null,
  "three_pt_attempts_allowed_per_game": null,
  "three_pt_blocks_per_game": null,
  "three_pt_defense_vs_league_avg": null,
  
  -- Overall metrics (all NULL except games_in_sample)
  "defensive_rating_last_15": null,
  "opponent_points_per_game": null,
  "opponent_pace": null,
  "games_in_sample": 3,
  
  -- Strengths/weaknesses (NULL)
  "strongest_zone": null,
  "weakest_zone": null,
  
  -- Data quality
  "data_quality_tier": "low",
  "calculation_notes": null,
  
  -- Source tracking (still populated!)
  "source_team_defense_last_updated": "2024-10-28T23:05:00Z",
  "source_team_defense_rows_found": 90,
  "source_team_defense_completeness_pct": 100.00,
  "source_team_defense_hash": "7x8y9z0a1b2c3d4e5f6g7h8i9j0k1l2m",

  -- Smart patterns
  "data_hash": "9m0n1o2p3q4r5s6t7u8v9w0x1y2z3a4b",

  -- Early season (SET)
  "early_season_flag": true,
  "insufficient_data_reason": "Only 3 games available, need 15",

  -- Processing metadata
  "processed_at": "2024-10-28T23:10:00Z",
  "created_at": "2024-10-28T23:10:15Z"
}
*/

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Check all teams processed today
-- Expected: 30 rows (all NBA teams)
SELECT 
  analysis_date,
  COUNT(*) as teams_processed,
  COUNT(CASE WHEN early_season_flag = TRUE THEN 1 END) as placeholders,
  COUNT(CASE WHEN paint_pct_allowed_last_15 IS NOT NULL THEN 1 END) as real_data
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
GROUP BY analysis_date;

-- Query 2: Check for data quality issues
-- Expected: 0 rows (no outliers)
SELECT 
  team_abbr,
  analysis_date,
  paint_pct_allowed_last_15,
  mid_range_pct_allowed_last_15,
  three_pt_pct_allowed_last_15,
  games_in_sample
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag IS NULL  -- Only check real data
  AND (
    paint_pct_allowed_last_15 < 0.30 OR paint_pct_allowed_last_15 > 0.70
    OR mid_range_pct_allowed_last_15 < 0.25 OR mid_range_pct_allowed_last_15 > 0.60
    OR three_pt_pct_allowed_last_15 < 0.25 OR three_pt_pct_allowed_last_15 > 0.45
  );

-- Query 3: Check source tracking populated
-- Expected: all counts = teams_processed, avg_completeness near 100
SELECT 
  analysis_date,
  COUNT(*) as teams_processed,
  COUNT(source_team_defense_last_updated) as has_last_updated,
  COUNT(source_team_defense_rows_found) as has_rows_found,
  COUNT(source_team_defense_completeness_pct) as has_completeness,
  AVG(source_team_defense_completeness_pct) as avg_completeness,
  MIN(source_team_defense_completeness_pct) as min_completeness
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY analysis_date
ORDER BY analysis_date DESC;

-- Query 4: Check for stale source data
-- Expected: 0 rows (source data <24 hours old)
SELECT 
  team_abbr,
  analysis_date,
  source_team_defense_last_updated,
  TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(),
    source_team_defense_last_updated,
    HOUR
  ) as age_hours
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(),
    source_team_defense_last_updated,
    HOUR
  ) > 24;

-- Query 5: Identify defensive strengths across league
-- Shows which teams are best/worst at defending each zone
SELECT 
  analysis_date,
  
  -- Best paint defense (most negative)
  (SELECT team_abbr FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis` t
   WHERE t.analysis_date = main.analysis_date
   ORDER BY paint_defense_vs_league_avg ASC LIMIT 1) as best_paint_defense,
  
  -- Worst paint defense (most positive)
  (SELECT team_abbr FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis` t
   WHERE t.analysis_date = main.analysis_date
   ORDER BY paint_defense_vs_league_avg DESC LIMIT 1) as worst_paint_defense,
  
  -- Best three-point defense
  (SELECT team_abbr FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis` t
   WHERE t.analysis_date = main.analysis_date
   ORDER BY three_pt_defense_vs_league_avg ASC LIMIT 1) as best_three_pt_defense,
  
  -- Worst three-point defense
  (SELECT team_abbr FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis` t
   WHERE t.analysis_date = main.analysis_date
   ORDER BY three_pt_defense_vs_league_avg DESC LIMIT 1) as worst_three_pt_defense
  
FROM (SELECT DISTINCT analysis_date FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`) main
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY analysis_date DESC;

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Latest defensive ratings by team
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_latest_team_defense` AS
SELECT 
  team_abbr,
  analysis_date,
  
  -- Paint defense
  paint_pct_allowed_last_15,
  paint_defense_vs_league_avg,
  
  -- Mid-range defense
  mid_range_pct_allowed_last_15,
  mid_range_defense_vs_league_avg,
  
  -- Three-point defense
  three_pt_pct_allowed_last_15,
  three_pt_defense_vs_league_avg,
  
  -- Overall
  defensive_rating_last_15,
  
  -- Strengths
  strongest_zone,
  weakest_zone,
  
  -- Quality
  games_in_sample,
  data_quality_tier,
  early_season_flag,
  
  processed_at
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = (
  SELECT MAX(analysis_date) 
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
)
ORDER BY team_abbr;

-- View: Teams with extreme defensive profiles
CREATE OR REPLACE VIEW `nba-props-platform.nba_precompute.v_extreme_defense` AS
SELECT 
  team_abbr,
  analysis_date,
  
  -- Classification
  CASE 
    WHEN paint_defense_vs_league_avg <= -5 THEN 'ELITE_PAINT'
    WHEN paint_defense_vs_league_avg >= 5 THEN 'WEAK_PAINT'
    WHEN three_pt_defense_vs_league_avg <= -3 THEN 'ELITE_PERIMETER'
    WHEN three_pt_defense_vs_league_avg >= 3 THEN 'WEAK_PERIMETER'
    ELSE 'BALANCED'
  END as defensive_profile,
  
  paint_pct_allowed_last_15,
  paint_defense_vs_league_avg,
  three_pt_pct_allowed_last_15,
  three_pt_defense_vs_league_avg,
  
  strongest_zone,
  weakest_zone
  
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag IS NULL
ORDER BY 
  CASE 
    WHEN ABS(paint_defense_vs_league_avg) > ABS(three_pt_defense_vs_league_avg) 
    THEN ABS(paint_defense_vs_league_avg)
    ELSE ABS(three_pt_defense_vs_league_avg)
  END DESC;

-- ============================================================================
-- USAGE NOTES
-- ============================================================================
--
-- DEPENDENCIES:
--   Source: nba_analytics.team_defense_game_summary (Phase 3)
--   Must be processed nightly before this processor runs
--
-- UPDATE SCHEDULE:
--   Time: 11:00 PM daily
--   Duration: ~2 minutes (30 teams)
--   Must complete by: 11:15 PM (before player processors)
--
-- EARLY SEASON HANDLING:
--   First 14 days of season: Writes placeholder rows
--   All business metrics = NULL
--   early_season_flag = TRUE
--   Downstream should filter: WHERE early_season_flag IS NULL OR early_season_flag = FALSE
--
-- DOWNSTREAM USAGE:
--   - player_shot_zone_analysis (uses opponent defense data)
--   - player_composite_factors (uses for shot_zone_mismatch_score)
--   - Phase 5 prediction systems (matchup analysis)
--
-- DATA QUALITY:
--   - All 30 teams must be processed (no failures allowed)
--   - Source completeness should be 100%
--   - FG% values should be in reasonable ranges (see validation queries)
--
-- MONITORING:
--   - Alert if <30 teams processed
--   - Alert if processing takes >5 minutes
--   - Alert if source data >24 hours old
--   - Alert if completeness <100%
--
-- REGENERATION:
--   Can be regenerated from Phase 3 data at any time
--   No external dependencies beyond team_defense_game_summary
--
-- ============================================================================
-- END OF SCHEMA
-- ============================================================================