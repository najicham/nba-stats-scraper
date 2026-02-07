-- BDL Service Issues - Consolidated daily view of BDL API health
-- Created: Session 149 (2026-02-07)
--
-- Usage:
--   SELECT * FROM nba_orchestration.bdl_service_issues ORDER BY game_date DESC LIMIT 30;
--   SELECT * FROM nba_orchestration.bdl_service_issues WHERE issue_type != 'OPERATIONAL';
--
-- Sources:
--   - nba_orchestration.bdl_game_scrape_attempts (availability/latency)
--   - nba_orchestration.source_discrepancies (data quality mismatches)

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.bdl_service_issues` AS
WITH
-- Daily availability from scrape attempts
daily_availability AS (
  SELECT
    game_date,
    COUNT(DISTINCT CONCAT(home_team, '_', away_team)) as games_expected,
    COUNTIF(was_available) as games_available,
    COUNTIF(NOT was_available) as games_missing,
    ROUND(SAFE_DIVIDE(COUNTIF(was_available), COUNT(DISTINCT CONCAT(home_team, '_', away_team))) * 100, 1) as availability_pct,
    MAX(scrape_timestamp) as last_scrape
  FROM `nba_orchestration.bdl_game_scrape_attempts`
  GROUP BY game_date
),

-- Daily quality from source discrepancies (player-level, excluding summary rows)
daily_quality AS (
  SELECT
    game_date,
    COUNTIF(severity = 'major') as major_issues,
    COUNTIF(severity = 'minor') as minor_issues,
    COUNT(*) as total_discrepancies
  FROM `nba_orchestration.source_discrepancies`
  WHERE backup_source = 'bdl'
    AND player_lookup != '_SUMMARY_'
  GROUP BY game_date
),

-- Daily summary rows (contain aggregate quality metrics)
daily_summary AS (
  SELECT
    game_date,
    JSON_EXTRACT_SCALAR(discrepancies_json, '$.coverage_percent') as coverage_pct,
    JSON_EXTRACT_SCALAR(discrepancies_json, '$.accuracy_pct') as accuracy_pct,
    JSON_EXTRACT_SCALAR(discrepancies_json, '$.major_discrepancy_pct') as major_pct,
    JSON_EXTRACT_SCALAR(discrepancies_json, '$.total_players') as total_players,
    JSON_EXTRACT_SCALAR(discrepancies_json, '$.bdl_coverage') as bdl_coverage,
    JSON_EXTRACT_SCALAR(discrepancies_json, '$.missing_in_bdl') as missing_players,
    JSON_EXTRACT_SCALAR(discrepancies_json, '$.bdl_status') as bdl_status
  FROM `nba_orchestration.source_discrepancies`
  WHERE backup_source = 'bdl'
    AND player_lookup = '_SUMMARY_'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date ORDER BY detected_at DESC) = 1
),

-- Combine into daily status
daily_status AS (
  SELECT
    a.game_date,
    a.games_expected,
    a.games_available,
    a.games_missing,
    a.availability_pct,
    COALESCE(q.major_issues, 0) as major_issues,
    COALESCE(q.minor_issues, 0) as minor_issues,
    s.coverage_pct,
    s.accuracy_pct,
    s.major_pct as major_discrepancy_pct,
    s.missing_players,
    s.bdl_status,
    CASE
      WHEN a.availability_pct = 0 THEN 'FULL_OUTAGE'
      WHEN a.availability_pct < 50 THEN 'MAJOR_OUTAGE'
      WHEN a.availability_pct < 90 THEN 'PARTIAL_OUTAGE'
      WHEN COALESCE(q.major_issues, 0) > 10 THEN 'QUALITY_DEGRADATION'
      WHEN COALESCE(q.major_issues, 0) > 0 THEN 'MINOR_QUALITY_ISSUES'
      WHEN a.availability_pct >= 90 THEN 'OPERATIONAL'
      ELSE 'UNKNOWN'
    END as issue_type,
    CASE
      WHEN a.availability_pct = 0 THEN CONCAT('No data returned (', a.games_expected, ' games expected)')
      WHEN a.availability_pct < 50 THEN CONCAT('Partial outage: ', a.games_available, '/', a.games_expected, ' games')
      WHEN COALESCE(q.major_issues, 0) > 10 THEN CONCAT(q.major_issues, ' major data mismatches (wrong minutes/points)')
      WHEN COALESCE(q.major_issues, 0) > 0 THEN CONCAT(q.major_issues, ' minor data mismatches')
      WHEN a.availability_pct >= 90 THEN 'Operational'
      ELSE 'No monitoring data'
    END as issue_summary
  FROM daily_availability a
  LEFT JOIN daily_quality q ON a.game_date = q.game_date
  LEFT JOIN daily_summary s ON a.game_date = s.game_date
)

SELECT * FROM daily_status
ORDER BY game_date DESC
