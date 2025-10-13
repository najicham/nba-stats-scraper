-- ============================================================================
-- File: validation/queries/raw/nbac_injury_report/peak_hour_validation.sql
-- Purpose: Validate critical 5 PM and 8 PM ET reports on game days
-- Usage: Run to verify most important reporting times
-- ============================================================================
-- Expected Results:
--   - Game days should have reports at 5 PM (hour 17) and 8 PM (hour 20)
--   - These hours have most comprehensive injury data
--   - Missing peak hour = high-risk for prop betting
-- ============================================================================

WITH 
-- Get all game dates
game_dates AS (
  SELECT DISTINCT
    game_date,
    COUNT(*) as games_count
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'  -- UPDATE: Season range
    AND is_playoffs = FALSE
    AND game_date BETWEEN '2021-10-01' AND '2025-06-30'  -- Partition filter
  GROUP BY game_date
),

-- Check for peak hour reports
peak_hour_reports AS (
  SELECT 
    report_date,
    report_hour,
    COUNT(DISTINCT player_lookup) as players_reported,
    COUNT(*) as total_records,
    AVG(confidence_score) as avg_confidence,
    STRING_AGG(DISTINCT injury_status ORDER BY injury_status) as statuses_present
  FROM `nba-props-platform.nba_raw.nbac_injury_report`
  WHERE report_date BETWEEN '2021-10-01' AND '2025-06-30'
    AND report_hour IN (17, 20)  -- 5 PM and 8 PM ET
  GROUP BY report_date, report_hour
),

-- Combine to find missing peak hours
game_day_peak_hours AS (
  SELECT 
    g.game_date,
    g.games_count,
    -- 5 PM report
    MAX(CASE WHEN p.report_hour = 17 THEN p.players_reported END) as players_5pm,
    MAX(CASE WHEN p.report_hour = 17 THEN p.avg_confidence END) as confidence_5pm,
    -- 8 PM report  
    MAX(CASE WHEN p.report_hour = 20 THEN p.players_reported END) as players_8pm,
    MAX(CASE WHEN p.report_hour = 20 THEN p.avg_confidence END) as confidence_8pm
  FROM game_dates g
  LEFT JOIN peak_hour_reports p ON g.game_date = p.report_date
  GROUP BY g.game_date, g.games_count
)

SELECT 
  game_date,
  FORMAT_DATE('%A', game_date) as day_of_week,
  games_count as games_scheduled,
  COALESCE(players_5pm, 0) as players_5pm_report,
  ROUND(confidence_5pm, 3) as confidence_5pm,
  COALESCE(players_8pm, 0) as players_8pm_report,
  ROUND(confidence_8pm, 3) as confidence_8pm,
  CASE
    WHEN players_5pm IS NULL AND players_8pm IS NULL THEN '🔴 CRITICAL: Both peak hours missing'
    WHEN players_5pm IS NULL THEN '🟡 ERROR: Missing 5 PM report'
    WHEN players_8pm IS NULL THEN '🟡 ERROR: Missing 8 PM report'
    WHEN players_5pm < 10 OR players_8pm < 10 THEN '⚠️  WARNING: Low player counts'
    ELSE '✅ Complete'
  END as status
FROM game_day_peak_hours
WHERE 
  -- Only show issues
  (players_5pm IS NULL OR players_8pm IS NULL OR players_5pm < 10 OR players_8pm < 10)
ORDER BY 
  game_date DESC;

