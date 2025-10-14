-- ============================================================================
-- File: validation/queries/raw/bdl_standings/data_quality_check.sql
-- ============================================================================
-- BDL Standings Data Quality Check
-- Purpose: Mathematical validation of all standings calculations
-- Validates: Record math, win percentages, record string parsing
-- Run: Weekly, after major backfills
-- ============================================================================

WITH latest_standings AS (
  SELECT *
  FROM `nba-props-platform.nba_raw.bdl_standings`
  WHERE date_recorded = (SELECT MAX(date_recorded) FROM `nba-props-platform.nba_raw.bdl_standings`)
),

quality_checks AS (
  SELECT
    team_abbr,
    team_full_name,
    date_recorded,
    season_display,
    conference,
    conference_rank,
    RANK() OVER (PARTITION BY conference ORDER BY win_percentage DESC, wins DESC) as expected_rank,
    wins,
    losses,
    games_played,
    wins + losses as calculated_games_played,
    wins + losses - games_played as games_played_diff,
    win_percentage,
    ROUND(wins / NULLIF(games_played, 0), 3) as calculated_win_pct,
    ABS(win_percentage - ROUND(wins / NULLIF(games_played, 0), 3)) as win_pct_diff,
    conference_record,
    conference_wins,
    conference_losses,
    conference_wins + conference_losses as conf_total_games,
    CASE 
      WHEN conference_wins > wins THEN TRUE 
      WHEN conference_losses > losses THEN TRUE
      ELSE FALSE 
    END as conf_record_exceeds_total,
    division_record,
    division_wins,
    division_losses,
    division_wins + division_losses as div_total_games,
    CASE 
      WHEN division_wins > wins THEN TRUE 
      WHEN division_losses > losses THEN TRUE
      ELSE FALSE 
    END as div_record_exceeds_total,
    home_record,
    home_wins,
    home_losses,
    road_record,
    road_wins,
    road_losses,
    home_wins + road_wins as calculated_total_wins,
    home_losses + road_losses as calculated_total_losses,
    ABS(wins - (home_wins + road_wins)) as home_road_wins_diff,
    ABS(losses - (home_losses + road_losses)) as home_road_losses_diff
  FROM latest_standings
),

ranking_validation AS (
  SELECT
    conference,
    COUNT(*) as total_teams,
    SUM(CASE WHEN conference_rank = expected_rank THEN 1 ELSE 0 END) as correct_ranks,
    SUM(CASE WHEN conference_rank != expected_rank THEN 1 ELSE 0 END) as incorrect_ranks
  FROM quality_checks
  GROUP BY conference
)

