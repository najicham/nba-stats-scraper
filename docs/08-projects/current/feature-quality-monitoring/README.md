# Feature Quality Monitoring System

**Date:** 2026-01-30
**Status:** Proposal
**Priority:** High (prevents fatigue_score-type bugs from going undetected)

---

## Problem Statement

The fatigue_score=0 bug (Session 46-47) went undetected for days because:
1. No automated monitoring compared feature values to historical baselines
2. Validation only checked if values were within bounds (0-100), not if they were *reasonable*
3. No alerting when feature distributions shifted dramatically

**Impact:** Wrong predictions for days, corrupted grading metrics, lost user trust.

---

## Proposed Solution

A **Feature Quality Monitoring System** that:
1. Computes historical baselines (mean, stddev) for each ML feature
2. Compares recent values to baselines using z-scores
3. Alerts when features deviate significantly from expected ranges
4. Runs automatically with daily health checks

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Feature Quality Monitoring                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐    ┌───────────────┐    ┌────────────────────┐   │
│  │ ML Feature   │───>│ Quality       │───>│ Alert Decision     │   │
│  │ Store v2     │    │ Calculator    │    │ Engine             │   │
│  └──────────────┘    └───────────────┘    └────────────────────┘   │
│         │                   │                       │               │
│         │                   ▼                       ▼               │
│         │           ┌───────────────┐     ┌────────────────────┐   │
│         │           │ quality_trends│     │ Slack/Email Alerts │   │
│         │           │ (BigQuery)    │     │ (existing system)  │   │
│         │           └───────────────┘     └────────────────────┘   │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Feature Statistics Query (SQL)                                │  │
│  │ - Baseline: last 30 days (mean, stddev, percentiles)         │  │
│  │ - Recent: last 3 days (mean)                                  │  │
│  │ - Z-score: (recent_mean - baseline_mean) / baseline_stddev   │  │
│  │ - Alert if |z-score| > 2.0 or value outside expected range   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: SQL-Based Detection (Quick Win)

Create a SQL query that computes feature health in a single pass:

```sql
-- Feature Quality Health Check
-- Compares recent feature values to 30-day baseline
-- Alerts on significant deviations

WITH feature_names AS (
  -- Map array indices to feature names
  SELECT 0 AS idx, 'points_avg_last_5' AS name, 0 AS min_val, 80 AS max_val UNION ALL
  SELECT 1, 'points_avg_last_10', 0, 80 UNION ALL
  SELECT 2, 'points_avg_season', 0, 60 UNION ALL
  SELECT 5, 'fatigue_score', 0, 100 UNION ALL
  SELECT 6, 'shot_zone_mismatch_score', 0, 100 UNION ALL
  SELECT 7, 'pace_score', 0, 100 UNION ALL
  SELECT 8, 'usage_spike_score', 0, 100 UNION ALL
  SELECT 31, 'minutes_avg_last_10', 0, 48 UNION ALL
  SELECT 32, 'ppm_avg_last_10', 0, 1.5
  -- Add all 37 features...
),

baseline AS (
  -- Historical baseline: last 30 days (excluding last 3)
  SELECT
    fn.idx,
    fn.name AS feature_name,
    fn.min_val,
    fn.max_val,
    AVG(features[OFFSET(fn.idx)]) AS baseline_mean,
    STDDEV(features[OFFSET(fn.idx)]) AS baseline_stddev,
    APPROX_QUANTILES(features[OFFSET(fn.idx)], 100)[OFFSET(5)] AS p5,
    APPROX_QUANTILES(features[OFFSET(fn.idx)], 100)[OFFSET(95)] AS p95,
    COUNT(*) AS baseline_samples
  FROM `nba_predictions.ml_feature_store_v2`, feature_names fn
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 33 DAY)
                      AND DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    AND features IS NOT NULL
    AND ARRAY_LENGTH(features) > fn.idx
  GROUP BY fn.idx, fn.name, fn.min_val, fn.max_val
),

recent AS (
  -- Recent window: last 3 days
  SELECT
    fn.idx,
    AVG(features[OFFSET(fn.idx)]) AS recent_mean,
    MIN(features[OFFSET(fn.idx)]) AS recent_min,
    MAX(features[OFFSET(fn.idx)]) AS recent_max,
    COUNT(*) AS recent_samples,
    COUNTIF(features[OFFSET(fn.idx)] = 0) AS zero_count,
    COUNTIF(features[OFFSET(fn.idx)] IS NULL) AS null_count
  FROM `nba_predictions.ml_feature_store_v2`, feature_names fn
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    AND features IS NOT NULL
    AND ARRAY_LENGTH(features) > fn.idx
  GROUP BY fn.idx
)

SELECT
  b.feature_name,
  b.idx AS feature_index,

  -- Baseline stats
  ROUND(b.baseline_mean, 2) AS baseline_mean,
  ROUND(b.baseline_stddev, 2) AS baseline_stddev,
  b.baseline_samples,

  -- Recent stats
  ROUND(r.recent_mean, 2) AS recent_mean,
  ROUND(r.recent_min, 2) AS recent_min,
  ROUND(r.recent_max, 2) AS recent_max,
  r.recent_samples,
  r.zero_count,
  r.null_count,

  -- Deviation analysis
  ROUND((r.recent_mean - b.baseline_mean) / NULLIF(b.baseline_stddev, 0), 2) AS z_score,
  ROUND(((r.recent_mean - b.baseline_mean) / NULLIF(b.baseline_mean, 0)) * 100, 1) AS pct_change,

  -- Alert conditions
  CASE
    WHEN ABS((r.recent_mean - b.baseline_mean) / NULLIF(b.baseline_stddev, 0)) > 3.0 THEN 'CRITICAL'
    WHEN ABS((r.recent_mean - b.baseline_mean) / NULLIF(b.baseline_stddev, 0)) > 2.0 THEN 'WARNING'
    WHEN r.recent_min < b.min_val OR r.recent_max > b.max_val THEN 'RANGE_VIOLATION'
    WHEN r.zero_count > r.recent_samples * 0.1 THEN 'HIGH_ZERO_RATE'
    ELSE 'OK'
  END AS status,

  -- Expected range
  b.min_val AS expected_min,
  b.max_val AS expected_max

FROM baseline b
JOIN recent r ON b.idx = r.idx
ORDER BY
  CASE
    WHEN ABS((r.recent_mean - b.baseline_mean) / NULLIF(b.baseline_stddev, 0)) > 3.0 THEN 1
    WHEN ABS((r.recent_mean - b.baseline_mean) / NULLIF(b.baseline_stddev, 0)) > 2.0 THEN 2
    ELSE 3
  END,
  ABS((r.recent_mean - b.baseline_mean) / NULLIF(b.baseline_stddev, 0)) DESC
```

