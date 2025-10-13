-- ============================================================================
-- File: validation/queries/raw/nbac_injury_report/hourly_snapshot_completeness.sql
-- Purpose: Detect scraper failures by checking for dates with missing hourly snapshots
-- Usage: Run after backfills or to verify historical data integrity
-- ============================================================================
-- Expected Results:
--   - During active season: 5-10 hourly snapshots per day (peak at 5 PM, 8 PM ET)
--   - Off-season: 0-3 snapshots per day (normal)
--   - status = "🔴 CRITICAL" means scraper likely failed
-- ============================================================================

WITH 
-- Get all dates in range and count hourly snapshots
daily_snapshot_counts AS (
  SELECT 
    report_date,
    COUNT(DISTINCT report_hour) as unique_hours,
    COUNT(*) as total_player_records,
    COUNT(DISTINCT player_lookup) as unique_players,
    AVG(confidence_score) as avg_confidence,
    -- Detect peak hours (5 PM = 17, 8 PM = 20 in ET)
    COUNTIF(report_hour = 17) as has_5pm_report,
    COUNTIF(report_hour = 20) as has_8pm_report,
    MIN(report_hour) as earliest_hour,
    MAX(report_hour) as latest_hour
  FROM `nba-props-platform.nba_raw.nbac_injury_report`
  WHERE report_date BETWEEN '2021-10-01' AND '2025-06-30'  -- UPDATE: Active season
  GROUP BY report_date
),

-- Join with schedule to identify game days
schedule_context AS (
  SELECT DISTINCT
    game_date,
    COUNT(*) as games_scheduled
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'  -- UPDATE: Match injury report range
    AND is_playoffs = FALSE
    AND game_date BETWEEN '2021-10-01' AND '2025-06-30'  -- Partition filter
  GROUP BY game_date
),

-- Combine and categorize
daily_summary AS (
  SELECT 
    d.report_date,
    d.unique_hours,
    d.total_player_records,
    d.unique_players,
    d.avg_confidence,
    d.has_5pm_report,
    d.has_8pm_report,
    d.earliest_hour,
    d.latest_hour,
    COALESCE(s.games_scheduled, 0) as games_scheduled,
    CASE
      -- Game day with zero reports = CRITICAL
      WHEN COALESCE(s.games_scheduled, 0) > 0 AND d.unique_hours IS NULL THEN '🔴 CRITICAL: Game day - no reports'
      WHEN COALESCE(s.games_scheduled, 0) > 0 AND d.unique_hours <= 2 THEN '🔴 CRITICAL: Game day - very few snapshots'
      
      -- Game day missing peak hours = ERROR
      WHEN COALESCE(s.games_scheduled, 0) > 0 AND d.has_5pm_report = 0 THEN '🟡 ERROR: Game day missing 5 PM report'
      WHEN COALESCE(s.games_scheduled, 0) > 0 AND d.has_8pm_report = 0 THEN '🟡 ERROR: Game day missing 8 PM report'
      
      -- Game day with good coverage = COMPLETE
      WHEN COALESCE(s.games_scheduled, 0) > 0 AND d.unique_hours >= 5 THEN '✅ Complete: Game day'
      
      -- Off day with no reports = EXPECTED
      WHEN COALESCE(s.games_scheduled, 0) = 0 AND d.unique_hours IS NULL THEN '⚪ Expected: Off day - no reports'
      WHEN COALESCE(s.games_scheduled, 0) = 0 AND d.unique_hours <= 3 THEN '⚪ Expected: Off day - sparse reports'
      
      -- Moderate coverage
      WHEN d.unique_hours BETWEEN 3 AND 4 THEN '⚠️  WARNING: Moderate coverage'
      
      ELSE '✅ Complete'
    END as status
  FROM daily_snapshot_counts d
  LEFT JOIN schedule_context s ON d.report_date = s.game_date
  
  UNION ALL
  
  -- Include dates with games but NO injury reports (complete failure)
  SELECT 
    s.game_date as report_date,
    0 as unique_hours,
    0 as total_player_records,
    0 as unique_players,
    NULL as avg_confidence,
    0 as has_5pm_report,
    0 as has_8pm_report,
    NULL as earliest_hour,
    NULL as latest_hour,
    s.games_scheduled,
    '🔴 CRITICAL: Game day - no reports' as status
  FROM schedule_context s
  WHERE NOT EXISTS (
    SELECT 1 
    FROM daily_snapshot_counts d 
    WHERE d.report_date = s.game_date
  )
)

SELECT 
  report_date,
  FORMAT_DATE('%A', report_date) as day_of_week,
  games_scheduled,
  COALESCE(unique_hours, 0) as hourly_snapshots,
  COALESCE(unique_players, 0) as unique_players,
  COALESCE(total_player_records, 0) as total_records,
  CASE WHEN has_5pm_report > 0 THEN '✓' ELSE '✗' END as has_5pm,
  CASE WHEN has_8pm_report > 0 THEN '✓' ELSE '✗' END as has_8pm,
  ROUND(avg_confidence, 3) as avg_confidence,
  status
FROM daily_summary
ORDER BY 
  -- Sort critical issues first
  CASE 
    WHEN status LIKE '%CRITICAL%' THEN 1
    WHEN status LIKE '%ERROR%' THEN 2
    WHEN status LIKE '%WARNING%' THEN 3
    ELSE 4
  END,
  report_date DESC;
