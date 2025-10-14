-- ============================================================================
-- File: validation/queries/raw/nbac_player_movement/scraper_freshness_check.sql
-- Purpose: Check when data was last scraped/inserted with seasonal context
-- Usage: Run daily to monitor scraper health (with appropriate expectations)
-- ============================================================================
-- Expected Results:
--   - Status interpretation depends on season (see seasonal_context)
--   - Green (✅) = scraper healthy for this time of year
--   - Yellow (🟡) = worth checking but may be normal
--   - Red (❌/🔴) = investigate immediately
-- ============================================================================

WITH
latest_data AS (
  SELECT
    MAX(transaction_date) as most_recent_transaction_date,
    MAX(scrape_timestamp) as most_recent_scrape_timestamp,
    MAX(created_at) as most_recent_insert_timestamp,
    COUNT(CASE WHEN created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) THEN 1 END) as inserts_last_24h,
    COUNT(CASE WHEN created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR) THEN 1 END) as inserts_last_72h
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
),

seasonal_expectations AS (
  SELECT
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8) THEN 'Free Agency'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) = 2 THEN 'Trade Deadline'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 'Playoffs'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (9, 10) THEN 'Pre-Season'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (11, 12, 1, 3, 4) THEN 'Regular Season'
      ELSE 'Off-Season'
    END as current_period,
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8) THEN 'Expect daily new transactions'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) = 2 THEN 'Expect frequent updates around deadline'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 'Minimal activity is NORMAL'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (9, 10) THEN 'Moderate activity (rosters finalizing)'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (11, 12, 1, 3, 4) THEN 'Low activity is NORMAL (mid-season)'
      ELSE 'No activity for weeks is NORMAL'
    END as expectation,
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8) THEN 3
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) = 2 THEN 7
      ELSE 30
    END as alert_threshold_days
),

status_calculation AS (
  SELECT
    l.*,
    s.current_period,
    s.expectation,
    s.alert_threshold_days,
    DATE_DIFF(CURRENT_DATE(), l.most_recent_transaction_date, DAY) as days_since_transaction,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), l.most_recent_scrape_timestamp, HOUR) as hours_since_scrape,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), l.most_recent_insert_timestamp, HOUR) as hours_since_insert,
    CASE
      WHEN DATE_DIFF(CURRENT_DATE(), l.most_recent_transaction_date, DAY) <= s.alert_threshold_days
      THEN '✅ Recent activity'
      WHEN DATE_DIFF(CURRENT_DATE(), l.most_recent_transaction_date, DAY) <= 30
        AND s.current_period NOT IN ('Free Agency', 'Trade Deadline')
      THEN '⚪ Normal quiet period'
      WHEN DATE_DIFF(CURRENT_DATE(), l.most_recent_transaction_date, DAY) > 30
        AND s.current_period IN ('Free Agency', 'Trade Deadline')
      THEN '❌ CRITICAL: No updates during active period'
      WHEN DATE_DIFF(CURRENT_DATE(), l.most_recent_transaction_date, DAY) > 90
      THEN '🔴 WARNING: Very stale data'
      ELSE '🟡 Worth checking'
    END as status
  FROM latest_data l
  CROSS JOIN seasonal_expectations s
)

SELECT
  CURRENT_DATE() as check_date,
  current_period,
  expectation,
  most_recent_transaction_date,
  days_since_transaction,
  CAST(most_recent_scrape_timestamp AS STRING) as last_scrape,
  hours_since_scrape,
  CAST(most_recent_insert_timestamp AS STRING) as last_insert,
  hours_since_insert,
  inserts_last_24h,
  inserts_last_72h,
  status,
  CASE
    WHEN inserts_last_24h > 0 THEN '✅ Scraper ran recently'
    WHEN inserts_last_72h > 0 THEN '🟡 No inserts in 24h (may be normal)'
    WHEN hours_since_insert > 168 THEN '⚠️ No inserts in 7+ days'
    ELSE '⚪ No recent inserts'
  END as scraper_health
FROM status_calculation;
