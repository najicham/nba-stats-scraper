-- ============================================================================
-- File: validation/queries/raw/bdl_standings/conference_standings_check.sql
-- ============================================================================
-- BDL Standings Conference Rankings Check
-- Purpose: Validate conference ranking integrity and order
-- Expected: Ranks 1-15 per conference, no gaps, no duplicates
-- Run: Weekly, after standings updates
-- ============================================================================

WITH latest_standings AS (
  SELECT *
  FROM `nba-props-platform.nba_raw.bdl_standings`
  WHERE date_recorded = (SELECT MAX(date_recorded) FROM `nba-props-platform.nba_raw.bdl_standings`)
),

conference_validation AS (
  SELECT
    conference,
    COUNT(*) as team_count,
    COUNT(DISTINCT conference_rank) as unique_ranks,
    MIN(conference_rank) as min_rank,
    MAX(conference_rank) as max_rank,
    ARRAY_LENGTH(ARRAY_AGG(DISTINCT conference_rank ORDER BY conference_rank)) as rank_count,
    COUNT(*) - COUNT(DISTINCT conference_rank) as duplicate_ranks
  FROM latest_standings
  GROUP BY conference
),

ranking_details AS (
  SELECT
    conference,
    conference_rank,
    COUNT(*) as teams_at_rank,
    STRING_AGG(team_abbr, ', ' ORDER BY wins DESC, team_abbr) as teams,
    STRING_AGG(CONCAT(CAST(wins AS STRING), '-', CAST(losses AS STRING)), ', ') as records
  FROM latest_standings
  GROUP BY conference, conference_rank
  HAVING COUNT(*) > 1
),

standings_with_validation AS (
  SELECT
    conference,
    conference_rank,
    team_abbr,
    team_full_name,
    wins,
    losses,
    win_percentage,
    games_played,
    ROUND(wins / NULLIF(games_played, 0), 3) as calculated_win_pct,
    ABS(win_percentage - ROUND(wins / NULLIF(games_played, 0), 3)) as win_pct_diff,
    RANK() OVER (PARTITION BY conference ORDER BY win_percentage DESC, wins DESC) as expected_rank,
    conference_rank - RANK() OVER (PARTITION BY conference ORDER BY win_percentage DESC, wins DESC) as rank_diff,
    CASE
      WHEN conference_rank = RANK() OVER (PARTITION BY conference ORDER BY win_percentage DESC, wins DESC)
        THEN '✅'
      ELSE '⚠️ Rank mismatch'
    END as rank_validation,
    CASE
      WHEN ABS(win_percentage - ROUND(wins / NULLIF(games_played, 0), 3)) > 0.001
        THEN '⚠️ Win% mismatch'
      ELSE '✅'
    END as win_pct_validation
  FROM latest_standings
),

division_stats AS (
  SELECT
    conference,
    division,
    COUNT(*) as teams_in_division,
    COUNT(DISTINCT division_rank) as unique_division_ranks,
    MIN(division_rank) as min_division_rank,
    MAX(division_rank) as max_division_rank,
    CASE
      WHEN COUNT(*) = 5 AND COUNT(DISTINCT division_rank) = 5 
           AND MIN(division_rank) = 1 AND MAX(division_rank) = 5
        THEN '✅ Valid'
      WHEN COUNT(*) != 5
        THEN CONCAT('⚠️ WARNING: ', CAST(COUNT(*) AS STRING), ' teams (expected 5)')
      ELSE '⚠️ Review needed'
    END as status
  FROM latest_standings
  GROUP BY conference, division
),

top_teams AS (
  SELECT
    conference,
    conference_rank,
    team_abbr,
    CONCAT(CAST(wins AS STRING), '-', CAST(losses AS STRING)) as record,
    win_percentage,
    CONCAT(CAST(home_wins AS STRING), '-', CAST(home_losses AS STRING)) as home_record,
    CONCAT(CAST(road_wins AS STRING), '-', CAST(road_losses AS STRING)) as road_record
  FROM latest_standings
  WHERE conference_rank <= 3
)

