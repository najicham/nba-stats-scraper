-- duplicate_detection_check.sql
-- Detects duplicate game_ids in nbac_schedule table
--
-- Expected: 0 rows (no duplicates after MERGE fix applied)
-- Alert threshold: > 0 duplicates
--
-- Created: 2026-01-11 (Session 9 - Schedule MERGE fix)

SELECT
  game_date,
  game_id,
  COUNT(*) as duplicate_count,
  ARRAY_AGG(DISTINCT game_status ORDER BY game_status) as status_values,
  ARRAY_AGG(DISTINCT game_status_text ORDER BY game_status_text) as status_texts,
  MIN(processed_at) as first_processed,
  MAX(processed_at) as last_processed
FROM `nba_raw.nbac_schedule`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date, game_id
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, game_date DESC;

-- Summary query for monitoring dashboards:
-- SELECT
--   CURRENT_TIMESTAMP() as check_time,
--   COUNTIF(cnt > 1) as games_with_duplicates,
--   SUM(IF(cnt > 1, cnt - 1, 0)) as total_duplicate_rows
-- FROM (
--   SELECT game_id, COUNT(*) as cnt
--   FROM nba_raw.nbac_schedule
--   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   GROUP BY game_id
-- );
