-- Data Loss Validation Script
-- Cross-references processor_run_history zero-record runs with actual BigQuery data
-- Created: 2026-01-14 (Session 33)

-- ============================================================================
-- 1. ODDS GAME LINES PROCESSOR (836 zero-record runs)
-- ============================================================================
WITH zero_runs AS (
  SELECT DISTINCT data_date
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name = 'OddsGameLinesProcessor'
    AND status = 'success'
    AND records_processed = 0
    AND data_date >= '2025-10-01'
  ORDER BY data_date
)
SELECT
  'OddsGameLinesProcessor' as processor,
  zr.data_date,
  COUNT(DISTINCT gl.game_id) as actual_games,
  COUNT(*) as actual_records,
  CASE
    WHEN COUNT(*) > 0 THEN 'HAS DATA - False positive (tracking bug)'
    WHEN zr.data_date > CURRENT_DATE() THEN 'FUTURE DATE - Legitimate zero'
    ELSE 'NO DATA - Real data loss'
  END as classification
FROM zero_runs zr
LEFT JOIN `nba-props-platform.nba_raw.odds_game_lines` gl
  ON zr.data_date = DATE(gl.commence_time)
GROUP BY zr.data_date
ORDER BY zr.data_date DESC
LIMIT 50;

-- ============================================================================
-- 2. ODDS API PROPS PROCESSOR (445 zero-record runs)
-- ============================================================================
WITH zero_runs AS (
  SELECT DISTINCT data_date
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name = 'OddsApiPropsProcessor'
    AND status = 'success'
    AND records_processed = 0
    AND data_date >= '2025-10-01'
  ORDER BY data_date
)
SELECT
  'OddsApiPropsProcessor' as processor,
  zr.data_date,
  COUNT(DISTINCT oap.game_id) as actual_games,
  COUNT(*) as actual_records,
  CASE
    WHEN COUNT(*) > 0 THEN 'HAS DATA - False positive (tracking bug)'
    WHEN zr.data_date > CURRENT_DATE() THEN 'FUTURE DATE - Legitimate zero'
    ELSE 'NO DATA - Real data loss'
  END as classification
FROM zero_runs zr
LEFT JOIN `nba-props-platform.nba_raw.odds_api_props` oap
  ON zr.data_date = DATE(oap.commence_time)
GROUP BY zr.data_date
ORDER BY zr.data_date DESC
LIMIT 50;

-- ============================================================================
-- 3. BASKETBALL REFERENCE ROSTER PROCESSOR (426 zero-record runs)
-- ============================================================================
WITH zero_runs AS (
  SELECT DISTINCT data_date
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name = 'BasketballRefRosterProcessor'
    AND status = 'success'
    AND records_processed = 0
    AND data_date >= '2025-10-01'
  ORDER BY data_date
)
SELECT
  'BasketballRefRosterProcessor' as processor,
  zr.data_date,
  COUNT(DISTINCT br.team_abbr) as actual_teams,
  COUNT(*) as actual_records,
  CASE
    WHEN COUNT(*) > 0 THEN 'HAS DATA - False positive (tracking bug)'
    ELSE 'NO DATA - Real data loss'
  END as classification
FROM zero_runs zr
LEFT JOIN `nba-props-platform.nba_raw.basketball_ref_rosters` br
  ON zr.data_date = br.season_date
GROUP BY zr.data_date
ORDER BY zr.data_date DESC
LIMIT 50;

-- ============================================================================
-- 4. BETTINGPROS PROCESSOR (59 zero-record runs)
-- ============================================================================
WITH zero_runs AS (
  SELECT DISTINCT data_date
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name = 'BettingPropsProcessor'
    AND status = 'success'
    AND records_processed = 0
    AND data_date >= '2025-10-01'
  ORDER BY data_date
)
SELECT
  'BettingPropsProcessor' as processor,
  zr.data_date,
  COUNT(DISTINCT bp.game_id) as actual_games,
  COUNT(*) as actual_records,
  CASE
    WHEN COUNT(*) > 0 THEN 'HAS DATA - False positive (tracking bug)'
    WHEN zr.data_date > CURRENT_DATE() THEN 'FUTURE DATE - Legitimate zero'
    ELSE 'NO DATA - Real data loss'
  END as classification
FROM zero_runs zr
LEFT JOIN `nba-props-platform.nba_raw.bettingpros_player_props` bp
  ON zr.data_date = DATE(bp.game_datetime)
GROUP BY zr.data_date
ORDER BY zr.data_date DESC
LIMIT 50;

-- ============================================================================
-- 5. BDL BOXSCORES PROCESSOR (55 zero-record runs)
-- ============================================================================
WITH zero_runs AS (
  SELECT DISTINCT data_date
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name = 'BdlBoxscoresProcessor'
    AND status = 'success'
    AND records_processed = 0
    AND data_date >= '2025-10-01'
  ORDER BY data_date
)
SELECT
  'BdlBoxscoresProcessor' as processor,
  zr.data_date,
  COUNT(DISTINCT bb.game_id) as actual_games,
  COUNT(*) as actual_records,
  CASE
    WHEN COUNT(*) > 0 THEN 'HAS DATA - False positive (tracking bug)'
    WHEN zr.data_date > CURRENT_DATE() THEN 'FUTURE DATE - Legitimate zero'
    ELSE 'NO DATA - Real data loss'
  END as classification
FROM zero_runs zr
LEFT JOIN `nba-props-platform.nba_raw.bdl_boxscores` bb
  ON zr.data_date = bb.game_date
GROUP BY zr.data_date
ORDER BY zr.data_date DESC
LIMIT 50;

-- ============================================================================
-- SUMMARY: All Top 5 Processors Combined
-- ============================================================================
WITH all_zero_runs AS (
  SELECT
    processor_name,
    data_date
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processor_name IN (
    'OddsGameLinesProcessor',
    'OddsApiPropsProcessor',
    'BasketballRefRosterProcessor',
    'BettingPropsProcessor',
    'BdlBoxscoresProcessor'
  )
    AND status = 'success'
    AND records_processed = 0
    AND data_date >= '2025-10-01'
)
SELECT
  processor_name,
  COUNT(*) as total_zero_runs,
  COUNT(DISTINCT data_date) as affected_dates,
  MIN(data_date) as earliest_date,
  MAX(data_date) as latest_date
FROM all_zero_runs
GROUP BY processor_name
ORDER BY total_zero_runs DESC;
