-- File: validation/queries/raw/nbac_play_by_play/find_missing_games.sql
-- ============================================================================
-- Find Missing Play-by-Play Games
-- Purpose: Identify scheduled games that lack play-by-play data
-- Cross-validates against schedule to find collection gaps
-- ============================================================================

WITH scheduled_games AS (
  SELECT DISTINCT
    s.game_id as schedule_game_id,
    s.game_date,
    s.home_team_tricode,
    s.away_team_tricode,
    s.game_status_text
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date >= '2024-01-01'  -- Partition filter
    AND s.is_playoffs = FALSE
    AND s.is_all_star = FALSE
    AND s.game_status_text IN ('Final', 'Completed')  -- Only completed games
),

pbp_games AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as event_count
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= '2024-01-01'
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
)

SELECT 
  s.game_date,
  FORMAT_DATE('%A', s.game_date) as day_of_week,
  s.schedule_game_id,
  s.away_team_tricode || ' @ ' || s.home_team_tricode as matchup,
  '❌ MISSING' as status
FROM scheduled_games s
LEFT JOIN pbp_games p
  ON s.game_date = p.game_date
  AND s.home_team_tricode = p.home_team_abbr
  AND s.away_team_tricode = p.away_team_abbr
WHERE p.game_id IS NULL
ORDER BY s.game_date DESC
LIMIT 100;  -- Show most recent 100 missing games
