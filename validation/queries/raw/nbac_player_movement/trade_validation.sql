-- ============================================================================
-- File: validation/queries/raw/nbac_player_movement/trade_validation.sql
-- Purpose: Validate multi-part trades are complete (no orphaned trade parts)
-- Usage: Run after backfills or when investigating data quality issues
-- ============================================================================
-- Expected Results:
--   - All trades should have 2+ parts (teams_involved >= 2)
--   - Most trades involve 2 teams (simple trades)
--   - 3+ team trades should be rare but valid
--   - No orphaned single-part trades unless legitimately one-sided
-- ============================================================================

WITH
trade_transactions AS (
  SELECT
    group_sort,
    transaction_date,
    season_year,
    player_id,
    player_full_name,
    team_id,
    team_abbr,
    transaction_description,
    is_player_transaction
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE transaction_type = 'Trade'
    AND season_year >= 2021
),

trade_summary AS (
  SELECT
    group_sort,
    MIN(transaction_date) as trade_date,
    MIN(season_year) as season_year,
    COUNT(*) as total_parts,
    COUNT(DISTINCT team_id) as teams_involved,
    STRING_AGG(DISTINCT team_abbr ORDER BY team_abbr) as teams,
    COUNT(CASE WHEN is_player_transaction = TRUE THEN 1 END) as players_involved,
    COUNT(CASE WHEN is_player_transaction = FALSE THEN 1 END) as draft_picks_cash,
    STRING_AGG(DISTINCT player_full_name ORDER BY player_full_name LIMIT 3) as sample_players
  FROM trade_transactions
  GROUP BY group_sort
),

trade_complexity_stats AS (
  SELECT
    season_year,
    COUNT(*) as total_trades,
    COUNT(CASE WHEN teams_involved = 1 THEN 1 END) as single_team_trades,
    COUNT(CASE WHEN teams_involved = 2 THEN 1 END) as two_team_trades,
    COUNT(CASE WHEN teams_involved >= 3 THEN 1 END) as multi_team_trades,
    ROUND(AVG(total_parts), 1) as avg_parts_per_trade,
    ROUND(AVG(players_involved), 1) as avg_players_per_trade
  FROM trade_summary
  GROUP BY season_year
)

-- Part 1: Season summary
SELECT
  'SUMMARY' as section,
  CONCAT(CAST(season_year AS STRING), '-', CAST(season_year + 1 AS STRING)) as season,
  CAST(total_trades AS STRING) as total_trades,
  CAST(two_team_trades AS STRING) as two_team,
  CAST(multi_team_trades AS STRING) as multi_team,
  CAST(single_team_trades AS STRING) as suspicious,
  CASE
    WHEN single_team_trades > 0 THEN '⚠️ Has orphaned trades'
    ELSE '✅ All trades complete'
  END as status
FROM trade_complexity_stats

UNION ALL

-- Part 2: Suspicious trades (1 team only - likely orphaned)
SELECT
  'ORPHANED' as section,
  group_sort as season,
  CAST(trade_date AS STRING) as total_trades,
  teams as two_team,
  CAST(total_parts AS STRING) as multi_team,
  CAST(teams_involved AS STRING) as suspicious,
  '❌ Only 1 team - incomplete trade' as status
FROM trade_summary
WHERE teams_involved = 1

UNION ALL

-- Part 3: Recent complex trades (3+ teams)
SELECT
  'COMPLEX' as section,
  group_sort as season,
  CAST(trade_date AS STRING) as total_trades,
  teams as two_team,
  CONCAT(CAST(players_involved AS STRING), ' players, ', CAST(draft_picks_cash AS STRING), ' picks/cash') as multi_team,
  sample_players as suspicious,
  CONCAT('✅ ', CAST(teams_involved AS STRING), ' teams') as status
FROM trade_summary
WHERE teams_involved >= 3
  AND trade_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)

ORDER BY section DESC, season DESC
LIMIT 100;
