-- ============================================================================
-- Fix Duplicate Predictions in prediction_grades Table
-- ============================================================================
-- Purpose: Remove duplicate predictions and prevent future duplicates
-- Date: 2026-01-17
-- Issue: ~5,000 duplicate predictions found (43% of total)
-- ============================================================================

-- Step 1: Analyze duplicates before deletion
-- ============================================================================

-- Count duplicates by date
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT CONCAT(player_lookup, '-', game_date, '-', system_id, '-', CAST(points_line AS STRING))) as unique_predictions,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '-', game_date, '-', system_id, '-', CAST(points_line AS STRING))) as duplicates
FROM `nba-props-platform.nba_predictions.prediction_grades`
GROUP BY game_date
HAVING duplicates > 0
ORDER BY duplicates DESC;

-- Find worst offenders
SELECT
  player_lookup,
  game_date,
  system_id,
  points_line,
  COUNT(*) as duplicate_count,
  ARRAY_AGG(prediction_id LIMIT 5) as sample_prediction_ids
FROM `nba-props-platform.nba_predictions.prediction_grades`
GROUP BY player_lookup, game_date, system_id, points_line
HAVING duplicate_count > 1
ORDER BY duplicate_count DESC
LIMIT 20;


-- Step 2: Create de-duplicated version of the table
-- ============================================================================
-- Strategy: Keep the FIRST occurrence (earliest graded_at) of each unique prediction

CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.prediction_grades_deduped`
PARTITION BY game_date
CLUSTER BY player_lookup, prediction_correct, confidence_score
AS
SELECT * EXCEPT(row_num)
FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_date, system_id, COALESCE(points_line, -999)
      ORDER BY graded_at ASC  -- Keep earliest graded prediction
    ) as row_num
  FROM `nba-props-platform.nba_predictions.prediction_grades`
)
WHERE row_num = 1;

-- Verify de-duplication worked
SELECT
  'Before' as dataset,
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(player_lookup, '-', game_date, '-', system_id, '-', CAST(points_line AS STRING))) as unique_predictions
FROM `nba-props-platform.nba_predictions.prediction_grades`

UNION ALL

SELECT
  'After' as dataset,
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(player_lookup, '-', game_date, '-', system_id, '-', CAST(points_line AS STRING))) as unique_predictions
FROM `nba-props-platform.nba_predictions.prediction_grades_deduped`;


-- Step 3: Backup original table and replace with de-duplicated version
-- ============================================================================
-- IMPORTANT: Run this manually after verifying de-duplication worked!

-- -- Backup original table
-- CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.prediction_grades_backup_20260117`
-- CLONE `nba-props-platform.nba_predictions.prediction_grades`;

-- -- Drop original table
-- DROP TABLE `nba-props-platform.nba_predictions.prediction_grades`;

-- -- Rename de-duplicated table to original name
-- ALTER TABLE `nba-props-platform.nba_predictions.prediction_grades_deduped`
-- RENAME TO prediction_grades;


-- Step 4: Create monitoring view to detect future duplicates
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.duplicate_predictions_monitor` AS
SELECT
  game_date,
  player_lookup,
  system_id,
  points_line,
  COUNT(*) as duplicate_count,
  MIN(graded_at) as first_graded,
  MAX(graded_at) as last_graded,
  TIMESTAMP_DIFF(MAX(graded_at), MIN(graded_at), SECOND) as seconds_between_duplicates,
  ARRAY_AGG(prediction_id ORDER BY graded_at) as all_prediction_ids
FROM `nba-props-platform.nba_predictions.prediction_grades`
GROUP BY game_date, player_lookup, system_id, points_line
HAVING duplicate_count > 1
ORDER BY game_date DESC, duplicate_count DESC;

-- Query to run daily to check for duplicates
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players_affected,
  SUM(duplicate_count - 1) as total_duplicates,
  MAX(duplicate_count) as worst_case
FROM `nba-props-platform.nba_predictions.duplicate_predictions_monitor`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- ============================================================================
-- Notes for Manual Execution
-- ============================================================================
-- 1. Run Step 1 (analyze) to understand the scope
-- 2. Run Step 2 (create deduped table) and verify counts
-- 3. Manually uncomment and run Step 3 (backup and replace)
-- 4. Run Step 4 (create monitoring view)
-- 5. Update grade_predictions_query.sql to use improved deduplication logic
-- ============================================================================
