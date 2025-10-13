-- ============================================================================
-- File: validation/queries/raw/bdl_injuries/confidence_score_monitoring.sql
-- Purpose: Monitor BDL parsing quality via confidence scores
-- Usage: Run to detect parsing degradation or data quality issues
-- ============================================================================
-- Expected Results:
--   - Average confidence should be 1.0 (BDL has excellent parsing)
--   - Sudden drops indicate API format changes or parsing issues
--   - Low confidence records may need manual review
-- ============================================================================

WITH
-- Daily confidence trends
daily_confidence AS (
  SELECT
    scrape_date,
    COUNT(*) as total_records,
    AVG(parsing_confidence) as avg_confidence,
    MIN(parsing_confidence) as min_confidence,
    MAX(parsing_confidence) as max_confidence,
    -- Count confidence buckets
    COUNTIF(parsing_confidence < 0.5) as very_low_confidence,
    COUNTIF(parsing_confidence BETWEEN 0.5 AND 0.7) as low_confidence,
    COUNTIF(parsing_confidence BETWEEN 0.7 AND 0.9) as medium_confidence,
    COUNTIF(parsing_confidence >= 0.9) as high_confidence,
    -- Calculate percentages
    ROUND(COUNTIF(parsing_confidence < 0.8) * 100.0 / COUNT(*), 1) as pct_below_80,
    -- Return date parsing
    COUNT(CASE WHEN return_date_parsed = TRUE THEN 1 END) as return_dates_parsed,
    COUNT(CASE WHEN return_date_parsed = FALSE THEN 1 END) as return_dates_unparsed,
    ROUND(COUNT(CASE WHEN return_date_parsed = TRUE THEN 1 END) * 100.0 / COUNT(*), 1) as pct_return_parsed,
    -- Data quality flags
    COUNT(CASE WHEN data_quality_flags IS NOT NULL AND data_quality_flags != '' THEN 1 END) as records_with_flags
  FROM `nba-props-platform.nba_raw.bdl_injuries`
  WHERE scrape_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY scrape_date
),

-- Add rolling averages
with_trends AS (
  SELECT
    *,
    AVG(avg_confidence) OVER (
      ORDER BY scrape_date
      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) as rolling_7day_avg_confidence,
    AVG(pct_return_parsed) OVER (
      ORDER BY scrape_date
      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) as rolling_7day_return_pct
  FROM daily_confidence
)

SELECT
  scrape_date,
  FORMAT_DATE('%A', scrape_date) as day_of_week,
  total_records,
  ROUND(avg_confidence, 3) as avg_confidence,
  ROUND(rolling_7day_avg_confidence, 3) as avg_7day,
  ROUND(min_confidence, 3) as min_confidence,
  very_low_confidence,
  low_confidence,
  medium_confidence,
  high_confidence,
  pct_below_80,
  return_dates_parsed,
  return_dates_unparsed,
  pct_return_parsed,
  records_with_flags,
  CASE
    WHEN avg_confidence < 0.6 THEN '🔴 CRITICAL: Very low confidence'
    WHEN avg_confidence < 0.8 THEN '🟡 ERROR: Low confidence'
    WHEN avg_confidence < rolling_7day_avg_confidence * 0.95 THEN '⚠️  WARNING: Below recent average'
    WHEN pct_below_80 > 20 THEN '⚠️  WARNING: >20% low confidence'
    WHEN pct_return_parsed < 80.0 THEN '⚠️  WARNING: Low return date parsing'
    ELSE '✅ Healthy'
  END as status
FROM with_trends
ORDER BY scrape_date DESC
LIMIT 30;
