-- =============================================================================
-- MLB Props Platform - Game Feed Per-Pitch Data
-- One row per pitch, sourced from MLB Stats API /game/{pk}/feed/live
-- File: schemas/bigquery/mlb_raw/mlb_game_feed_pitches_tables.sql
-- =============================================================================
--
-- Data Source: MLB Stats API (statsapi.mlb.com/api/v1.1/game/{pk}/feed/live)
-- Scraper: MlbGameFeedDailyScraper (iterates schedule, fetches all Final games)
-- Processor: MlbGameFeedPitchesProcessor
-- Update Frequency: Daily (3 AM ET during season)
--
-- Purpose:
--   statcast_pitcher_daily gives per-pitcher aggregates with a pitch_types JSON
--   dict (counts only). This table gives full pitch-level detail including
--   per-pitch velocity, spin rate, and result classification — enabling true
--   per-pitch-type velocity and whiff rate metrics.
--
-- Key use cases:
--   - Per-pitch-type velocity (avg, max) per pitcher
--   - Per-pitch-type whiff rate (swinging strikes / swings on that pitch type)
--   - Count-specific pitch usage (e.g. 2-strike putaway pitches)
--   - Inning velocity fade
--   - Advanced signals: K Pitch Effectiveness L3, Arsenal Concentration Score
--
-- Dedup key: (game_pk, at_bat_index, pitch_number)
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlb_game_feed_pitches` (
    -- ==========================================================================
    -- GAME CONTEXT
    -- ==========================================================================
    game_date DATE NOT NULL,
    game_pk INT64 NOT NULL,

    -- ==========================================================================
    -- PITCHER
    -- ==========================================================================
    pitcher_id INT64 NOT NULL,
    pitcher_name STRING,
    pitcher_lookup STRING,                      -- Normalized (no spaces/punct), matches statcast_pitcher_daily

    -- ==========================================================================
    -- BATTER
    -- ==========================================================================
    batter_id INT64,
    batter_name STRING,
    batter_side STRING,                         -- 'L' / 'R' (from batSide in matchup)

    -- ==========================================================================
    -- PITCH CLASSIFICATION
    -- ==========================================================================
    pitch_type_code STRING,                     -- 'FF', 'SL', 'CH', etc.
    pitch_type_desc STRING,                     -- 'Four-Seam Fastball', 'Slider', etc.

    -- ==========================================================================
    -- PITCH PHYSICS
    -- ==========================================================================
    velocity FLOAT64,                           -- pitchData.startSpeed (mph)
    spin_rate FLOAT64,                          -- pitchData.spinRate (rpm)
    extension FLOAT64,                          -- pitchData.extension (feet, if present)
    zone INT64,                                 -- pitchData.zone (1-14, MLB zone code)

    -- ==========================================================================
    -- PITCH RESULT (derived from details.description)
    -- ==========================================================================
    result_description STRING,                  -- Raw description: 'Swinging Strike', 'Ball', 'In play, run(s)', etc.
    is_swinging_strike BOOL,
    is_called_strike BOOL,
    is_foul BOOL,
    is_ball BOOL,
    is_in_play BOOL,
    is_swing BOOL,                              -- swinging_strike OR foul OR in_play
    is_in_zone BOOL,                            -- zone BETWEEN 1 AND 9
    is_chase BOOL,                              -- swing on out-of-zone pitch
    is_whiff BOOL,                              -- swinging_strike (synonym for clarity)

    -- ==========================================================================
    -- AT-BAT / COUNT CONTEXT
    -- ==========================================================================
    count_balls INT64,                          -- Balls before this pitch
    count_strikes INT64,                        -- Strikes before this pitch
    inning INT64,
    half_inning STRING,                         -- 'top' / 'bottom'
    at_bat_index INT64,                         -- 0-indexed within game
    pitch_number INT64,                         -- 1-indexed within at-bat

    -- ==========================================================================
    -- AT-BAT OUTCOME (set on the final pitch of the at-bat)
    -- ==========================================================================
    at_bat_event STRING,                        -- 'Strikeout', 'Walk', 'Single', etc. (NULL if not last pitch)
    is_at_bat_end BOOL,                         -- True on the terminal pitch of the at-bat

    -- ==========================================================================
    -- PROCESSING METADATA
    -- ==========================================================================
    source_file_path STRING,
    processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup, pitch_type_code
OPTIONS (
    require_partition_filter = TRUE,
    description = 'Per-pitch detail from MLB Stats API game feed. Populated daily. '
                  'Dedup key: (game_pk, at_bat_index, pitch_number). '
                  'Source of truth for per-pitch-type velocity and whiff rate.',
    labels = [('data_source', 'mlb_stats_api'), ('update_frequency', 'daily')]
);
