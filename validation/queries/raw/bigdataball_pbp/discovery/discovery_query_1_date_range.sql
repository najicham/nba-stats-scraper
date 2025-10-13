-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/discovery/discovery_query_1_date_range.sql
-- ============================================================================
-- BigDataBall Play-by-Play Discovery Query 1: Actual Date Range
-- Purpose: Find what data ACTUALLY exists in the table
-- ============================================================================
-- CRITICAL: Run this FIRST to verify coverage before creating validation queries
-- ============================================================================

SELECT 
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  COUNT(DISTINCT game_date) as total_dates_with_data,
  COUNT(*) as total_events,
  COUNT(DISTINCT game_id) as unique_games,
  ROUND(COUNT(*) / COUNT(DISTINCT game_id), 1) as avg_events_per_game,
  MIN(event_sequence) as min_event_sequence,
  MAX(event_sequence) as max_event_sequence
FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
WHERE game_date >= '2020-01-01';  -- Wide filter for discovery

-- Expected Results:
-- If processor reference is correct: Oct 2024 - Jun 2025 only
-- If you have 4 seasons: Oct 2021 - Jun 2025
-- THIS WILL TELL US THE TRUTH!
