-- Pending BigDataBall Games Tracking Table
-- Tracks games that were processed with NBAC fallback and need BDB re-run
--
-- Purpose: BigDataBall is the gold standard for shot zone data. When unavailable,
-- we fall back to NBAC but should re-run with BDB when it becomes available.
--
-- Business Rule: Don't re-run if prediction already made for that game date
-- (don't want to change predictions close to game time)
--
-- Created: Session 39 (2026-01-30)

CREATE TABLE IF NOT EXISTS `nba_orchestration.pending_bdb_games` (
    -- Game identification
    game_date DATE NOT NULL,
    game_id STRING NOT NULL,
    nba_game_id STRING,
    home_team STRING,
    away_team STRING,
    season_year INT64,

    -- Processing status
    fallback_source STRING NOT NULL,  -- 'nbac_play_by_play', 'estimated', 'none'
    original_processed_at TIMESTAMP NOT NULL,

    -- BDB availability tracking
    bdb_detected_at TIMESTAMP,        -- When BDB data was detected as available
    bdb_rerun_at TIMESTAMP,           -- When we re-ran with BDB data
    bdb_rerun_blocked_reason STRING,  -- If re-run was blocked (e.g., 'prediction_already_made')

    -- Prediction tracking (to prevent changing predictions close to game time)
    prediction_exists BOOL DEFAULT FALSE,
    prediction_made_at TIMESTAMP,
    game_start_time TIMESTAMP,        -- To know if too close to game time

    -- Resolution
    status STRING NOT NULL DEFAULT 'pending_bdb',  -- 'pending_bdb', 'bdb_available', 'reran', 'blocked', 'expired'
    resolution_type STRING,           -- 'auto_rerun', 'manual_rerun', 'blocked_by_prediction', 'expired_after_game'
    resolution_notes STRING,

    -- Quality tracking
    quality_before_rerun STRING,      -- 'silver', 'bronze'
    quality_after_rerun STRING,       -- 'gold' (if BDB used)
    shot_zones_complete_before BOOL,
    shot_zones_complete_after BOOL,

    -- Retry tracking
    bdb_check_count INT64 DEFAULT 0,
    last_bdb_check_at TIMESTAMP,
    next_bdb_check_at TIMESTAMP,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

-- Add comment for documentation
-- This table is used by:
-- 1. shot_zone_analyzer.py - Inserts when fallback is used
-- 2. bdb_pending_monitor.py - Checks for BDB availability and triggers re-run
-- 3. validate_tonight_data.py - Reports pending BDB games
