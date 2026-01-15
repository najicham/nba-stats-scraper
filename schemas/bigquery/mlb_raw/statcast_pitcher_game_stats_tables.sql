-- =============================================================================
-- MLB Props Platform - Statcast Pitcher Game Stats
-- Per-game pitch-level metrics for rolling feature engineering
-- File: schemas/bigquery/mlb_raw/statcast_pitcher_game_stats_tables.sql
-- =============================================================================
--
-- Data Source: Baseball Savant via pybaseball
-- Update Frequency: Daily during season (backfilled for historical)
--
-- Key Use Cases:
-- 1. Rolling SwStr% (3/5/10 game) for "unlucky pitcher" signal
-- 2. Velocity trends for injury/fatigue detection
-- 3. Pitch mix analysis for context features
--
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.statcast_pitcher_game_stats` (
    -- ==========================================================================
    -- IDENTIFIERS
    -- ==========================================================================
    game_date DATE NOT NULL,
    game_pk INT64,                          -- MLB game ID
    pitcher_id INT64 NOT NULL,              -- MLB player ID (MLBAM)
    pitcher_name STRING,                    -- Full name
    player_lookup STRING,                   -- Normalized name for joining

    -- Team info
    team_abbr STRING,
    opponent_abbr STRING,
    is_home BOOL,

    -- ==========================================================================
    -- SWINGING STRIKE METRICS (KEY FOR MODEL!)
    -- ==========================================================================
    total_pitches INT64,                    -- Total pitches thrown
    total_swings INT64,                     -- Pitches swung at (includes foul, in play)
    swinging_strikes INT64,                 -- Swinging strikes
    swstr_pct FLOAT64,                      -- Swinging strike % = swinging_strikes / total_pitches
    whiff_pct FLOAT64,                      -- Whiff % = swinging_strikes / total_swings

    called_strikes INT64,
    csw_count INT64,                        -- Called strikes + whiffs
    csw_pct FLOAT64,                        -- CSW% = csw_count / total_pitches

    -- ==========================================================================
    -- VELOCITY METRICS (KEY FOR INJURY DETECTION!)
    -- ==========================================================================
    fb_velocity_avg FLOAT64,                -- Fastball average velocity
    fb_velocity_max FLOAT64,                -- Fastball max velocity
    fb_velocity_min FLOAT64,                -- Fastball min velocity
    fb_pitch_count INT64,                   -- Number of fastballs

    all_pitch_velocity_avg FLOAT64,         -- All pitches average

    -- ==========================================================================
    -- PITCH MIX
    -- ==========================================================================
    fastball_pct FLOAT64,                   -- % fastballs (FF, SI, FC)
    breaking_pct FLOAT64,                   -- % breaking (SL, CU, KC, CS)
    offspeed_pct FLOAT64,                   -- % offspeed (CH, FS, FO)

    -- ==========================================================================
    -- OUTCOMES
    -- ==========================================================================
    strikeouts INT64,                       -- Total strikeouts in game
    walks INT64,                            -- Total walks
    hits_allowed INT64,

    -- ==========================================================================
    -- METADATA
    -- ==========================================================================
    season_year INT64,
    source_file_path STRING,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, season_year, team_abbr
OPTIONS (
    description = 'Per-game pitch-level stats from Baseball Savant for rolling SwStr% and velocity features',
    labels = [('data_source', 'baseball_savant'), ('update_frequency', 'daily')]
);

-- =============================================================================
-- USEFUL VIEWS
-- =============================================================================

-- Rolling SwStr% calculation view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.pitcher_rolling_swstr` AS
SELECT
    player_lookup,
    game_date,
    season_year,
    swstr_pct,
    whiff_pct,
    fb_velocity_avg,

    -- Rolling averages
    AVG(swstr_pct) OVER (
        PARTITION BY player_lookup
        ORDER BY game_date
        ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
    ) as swstr_pct_last_3,

    AVG(swstr_pct) OVER (
        PARTITION BY player_lookup
        ORDER BY game_date
        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ) as swstr_pct_last_5,

    AVG(fb_velocity_avg) OVER (
        PARTITION BY player_lookup
        ORDER BY game_date
        ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
    ) as fb_velocity_last_3,

    -- Season baseline
    AVG(swstr_pct) OVER (
        PARTITION BY player_lookup, season_year
        ORDER BY game_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as swstr_pct_season,

    AVG(fb_velocity_avg) OVER (
        PARTITION BY player_lookup, season_year
        ORDER BY game_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as fb_velocity_season

FROM `nba-props-platform.mlb_raw.statcast_pitcher_game_stats`;
