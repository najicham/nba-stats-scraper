-- ============================================================================
-- File: validation/queries/raw/bettingpros_player_props/find_missing_games.sql
-- Purpose: Identify specific dates with ZERO BettingPros props (CRITICAL issues)
-- Usage: Run when season_completeness_check shows missing dates
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query
--   3. Use results to identify dates needing rescraping
-- ============================================================================
-- Expected Results:
--   - List of game dates with NO props data (scraper failure)
--   - Empty result = all scheduled dates have at least some props
-- ============================================================================
-- Note: BettingPros uses game_date only (no game_id field)
-- ============================================================================

WITH
-- Get all game dates from schedule
all_scheduled_dates AS (
  SELECT 
    s.game_date,
    COUNT(*) as games_on_date,
    STRING_AGG(CONCAT(s.away_team_tricode, '@', s.home_team_tricode) LIMIT 5) as sample_matchups
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date BETWEEN '2024-10-22' AND '2025-06-20'  -- UPDATE: Season range
    AND s.is_playoffs = FALSE  -- Set TRUE for playoff validation
  GROUP BY s.game_date
),

-- Get all dates we have props for
props_dates AS (
  SELECT DISTINCT
    game_date,
    COUNT(*) as total_records,
    COUNT(DISTINCT player_lookup) as player_count,
    COUNT(DISTINCT bookmaker) as bookmaker_count,
    ROUND(AVG(validation_confidence), 2) as avg_confidence,
    COUNT(CASE WHEN validation_confidence >= 0.7 THEN 1 END) as high_confidence_records
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-06-20'  -- UPDATE: Match schedule range
  GROUP BY game_date
)

-- Find dates in schedule but not in props (CRITICAL)
SELECT
  s.game_date,
  FORMAT_DATE('%A', s.game_date) as day_of_week,
  s.games_on_date,
  s.sample_matchups,
  '🔴 CRITICAL: NO PROPS DATA' as status,
  'Scraper did not run or failed completely for this date' as likely_cause,
  '' as recommendation
FROM all_scheduled_dates s
LEFT JOIN props_dates p ON s.game_date = p.game_date
WHERE p.game_date IS NULL

UNION ALL

-- Also flag dates with suspiciously low coverage
SELECT
  p.game_date,
  FORMAT_DATE('%A', p.game_date) as day_of_week,
  s.games_on_date,
  s.sample_matchups,
  CONCAT('🟡 WARNING: Low coverage (', CAST(p.total_records AS STRING), ' records)') as status,
  CONCAT('Only ', CAST(p.player_count AS STRING), ' players, ', 
         CAST(p.bookmaker_count AS STRING), ' bookmakers') as likely_cause,
  'Check if scraper ran partially or data quality issues' as recommendation
FROM all_scheduled_dates s
JOIN props_dates p ON s.game_date = p.game_date
WHERE p.total_records < 50  -- Flag dates with <50 total records
   OR p.high_confidence_records = 0  -- Or no high-confidence data

ORDER BY game_date DESC;