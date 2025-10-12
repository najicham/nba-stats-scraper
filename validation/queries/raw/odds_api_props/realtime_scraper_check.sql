-- ============================================================================
-- File: validation/queries/raw/odds_api_props/realtime_scraper_check.sql
-- Purpose: Check if today's games are being scraped in real-time
-- Usage: Run during the day to monitor active scraper health
-- ============================================================================
-- Instructions:
--   1. Run this 2-3 hours before first game of the day
--   2. Games should start appearing as scraper runs
--   3. No date parameters needed - automatically checks today
-- ============================================================================
-- Expected Results:
--   - Early morning: status = "⏳ Scraper not started yet" (OK)
--   - Mid-day: status = "🔄 In Progress" with some games appearing
--   - Evening: status = "✅ All games scraped" or "⚠️ Some missing"
-- ============================================================================

WITH today_schedule AS (
  SELECT
    game_id,
    game_date,
    home_team_tricode,
    away_team_tricode,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode) as matchup,
    game_date_est,
    EXTRACT(HOUR FROM game_date_est) as game_hour
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = CURRENT_DATE()
),

today_props AS (
  SELECT
    p.game_id,
    p.home_team_abbr,
    p.away_team_abbr,
    COUNT(DISTINCT p.player_lookup) as unique_players,
    COUNT(DISTINCT p.bookmaker) as bookmaker_count,
    MAX(p.snapshot_timestamp) as latest_snapshot,
    STRING_AGG(DISTINCT p.bookmaker ORDER BY p.bookmaker) as bookmakers
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props` p
  WHERE p.game_date = CURRENT_DATE()
  GROUP BY p.game_id, p.home_team_abbr, p.away_team_abbr
),

scraper_summary AS (
  SELECT
    COUNT(DISTINCT s.game_id) as total_scheduled_games,
    COUNT(DISTINCT p.game_id) as games_with_props,
    COUNT(DISTINCT s.game_id) - COUNT(DISTINCT p.game_id) as games_missing_props,
    ROUND(AVG(p.unique_players), 1) as avg_players_per_game,
    MIN(s.game_hour) as earliest_game_hour,
    MAX(p.latest_snapshot) as latest_scrape_timestamp
  FROM today_schedule s
  LEFT JOIN today_props p
    ON s.game_id = p.game_id
    OR (s.home_team_tricode = p.home_team_abbr AND s.away_team_tricode = p.away_team_abbr)
)

-- Summary row
SELECT
  CURRENT_DATE() as check_date,
  CURRENT_TIMESTAMP() as check_time,
  total_scheduled_games,
  games_with_props,
  games_missing_props,
  avg_players_per_game,
  earliest_game_hour,
  latest_scrape_timestamp,
  CASE
    WHEN total_scheduled_games = 0 THEN '⚪ No games today'
    WHEN games_with_props = 0 AND EXTRACT(HOUR FROM CURRENT_TIMESTAMP()) < 10 
    THEN '⏳ Scraper not started yet (normal)'
    WHEN games_with_props = 0 
    THEN '❌ CRITICAL: Scraper not running'
    WHEN games_with_props < total_scheduled_games 
    THEN CONCAT('🔄 In Progress (', CAST(games_with_props AS STRING), '/', 
                CAST(total_scheduled_games AS STRING), ' games)')
    WHEN avg_players_per_game < 6.0
    THEN '🟡 Low coverage detected'
    ELSE '✅ All games scraped'
  END as status,
  CASE
    WHEN latest_scrape_timestamp IS NOT NULL 
    THEN CONCAT('Last scraped ', 
                CAST(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), latest_scrape_timestamp, MINUTE) AS STRING),
                ' minutes ago')
    ELSE 'No data yet'
  END as last_update
FROM scraper_summary

UNION ALL

-- Individual game details
SELECT
  CURRENT_DATE() as check_date,
  NULL as check_time,
  NULL as total_scheduled_games,
  NULL as games_with_props,
  NULL as games_missing_props,
  NULL as avg_players_per_game,
  NULL as earliest_game_hour,
  NULL as latest_scrape_timestamp,
  CONCAT(
    s.matchup, ' - ',
    CASE 
      WHEN p.game_id IS NULL THEN '⏳ Not scraped yet'
      WHEN p.unique_players < 6 THEN CONCAT('🟡 Low (', CAST(p.unique_players AS STRING), ' players)')
      ELSE CONCAT('✅ ', CAST(p.unique_players AS STRING), ' players')
    END
  ) as status,
  COALESCE(p.bookmakers, 'None') as last_update
FROM today_schedule s
LEFT JOIN today_props p
  ON s.game_id = p.game_id
  OR (s.home_team_tricode = p.home_team_abbr AND s.away_team_tricode = p.away_team_abbr)
ORDER BY check_time DESC NULLS LAST;