-- Combine all results into one output
(
SELECT 
  '🔍 CONFERENCE VALIDATION' as section,
  v.conference,
  CAST(v.team_count AS STRING) as team_count,
  CAST(v.unique_ranks AS STRING) as unique_ranks,
  CAST(v.min_rank AS STRING) as min_rank,
  CAST(v.max_rank AS STRING) as max_rank,
  CAST(v.duplicate_ranks AS STRING) as duplicate_ranks,
  CASE
    WHEN v.team_count = 15 AND v.unique_ranks = 15 
         AND v.min_rank = 1 AND v.max_rank = 15 
         AND v.duplicate_ranks = 0
      THEN '✅ Valid'
    WHEN v.team_count != 15
      THEN CONCAT('🔴 CRITICAL: ', CAST(v.team_count AS STRING), ' teams (expected 15)')
    WHEN v.duplicate_ranks > 0
      THEN CONCAT('⚠️ WARNING: ', CAST(v.duplicate_ranks AS STRING), ' duplicate ranks')
    WHEN v.unique_ranks != 15
      THEN '⚠️ WARNING: Ranking gaps detected'
    WHEN v.min_rank != 1 OR v.max_rank != 15
      THEN '⚠️ WARNING: Invalid rank range'
    ELSE '⚠️ Review needed'
  END as status,
  NULL as detail1,
  NULL as detail2,
  NULL as detail3,
  NULL as detail4,
  NULL as detail5
FROM conference_validation v

UNION ALL

-- Duplicate rankings if any
SELECT
  '⚠️ DUPLICATE RANKINGS' as section,
  conference,
  CAST(conference_rank AS STRING) as team_count,
  CAST(teams_at_rank AS STRING) as unique_ranks,
  teams as min_rank,
  records as max_rank,
  NULL as duplicate_ranks,
  NULL as status,
  NULL as detail1,
  NULL as detail2,
  NULL as detail3,
  NULL as detail4,
  NULL as detail5
FROM ranking_details

UNION ALL

-- Conference standings summary (top 5 from each)
SELECT
  '📊 CONFERENCE STANDINGS' as section,
  conference,
  CAST(conference_rank AS STRING),
  team_abbr,
  team_full_name,
  CONCAT(CAST(wins AS STRING), '-', CAST(losses AS STRING)) as max_rank,
  CAST(win_percentage AS STRING) as duplicate_ranks,
  rank_validation as status,
  win_pct_validation as detail1,
  NULL as detail2,
  NULL as detail3,
  NULL as detail4,
  NULL as detail5
FROM standings_with_validation
WHERE conference_rank <= 5

UNION ALL

-- Division rankings
SELECT
  '📊 DIVISION RANKINGS' as section,
  conference,
  division as team_count,
  CAST(teams_in_division AS STRING) as unique_ranks,
  CAST(unique_division_ranks AS STRING) as min_rank,
  CONCAT(CAST(min_division_rank AS STRING), '-', CAST(max_division_rank AS STRING)) as max_rank,
  NULL as duplicate_ranks,
  status,
  NULL as detail1,
  NULL as detail2,
  NULL as detail3,
  NULL as detail4,
  NULL as detail5
FROM division_stats

UNION ALL

-- Top teams summary
SELECT
  '🏆 TOP TEAMS' as section,
  conference,
  CAST(conference_rank AS STRING) as team_count,
  team_abbr as unique_ranks,
  record as min_rank,
  CAST(win_percentage AS STRING) as max_rank,
  home_record as duplicate_ranks,
  road_record as status,
  NULL as detail1,
  NULL as detail2,
  NULL as detail3,
  NULL as detail4,
  NULL as detail5
FROM top_teams

ORDER BY 
  CASE section
    WHEN '🔍 CONFERENCE VALIDATION' THEN 1
    WHEN '⚠️ DUPLICATE RANKINGS' THEN 2
    WHEN '📊 CONFERENCE STANDINGS' THEN 3
    WHEN '📊 DIVISION RANKINGS' THEN 4
    WHEN '🏆 TOP TEAMS' THEN 5
  END,
  conference,
  SAFE_CAST(team_count AS INT64)
);
