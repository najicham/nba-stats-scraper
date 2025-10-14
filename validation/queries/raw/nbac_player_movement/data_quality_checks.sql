-- ============================================================================
-- File: validation/queries/raw/nbac_player_movement/data_quality_checks.sql
-- Purpose: Comprehensive data quality validation (NULLs, duplicates, orphans)
-- Usage: Run after backfills or when investigating data integrity issues
-- ============================================================================
-- Expected Results:
--   - All critical fields should be non-NULL
--   - No duplicate primary keys (would indicate INSERT_NEW_ONLY failure)
--   - No orphaned non-player transactions outside trades
-- ============================================================================

WITH
-- Check 1: NULL value detection
null_checks AS (
  SELECT
    'NULL_VALUES' as check_type,
    'Required Fields' as check_name,
    COUNT(CASE WHEN transaction_type IS NULL THEN 1 END) as transaction_type_nulls,
    COUNT(CASE WHEN transaction_date IS NULL THEN 1 END) as transaction_date_nulls,
    COUNT(CASE WHEN season_year IS NULL THEN 1 END) as season_year_nulls,
    COUNT(CASE WHEN team_abbr IS NULL THEN 1 END) as team_abbr_nulls,
    COUNT(CASE WHEN player_lookup IS NULL AND is_player_transaction = TRUE THEN 1 END) as player_lookup_nulls,
    COUNT(CASE WHEN group_sort IS NULL THEN 1 END) as group_sort_nulls
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
),

-- Check 2: Duplicate detection (should be 0 with INSERT_NEW_ONLY)
duplicate_checks AS (
  SELECT
    'DUPLICATES' as check_type,
    'Primary Key Check' as check_name,
    COUNT(*) as total_records,
    COUNT(DISTINCT CONCAT(
      CAST(player_id AS STRING), '-',
      CAST(team_id AS STRING), '-',
      CAST(transaction_date AS STRING), '-',
      transaction_type, '-',
      group_sort
    )) as unique_keys,
    COUNT(*) - COUNT(DISTINCT CONCAT(
      CAST(player_id AS STRING), '-',
      CAST(team_id AS STRING), '-',
      CAST(transaction_date AS STRING), '-',
      transaction_type, '-',
      group_sort
    )) as duplicate_count
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
),

-- Check 3: Player vs Non-Player consistency
player_flag_checks AS (
  SELECT
    'PLAYER_FLAGS' as check_type,
    'is_player_transaction Validation' as check_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN is_player_transaction = TRUE AND player_id = 0 THEN 1 END) as player_flag_but_no_id,
    COUNT(CASE WHEN is_player_transaction = FALSE AND player_id != 0 THEN 1 END) as non_player_flag_but_has_id,
    COUNT(CASE WHEN is_player_transaction = FALSE AND transaction_type != 'Trade' THEN 1 END) as non_player_non_trade
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
),

-- Check 4: Recent data freshness
freshness_checks AS (
  SELECT
    'FRESHNESS' as check_type,
    'Recent Activity' as check_name,
    MAX(transaction_date) as most_recent_transaction,
    MAX(created_at) as most_recent_insert,
    DATE_DIFF(CURRENT_DATE(), MAX(transaction_date), DAY) as days_since_last_transaction,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_since_last_insert
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
)

-- Output formatted results
SELECT
  '1. NULL CHECKS' as section,
  CONCAT('Required Fields: ',
    CASE
      WHEN transaction_type_nulls + transaction_date_nulls + season_year_nulls + team_abbr_nulls = 0
      THEN '✅ No NULLs'
      ELSE CONCAT('❌ Found ', CAST(transaction_type_nulls + transaction_date_nulls + season_year_nulls + team_abbr_nulls AS STRING), ' NULL values')
    END
  ) as result,
  CONCAT('type:', CAST(transaction_type_nulls AS STRING),
         ' | date:', CAST(transaction_date_nulls AS STRING),
         ' | season:', CAST(season_year_nulls AS STRING),
         ' | team:', CAST(team_abbr_nulls AS STRING),
         ' | player:', CAST(player_lookup_nulls AS STRING)) as details
FROM null_checks

UNION ALL

SELECT
  '2. DUPLICATE CHECKS' as section,
  CONCAT('Primary Keys: ',
    CASE
      WHEN duplicate_count = 0 THEN '✅ No duplicates'
      ELSE CONCAT('❌ Found ', CAST(duplicate_count AS STRING), ' duplicates')
    END
  ) as result,
  CONCAT('Total: ', CAST(total_records AS STRING),
         ' | Unique: ', CAST(unique_keys AS STRING),
         ' | Duplicates: ', CAST(duplicate_count AS STRING)) as details
FROM duplicate_checks

UNION ALL

SELECT
  '3. PLAYER FLAG CHECKS' as section,
  CONCAT('Flag Consistency: ',
    CASE
      WHEN player_flag_but_no_id + non_player_flag_but_has_id = 0 THEN '✅ Consistent'
      ELSE CONCAT('⚠️ Found ', CAST(player_flag_but_no_id + non_player_flag_but_has_id AS STRING), ' inconsistencies')
    END
  ) as result,
  CONCAT('Player flag no ID: ', CAST(player_flag_but_no_id AS STRING),
         ' | Non-player has ID: ', CAST(non_player_flag_but_has_id AS STRING),
         ' | Non-player non-trade: ', CAST(non_player_non_trade AS STRING)) as details
FROM player_flag_checks

UNION ALL

SELECT
  '4. FRESHNESS CHECKS' as section,
  CONCAT('Recent Activity: ',
    CASE
      WHEN days_since_last_transaction <= 7 THEN '✅ Recent transactions'
      WHEN days_since_last_transaction <= 30 THEN '🟡 1-4 weeks old'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8, 2) THEN '⚠️ Old during active period'
      ELSE '⚪ Normal off-season gap'
    END
  ) as result,
  CONCAT('Last transaction: ', CAST(most_recent_transaction AS STRING),
         ' (', CAST(days_since_last_transaction AS STRING), ' days ago)',
         ' | Last insert: ', CAST(hours_since_last_insert AS STRING), ' hours ago') as details
FROM freshness_checks

ORDER BY section;
