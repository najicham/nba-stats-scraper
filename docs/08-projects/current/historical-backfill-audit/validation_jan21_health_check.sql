-- ============================================================================
-- NBA STATS SCRAPER - DAILY HEALTH CHECK
-- Date: January 21, 2026
-- Purpose: Comprehensive pipeline validation after Jan 20 data gap fix
-- ============================================================================

-- =============================================================================
-- CHECK 1: Jan 21 Games - BDL Games Table
-- =============================================================================
SELECT
  '1. JAN 21 GAMES - BDL' as check_name,
  COUNT(DISTINCT id) as game_count,
  STRING_AGG(DISTINCT CONCAT(visitor_team_abbreviation, '@', home_team_abbreviation), ', ' ORDER BY id) as games_list
FROM `nba-props-platform.nba_raw.bdl_games`
WHERE DATE(date) = '2026-01-21';

-- =============================================================================
-- CHECK 2: Jan 21 Games - BDL Boxscores
-- =============================================================================
SELECT
  '2. JAN 21 BOXSCORES - BDL' as check_name,
  COUNT(DISTINCT game_id) as games_with_boxscores,
  COUNT(*) as total_player_records,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(player_count_per_game), 1) as avg_players_per_game,
  MIN(player_count_per_game) as min_players_per_game,
  MAX(player_count_per_game) as max_players_per_game
FROM (
  SELECT
    game_id,
    COUNT(*) as player_count_per_game
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE DATE(game_date) = '2026-01-21'
  GROUP BY game_id
);

-- =============================================================================
-- CHECK 3: Jan 21 Games - Gamebook Player Stats
-- =============================================================================
SELECT
  '3. JAN 21 GAMEBOOK - NBAC' as check_name,
  COUNT(DISTINCT game_id) as games_with_gamebook,
  COUNT(*) as total_player_records,
  COUNT(CASE WHEN player_status = 'active' THEN 1 END) as active_players,
  COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as inactive_players,
  COUNT(CASE WHEN player_status = 'dnp' THEN 1 END) as dnp_players,
  ROUND(AVG(player_count_per_game), 1) as avg_players_per_game
FROM (
  SELECT
    game_id,
    player_status,
    COUNT(*) as player_count_per_game
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE DATE(game_date) = '2026-01-21'
  GROUP BY game_id, player_status
);

-- =============================================================================
-- CHECK 4: Recent Days Comparison (Jan 19-21)
-- =============================================================================
SELECT
  '4. RECENT DAYS - BDL vs GAMEBOOK' as check_name,
  game_date,
  COALESCE(bdl_games, 0) as bdl_games,
  COALESCE(gamebook_games, 0) as gamebook_games,
  COALESCE(bdl_players, 0) as bdl_players,
  COALESCE(gamebook_players, 0) as gamebook_players,
  CASE
    WHEN COALESCE(bdl_games, 0) = COALESCE(gamebook_games, 0)
      AND COALESCE(bdl_games, 0) > 0
    THEN '✅ Match'
    WHEN COALESCE(bdl_games, 0) = 0 AND COALESCE(gamebook_games, 0) = 0
    THEN '⚪ No games'
    WHEN COALESCE(bdl_games, 0) > COALESCE(gamebook_games, 0)
    THEN '⚠️ Gamebook missing'
    WHEN COALESCE(gamebook_games, 0) > COALESCE(bdl_games, 0)
    THEN '⚠️ BDL missing'
    ELSE '❓ Unknown'
  END as status
FROM (
  SELECT DATE(game_date) as game_date
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
  UNION DISTINCT
  SELECT DATE(game_date)
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
) dates
LEFT JOIN (
  SELECT
    DATE(game_date) as game_date,
    COUNT(DISTINCT game_id) as bdl_games,
    COUNT(*) as bdl_players
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
  GROUP BY DATE(game_date)
) bdl ON dates.game_date = bdl.game_date
LEFT JOIN (
  SELECT
    DATE(game_date) as game_date,
    COUNT(DISTINCT game_id) as gamebook_games,
    COUNT(*) as gamebook_players
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
  GROUP BY DATE(game_date)
) gamebook ON dates.game_date = gamebook.game_date
ORDER BY game_date DESC;

-- =============================================================================
-- CHECK 5: Jan 20 Verification (Post-Backfill)
-- =============================================================================
SELECT
  '5. JAN 20 VERIFICATION - POST BACKFILL' as check_name,
  game_id,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(*) as total_records,
  COUNT(CASE WHEN player_status = 'active' THEN 1 END) as active,
  COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as inactive,
  COUNT(CASE WHEN player_status = 'dnp' THEN 1 END) as dnp
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE DATE(game_date) = '2026-01-20'
GROUP BY game_id
ORDER BY game_id;

