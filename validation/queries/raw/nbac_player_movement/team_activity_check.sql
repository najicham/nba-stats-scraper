-- ============================================================================
-- File: validation/queries/raw/nbac_player_movement/team_activity_check.sql
-- Purpose: Verify all 30 teams have reasonable transaction activity
-- Usage: Run monthly or when investigating specific team data issues
-- ============================================================================
-- Expected Results:
--   - All 30 teams should appear in recent seasons
--   - Teams with 0 transactions in current season = data issue
--   - Teams with <5 transactions in full season = investigate
-- ============================================================================

WITH
current_season AS (
  -- Get the most recent season that actually has transaction data
  -- (handles case where new NBA season just started but no transactions yet)
  SELECT MAX(season_year) as season_year
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
),

all_teams AS (
  SELECT team_abbr
  FROM UNNEST([
    'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
    'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
    'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
  ]) as team_abbr
),

team_transactions AS (
  SELECT
    season_year,
    team_abbr,
    COUNT(*) as total_transactions,
    COUNT(CASE WHEN transaction_type = 'Signing' THEN 1 END) as signings,
    COUNT(CASE WHEN transaction_type = 'Waive' THEN 1 END) as waives,
    COUNT(CASE WHEN transaction_type = 'Trade' THEN 1 END) as trades,
    COUNT(DISTINCT player_id) as unique_players,
    MAX(transaction_date) as most_recent_transaction
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
  GROUP BY season_year, team_abbr
),

-- Get current season stats
current_season_stats AS (
  SELECT
    t.team_abbr,
    COALESCE(tt.total_transactions, 0) as transactions,
    COALESCE(tt.signings, 0) as signings,
    COALESCE(tt.waives, 0) as waives,
    COALESCE(tt.trades, 0) as trades,
    COALESCE(tt.unique_players, 0) as players,
    tt.most_recent_transaction,
    CASE
      WHEN tt.total_transactions IS NULL THEN '❌ No data'
      WHEN tt.total_transactions = 0 THEN '❌ No transactions'
      WHEN tt.total_transactions < 5 THEN '⚠️ Very low'
      WHEN tt.total_transactions < 10 THEN '🟡 Low'
      ELSE '✅ Active'
    END as status
  FROM all_teams t
  CROSS JOIN current_season cs
  LEFT JOIN team_transactions tt
    ON t.team_abbr = tt.team_abbr
    AND tt.season_year = cs.season_year
)

SELECT
  team_abbr,
  transactions,
  signings,
  waives,
  trades,
  players,
  most_recent_transaction,
  status,
  CASE
    WHEN most_recent_transaction IS NULL THEN 'Never seen'
    WHEN DATE_DIFF(CURRENT_DATE(), most_recent_transaction, DAY) > 90
      AND EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8, 2)
    THEN CONCAT('⚠️ ', CAST(DATE_DIFF(CURRENT_DATE(), most_recent_transaction, DAY) AS STRING), ' days old (active period)')
    WHEN DATE_DIFF(CURRENT_DATE(), most_recent_transaction, DAY) > 180
    THEN CONCAT(CAST(DATE_DIFF(CURRENT_DATE(), most_recent_transaction, DAY) AS STRING), ' days old')
    ELSE 'Recent'
  END as recency_note
FROM current_season_stats
ORDER BY
  CASE status
    WHEN '❌ No data' THEN 1
    WHEN '❌ No transactions' THEN 2
    WHEN '⚠️ Very low' THEN 3
    WHEN '🟡 Low' THEN 4
    ELSE 5
  END,
  transactions ASC;
