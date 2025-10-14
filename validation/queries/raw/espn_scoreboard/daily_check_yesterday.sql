-- ============================================================================
-- File: validation/queries/raw/espn_scoreboard/daily_check_yesterday.sql
-- Purpose: Morning validation check for ESPN backup scoreboard data
-- Usage: Run at 6 AM PT after Early Morning Final Check workflow (5 AM)
-- ============================================================================
-- Expected Results:
--   - Backup source: 0 games is VALID (not all games collected)
--   - If games exist, verify completion status and reasonable scores
--   - Cross-check team mapping (ESPN codes → NBA codes)
-- ============================================================================

WITH 
-- ESPN data from yesterday
espn_yesterday AS (
  SELECT 
    game_id,
    game_date,
    home_team_abbr,
    away_team_abbr,
    home_team_espn_abbr,
    away_team_espn_abbr,
    home_team_score,
    away_team_score,
    is_completed,
    game_status,
    processing_confidence,
    scrape_timestamp
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

-- Schedule data to know total games yesterday
schedule_yesterday AS (
  SELECT COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND is_playoffs = FALSE
    AND is_all_star = FALSE
),

-- Summary statistics
summary AS (
  SELECT
    COUNT(*) as espn_games,
    COUNT(CASE WHEN is_completed = TRUE THEN 1 END) as completed_games,
    COUNT(CASE WHEN home_team_score + away_team_score < 150 THEN 1 END) as low_scoring_games,
    COUNT(CASE WHEN home_team_score + away_team_score > 250 THEN 1 END) as high_scoring_games,
    COUNT(CASE WHEN home_team_espn_abbr != home_team_abbr THEN 1 END) as mapped_teams,
    AVG(processing_confidence) as avg_confidence,
    MAX(scrape_timestamp) as latest_scrape
  FROM espn_yesterday
)

-- Main output: Combined results with proper BigQuery syntax
(
  SELECT 
    '🔍 ESPN BACKUP SOURCE' as check_type,
    CAST(DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) AS STRING) as check_date,
    CAST(s.scheduled_games AS STRING) as total_scheduled,
    CAST(COALESCE(su.espn_games, 0) AS STRING) as espn_collected,
    CASE
      WHEN s.scheduled_games = 0 THEN '⚪ No games scheduled'
      WHEN COALESCE(su.espn_games, 0) = 0 THEN '✅ OK - Backup source'
      WHEN su.espn_games < s.scheduled_games THEN '✅ Partial coverage (backup)'
      ELSE '✅ Good coverage'
    END as status,
    CONCAT(
      COALESCE(su.completed_games, 0), ' completed, ',
      COALESCE(su.mapped_teams, 0), ' mapped teams, ',
      'Conf: ', ROUND(COALESCE(su.avg_confidence, 0), 2)
    ) as details,
    1 as sort_order
  FROM schedule_yesterday s
  LEFT JOIN summary su ON TRUE

  UNION ALL

  -- Game details (if any exist)
  SELECT 
    '📋 GAME DETAILS' as check_type,
    game_id as check_date,
    CONCAT(away_team_abbr, ' @ ', home_team_abbr) as total_scheduled,
    CONCAT(away_team_score, '-', home_team_score) as espn_collected,
    CASE WHEN is_completed THEN '✅ Complete' ELSE '⏳ In Progress' END as status,
    CASE 
      WHEN home_team_espn_abbr != home_team_abbr THEN CONCAT('Mapped: ', home_team_espn_abbr, '→', home_team_abbr)
      ELSE 'No mapping'
    END as details,
    2 as sort_order
  FROM espn_yesterday
)
ORDER BY sort_order, check_date;