-- =============================================================================
-- CHECK 6: Analytics Pipeline - Player Game Summary (Recent)
-- =============================================================================
SELECT
  '6. ANALYTICS - PLAYER GAME SUMMARY' as check_name,
  DATE(game_date) as game_date,
  COUNT(DISTINCT game_id) as games_processed,
  COUNT(DISTINCT player_id) as unique_players,
  COUNT(*) as total_records,
  -- Data quality checks
  COUNTIF(minutes IS NULL) as null_minutes,
  COUNTIF(points IS NULL) as null_points,
  COUNTIF(rebounds IS NULL) as null_rebounds,
  COUNTIF(assists IS NULL) as null_assists,
  -- Quality percentage
  ROUND(100.0 * (1 - COUNTIF(minutes IS NULL OR points IS NULL) / COUNT(*)), 2) as data_quality_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
GROUP BY DATE(game_date)
ORDER BY game_date DESC;

-- =============================================================================
-- CHECK 7: Data Completeness - Missing Games Detection
-- =============================================================================
WITH bdl_dates AS (
  SELECT DISTINCT DATE(game_date) as game_date, COUNT(DISTINCT game_id) as bdl_count
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
  GROUP BY DATE(game_date)
),
gamebook_dates AS (
  SELECT DISTINCT DATE(game_date) as game_date, COUNT(DISTINCT game_id) as gamebook_count
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
  GROUP BY DATE(game_date)
),
analytics_dates AS (
  SELECT DISTINCT DATE(game_date) as game_date, COUNT(DISTINCT game_id) as analytics_count
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
  GROUP BY DATE(game_date)
)
SELECT
  '7. DATA COMPLETENESS - RAW TO ANALYTICS' as check_name,
  COALESCE(b.game_date, g.game_date, a.game_date) as game_date,
  COALESCE(b.bdl_count, 0) as bdl_games,
  COALESCE(g.gamebook_count, 0) as gamebook_games,
  COALESCE(a.analytics_count, 0) as analytics_games,
  CASE
    WHEN COALESCE(b.bdl_count, 0) = COALESCE(g.gamebook_count, 0)
      AND COALESCE(b.bdl_count, 0) = COALESCE(a.analytics_count, 0)
      AND COALESCE(b.bdl_count, 0) > 0
    THEN '✅ Complete flow'
    WHEN COALESCE(b.bdl_count, 0) = 0 AND COALESCE(g.gamebook_count, 0) = 0
    THEN '⚪ No games'
    WHEN COALESCE(a.analytics_count, 0) < COALESCE(b.bdl_count, 0)
    THEN '⚠️ Analytics incomplete'
    WHEN COALESCE(g.gamebook_count, 0) < COALESCE(b.bdl_count, 0)
    THEN '⚠️ Gamebook missing'
    ELSE '❓ Inconsistent'
  END as pipeline_status
FROM bdl_dates b
FULL OUTER JOIN gamebook_dates g ON b.game_date = g.game_date
FULL OUTER JOIN analytics_dates a ON COALESCE(b.game_date, g.game_date) = a.game_date
ORDER BY game_date DESC;

-- =============================================================================
-- CHECK 8: Data Quality - Null Field Detection
-- =============================================================================
SELECT
  '8. DATA QUALITY - BDL BOXSCORES' as check_name,
  DATE(game_date) as game_date,
  COUNT(*) as total_records,
  COUNTIF(min IS NULL) as null_minutes,
  COUNTIF(pts IS NULL) as null_points,
  COUNTIF(reb IS NULL) as null_rebounds,
  COUNTIF(ast IS NULL) as null_assists,
  COUNTIF(fg_pct IS NULL) as null_fg_pct,
  ROUND(100.0 * COUNTIF(min IS NULL OR pts IS NULL OR reb IS NULL OR ast IS NULL) / COUNT(*), 2) as missing_data_pct
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
GROUP BY DATE(game_date)
ORDER BY game_date DESC;

-- =============================================================================
-- CHECK 9: Recent Game Details (Last 5 Days)
-- =============================================================================
SELECT
  '9. RECENT GAMES - LAST 5 DAYS' as check_name,
  DATE(game_date) as game_date,
  COUNT(DISTINCT game_id) as total_games,
  STRING_AGG(
    DISTINCT CONCAT(
      SUBSTR(game_id, 10, 3), '@', SUBSTR(game_id, 14, 3)
    ),
    ', '
    ORDER BY game_id
  ) as games
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE DATE(game_date) BETWEEN DATE_SUB('2026-01-21', INTERVAL 5 DAY) AND '2026-01-21'
GROUP BY DATE(game_date)
ORDER BY game_date DESC;

