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
-- Per-game retry analysis: was data eventually available? how many attempts?
per_game AS (
  SELECT
    game_date,
    home_team,
    away_team,
    COUNT(*) as attempts,
    COUNTIF(was_available) as successful_attempts,
    MAX(CAST(was_available AS INT64)) = 1 as eventually_available,
    MIN(scrape_timestamp) as first_attempt,
    MIN(IF(was_available, scrape_timestamp, NULL)) as first_success,
    -- Latency: hours between game date and first successful scrape
    TIMESTAMP_DIFF(
      MIN(IF(was_available, scrape_timestamp, NULL)),
      TIMESTAMP(game_date),
      HOUR
    ) as hours_to_first_success
  FROM `nba_orchestration.bdl_game_scrape_attempts`
  GROUP BY game_date, home_team, away_team
),

-- Daily availability from per-game data
daily_availability AS (
  SELECT
    game_date,
    COUNT(*) as games_expected,
    COUNTIF(eventually_available) as games_eventually_available,
    COUNTIF(NOT eventually_available) as games_never_available,
    ROUND(SAFE_DIVIDE(COUNTIF(eventually_available), COUNT(*)) * 100, 1) as eventual_availability_pct,
    SUM(attempts) as total_scrape_attempts,
    SUM(successful_attempts) as total_successful_attempts,
    -- Latency stats (only for games that eventually succeeded)
    ROUND(AVG(IF(eventually_available, hours_to_first_success, NULL)), 1) as avg_hours_to_data,
    MAX(IF(eventually_available, hours_to_first_success, NULL)) as max_hours_to_data,
    -- Retry burden: how many attempts needed per game
    ROUND(AVG(attempts), 1) as avg_attempts_per_game
  FROM per_game
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
    a.games_eventually_available,
    a.games_never_available,
    a.eventual_availability_pct,
    a.total_scrape_attempts,
    a.avg_attempts_per_game,
    a.avg_hours_to_data,
    a.max_hours_to_data,
    COALESCE(q.major_issues, 0) as major_issues,
    COALESCE(q.minor_issues, 0) as minor_issues,
    s.coverage_pct,
    s.accuracy_pct,
    s.major_pct as major_discrepancy_pct,
    s.missing_players,
    s.bdl_status,
    CASE
      WHEN a.eventual_availability_pct = 0 THEN 'FULL_OUTAGE'
      WHEN a.eventual_availability_pct < 50 THEN 'MAJOR_OUTAGE'
      WHEN a.eventual_availability_pct < 90 THEN 'PARTIAL_OUTAGE'
      WHEN COALESCE(q.major_issues, 0) > 10 THEN 'QUALITY_DEGRADATION'
      WHEN COALESCE(q.major_issues, 0) > 0 THEN 'MINOR_QUALITY_ISSUES'
      WHEN a.avg_hours_to_data > 24 THEN 'LATE_DATA'
      WHEN a.eventual_availability_pct >= 90 THEN 'OPERATIONAL'
      ELSE 'UNKNOWN'
    END as issue_type,
    CASE
      WHEN a.eventual_availability_pct = 0 THEN
        CONCAT('No data returned (', a.games_expected, ' games, ', a.total_scrape_attempts, ' attempts)')
      WHEN a.eventual_availability_pct < 50 THEN
        CONCAT('Partial outage: ', a.games_eventually_available, '/', a.games_expected, ' games eventually available')
      WHEN COALESCE(q.major_issues, 0) > 10 THEN
        CONCAT(q.major_issues, ' major data mismatches (wrong minutes/points)')
      WHEN a.avg_hours_to_data > 24 THEN
        CONCAT('Data arrived late: avg ', CAST(a.avg_hours_to_data AS STRING), 'h, max ', CAST(a.max_hours_to_data AS STRING), 'h')
      WHEN a.eventual_availability_pct >= 90 THEN 'Operational'
      ELSE CONCAT(a.games_eventually_available, '/', a.games_expected, ' games available')
    END as issue_summary
  FROM daily_availability a
  LEFT JOIN daily_quality q ON a.game_date = q.game_date
  LEFT JOIN daily_summary s ON a.game_date = s.game_date
)

SELECT * FROM daily_status
ORDER BY game_date DESC
