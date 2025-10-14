-- ============================================================================
-- File: validation/queries/raw/nbac_player_movement/season_completeness_check.sql
-- Purpose: Season-by-season validation of player movement transactions
-- Usage: Run after backfills or monthly to verify historical data integrity
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show 0 for null_season, null_team
--   - Each season should have 600-1,100 transactions
--   - All 30 teams should appear each season
--   - Transaction type distribution: ~47% Signing, ~31% Waive, ~20% Trade
-- ============================================================================

WITH
transactions_with_validation AS (
  SELECT
    transaction_type,
    transaction_date,
    season_year,
    player_id,
    player_full_name,
    player_lookup,
    team_id,
    team_abbr,
    is_player_transaction,
    group_sort,
    CASE
      WHEN season_year IS NULL THEN 1 ELSE 0
    END as has_null_season,
    CASE
      WHEN team_abbr IS NULL THEN 1 ELSE 0
    END as has_null_team,
    CASE
      WHEN player_lookup IS NULL AND is_player_transaction = TRUE THEN 1 ELSE 0
    END as has_player_name_issue
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    '---' as season,
    'Quality Checks' as team,
    CAST(COUNT(*) AS STRING) as metric1,
    CAST(SUM(has_null_season) AS STRING) as metric2,
    CAST(SUM(has_null_team) AS STRING) as metric3,
    CAST(SUM(has_player_name_issue) AS STRING) as metric4,
    'total_records | null_season | null_team | missing_player_name' as description
  FROM transactions_with_validation
),

-- Calculate transactions per season and team
season_team_stats AS (
  SELECT
    season_year,
    team_abbr,
    COUNT(*) as total_transactions,
    COUNT(CASE WHEN transaction_type = 'Signing' THEN 1 END) as signings,
    COUNT(CASE WHEN transaction_type = 'Waive' THEN 1 END) as waives,
    COUNT(CASE WHEN transaction_type = 'Trade' THEN 1 END) as trades,
    COUNT(CASE WHEN transaction_type = 'ContractConverted' THEN 1 END) as conversions,
    COUNT(CASE WHEN transaction_type = 'AwardOnWaivers' THEN 1 END) as waiver_awards,
    COUNT(DISTINCT player_id) as unique_players,
    COUNT(CASE WHEN is_player_transaction = FALSE THEN 1 END) as non_player_assets
  FROM transactions_with_validation
  GROUP BY season_year, team_abbr
),

-- Season totals for summary row
season_totals AS (
  SELECT
    season_year,
    'SEASON TOTAL' as team_abbr,
    SUM(total_transactions) as total_transactions,
    SUM(signings) as signings,
    SUM(waives) as waives,
    SUM(trades) as trades,
    SUM(conversions) as conversions,
    SUM(waiver_awards) as waiver_awards,
    SUM(unique_players) as unique_players,
    SUM(non_player_assets) as non_player_assets
  FROM season_team_stats
  GROUP BY season_year
)

-- Output diagnostics first
SELECT
  row_type,
  season,
  team,
  metric1 as info1,
  metric2 as info2,
  metric3 as info3,
  metric4 as info4,
  description as notes
FROM diagnostics

UNION ALL

-- Then season totals
SELECT
  'SUMMARY' as row_type,
  CONCAT(CAST(season_year AS STRING), '-', CAST(season_year + 1 AS STRING)) as season,
  team_abbr as team,
  CAST(total_transactions AS STRING) as info1,
  CAST(signings AS STRING) as info2,
  CAST(waives AS STRING) as info3,
  CAST(trades AS STRING) as info4,
  CASE
    WHEN total_transactions < 500 THEN '⚠️ Low volume'
    WHEN total_transactions > 1200 THEN '⚠️ High volume'
    ELSE '✅ Normal range'
  END as notes
FROM season_totals

UNION ALL

-- Then team stats
SELECT
  'TEAM' as row_type,
  CONCAT(CAST(season_year AS STRING), '-', CAST(season_year + 1 AS STRING)) as season,
  team_abbr as team,
  CAST(total_transactions AS STRING) as info1,
  CAST(signings AS STRING) as info2,
  CAST(waives AS STRING) as info3,
  CAST(trades AS STRING) as info4,
  CASE
    WHEN total_transactions = 0 THEN '❌ No transactions'
    WHEN total_transactions < 10 THEN '⚠️ Very low'
    WHEN unique_players < 5 THEN '⚠️ Few players'
    ELSE ''
  END as notes
FROM season_team_stats
ORDER BY
  row_type,
  season DESC,
  team;
