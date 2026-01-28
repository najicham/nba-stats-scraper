-- File: monitoring/queries/partial_game_detection.sql
-- Description: Detect games processed with incomplete/partial data
-- Added: 2026-01-27 as part of data quality investigation fixes
--
-- Partial games typically occur when:
-- 1. Game data was scraped while game was still in progress
-- 2. API returned incomplete data
-- 3. Source had temporary issues
--
-- Detection logic:
-- - Team total minutes < 200 (48 min regulation * 5 starters = 240 expected)
-- - game_status != 'Final' at processing time
-- - fg_attempts < 50 for a team (typical team takes 80-100 shots)

-- Current partial games by team
SELECT
  game_date,
  game_id,
  team_abbr,
  SUM(CAST(minutes_played AS FLOAT64)) as total_minutes,
  SUM(fg_attempts) as total_fg_attempts,
  COUNT(*) as player_count,
  COUNTIF(is_active = TRUE) as active_players,
  MAX(game_status_at_processing) as game_status,
  MAX(is_partial_game_data) as flagged_partial,
  MAX(game_completeness_pct) as completeness_pct,
  CASE
    WHEN SUM(CAST(minutes_played AS FLOAT64)) < 180 THEN 'CRITICAL - < 180 minutes'
    WHEN SUM(CAST(minutes_played AS FLOAT64)) < 200 THEN 'WARNING - < 200 minutes'
    WHEN SUM(fg_attempts) < 50 THEN 'WARNING - < 50 FGA'
    ELSE 'OK'
  END as status
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND is_active = TRUE
GROUP BY game_date, game_id, team_abbr
HAVING SUM(CAST(minutes_played AS FLOAT64)) < 200
    OR SUM(fg_attempts) < 50
ORDER BY game_date DESC, total_minutes ASC;

-- Games where one team is partial but other is complete (indicates data issue)
WITH team_totals AS (
  SELECT
    game_date,
    game_id,
    team_abbr,
    SUM(CAST(minutes_played AS FLOAT64)) as total_minutes,
    SUM(fg_attempts) as total_fg_attempts
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND is_active = TRUE
  GROUP BY game_date, game_id, team_abbr
)
SELECT
  t1.game_date,
  t1.game_id,
  t1.team_abbr as team1,
  t1.total_minutes as team1_minutes,
  t2.team_abbr as team2,
  t2.total_minutes as team2_minutes,
  ABS(t1.total_minutes - t2.total_minutes) as minutes_diff,
  'ASYMMETRIC DATA' as issue
FROM team_totals t1
JOIN team_totals t2 ON t1.game_id = t2.game_id AND t1.team_abbr < t2.team_abbr
WHERE ABS(t1.total_minutes - t2.total_minutes) > 40
ORDER BY minutes_diff DESC;

-- Summary by date
SELECT
  game_date,
  COUNT(DISTINCT game_id) as total_games,
  COUNTIF(is_partial_game_data = TRUE) as partial_game_records,
  COUNTIF(game_status_at_processing != 'Final') as non_final_status,
  COUNT(DISTINCT CASE WHEN is_partial_game_data = TRUE THEN game_id END) as games_with_partial_data
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
