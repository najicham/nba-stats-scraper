-- ============================================================================
-- MLB Props Platform - FanGraphs Pitcher Season Stats
-- Season-level advanced metrics for strikeout prediction
-- File: schemas/bigquery/mlb_raw/fangraphs_pitcher_season_stats_tables.sql
-- ============================================================================
--
-- Data Source: FanGraphs via pybaseball
-- Update Frequency: Daily during season
--
-- Key Metrics for K Prediction:
-- - SwStr% (Swinging Strike %): Leading indicator of K ability
-- - CSW% (Called Strike + Whiff %): Overall strike effectiveness
-- - K% / BB%: Strikeout and walk rates
-- - Velocity metrics (when available from Statcast merge)
--
-- Usage: Join to pitcher_game_summary by player_lookup + season_year
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.fangraphs_pitcher_season_stats` (
  -- ============================================================================
  -- IDENTIFIERS
  -- ============================================================================
  fangraphs_id INT64,                           -- FanGraphs player ID
  player_name STRING NOT NULL,                  -- Display name from FanGraphs
  player_lookup STRING NOT NULL,                -- Normalized name for joining
  team STRING,                                  -- Team abbreviation
  season_year INT64 NOT NULL,                   -- Season year

  -- ============================================================================
  -- BASIC STATS
  -- ============================================================================
  age INT64,                                    -- Player age
  games INT64,                                  -- Games played
  games_started INT64,                          -- Games started
  wins INT64,
  losses INT64,
  saves INT64,
  innings_pitched NUMERIC(6,1),                 -- Total innings pitched

  -- ============================================================================
  -- STRIKEOUT METRICS (KEY FEATURES)
  -- ============================================================================
  strikeouts INT64,                             -- Total strikeouts
  k_per_9 NUMERIC(5,2),                         -- K/9 rate
  k_pct NUMERIC(5,3),                           -- Strikeout percentage (K/PA)
  bb_per_9 NUMERIC(5,2),                        -- BB/9 rate
  bb_pct NUMERIC(5,3),                          -- Walk percentage
  k_bb_ratio NUMERIC(5,2),                      -- K/BB ratio

  -- ============================================================================
  -- SWINGING STRIKE METRICS (LEADING INDICATORS)
  -- ============================================================================
  swstr_pct NUMERIC(5,3),                       -- Swinging strike % (KEY FEATURE!)
  csw_pct NUMERIC(5,3),                         -- Called strike + whiff %
  o_swing_pct NUMERIC(5,3),                     -- Chase rate (swings outside zone)
  z_swing_pct NUMERIC(5,3),                     -- In-zone swing rate
  swing_pct NUMERIC(5,3),                       -- Overall swing rate
  contact_pct NUMERIC(5,3),                     -- Contact rate
  z_contact_pct NUMERIC(5,3),                   -- In-zone contact rate
  o_contact_pct NUMERIC(5,3),                   -- Outside zone contact rate

  -- ============================================================================
  -- TRADITIONAL STATS
  -- ============================================================================
  era NUMERIC(5,2),                             -- Earned run average
  whip NUMERIC(5,3),                            -- Walks + Hits per IP
  fip NUMERIC(5,2),                             -- Fielding Independent Pitching
  xfip NUMERIC(5,2),                            -- Expected FIP

  -- ============================================================================
  -- BATTED BALL METRICS
  -- ============================================================================
  gb_pct NUMERIC(5,3),                          -- Ground ball %
  fb_pct NUMERIC(5,3),                          -- Fly ball %
  ld_pct NUMERIC(5,3),                          -- Line drive %
  hr_per_fb NUMERIC(5,3),                       -- HR per fly ball

  -- ============================================================================
  -- VALUE METRICS
  -- ============================================================================
  war NUMERIC(5,2),                             -- Wins Above Replacement

  -- ============================================================================
  -- METADATA
  -- ============================================================================
  snapshot_date DATE NOT NULL,                  -- When data was captured
  source_file_path STRING,
  data_hash STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY player_lookup, season_year
OPTIONS (
  description = "FanGraphs pitcher season stats with SwStr% and advanced plate discipline metrics. Key data source for K prediction leading indicators.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Current season stats (latest snapshot)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.fangraphs_pitcher_current` AS
SELECT * EXCEPT(rn)
FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY player_lookup, season_year ORDER BY snapshot_date DESC) as rn
  FROM `nba-props-platform.mlb_raw.fangraphs_pitcher_season_stats`
  WHERE snapshot_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
WHERE rn = 1;

-- High SwStr% pitchers (elite K stuff)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.fangraphs_elite_k_pitchers` AS
SELECT
  player_lookup,
  player_name,
  team,
  season_year,
  swstr_pct,
  csw_pct,
  k_per_9,
  k_pct,
  innings_pitched
FROM `nba-props-platform.mlb_raw.fangraphs_pitcher_current`
WHERE swstr_pct >= 0.12  -- 12%+ SwStr% is elite
  AND innings_pitched >= 50
ORDER BY swstr_pct DESC;

-- SwStr% vs K correlation analysis
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.fangraphs_swstr_k_correlation` AS
SELECT
  season_year,
  COUNT(*) as pitchers,
  AVG(swstr_pct) as avg_swstr,
  AVG(k_pct) as avg_k_pct,
  CORR(swstr_pct, k_pct) as swstr_k_correlation
FROM `nba-props-platform.mlb_raw.fangraphs_pitcher_current`
WHERE innings_pitched >= 30
GROUP BY season_year
ORDER BY season_year DESC;
