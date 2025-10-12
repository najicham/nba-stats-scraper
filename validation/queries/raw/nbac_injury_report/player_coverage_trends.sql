-- ============================================================================
-- File: validation/queries/raw/nbac_injury_report/player_coverage_trends.sql
-- Purpose: Track player count trends to detect data quality degradation
-- Usage: Run weekly to spot anomalies
-- ============================================================================
-- Expected Results:
--   - Active season: 40-70 unique players per day typical
--   - Off-season: 0-10 players typical
--   - Sudden drops = potential scraper issue
-- ============================================================================

WITH 
-- Daily player counts
daily_player_counts AS (
  SELECT 
    report_date,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT report_hour) as hourly_snapshots,
    COUNT(*) as total_records,
    AVG(confidence_score) as avg_confidence,
    -- Status breakdown
    COUNTIF(injury_status = 'out') as out_count,
    COUNTIF(injury_status = 'questionable') as questionable_count,
    COUNTIF(injury_status = 'doubtful') as doubtful_count,
    COUNTIF(injury_status = 'probable') as probable_count
  FROM `nba-props-platform.nba_raw.nbac_injury_report`
  WHERE report_date BETWEEN '2024-10-01' AND '2025-04-30'  -- UPDATE: Season range
  GROUP BY report_date
),

-- Calculate rolling averages
with_trends AS (
  SELECT 
    *,
    AVG(unique_players) OVER (
      ORDER BY report_date 
      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) as rolling_7day_avg,
    AVG(unique_players) OVER (
      ORDER BY report_date 
      ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) as rolling_30day_avg
  FROM daily_player_counts
),

-- Join with schedule for context
with_schedule_context AS (
  SELECT 
    t.*,
    CASE WHEN s.game_date IS NOT NULL THEN TRUE ELSE FALSE END as is_game_day,
    COALESCE(s.games_count, 0) as games_count
  FROM with_trends t
  LEFT JOIN (
    SELECT 
      game_date,
      COUNT(*) as games_count
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_date BETWEEN '2024-10-01' AND '2025-04-30'
      AND is_playoffs = FALSE
      AND game_date BETWEEN '2024-10-01' AND '2025-04-30'  -- Partition filter
    GROUP BY game_date
  ) s ON t.report_date = s.game_date
)

SELECT 
  report_date,
  FORMAT_DATE('%A', report_date) as day_of_week,
  is_game_day,
  games_count,
  unique_players,
  ROUND(rolling_7day_avg, 1) as avg_7day,
  ROUND(rolling_30day_avg, 1) as avg_30day,
  hourly_snapshots,
  out_count,
  questionable_count,
  doubtful_count,
  ROUND(avg_confidence, 3) as avg_confidence,
  CASE
    -- Sudden drop on game day = CRITICAL
    WHEN is_game_day = TRUE AND unique_players < rolling_7day_avg * 0.5 
      THEN '🔴 CRITICAL: 50%+ drop on game day'
    
    -- Moderate drop on game day = WARNING
    WHEN is_game_day = TRUE AND unique_players < rolling_7day_avg * 0.7 
      THEN '⚠️  WARNING: 30%+ drop on game day'
    
    -- Off-day with zero players = EXPECTED
    WHEN is_game_day = FALSE AND unique_players = 0 
      THEN '⚪ Expected: Off day'
    
    -- Normal variation
    WHEN ABS(unique_players - rolling_7day_avg) < rolling_7day_avg * 0.2 
      THEN '✅ Normal'
    
    ELSE '📊 Review: Outside normal range'
  END as status
FROM with_schedule_context
ORDER BY report_date DESC
LIMIT 60;
