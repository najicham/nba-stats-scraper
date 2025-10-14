-- ============================================================================
-- File: validation/queries/raw/nbac_player_movement/recent_activity_check.sql
-- Purpose: View recent transaction activity (last 30 days)
-- Usage: Run weekly or when monitoring current season activity
-- ============================================================================
-- Expected Results:
--   - During free agency (July-August): Expect daily activity
--   - During trade deadline (February): Expect frequent updates
--   - During playoffs (May-June): Minimal activity is normal
--   - Off-season: No activity for weeks is expected
-- ============================================================================

WITH
recent_transactions AS (
  SELECT
    transaction_date,
    transaction_type,
    team_abbr,
    player_full_name,
    transaction_description,
    is_player_transaction,
    group_sort,
    created_at
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE transaction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND season_year >= 2021
),

daily_summary AS (
  SELECT
    transaction_date,
    COUNT(*) as total_transactions,
    COUNT(CASE WHEN transaction_type = 'Signing' THEN 1 END) as signings,
    COUNT(CASE WHEN transaction_type = 'Waive' THEN 1 END) as waives,
    COUNT(CASE WHEN transaction_type = 'Trade' THEN 1 END) as trades,
    COUNT(DISTINCT team_abbr) as teams_active,
    COUNT(DISTINCT CASE WHEN is_player_transaction = TRUE THEN player_full_name END) as unique_players
  FROM recent_transactions
  GROUP BY transaction_date
),

team_activity AS (
  SELECT
    team_abbr,
    COUNT(*) as total_transactions,
    COUNT(CASE WHEN transaction_type = 'Signing' THEN 1 END) as signings,
    COUNT(CASE WHEN transaction_type = 'Waive' THEN 1 END) as waives,
    COUNT(CASE WHEN transaction_type = 'Trade' THEN 1 END) as trades,
    STRING_AGG(DISTINCT player_full_name ORDER BY player_full_name LIMIT 3) as sample_players,
    MAX(transaction_date) as most_recent
  FROM recent_transactions
  WHERE is_player_transaction = TRUE
  GROUP BY team_abbr
),

seasonal_context AS (
  SELECT
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8) THEN 'Free Agency (Expect High Activity)'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) = 2 THEN 'Trade Deadline (Expect Moderate Activity)'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 'Playoffs (Low Activity Normal)'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (9, 10) THEN 'Pre-Season (Moderate Activity)'
      ELSE 'Regular Season (Low Activity Normal)'
    END as period_context,
    COUNT(*) as total_last_30_days
  FROM recent_transactions
)

-- Combine all sections (BigQuery UNION ALL requires proper structure)
(
  -- Part 1: Context and Summary
  SELECT
    'CONTEXT' as section,
    period_context as info1,
    CAST(total_last_30_days AS STRING) as info2,
    CASE
      WHEN total_last_30_days = 0 AND period_context LIKE '%High Activity%' THEN '⚠️ No transactions during active period'
      WHEN total_last_30_days = 0 THEN '⚪ No transactions (may be normal)'
      WHEN total_last_30_days < 10 AND period_context LIKE '%High Activity%' THEN '🟡 Low activity during active period'
      ELSE '✅ Has activity'
    END as info3,
    '' as info4,
    '' as info5,
    1 as sort_order
  FROM seasonal_context

  UNION ALL

  -- Part 2: Daily activity
  SELECT
    'DAILY' as section,
    CAST(transaction_date AS STRING) as info1,
    CAST(total_transactions AS STRING) as info2,
    CONCAT(CAST(signings AS STRING), ' sign / ',
           CAST(waives AS STRING), ' waive / ',
           CAST(trades AS STRING), ' trade') as info3,
    CAST(teams_active AS STRING) as info4,
    CAST(unique_players AS STRING) as info5,
    2 as sort_order
  FROM daily_summary

  UNION ALL

  -- Part 3: Team activity summary
  SELECT
    'TEAMS' as section,
    team_abbr as info1,
    CAST(total_transactions AS STRING) as info2,
    CONCAT(CAST(signings AS STRING), '/', CAST(waives AS STRING), '/', CAST(trades AS STRING)) as info3,
    sample_players as info4,
    CAST(most_recent AS STRING) as info5,
    3 as sort_order
  FROM team_activity
)
ORDER BY 
  sort_order,
  CASE WHEN section = 'DAILY' THEN info1 ELSE '' END DESC,
  CASE WHEN section = 'TEAMS' THEN CAST(info2 AS INT64) ELSE 0 END DESC
LIMIT 50;