-- Combine all quality check results
(
SELECT
  '🔍 DATA QUALITY ISSUES' as section,
  team_abbr,
  team_full_name,
  conference,
  CASE
    WHEN games_played_diff != 0 
      THEN CONCAT('🔴 Games played mismatch: ', 
                  CAST(wins AS STRING), '+', CAST(losses AS STRING), 
                  '=', CAST(calculated_games_played AS STRING),
                  ' but games_played=', CAST(games_played AS STRING))
    WHEN win_pct_diff > 0.001
      THEN CONCAT('⚠️ Win % mismatch: stored=', CAST(win_percentage AS STRING), 
                  ' calculated=', CAST(calculated_win_pct AS STRING))
    WHEN conf_record_exceeds_total
      THEN '🔴 Conference record exceeds total record'
    WHEN div_record_exceeds_total
      THEN '🔴 Division record exceeds total record'
    WHEN home_road_wins_diff > 0 OR home_road_losses_diff > 0
      THEN CONCAT('🔴 Home/Road split error: home+road wins=', 
                  CAST(calculated_total_wins AS STRING), 
                  ' but total wins=', CAST(wins AS STRING))
    ELSE '✅ All checks passed'
  END as issue_description,
  CASE
    WHEN games_played_diff != 0 OR conf_record_exceeds_total 
         OR div_record_exceeds_total OR home_road_wins_diff > 0
      THEN 'CRITICAL'
    WHEN win_pct_diff > 0.001
      THEN 'WARNING'
    ELSE 'OK'
  END as severity,
  NULL as extra1,
  NULL as extra2,
  NULL as extra3
FROM quality_checks
WHERE games_played_diff != 0
   OR win_pct_diff > 0.001
   OR conf_record_exceeds_total
   OR div_record_exceeds_total
   OR home_road_wins_diff > 0
   OR home_road_losses_diff > 0

UNION ALL

-- Record string parsing validation
SELECT
  '📝 RECORD STRING PARSING' as section,
  team_abbr,
  NULL as team_full_name,
  CONCAT('Conf: ', conference_record, ' (', CAST(conference_wins AS STRING), '-', CAST(conference_losses AS STRING), ')') as conference,
  CASE
    WHEN conference_record IS NULL AND (conference_wins IS NULL OR conference_losses IS NULL)
      THEN '⚪ No conference record data'
    WHEN conference_record IS NOT NULL 
         AND CONCAT(CAST(conference_wins AS STRING), '-', CAST(conference_losses AS STRING)) = conference_record
      THEN '✅ Correctly parsed'
    WHEN conference_record IS NOT NULL 
         AND conference_wins = 0 AND conference_losses = 0
      THEN '🔴 CRITICAL: Parsing failed (0-0)'
    ELSE '⚠️ WARNING: Parsing mismatch'
  END as issue_description,
  CASE
    WHEN division_record IS NULL AND (division_wins IS NULL OR division_losses IS NULL)
      THEN '⚪ No division record data'
    WHEN division_record IS NOT NULL 
         AND CONCAT(CAST(division_wins AS STRING), '-', CAST(division_losses AS STRING)) = division_record
      THEN '✅ Correctly parsed'
    WHEN division_record IS NOT NULL 
         AND division_wins = 0 AND division_losses = 0
      THEN '🔴 CRITICAL: Parsing failed (0-0)'
    ELSE '⚠️ WARNING: Parsing mismatch'
  END as severity,
  CONCAT('Div: ', division_record, ' (', CAST(division_wins AS STRING), '-', CAST(division_losses AS STRING), ')') as extra1,
  NULL as extra2,
  NULL as extra3
FROM quality_checks
WHERE (conference_record IS NOT NULL AND (conference_wins = 0 AND conference_losses = 0))
   OR (division_record IS NOT NULL AND (division_wins = 0 AND division_losses = 0))
   OR (conference_record IS NOT NULL 
       AND CONCAT(CAST(conference_wins AS STRING), '-', CAST(conference_losses AS STRING)) != conference_record)
   OR (division_record IS NOT NULL 
       AND CONCAT(CAST(division_wins AS STRING), '-', CAST(division_losses AS STRING)) != division_record)

UNION ALL

-- Overall quality summary
SELECT
  '📊 QUALITY SUMMARY' as section,
  CAST(date_recorded AS STRING) as team_abbr,
  CONCAT('Total: ', CAST(COUNT(*) AS STRING)) as team_full_name,
  CONCAT('Games played correct: ', CAST(SUM(CASE WHEN games_played_diff = 0 THEN 1 ELSE 0 END) AS STRING)) as conference,
  CONCAT('Win pct correct: ', CAST(SUM(CASE WHEN win_pct_diff <= 0.001 THEN 1 ELSE 0 END) AS STRING)) as issue_description,
  CONCAT('Conf record valid: ', CAST(SUM(CASE WHEN NOT conf_record_exceeds_total THEN 1 ELSE 0 END) AS STRING)) as severity,
  CONCAT('Div record valid: ', CAST(SUM(CASE WHEN NOT div_record_exceeds_total THEN 1 ELSE 0 END) AS STRING)) as extra1,
  CONCAT('Home/road correct: ', CAST(SUM(CASE WHEN home_road_wins_diff = 0 AND home_road_losses_diff = 0 THEN 1 ELSE 0 END) AS STRING)) as extra2,
  CONCAT('Overall: ', CAST(ROUND(SUM(CASE WHEN games_played_diff = 0 
                      AND win_pct_diff <= 0.001 
                      AND NOT conf_record_exceeds_total 
                      AND NOT div_record_exceeds_total 
                      AND home_road_wins_diff = 0 
                      AND home_road_losses_diff = 0 
                 THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) AS STRING), '%') as extra3
FROM quality_checks
GROUP BY date_recorded

UNION ALL

-- Ranking order validation
SELECT
  '🏆 RANKING ORDER VALIDATION' as section,
  conference as team_abbr,
  CONCAT('Total: ', CAST(total_teams AS STRING)) as team_full_name,
  CONCAT('Correct: ', CAST(correct_ranks AS STRING)) as conference,
  CONCAT('Incorrect: ', CAST(incorrect_ranks AS STRING)) as issue_description,
  CASE
    WHEN incorrect_ranks = 0
      THEN '✅ All rankings correct'
    ELSE CONCAT('⚠️ ', CAST(incorrect_ranks AS STRING), ' ranking mismatches')
  END as severity,
  NULL as extra1,
  NULL as extra2,
  NULL as extra3
FROM ranking_validation

ORDER BY 
  CASE section
    WHEN '🔍 DATA QUALITY ISSUES' THEN 1
    WHEN '📝 RECORD STRING PARSING' THEN 2
    WHEN '📊 QUALITY SUMMARY' THEN 3
    WHEN '🏆 RANKING ORDER VALIDATION' THEN 4
  END,
  team_abbr
);
