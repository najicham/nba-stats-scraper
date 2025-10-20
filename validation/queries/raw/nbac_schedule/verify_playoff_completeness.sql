-- ============================================================================
-- File: validation/queries/raw/nbac_schedule/verify_playoff_completeness.sql
-- Purpose: Verify playoff structure and game counts make sense
-- Status: FIXED - Removed trailing UNION ALL causing syntax error
-- ============================================================================

WITH
-- Get all playoff games in date range
playoff_games AS (
  SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    home_team_name,
    away_team_name,
    playoff_round,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode) as matchup
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2023-04-15' AND '2024-06-20'  -- UPDATE: Latest complete playoff period
    AND is_playoffs = TRUE
    AND game_date >= '2023-04-15'  -- Partition filter
),

-- Expand to team-round combinations
team_playoff_rounds AS (
  SELECT
    home_team_tricode as team,
    home_team_name as team_name,
    playoff_round,
    game_id
  FROM playoff_games

  UNION ALL

  SELECT
    away_team_tricode as team,
    away_team_name as team_name,
    playoff_round,
    game_id
  FROM playoff_games
),

-- Count games per team per round
team_round_stats AS (
  SELECT
    team,
    MAX(team_name) as team_name,
    playoff_round,
    COUNT(DISTINCT game_id) as games,
    CASE playoff_round
      WHEN 'first_round' THEN 'First Round'
      WHEN 'conference_semis' THEN 'Conference Semis'
      WHEN 'conference_finals' THEN 'Conference Finals'
      WHEN 'nba_finals' THEN 'NBA Finals'
      ELSE playoff_round
    END as round_display
  FROM team_playoff_rounds
  WHERE playoff_round IS NOT NULL
  GROUP BY team, playoff_round
),

-- Count teams per round
round_summary AS (
  SELECT
    playoff_round,
    MAX(round_display) as round_display,
    COUNT(DISTINCT team) as teams,
    SUM(games) / 2 as total_games,  -- Divide by 2 since each game counted twice
    MIN(games) as min_games,
    MAX(games) as max_games,
    ROUND(AVG(games), 1) as avg_games,
    CASE playoff_round
      WHEN 'first_round' THEN 16
      WHEN 'conference_semis' THEN 8
      WHEN 'conference_finals' THEN 4
      WHEN 'nba_finals' THEN 2
      ELSE NULL
    END as expected_teams
  FROM team_round_stats
  GROUP BY playoff_round
),

-- Validate round structure
round_validation AS (
  SELECT
    round_display,
    teams,
    expected_teams,
    total_games,
    min_games,
    max_games,
    avg_games,
    CASE
      WHEN teams < expected_teams THEN CONCAT('🔴 Missing ', CAST(expected_teams - teams AS STRING), ' teams')
      WHEN teams > expected_teams THEN CONCAT('🔴 Extra ', CAST(teams - expected_teams AS STRING), ' teams')
      WHEN min_games < 4 THEN '🟡 Series with <4 games (unusual)'
      WHEN max_games > 7 THEN '🔴 Series with >7 games (impossible!)'
      ELSE '✅ Structure OK'
    END as status
  FROM round_summary
),

-- Find teams with unusual playoff runs
team_validation AS (
  SELECT
    t.team,
    t.team_name,
    COUNT(DISTINCT t.playoff_round) as rounds_played,
    STRING_AGG(t.round_display ORDER BY
      CASE t.playoff_round
        WHEN 'first_round' THEN 1
        WHEN 'conference_semis' THEN 2
        WHEN 'conference_finals' THEN 3
        WHEN 'nba_finals' THEN 4
      END, ' → ') as playoff_path,
    SUM(t.games) as total_games,
    CASE
      WHEN COUNT(DISTINCT t.playoff_round) = 4 THEN '🏆 Finals participant'
      WHEN COUNT(DISTINCT t.playoff_round) = 3 THEN '🏀 Conference Finals'
      WHEN COUNT(DISTINCT t.playoff_round) = 2 THEN '📊 Conference Semis'
      WHEN COUNT(DISTINCT t.playoff_round) = 1 THEN '📉 First Round exit'
      ELSE '❓ Unusual pattern'
    END as playoff_result
  FROM team_round_stats t
  GROUP BY t.team, t.team_name
)

-- Output 1: Round structure validation
SELECT
  '=== PLAYOFF STRUCTURE ===' as section,
  '' as detail1,
  '' as detail2,
  '' as detail3,
  '' as detail4,
  '' as status

UNION ALL

SELECT
  round_display as section,
  CONCAT('Teams: ', CAST(teams AS STRING), ' (expected ', CAST(expected_teams AS STRING), ')') as detail1,
  CONCAT('Games: ', CAST(total_games AS STRING)) as detail2,
  CONCAT('Per team: ', CAST(min_games AS STRING), '-', CAST(max_games AS STRING), ' games') as detail3,
  CONCAT('Avg: ', CAST(avg_games AS STRING)) as detail4,
  status
FROM round_validation
ORDER BY
  CASE section
    WHEN '=== PLAYOFF STRUCTURE ===' THEN 0
    WHEN 'First Round' THEN 1
    WHEN 'Conference Semis' THEN 2
    WHEN 'Conference Finals' THEN 3
    WHEN 'NBA Finals' THEN 4
    ELSE 5
  END

UNION ALL

-- Output 2: Team playoff runs
SELECT
  '' as section,
  '' as detail1,
  '' as detail2,
  '' as detail3,
  '' as detail4,
  '' as status

UNION ALL

SELECT
  '=== TEAM PLAYOFF RUNS ===' as section,
  '' as detail1,
  '' as detail2,
  '' as detail3,
  '' as detail4,
  '' as status

UNION ALL

SELECT
  team as section,
  team_name as detail1,
  playoff_path as detail2,
  CONCAT(CAST(total_games AS STRING), ' games') as detail3,
  playoff_result as detail4,
  '' as status
FROM team_validation
ORDER BY total_games DESC, team;
