-- Confidence Distribution Alert Query
-- Purpose: Detect when confidence score distribution changes significantly
-- Created: Session 37 (2026-01-30)
--
-- Background:
-- On January 9, 2026, the 0.95 and 0.90 confidence levels completely disappeared
-- without any alerting. This query detects such distribution shifts.
--
-- Usage:
-- Run daily as part of /validate-daily
-- Alert if any high-confidence buckets show >50% change from baseline

-- Compare today's distribution to 7-day baseline
WITH today_distribution AS (
    SELECT
        ROUND(confidence_score, 1) as confidence_bucket,
        COUNT(*) as count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = CURRENT_DATE()
      AND system_id = 'catboost_v8'
      AND is_active = TRUE
    GROUP BY 1
),
baseline_distribution AS (
    SELECT
        confidence_bucket,
        AVG(daily_count) as avg_count,
        STDDEV(daily_count) as std_count
    FROM (
        SELECT
            game_date,
            ROUND(confidence_score, 1) as confidence_bucket,
            COUNT(*) as daily_count
        FROM nba_predictions.player_prop_predictions
        WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
              AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
          AND system_id = 'catboost_v8'
          AND is_active = TRUE
        GROUP BY 1, 2
    )
    GROUP BY confidence_bucket
),
comparison AS (
    SELECT
        COALESCE(t.confidence_bucket, b.confidence_bucket) as confidence_bucket,
        COALESCE(t.count, 0) as today_count,
        COALESCE(b.avg_count, 0) as baseline_avg,
        COALESCE(b.std_count, 0) as baseline_std,
        CASE
            WHEN b.avg_count IS NULL OR b.avg_count = 0 THEN 'NEW_BUCKET'
            WHEN t.count IS NULL OR t.count = 0 THEN 'DISAPPEARED'
            ELSE ROUND(100.0 * (COALESCE(t.count, 0) - b.avg_count) / NULLIF(b.avg_count, 0), 1)
        END as pct_change
    FROM today_distribution t
    FULL OUTER JOIN baseline_distribution b USING (confidence_bucket)
)
SELECT
    confidence_bucket,
    today_count,
    ROUND(baseline_avg, 1) as baseline_avg,
    pct_change,
    CASE
        -- Critical: High-confidence buckets disappeared
        WHEN confidence_bucket >= 0.9 AND pct_change = 'DISAPPEARED'
            THEN '🔴 CRITICAL: Decile 10 bucket disappeared!'
        WHEN confidence_bucket >= 0.9 AND SAFE_CAST(pct_change AS FLOAT64) < -50
            THEN '🔴 CRITICAL: Decile 10 dropped >50%'
        -- Warning: Significant changes
        WHEN confidence_bucket >= 0.85 AND pct_change = 'DISAPPEARED'
            THEN '🟡 WARNING: High-confidence bucket disappeared'
        WHEN SAFE_CAST(pct_change AS FLOAT64) < -50 OR SAFE_CAST(pct_change AS FLOAT64) > 100
            THEN '🟡 WARNING: >50% change from baseline'
        -- New bucket appearing
        WHEN pct_change = 'NEW_BUCKET' AND today_count > 10
            THEN '🟡 INFO: New confidence bucket appeared'
        ELSE '✅ OK'
    END as status
FROM comparison
WHERE confidence_bucket >= 0.8  -- Focus on high-confidence predictions
ORDER BY confidence_bucket DESC;


-- ============================================================================
-- SUMMARY QUERY: Quick health check
-- ============================================================================

-- Quick summary for daily validation
SELECT
    'catboost_v8' as system_id,
    CURRENT_DATE() as check_date,
    COUNT(*) as total_predictions,
    COUNTIF(confidence_score >= 0.9) as decile_10_count,
    COUNTIF(confidence_score >= 0.85 AND confidence_score < 0.9) as decile_9_count,
    ROUND(100.0 * COUNTIF(confidence_score >= 0.9) / NULLIF(COUNT(*), 0), 1) as pct_high_confidence,
    ROUND(AVG(confidence_score), 3) as avg_confidence,
    ROUND(MAX(confidence_score), 3) as max_confidence,
    CASE
        WHEN COUNTIF(confidence_score >= 0.9) = 0 THEN '🔴 CRITICAL: No decile 10 predictions!'
        WHEN COUNTIF(confidence_score >= 0.9) < 10 THEN '🟡 WARNING: Very few decile 10 predictions'
        WHEN MAX(confidence_score) < 0.92 THEN '🟡 WARNING: Max confidence below 0.92'
        ELSE '✅ OK'
    END as health_status
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v8'
  AND is_active = TRUE;
