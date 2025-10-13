-- ============================================================================
-- File: validation/queries/raw/br_rosters/find_missing_teams.sql
-- Purpose: Identify specific team-season combinations missing roster data
-- Usage: Run when season_completeness_check shows incomplete data
-- ============================================================================
-- Expected Results:
--   - Empty result set = complete data (all 30 teams × 4 seasons present)
--   - Any results = specific team-season combos to backfill
-- ============================================================================
-- Instructions:
--   1. Update season_year ranges if checking different seasons
--   2. Verify all 30 current NBA teams are in expected_teams CTE
--   3. Cross-check against Basketball Reference website for accuracy
-- ============================================================================

WITH
-- Define all NBA teams (30 teams as of 2024-25)
expected_teams AS (
  SELECT team_abbrev FROM UNNEST([
    'ATL', 'BOS', 'BRK', 'CHO', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
    'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
    'OKC', 'ORL', 'PHI', 'PHO', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
  ]) AS team_abbrev
),

-- Define seasons to check
expected_seasons AS (
  SELECT season_year, season_display FROM UNNEST([
    STRUCT(2021 AS season_year, '2021-22' AS season_display),
    STRUCT(2022 AS season_year, '2022-23' AS season_display),
    STRUCT(2023 AS season_year, '2023-24' AS season_display),
    STRUCT(2024 AS season_year, '2024-25' AS season_display)
  ])
),

-- Create all expected team-season combinations (30 teams × 4 seasons = 120)
expected_combos AS (
  SELECT
    s.season_year,
    s.season_display,
    t.team_abbrev
  FROM expected_seasons s
  CROSS JOIN expected_teams t
),

-- Get actual team-season combinations from roster data
actual_combos AS (
  SELECT DISTINCT
    season_year,
    season_display,
    team_abbrev,
    COUNT(DISTINCT player_full_name) as player_count
  FROM `nba-props-platform.nba_raw.br_rosters_current`
  WHERE season_year BETWEEN 2021 AND 2024
  GROUP BY season_year, season_display, team_abbrev
)

-- Find missing combinations
SELECT
  e.season_year,
  e.season_display,
  e.team_abbrev,
  COALESCE(a.player_count, 0) as actual_player_count,
  CASE
    WHEN a.team_abbrev IS NULL THEN '❌ Completely missing'
    WHEN a.player_count < 10 THEN '⚠️ Suspiciously low player count'
    ELSE ''
  END as status,
  'Check Basketball Reference for this team-season' as action_needed
FROM expected_combos e
LEFT JOIN actual_combos a
  ON e.season_year = a.season_year
  AND e.team_abbrev = a.team_abbrev
WHERE
  a.team_abbrev IS NULL  -- Missing entirely
  OR a.player_count < 10  -- Suspiciously low (probably incomplete scrape)
ORDER BY
  e.season_year DESC,
  e.team_abbrev;
