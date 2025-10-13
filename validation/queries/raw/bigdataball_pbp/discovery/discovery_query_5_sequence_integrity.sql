-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/discovery/discovery_query_5_sequence_integrity.sql
-- ============================================================================
-- BigDataBall Play-by-Play Discovery Query 5: Event Sequence Integrity
-- Purpose: Check if event sequences are complete and properly ordered
-- ============================================================================
-- This is UNIQUE to play-by-play data (not applicable to box scores)
-- 
-- Good data:
--   - event_sequence starts at 1 or 0
--   - No large gaps in sequence numbers
--   - Sequences are continuous per game
-- 
-- Bad data:
--   - Sequences start at random numbers
--   - Large gaps = missing events
--   - Duplicate sequences = data quality issue
-- ============================================================================

WITH game_sequences AS (
  SELECT
    game_id,
    game_date,
    COUNT(*) as total_events,
    MIN(event_sequence) as first_sequence,
    MAX(event_sequence) as last_sequence,
    MAX(event_sequence) - MIN(event_sequence) + 1 as expected_events,
    COUNT(DISTINCT event_sequence) as unique_sequences
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date >= '2024-01-01'  -- UPDATE based on Discovery Q1
  GROUP BY game_id, game_date
)
SELECT
  game_date,
  game_id,
  total_events,
  first_sequence,
  last_sequence,
  expected_events,
  unique_sequences,
  total_events - unique_sequences as duplicate_sequences,
  expected_events - unique_sequences as missing_sequences,
  CASE
    WHEN first_sequence NOT IN (0, 1) THEN '⚠️ Unusual start sequence'
    WHEN total_events != unique_sequences THEN '🔴 DUPLICATE SEQUENCES'
    WHEN expected_events - unique_sequences > 5 THEN '🔴 LARGE GAPS in sequence'
    WHEN expected_events - unique_sequences > 0 THEN '⚠️ Small gaps in sequence'
    ELSE '✅ Complete & ordered'
  END as status
FROM game_sequences
WHERE 
  first_sequence NOT IN (0, 1)  -- Non-standard start
  OR total_events != unique_sequences  -- Duplicates
  OR expected_events - unique_sequences > 0  -- Gaps
ORDER BY game_date DESC
LIMIT 100;

-- Interpretation:
-- ✅ Complete: first_sequence=0 or 1, no gaps, no duplicates
-- 🔴 CRITICAL: Duplicates or large gaps = data corruption
-- ⚠️ WARNING: Small gaps or unusual start = investigate specific games