**How it would have caught the fatigue_score bug:**
- Baseline mean for fatigue_score: ~90 (players are generally well-rested)
- Recent mean with bug: ~0 (all zeros from buggy code)
- Z-score: (0 - 90) / 10 = -9.0 → **CRITICAL**
- Also: zero_count = 100% of samples → **HIGH_ZERO_RATE**

---

### Phase 2: Automated Daily Check

Add to `daily_health_summary` Cloud Function:

```python
def check_feature_quality(bq_client):
    """Run feature quality SQL and return health status."""
    query = """
    -- (SQL from above, simplified to return only issues)
    SELECT feature_name, status, z_score, pct_change, recent_mean, baseline_mean
    FROM feature_quality_check
    WHERE status != 'OK'
    ORDER BY z_score DESC
    """

    results = list(bq_client.query(query).result())

    if not results:
        return {"status": "healthy", "issues": []}

    critical = [r for r in results if r.status == 'CRITICAL']
    warnings = [r for r in results if r.status in ('WARNING', 'RANGE_VIOLATION', 'HIGH_ZERO_RATE')]

    return {
        "status": "critical" if critical else "warning" if warnings else "healthy",
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "issues": [
            {
                "feature": r.feature_name,
                "status": r.status,
                "z_score": r.z_score,
                "recent": r.recent_mean,
                "baseline": r.baseline_mean,
                "change": f"{r.pct_change:+.1f}%"
            }
            for r in results[:10]  # Top 10 issues
        ]
    }
```

---

### Phase 3: Store Historical Metrics

Use existing `nba_monitoring.quality_trends` table:

```sql
-- Daily job to populate feature quality metrics
INSERT INTO `nba_monitoring.quality_trends`
(metric_date, metric_name, metric_value, rolling_7d_avg, rolling_7d_stddev,
 trend_direction, deviation_from_avg, alert_triggered)

SELECT
  CURRENT_DATE() AS metric_date,
  CONCAT('feature_', fn.name, '_mean') AS metric_name,
  AVG(features[OFFSET(fn.idx)]) AS metric_value,
  -- Rolling stats computed separately
  NULL AS rolling_7d_avg,
  NULL AS rolling_7d_stddev,
  NULL AS trend_direction,
  NULL AS deviation_from_avg,
  FALSE AS alert_triggered
FROM `nba_predictions.ml_feature_store_v2`, feature_names fn
WHERE game_date = CURRENT_DATE()
GROUP BY fn.idx, fn.name
```

This enables:
- Time-series visualization of feature trends
- Week-over-week comparisons
- Automated alerts when rolling averages shift

---

### Phase 4: Real-time Pre-write Validation

Extend `worker.py` validation pattern to ML feature store processor:

