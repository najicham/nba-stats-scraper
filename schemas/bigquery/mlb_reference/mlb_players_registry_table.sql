-- ============================================================================
-- MLB Players Registry Table
-- Authoritative player validation for MLB strikeout predictions
-- File: schemas/bigquery/mlb_reference/mlb_players_registry_table.sql
-- ============================================================================
--
-- Purpose: Maintain authoritative MLB player records for joining across:
-- - Ball Don't Lie stats (pitcher_stats, batter_stats)
-- - Odds API props (pitcher_props, batter_props)
-- - Analytics tables
--
-- Key for Bottom-Up Model:
-- - Links batters to their strikeout histories
-- - Links pitchers to their strikeout lines
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_reference.mlb_players_registry` (
    -- =========================================================================
    -- PLAYER IDENTIFICATION
    -- =========================================================================

    player_lookup STRING NOT NULL,             -- Normalized lookup key (lowercase, no spaces)
    bdl_player_id INT64,                       -- Ball Don't Lie player ID
    player_full_name STRING NOT NULL,          -- Display name
    first_name STRING,                         -- First name
    last_name STRING,                          -- Last name
    team_abbr STRING NOT NULL,                 -- Current team abbreviation
    season_year INT64 NOT NULL,                -- Season year (2024, 2025, etc.)

    -- =========================================================================
    -- PLAYER TYPE (Critical for model)
    -- =========================================================================

    player_type STRING NOT NULL,               -- 'PITCHER' or 'BATTER'
    position STRING,                           -- Detailed position (SP, RP, C, 1B, etc.)
    is_starter BOOL,                           -- For pitchers: starting pitcher
    throws STRING,                             -- 'L' or 'R' (for pitchers)
    bats STRING,                               -- 'L', 'R', or 'S' (for batters)

    -- =========================================================================
    -- GAME PARTICIPATION
    -- =========================================================================

    first_game_date DATE,                      -- First game this season
    last_game_date DATE,                       -- Most recent game
    games_played INT64,                        -- Total games this season

    -- =========================================================================
    -- SEASON STATS SUMMARY (for quick lookups)
    -- =========================================================================

    -- Pitcher stats
    season_strikeouts INT64,                   -- Season K total (pitchers)
    season_innings NUMERIC(6,1),               -- Season IP (pitchers)
    season_k_per_9 NUMERIC(4,2),               -- K/9 rate (pitchers)

    -- Batter stats
    season_at_bats INT64,                      -- Season AB (batters)
    season_batter_ks INT64,                    -- Season strikeouts (batters)
    season_k_rate NUMERIC(4,3),                -- K rate (batters)

    -- =========================================================================
    -- DATA SOURCE TRACKING
    -- =========================================================================

    source_priority STRING,                    -- 'bdl_stats', 'odds_api', 'active_players'
    confidence_score NUMERIC(3,2),             -- Data quality confidence (0.0-1.0)

    -- =========================================================================
    -- PROCESSING METADATA
    -- =========================================================================

    last_updated_by STRING,                    -- Which processor last updated
    update_count INT64 DEFAULT 0,              -- Number of times updated
    created_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP NOT NULL
)
CLUSTER BY player_lookup, team_abbr, season_year, player_type
OPTIONS (
  description = "MLB players registry for authoritative player validation. Key for joining pitcher and batter data across sources."
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Active pitchers (current season)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_reference.mlb_active_pitchers` AS
SELECT *
FROM `nba-props-platform.mlb_reference.mlb_players_registry`
WHERE player_type = 'PITCHER'
  AND season_year = EXTRACT(YEAR FROM CURRENT_DATE())
  AND last_game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Active batters (current season)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_reference.mlb_active_batters` AS
SELECT *
FROM `nba-props-platform.mlb_reference.mlb_players_registry`
WHERE player_type = 'BATTER'
  AND season_year = EXTRACT(YEAR FROM CURRENT_DATE())
  AND last_game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- High-K pitchers (for model focus)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_reference.mlb_high_k_pitchers` AS
SELECT
  player_lookup,
  player_full_name,
  team_abbr,
  season_strikeouts,
  season_innings,
  season_k_per_9,
  games_played
FROM `nba-props-platform.mlb_reference.mlb_players_registry`
WHERE player_type = 'PITCHER'
  AND season_year = EXTRACT(YEAR FROM CURRENT_DATE())
  AND season_innings >= 50.0
  AND season_k_per_9 >= 8.0
ORDER BY season_k_per_9 DESC;

-- High-K batters (strikeout prone - important for bottom-up model)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_reference.mlb_high_k_batters` AS
SELECT
  player_lookup,
  player_full_name,
  team_abbr,
  season_batter_ks,
  season_at_bats,
  season_k_rate,
  games_played
FROM `nba-props-platform.mlb_reference.mlb_players_registry`
WHERE player_type = 'BATTER'
  AND season_year = EXTRACT(YEAR FROM CURRENT_DATE())
  AND season_at_bats >= 100
  AND season_k_rate >= 0.25  -- 25%+ K rate
ORDER BY season_k_rate DESC;
