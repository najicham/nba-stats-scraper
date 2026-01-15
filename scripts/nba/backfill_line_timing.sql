-- =============================================================================
-- LINE TIMING BACKFILL QUERY (Option C - Manual Review)
-- =============================================================================
-- Created: 2026-01-15
-- Purpose: Estimate line_minutes_before_game for historical predictions
--
-- DECISION NEEDED: Run this after manual review
--
-- Summary:
--   - 136,946 total predictions since 2025-01-01
--   - 1,935 predictions with ODDS_API source (backfill candidates)
--   - Estimated lines (134k+) will remain NULL (no timing data)
-- =============================================================================

-- =============================================================================
-- STEP 1: VALIDATION QUERY - Run first to understand match quality
-- =============================================================================
-- This shows how many predictions can be matched and the timing distribution

SELECT
  p.game_date,
  COUNT(*) as predictions,
  COUNTIF(o.minutes_before_tipoff IS NOT NULL) as matched,
  ROUND(100.0 * COUNTIF(o.minutes_before_tipoff IS NOT NULL) / COUNT(*), 1) as match_pct,
  ROUND(AVG(o.minutes_before_tipoff), 0) as avg_timing_mins,
  -- Check how close we're matching (timestamp diff)
  ROUND(AVG(ABS(TIMESTAMP_DIFF(o.snapshot_timestamp, p.created_at, MINUTE))), 0) as avg_time_diff_mins
FROM nba_predictions.player_prop_predictions p
LEFT JOIN (
  -- Get closest matching odds snapshot for each prediction
  SELECT DISTINCT
    player_lookup,
    game_date,
    points_line,
    minutes_before_tipoff,
    snapshot_timestamp,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_date, points_line
      ORDER BY snapshot_timestamp DESC
    ) as rn
  FROM nba_raw.odds_api_player_points_props
) o ON
  o.player_lookup = p.player_lookup
  AND o.game_date = p.game_date
  AND o.points_line = p.current_points_line
  AND o.rn = 1
WHERE p.line_source_api = 'ODDS_API'
  AND p.line_minutes_before_game IS NULL
  AND p.game_date >= '2025-01-01'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 20;


-- =============================================================================
-- STEP 2: DRY RUN - See what values would be set (no changes)
-- =============================================================================
-- Run this to preview the backfill before committing

SELECT
  p.prediction_id,
  p.player_lookup,
  p.game_date,
  p.current_points_line,
  p.created_at,
  o.minutes_before_tipoff as estimated_timing,
  o.snapshot_timestamp as matched_snapshot,
  ABS(TIMESTAMP_DIFF(o.snapshot_timestamp, p.created_at, MINUTE)) as match_diff_mins
FROM nba_predictions.player_prop_predictions p
INNER JOIN (
  SELECT
    player_lookup,
    game_date,
    points_line,
    minutes_before_tipoff,
    snapshot_timestamp,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_date, points_line
      ORDER BY snapshot_timestamp DESC
    ) as rn
  FROM nba_raw.odds_api_player_points_props
) o ON
  o.player_lookup = p.player_lookup
  AND o.game_date = p.game_date
  AND o.points_line = p.current_points_line
  AND o.rn = 1
WHERE p.line_source_api = 'ODDS_API'
  AND p.line_minutes_before_game IS NULL
  AND p.game_date >= '2025-01-08'  -- Limit to recent data for preview
ORDER BY p.game_date DESC, p.player_lookup
LIMIT 50;


-- =============================================================================
-- STEP 3: ACTUAL BACKFILL - Run only after validation looks good
-- =============================================================================
-- WARNING: This modifies production data!
--
-- Approach:
--   1. Match predictions to odds by: player_lookup, game_date, points_line
--   2. Use most recent odds snapshot (closest to the actual line value)
--   3. Only update ODDS_API predictions (skip ESTIMATED/BETTINGPROS)
--
-- Limitations:
--   - Multiple snapshots may have same line value (we take most recent)
--   - Line may not have changed for hours (timing could be off)
--   - Only works for exact line matches (precision differences may miss)

UPDATE nba_predictions.player_prop_predictions p
SET line_minutes_before_game = (
  SELECT o.minutes_before_tipoff
  FROM (
    SELECT
      player_lookup,
      game_date,
      points_line,
      minutes_before_tipoff,
      ROW_NUMBER() OVER (
        PARTITION BY player_lookup, game_date, points_line
        ORDER BY snapshot_timestamp DESC
      ) as rn
    FROM nba_raw.odds_api_player_points_props
  ) o
  WHERE o.player_lookup = p.player_lookup
    AND o.game_date = p.game_date
    AND o.points_line = p.current_points_line
    AND o.rn = 1
)
WHERE p.line_source_api = 'ODDS_API'
  AND p.line_minutes_before_game IS NULL
  AND p.game_date >= '2025-01-01';


-- =============================================================================
-- STEP 4: POST-BACKFILL VALIDATION
-- =============================================================================
-- Run after backfill to verify results

SELECT
  CASE
    WHEN line_minutes_before_game < 60 THEN 'closing (< 1hr)'
    WHEN line_minutes_before_game < 180 THEN 'afternoon (1-3hr)'
    WHEN line_minutes_before_game < 360 THEN 'morning (3-6hr)'
    ELSE 'early (> 6hr)'
  END as timing_bucket,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE line_source_api = 'ODDS_API'
  AND line_minutes_before_game IS NOT NULL
  AND game_date >= '2025-01-01'
GROUP BY 1
ORDER BY
  CASE
    WHEN line_minutes_before_game < 60 THEN 1
    WHEN line_minutes_before_game < 180 THEN 2
    WHEN line_minutes_before_game < 360 THEN 3
    ELSE 4
  END;


-- =============================================================================
-- NOTES FOR REVIEWER
-- =============================================================================
/*
PROS of running this backfill:
  - Enables historical analysis immediately
  - Can compare closing line vs early line performance
  - ~1,935 predictions would get timing data

CONS / RISKS:
  - Imprecise: If line didn't change for hours, timing may be inaccurate
  - Multiple snapshots with same line: We pick most recent, but actual
    prediction might have used an earlier snapshot
  - Only 1.4% of predictions have ODDS_API source (most are ESTIMATED)

RECOMMENDATION:
  1. Run STEP 1 (Validation) first to see match rates
  2. Run STEP 2 (Dry Run) to preview specific matches
  3. If match quality looks good (>80% match rate, avg_time_diff < 30 min),
     proceed with STEP 3
  4. Run STEP 4 to verify distribution after backfill

ALTERNATIVE: Skip backfill entirely
  - New predictions (after today) will have accurate timing
  - Historical analysis can be done in ~1 week with new data
  - No risk of incorrect attribution
*/
