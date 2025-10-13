-- ============================================================================
-- File: validation/queries/raw/nbac_referee/verify_playoff_completeness.sql
-- Purpose: Verify all playoff games have complete referee assignments (4 officials)
-- Usage: Run after playoff games to verify coverage
-- ============================================================================
-- Expected Results:
--   - All playoff games should have exactly 4 officials
--   - No missing playoff games from schedule
-- ============================================================================

WITH
-- Get all playoff games from schedule
playoff_schedule AS (
  SELECT DISTINCT
    s.game_date,
    s.game_id,
    s.home_team_tricode,
    s.away_team_tricode,
    CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup,
    s.playoff_round_desc as round
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date BETWEEN '2024-04-13' AND '2025-06-30'  -- UPDATE: Playoff dates
    AND s.is_playoffs = TRUE
),

-- Get referee assignments for playoff games
playoff_refs AS (
  SELECT
    r.game_date,
    r.game_id,
    r.home_team_abbr,
    r.away_team_abbr,
    COUNT(DISTINCT official_code) as official_count,
    STRING_AGG(official_name ORDER BY official_position) as officials
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments` r
  WHERE r.game_date BETWEEN '2024-04-13' AND '2025-06-30'  -- UPDATE: Match schedule
  GROUP BY r.game_date, r.game_id, r.home_team_abbr, r.away_team_abbr
)

SELECT
  s.game_date,
  FORMAT_DATE('%A', s.game_date) as day_of_week,
  s.matchup,
  s.round,
  COALESCE(r.official_count, 0) as official_count,
  CASE
    WHEN r.game_date IS NULL THEN '❌ MISSING ALL REFEREE DATA'
    WHEN r.official_count < 4 THEN CONCAT('⚠️ INCOMPLETE: Only ', CAST(r.official_count AS STRING), '/4 officials')
    WHEN r.official_count = 4 THEN '✅ Complete'
    WHEN r.official_count > 4 THEN '🔴 ERROR: Too many officials'
    ELSE '❓ Unknown'
  END as status,
  r.officials
FROM playoff_schedule s
LEFT JOIN playoff_refs r
  ON s.game_date = r.game_date
  AND s.home_team_tricode = r.home_team_abbr
  AND s.away_team_tricode = r.away_team_abbr
ORDER BY s.game_date, s.matchup;