-- =============================================================================
-- CHECK 10: Missing Player Records Detection
-- =============================================================================
WITH game_player_counts AS (
  SELECT
    DATE(game_date) as game_date,
    game_id,
    COUNT(*) as player_count
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
  GROUP BY DATE(game_date), game_id
)
SELECT
  '10. MISSING PLAYER RECORDS - GAMES WITH LOW COUNTS' as check_name,
  game_date,
  game_id,
  player_count,
  CASE
    WHEN player_count < 20 THEN '❌ Critical - Too few players'
    WHEN player_count < 25 THEN '⚠️ Warning - Low player count'
    WHEN player_count BETWEEN 25 AND 35 THEN '✅ Normal'
    WHEN player_count > 35 THEN '⚠️ High player count (check for duplicates)'
    ELSE '❓ Unknown'
  END as status
FROM game_player_counts
WHERE player_count < 25 OR player_count > 35
ORDER BY game_date DESC, player_count ASC;

-- =============================================================================
-- CHECK 11: Team Analytics Tables Check
-- =============================================================================
SELECT
  '11. TEAM ANALYTICS - RECENT GAMES' as check_name,
  DATE(game_date) as game_date,
  COUNT(DISTINCT game_id) as games_in_team_analytics,
  COUNT(DISTINCT team_id) as unique_teams
FROM `nba-props-platform.nba_analytics.team_game_summary`
WHERE DATE(game_date) BETWEEN '2026-01-19' AND '2026-01-21'
GROUP BY DATE(game_date)
ORDER BY game_date DESC;

-- =============================================================================
-- CHECK 12: Jan 21 Detailed Game Status
-- =============================================================================
SELECT
  '12. JAN 21 DETAILED STATUS' as check_name,
  'BDL Boxscores' as source,
  g.game_id,
  CONCAT(v.abbreviation, '@', h.abbreviation) as matchup,
  COUNT(DISTINCT b.player_lookup) as players,
  ROUND(AVG(b.min), 1) as avg_minutes,
  SUM(b.pts) as total_points
FROM `nba-props-platform.nba_raw.bdl_player_boxscores` b
JOIN `nba-props-platform.nba_raw.bdl_games` g ON b.game_id = g.id
LEFT JOIN `nba-props-platform.nba_raw.bdl_teams` v ON g.visitor_team_id = v.id
LEFT JOIN `nba-props-platform.nba_raw.bdl_teams` h ON g.home_team_id = h.id
WHERE DATE(b.game_date) = '2026-01-21'
GROUP BY g.game_id, v.abbreviation, h.abbreviation
ORDER BY g.game_id;

-- =============================================================================
-- CHECK 13: Pipeline Timing Analysis
-- =============================================================================
SELECT
  '13. PIPELINE TIMING - DATA FRESHNESS' as check_name,
  'BDL Boxscores' as source,
  MAX(DATE(game_date)) as latest_game_date,
  MAX(_loaded_at) as latest_load_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(_loaded_at), HOUR) as hours_since_load
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE DATE(game_date) >= '2026-01-19'
UNION ALL
SELECT
  '13. PIPELINE TIMING - DATA FRESHNESS' as check_name,
  'Gamebook' as source,
  MAX(DATE(game_date)) as latest_game_date,
  MAX(_loaded_at) as latest_load_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(_loaded_at), HOUR) as hours_since_load
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE DATE(game_date) >= '2026-01-19'
UNION ALL
SELECT
  '13. PIPELINE TIMING - DATA FRESHNESS' as check_name,
  'Analytics' as source,
  MAX(DATE(game_date)) as latest_game_date,
  MAX(_loaded_at) as latest_load_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(_loaded_at), HOUR) as hours_since_load
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE DATE(game_date) >= '2026-01-19';

-- =============================================================================
-- SUMMARY STATUS CHECK
-- =============================================================================
WITH bdl_jan21 AS (
  SELECT COUNT(DISTINCT game_id) as game_count
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE DATE(game_date) = '2026-01-21'
),
gamebook_jan21 AS (
  SELECT COUNT(DISTINCT game_id) as game_count
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE DATE(game_date) = '2026-01-21'
),
analytics_jan21 AS (
  SELECT COUNT(DISTINCT game_id) as game_count
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE DATE(game_date) = '2026-01-21'
)
SELECT
  '=== SUMMARY STATUS ===' as check_name,
  b.game_count as bdl_games_jan21,
  g.game_count as gamebook_games_jan21,
  a.game_count as analytics_games_jan21,
  CASE
    WHEN b.game_count = g.game_count AND b.game_count = a.game_count AND b.game_count > 0
    THEN '✅ ALL SYSTEMS HEALTHY - Data flowing normally'
    WHEN b.game_count = 0 AND g.game_count = 0
    THEN '⚪ NO GAMES TODAY - Normal for off day'
    WHEN b.game_count > 0 AND g.game_count = 0
    THEN '❌ CRITICAL - Gamebook not processing (similar to Jan 20 issue)'
    WHEN a.game_count < b.game_count
    THEN '⚠️ WARNING - Analytics pipeline lagging'
    ELSE '❓ INCONSISTENT STATE - Investigate'
  END as overall_status
FROM bdl_jan21 b
CROSS JOIN gamebook_jan21 g
CROSS JOIN analytics_jan21 a;
