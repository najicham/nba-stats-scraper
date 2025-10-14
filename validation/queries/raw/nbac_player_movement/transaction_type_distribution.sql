-- ============================================================================
-- File: validation/queries/raw/nbac_player_movement/transaction_type_distribution.sql
-- Purpose: Verify transaction type ratios match expected distributions
-- Usage: Run monthly to detect data quality issues in transaction types
-- ============================================================================
-- Expected Results:
--   - Signing: ~47% (most common, includes re-signings and new contracts)
--   - Waive: ~31% (teams releasing players)
--   - Trade: ~20% (includes multi-part trades)
--   - ContractConverted: ~1.6% (two-way to standard conversions)
--   - AwardOnWaivers: ~0.6% (claiming players off waivers)
-- ============================================================================

WITH
transaction_counts AS (
  SELECT
    season_year,
    transaction_type,
    COUNT(*) as count,
    COUNT(CASE WHEN is_player_transaction = TRUE THEN 1 END) as player_count,
    COUNT(CASE WHEN is_player_transaction = FALSE THEN 1 END) as non_player_count
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
  GROUP BY season_year, transaction_type
),

season_totals AS (
  SELECT
    season_year,
    SUM(count) as total_transactions
  FROM transaction_counts
  GROUP BY season_year
),

percentages AS (
  SELECT
    tc.season_year,
    tc.transaction_type,
    tc.count,
    tc.player_count,
    tc.non_player_count,
    st.total_transactions,
    ROUND(100.0 * tc.count / st.total_transactions, 1) as percentage,
    -- Expected percentages for comparison
    CASE
      WHEN tc.transaction_type = 'Signing' THEN 47.5
      WHEN tc.transaction_type = 'Waive' THEN 30.6
      WHEN tc.transaction_type = 'Trade' THEN 19.8
      WHEN tc.transaction_type = 'ContractConverted' THEN 1.6
      WHEN tc.transaction_type = 'AwardOnWaivers' THEN 0.6
      ELSE 0
    END as expected_percentage
  FROM transaction_counts tc
  JOIN season_totals st ON tc.season_year = st.season_year
)

SELECT
  CONCAT(CAST(season_year AS STRING), '-', CAST(season_year + 1 AS STRING)) as season,
  transaction_type,
  count as total_count,
  player_count,
  non_player_count,
  CONCAT(CAST(percentage AS STRING), '%') as actual_pct,
  CONCAT(CAST(expected_percentage AS STRING), '%') as expected_pct,
  ROUND(percentage - expected_percentage, 1) as variance,
  CASE
    WHEN ABS(percentage - expected_percentage) <= 5.0 THEN '✅ Normal'
    WHEN ABS(percentage - expected_percentage) <= 10.0 THEN '🟡 Slight variance'
    ELSE '⚠️ Significant variance'
  END as status,
  CASE
    WHEN transaction_type = 'Trade' AND non_player_count > 0
    THEN CONCAT('(', CAST(non_player_count AS STRING), ' draft picks/cash)')
    WHEN transaction_type IN ('Signing', 'Waive') AND non_player_count > 0
    THEN '⚠️ Unexpected non-player records'
    ELSE ''
  END as notes
FROM percentages
ORDER BY season_year DESC, count DESC;
