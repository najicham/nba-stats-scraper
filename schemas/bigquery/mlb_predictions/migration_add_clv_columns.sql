-- Migration: Add CLV columns to mlb_predictions.prediction_accuracy
-- Created: 2026-05-13 (Session 3 of MLB roadmap, A5 build)
--
-- Adds 4 nullable CLV columns. Populated by mlb_grading_service when a matching
-- mlb_raw.pitcher_props_closing row is available; otherwise NULL with quality flag.
--
-- Layered design: closing_line + closing_bookmaker + closing_snapshot_time pin the
-- row used; clv_directional is the signed-by-recommendation buy quality
-- (+ when the player got better than market close).

ALTER TABLE `nba-props-platform.mlb_predictions.prediction_accuracy`
  ADD COLUMN IF NOT EXISTS pick_time_line        NUMERIC,
  ADD COLUMN IF NOT EXISTS closing_line          NUMERIC,
  ADD COLUMN IF NOT EXISTS closing_bookmaker     STRING,
  ADD COLUMN IF NOT EXISTS closing_snapshot_time TIMESTAMP,
  ADD COLUMN IF NOT EXISTS clv_raw               NUMERIC,
  ADD COLUMN IF NOT EXISTS clv_directional       NUMERIC,
  ADD COLUMN IF NOT EXISTS clv_quality_flag      STRING;
