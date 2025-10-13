-- ============================================================================
-- File: validation/queries/raw/bettingpros_player_props/verify_playoff_completeness.sql
-- Purpose: Verify BettingPros props coverage for all playoff games
-- Usage: Run after playoffs complete to ensure full historical coverage
-- ============================================================================
-- Expected Results:
--   - All playoff games should have props data
--   - Finals games should have highest coverage (50+ props/game)
--   - Each round should be complete
-- ============================================================================

WITH playoff_schedule AS (
  SELECT
    s.game_date,
    s.game_id,
    s.home_team_tricode,
    s.away_team_tricode,
    s.game_status_text,
    CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup,
    CASE
      WHEN s.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN s.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN s.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN s.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.is_playoffs = TRUE
    AND s.game_date BETWEEN '2021-04-15' AND '2025-06-30'  -- Playoff date range
),

playoff_props AS (
  SELECT
    p.game_date,
    COUNT(*) as total_records,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT bookmaker) as unique_bookmakers,
    ROUND(AVG(validation_confidence), 2) as avg_confidence,
    COUNT(CASE WHEN validation_confidence >= 0.7 THEN 1 END) as high_confidence_records
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props` p
  JOIN playoff_schedule ps
    ON p.game_date = ps.game_date
  GROUP BY p.game_date
),

playoff_coverage AS (
  SELECT
    ps.season,
    ps.game_date,
    ps.matchup,
    ps.game_status_text,
    COALESCE(pp.total_records, 0) as total_records,
    COALESCE(pp.unique_players, 0) as unique_players,
    COALESCE(pp.unique_bookmakers, 0) as unique_bookmakers,
    COALESCE(pp.avg_confidence, 0) as avg_confidence,
    COALESCE(pp.high_confidence_records, 0) as high_confidence_records
  FROM playoff_schedule ps
  LEFT JOIN playoff_props pp ON ps.game_date = pp.game_date
)

(
-- Game-level details with season summary
SELECT
  'GAME' as result_type,
  season as detail1,
  CAST(game_date AS STRING) as detail2,
  matchup as detail3,
  CAST(total_records AS STRING) as detail4,
  CAST(unique_players AS STRING) as detail5,
  CAST(avg_confidence AS STRING) as detail6,
  CASE
    WHEN total_records = 0 THEN '🔴 CRITICAL: NO DATA'
    WHEN high_confidence_records = 0 THEN '🔴 CRITICAL: No high-confidence data'
    WHEN total_records < 30 THEN
      CONCAT('🟡 WARNING: Low coverage (', CAST(total_records AS STRING), ' records)')
    WHEN avg_confidence < 0.6 THEN
      CONCAT('🟡 WARNING: Low confidence (', CAST(avg_confidence AS STRING), ')')
    ELSE '✅ Complete'
  END as status
FROM playoff_coverage

UNION ALL

-- Section separator
SELECT
  'SEPARATOR' as result_type,
  'Season Summary' as detail1,
  '---' as detail2,
  '' as detail3,
  '' as detail4,
  '' as detail5,
  '' as detail6,
  '' as status

UNION ALL

-- Season summary
SELECT
  'SUMMARY' as result_type,
  season as detail1,
  CAST(total_playoff_games AS STRING) as detail2,
  CAST(games_with_props AS STRING) as detail3,
  CAST(missing_games AS STRING) as detail4,
  CAST(coverage_pct AS STRING) as detail5,
  CAST(avg_records_per_game AS STRING) as detail6,
  CASE
    WHEN total_playoff_games = games_with_props THEN '✅ Complete'
    WHEN games_with_props = 0 THEN '❌ No playoff data'
    ELSE CONCAT('🟡 Partial: ', CAST(missing_games AS STRING), ' missing')
  END as status
FROM (
  SELECT
    season,
    COUNT(*) as total_playoff_games,
    SUM(CASE WHEN total_records > 0 THEN 1 ELSE 0 END) as games_with_props,
    COUNT(*) - SUM(CASE WHEN total_records > 0 THEN 1 ELSE 0 END) as missing_games,
    ROUND(100.0 * SUM(CASE WHEN total_records > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as coverage_pct,
    ROUND(AVG(total_records), 1) as avg_records_per_game,
    ROUND(AVG(avg_confidence), 2) as avg_confidence
  FROM playoff_coverage
  GROUP BY season
)
ORDER BY result_type, detail1 DESC
LIMIT 150
);