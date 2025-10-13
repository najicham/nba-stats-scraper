-- ============================================================================
-- File: validation/queries/raw/nbac_referee/official_count_validation.sql
-- Purpose: Validate correct number of officials per game (3 regular, 4 playoff)
-- Usage: Run to identify games with incorrect official assignments
-- ============================================================================
-- Expected Results:
--   - Regular season games should have exactly 3 officials
--   - Playoff games should have exactly 4 officials
--   - Any deviations indicate data quality issues
-- ============================================================================

WITH game_official_counts AS (
  SELECT
    r.game_date,
    r.game_id,
    r.home_team_abbr,
    r.away_team_abbr,
    CONCAT(r.away_team_abbr, ' @ ', r.home_team_abbr) as matchup,
    s.is_playoffs,
    COUNT(DISTINCT r.official_code) as official_count,
    COUNT(DISTINCT r.official_position) as unique_positions,
    STRING_AGG(r.official_name ORDER BY r.official_position) as officials,
    STRING_AGG(CAST(r.official_position AS STRING) ORDER BY r.official_position) as positions
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments` r
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON r.game_date = s.game_date
    AND r.home_team_abbr = s.home_team_tricode
    AND r.away_team_abbr = s.away_team_tricode
  WHERE r.game_date BETWEEN '2024-01-01' AND CURRENT_DATE()  -- UPDATE: Date range as needed
    AND s.game_date BETWEEN '2024-01-01' AND CURRENT_DATE()
  GROUP BY r.game_date, r.game_id, r.home_team_abbr, r.away_team_abbr, s.is_playoffs
)

SELECT
  game_date,
  FORMAT_DATE('%A', game_date) as day_of_week,
  matchup,
  CASE WHEN is_playoffs THEN 'Playoffs' ELSE 'Regular Season' END as game_type,
  official_count,
  unique_positions,
  CASE
    WHEN is_playoffs = FALSE AND official_count = 3 THEN '✅ Correct'
    WHEN is_playoffs = TRUE AND official_count = 4 THEN '✅ Correct'
    WHEN is_playoffs = FALSE AND official_count < 3 THEN CONCAT('❌ MISSING: Need ', CAST(3 - official_count AS STRING), ' more')
    WHEN is_playoffs = TRUE AND official_count < 4 THEN CONCAT('❌ MISSING: Need ', CAST(4 - official_count AS STRING), ' more')
    WHEN is_playoffs = FALSE AND official_count > 3 THEN CONCAT('🔴 ERROR: ', CAST(official_count - 3 AS STRING), ' extra officials')
    WHEN is_playoffs = TRUE AND official_count > 4 THEN CONCAT('🔴 ERROR: ', CAST(official_count - 4 AS STRING), ' extra officials')
    ELSE '❓ Unknown issue'
  END as status,
  officials,
  positions
FROM game_official_counts
WHERE 
  -- Show only games with wrong counts
  (is_playoffs = FALSE AND official_count != 3)
  OR (is_playoffs = TRUE AND official_count != 4)
ORDER BY game_date DESC, matchup;
