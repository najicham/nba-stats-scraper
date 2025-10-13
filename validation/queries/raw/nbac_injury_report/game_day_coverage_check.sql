-- ============================================================================
-- File: validation/queries/raw/nbac_injury_report/game_day_coverage_check.sql
-- Purpose: Cross-validate with schedule - ensure reports on all game days
-- Usage: Run to detect missing injury reports on game days
-- ============================================================================
-- Expected Results:
--   - Every game day should have injury reports
--   - Missing reports on game days = CRITICAL risk for props
-- ============================================================================

WITH 
-- Get all game dates from schedule
all_game_dates AS (
  SELECT DISTINCT
    game_date,
    COUNT(*) as games_scheduled,
    -- FIXED: Removed DISTINCT to allow ORDER BY on different column
    STRING_AGG(CONCAT(away_team_tricode, '@', home_team_tricode) ORDER BY game_id) as matchups
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'  -- UPDATE: Season range
    AND is_playoffs = FALSE
    AND game_date BETWEEN '2021-10-01' AND '2025-06-30'  -- Partition filter
  GROUP BY game_date
),

-- Get injury report coverage for those dates
injury_report_coverage AS (
  SELECT 
    report_date,
    COUNT(DISTINCT report_hour) as hourly_snapshots,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(*) as total_records,
    AVG(confidence_score) as avg_confidence,
    -- Check for peak hours
    MAX(CASE WHEN report_hour = 17 THEN 1 ELSE 0 END) as has_5pm,
    MAX(CASE WHEN report_hour = 20 THEN 1 ELSE 0 END) as has_8pm
  FROM `nba-props-platform.nba_raw.nbac_injury_report`
  WHERE report_date BETWEEN '2021-10-01' AND '2025-06-30'
  GROUP BY report_date
)

SELECT 
  g.game_date,
  FORMAT_DATE('%A', g.game_date) as day_of_week,
  g.games_scheduled,
  COALESCE(i.hourly_snapshots, 0) as hourly_snapshots,
  COALESCE(i.unique_players, 0) as unique_players,
  CASE WHEN i.has_5pm = 1 THEN '✓' ELSE '✗' END as has_5pm_report,
  CASE WHEN i.has_8pm = 1 THEN '✓' ELSE '✗' END as has_8pm_report,
  ROUND(i.avg_confidence, 3) as avg_confidence,
  CASE
    WHEN i.report_date IS NULL THEN '🔴 CRITICAL: No injury reports'
    WHEN i.hourly_snapshots < 3 THEN '🔴 CRITICAL: Very few snapshots'
    WHEN i.has_5pm = 0 AND i.has_8pm = 0 THEN '🟡 ERROR: Missing peak hours'
    WHEN i.unique_players < 20 THEN '⚠️  WARNING: Low player count'
    ELSE '✅ Complete'
  END as status,
  -- Show sample matchups for context (truncated to avoid long strings)
  CASE 
    WHEN LENGTH(g.matchups) > 100 THEN CONCAT(SUBSTR(g.matchups, 1, 97), '...')
    ELSE g.matchups
  END as sample_matchups
FROM all_game_dates g
LEFT JOIN injury_report_coverage i ON g.game_date = i.report_date
WHERE 
  -- Only show issues or recent dates
  (i.report_date IS NULL OR i.hourly_snapshots < 5 OR g.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
ORDER BY 
  -- Critical issues first
  CASE 
    WHEN i.report_date IS NULL THEN 1
    WHEN i.hourly_snapshots < 3 THEN 2
    ELSE 3
  END,
  g.game_date DESC;