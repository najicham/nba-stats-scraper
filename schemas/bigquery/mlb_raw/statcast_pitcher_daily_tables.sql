-- =============================================================================
-- MLB Props Platform - Statcast Pitcher Daily Summary
-- Per-game Statcast metrics from daily batch scraper (mlb_statcast_daily.py)
-- File: schemas/bigquery/mlb_raw/statcast_pitcher_daily_tables.sql
-- =============================================================================
--
-- Data Source: Baseball Savant via pybaseball (daily batch)
-- Processor: MlbStatcastDailyProcessor
-- Update Frequency: Daily during season
--
-- Key Use Cases:
-- 1. Rolling SwStr%/CSW% for strikeout prediction features
-- 2. Whiff rate trends for "stuff quality" signal
-- 3. Velocity tracking for injury/fatigue detection
-- 4. Chase rate for pitcher command assessment
-- 5. Pitch mix analysis for context features
--
-- Differs from statcast_pitcher_game_stats:
--   - Sourced from daily batch scraper (all pitchers per date in one call)
--   - Includes zone_pct, chase_rate, and raw pitch_types JSON
--   - Uses data_hash for change detection on re-processing
--
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.statcast_pitcher_daily` (
    -- ==========================================================================
    -- IDENTIFIERS
    -- ==========================================================================
    game_date DATE NOT NULL,
    game_pk INT64,                              -- MLB game ID
    pitcher_id INT64 NOT NULL,                  -- MLB player ID (MLBAM)
    pitcher_name STRING,                        -- Full name (from pybaseball)
    player_lookup STRING,                       -- Normalized name for joining

    -- ==========================================================================
    -- PITCH COUNTS
    -- ==========================================================================
    total_pitches INT64,                        -- Total pitches thrown
    swinging_strikes INT64,                     -- Swinging strikes
    called_strikes INT64,                       -- Called strikes (looking)
    fouls INT64,                                -- Foul balls
    balls INT64,                                -- Balls (incl. blocked, HBP)
    in_play INT64,                              -- Balls put in play

    -- ==========================================================================
    -- VELOCITY METRICS
    -- ==========================================================================
    avg_velocity FLOAT64,                       -- Average fastball velocity (FF/SI/FC)
    max_velocity FLOAT64,                       -- Max pitch velocity (all types)
    avg_spin_rate FLOAT64,                      -- Average spin rate (all pitches)

    -- ==========================================================================
    -- RATES (MOST PREDICTIVE OF K OUTCOMES)
    -- ==========================================================================
    swstr_pct FLOAT64,                          -- Swinging strike % (swinging_strikes / total_pitches)
    csw_pct FLOAT64,                            -- Called + swinging strike % ((called + swinging) / total)
    whiff_rate FLOAT64,                         -- Whiff rate (swinging_strikes / total_swings)
    zone_pct FLOAT64,                           -- % of pitches in strike zone (zones 1-9)
    chase_rate FLOAT64,                         -- Out-of-zone swing % (chases / out-of-zone pitches)

    -- ==========================================================================
    -- PITCH MIX
    -- ==========================================================================
    pitch_types STRING,                         -- JSON: {"FF": 42, "SL": 28, "CH": 18, ...}

    -- ==========================================================================
    -- PROCESSING METADATA
    -- ==========================================================================
    source_file_path STRING,                    -- GCS path of source JSON
    data_hash STRING,                           -- MD5 hash of key fields for change detection
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_id, player_lookup
OPTIONS (
    require_partition_filter = TRUE,
    description = 'Daily Statcast pitcher metrics from Baseball Savant via pybaseball. '
                  'SwStr% and whiff_rate are the most predictive features for strikeout modeling.',
    labels = [('data_source', 'baseball_savant'), ('update_frequency', 'daily')]
);