```python
# In ml_feature_store_processor.py

FEATURE_BASELINES = {
    # Feature index: (expected_min, expected_max, typical_mean, alert_threshold)
    5: (0, 100, 90, 50),   # fatigue_score: typically ~90, alert if <50
    6: (0, 100, 50, 20),   # shot_zone_mismatch
    31: (0, 48, 25, 10),   # minutes_avg_last_10: typically ~25min
    32: (0, 1.5, 0.6, 0.3), # ppm_avg_last_10: typically ~0.6
}

def _validate_feature_distribution(features: list, player_count: int) -> list:
    """
    Validate feature distribution before writing batch to BigQuery.

    Checks:
    1. Features are within expected ranges
    2. Feature means are reasonable (not all zeros, not all max)
    3. Distribution has expected variance (not collapsed)
    """
    issues = []

    for idx, (min_val, max_val, typical_mean, alert_threshold) in FEATURE_BASELINES.items():
        values = [f[idx] for f in features if f is not None and len(f) > idx]

        if not values:
            issues.append(f"CRITICAL: Feature {idx} has no values")
            continue

        mean_val = sum(values) / len(values)
        zero_count = sum(1 for v in values if v == 0)
        zero_pct = zero_count / len(values)

        # Check for collapsed distribution (bug indicator)
        if zero_pct > 0.5:
            issues.append(f"CRITICAL: Feature {idx} has {zero_pct:.0%} zeros (expected <10%)")

        # Check mean is reasonable
        if abs(mean_val - typical_mean) > alert_threshold:
            issues.append(f"WARNING: Feature {idx} mean={mean_val:.1f} vs typical={typical_mean:.1f}")

        # Check range violations
        out_of_range = sum(1 for v in values if v < min_val or v > max_val)
        if out_of_range > 0:
            issues.append(f"WARNING: Feature {idx} has {out_of_range} values outside [{min_val}, {max_val}]")

    return issues
```

---

## Detection Examples

### Example 1: fatigue_score=0 Bug

| Check | Baseline | Recent | Result |
|-------|----------|--------|--------|
| Mean | 90.2 | 0.0 | **Z-score: -9.0 (CRITICAL)** |
| Zero rate | 0.1% | 100% | **HIGH_ZERO_RATE** |
| Range | 0-100 | 0-0 | OK (within bounds but collapsed) |

**Alert:** "CRITICAL: fatigue_score mean dropped from 90.2 to 0.0 (z-score: -9.0). 100% of values are zero."

### Example 2: Gradual Drift

| Check | Week 1 | Week 2 | Week 3 | Week 4 |
|-------|--------|--------|--------|--------|
| points_avg_last_5 mean | 15.2 | 14.8 | 14.1 | 12.5 |
| Z-score vs baseline | -0.3 | -0.6 | -1.2 | -2.1 |
| Status | OK | OK | OK | **WARNING** |

**Alert:** "WARNING: points_avg_last_5 trending down. Week 4 mean (12.5) is 2.1 stddev below baseline (15.2)."

### Example 3: Data Source Failure

| Check | Baseline | Recent | Result |
|-------|----------|--------|--------|
| vegas_points_line null rate | 5% | 95% | **CRITICAL** |
| has_vegas_line mean | 0.95 | 0.05 | **Z-score: -15.0** |

**Alert:** "CRITICAL: Vegas line data missing for 95% of players. Check odds_api scraper."

---

## Integration with Existing Systems

### 1. Daily Health Summary (Cloud Function)
```python
# Add to HealthChecker.run_health_check()
feature_health = self.check_feature_quality()
if feature_health['status'] == 'critical':
    self.send_alert(f"🚨 CRITICAL: {feature_health['critical_count']} features have anomalies")
```

### 2. Feature Drift Detector
Extend `shared/validation/feature_drift_detector.py` to monitor all 37 features (currently only 12).

### 3. Pre-write Validation
Add distribution check before `BigQueryBatchWriter.flush()` in ML feature store processor.

### 4. Slack Alerts
Use existing `AlertManager` with rate limiting to prevent alert floods.

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Time to detect fatigue_score-type bug | <1 hour (vs days) |
| False positive rate | <5% of alerts |
| Feature coverage | 100% of 37 features monitored |
| Alert latency | <30 min after data write |

---

## Next Steps

1. **Immediate:** Create SQL query and test against historical data
2. **This week:** Add feature quality check to daily_health_summary
3. **Next week:** Implement pre-write validation in ML feature store processor
4. **Ongoing:** Build dashboard in BigQuery for trend visualization

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `validation/queries/monitoring/feature_quality_check.sql` | **CREATE** - Main SQL query |
| `shared/validation/feature_quality_monitor.py` | **CREATE** - Python wrapper |
| `orchestration/cloud_functions/daily_health_summary/main.py` | **MODIFY** - Add feature check |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | **MODIFY** - Pre-write validation |
| `shared/validation/feature_drift_detector.py` | **MODIFY** - Expand to 37 features |

---

*Document created: 2026-01-30*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
