# Session 28: Data Corruption Incident Analysis

**Date:** 2026-01-30
**Severity:** HIGH - Data integrity issue affecting accuracy reporting
**Status:** Identified, needs fix

---

## Executive Summary

Session 28 discovered that what appeared to be "model drift" was actually caused by **two distinct issues**:

1. **Data Corruption (Jan 28 only)**: The grading pipeline corrupted `predicted_points` values in `prediction_accuracy` for Jan 28, inflating them by 1.7x-4.3x
2. **Real Performance Degradation (Jan 2026)**: Model performance has genuinely degraded in January 2026, but not as severely as the corrupted metrics suggested

---

## Issue 1: Data Corruption in prediction_accuracy

### What Happened

On January 29, 2026 at ~18:00 UTC, the grading process for January 28 games wrote corrupted data:

| Player | Original (player_prop_predictions) | Graded (prediction_accuracy) | Multiplier |
|--------|-----------------------------------|------------------------------|------------|
| anthonyedwards | 35.0 | 60.0 | 1.71x |
| brandonmiller | 16.1 | 42.1 | 2.61x |
| stephencurry | 20.7 | 45.0 | 2.17x |
| anferneesimons | 4.8 | 20.8 | 4.33x |

Additionally, each player had **5 duplicate records** with different `line_value` entries (+/- $1 from base line).

### Impact

| Metric | Corrupted Value | Correct Value |
|--------|----------------|---------------|
| Jan 28 Hit Rate | 52.6% | 48.1% |
| Jan 28 MAE | 9.85 | 6.40 |

The corruption actually **increased** the reported hit rate (because inflated predictions pushed more recommendations to OVER, which happened to align with some outcomes).

### Root Cause

**Unknown** - requires further investigation. Possible causes:
- Bug in grading processor creating Cartesian join with line snapshots
- Manual script execution with incorrect parameters
- Data transformation error during grading

### Verification Queries

```sql
-- Check for prediction value mismatch between tables
SELECT
  pp.game_date,
  COUNT(*) as records,
  ROUND(AVG(ABS(pp.predicted_points - pa.predicted_points)), 3) as avg_diff
FROM nba_predictions.player_prop_predictions pp
JOIN nba_predictions.prediction_accuracy pa
  ON pp.player_lookup = pa.player_lookup
  AND pp.game_date = pa.game_date
  AND pp.system_id = pa.system_id
WHERE pp.system_id = 'catboost_v8'
  AND pp.is_active = true
GROUP BY 1
HAVING avg_diff > 0.1  -- Flag any date with prediction mismatch
ORDER BY 1 DESC
```

---

## Issue 2: Real Model Performance Degradation

### Performance by Period

After accounting for data corruption, here's the real model performance:

| Period | Hit Rate | MAE | Data Status |
|--------|----------|-----|-------------|
| 2024-25 Season | 74.3% | 4.18 | ✅ Clean |
| Oct-Dec 2025 | 74.2% | 4.08 | ✅ Clean |
| Jan 1-27 2026 | ~57% | ~5.5 | ✅ Clean |
| Jan 28 2026 | 48.1% | 6.40 | ⚠️ Corrupted table, correct values shown |

### Weekly Breakdown (Jan 2026, production V8)

| Week | Date Range | Hit Rate | MAE |
|------|------------|----------|-----|
| 0 | Jan 1-3 | 67.0% | 4.81 |
| 1 | Jan 4-10 | 60.1% | 4.79 |
| 2 | Jan 11-17 | 56.3% | 6.02 |
| 3 | Jan 18-20 | 52.8% | 5.70 |
| 4 | Jan 25-28 | 52.9% | 8.12* |

*Week 4 MAE is inflated due to Jan 28 corruption

### Key Finding

The model's performance **has degraded** in January 2026, but:
- Early January was still reasonable (60-67%)
- Degradation accelerated mid-month
- The 61% overall 2025-26 hit rate from experiments is approximately correct
- Retraining experiments did **not** find a configuration that restores 70%+ performance on Jan 2026

---

## Retraining Experiment Results

All experiments evaluated on Jan 2026 (clean evaluation, not using corrupted prediction_accuracy):

| Experiment | Training Period | Jan 2026 Hit Rate | High-Conf (5+) |
|------------|----------------|-------------------|----------------|
| RECENT_2024_25 | 2024-10 to 2025-06 | 53.6% | 68.8% |
| ALL_DATA | 2021-11 to 2025-12 | 53.5% | 64.2% |
| COMBINED_RECENT | 2024-10 to 2025-12 | 53.0% | 66.9% |
| INSEASON_2025_26 | 2025-10 to 2025-12 | 52.5% | 61.1% |

**Conclusion**: No retraining configuration significantly improves Jan 2026 performance. The model may be facing:
- Fundamental changes in NBA player/team dynamics
- Vegas lines becoming more accurate (reducing edge)
- Need for architecture changes, not just retraining

---

## Immediate Actions Required

### 1. Fix Corrupted Jan 28 Data

```sql
-- Delete corrupted Jan 28 records
DELETE FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-28'
  AND system_id = 'catboost_v8';

-- Re-run grading for Jan 28 (after fixing root cause)
```

### 2. Investigate Grading Root Cause

- Check Cloud Function logs for Jan 29 18:00 UTC
- Review any manual scripts that ran
- Look for duplicate inserts or data transformation bugs

### 3. Add Data Integrity Validation

See Prevention Mechanisms section below.

---

## Prevention Mechanisms

### 1. Pre-Grade Validation Hook

Add validation before grading writes:

```python
def validate_grading_batch(predictions_df: pd.DataFrame, graded_df: pd.DataFrame) -> bool:
    """Validate graded data before writing to BigQuery."""
    # Check predicted_points hasn't changed
    merged = predictions_df.merge(graded_df, on=['player_lookup', 'game_date', 'system_id'])
    if (merged['predicted_points_x'] != merged['predicted_points_y']).any():
        raise DataIntegrityError("predicted_points mismatch detected")

    # Check for unexpected duplicates
    dupe_count = graded_df.groupby(['player_lookup', 'game_date', 'system_id', 'line_value']).size()
    if (dupe_count > 1).any():
        raise DataIntegrityError("Duplicate grading records detected")

    return True
```

### 2. Daily Data Integrity Check

Add to `/validate-daily` skill:

```sql
-- Prediction value consistency check
SELECT
  game_date,
  ROUND(AVG(ABS(pp.predicted_points - pa.predicted_points)), 3) as prediction_drift
FROM nba_predictions.player_prop_predictions pp
JOIN nba_predictions.prediction_accuracy pa USING (player_lookup, game_date, system_id)
WHERE pp.game_date >= CURRENT_DATE() - 7
  AND pp.is_active = true
GROUP BY 1
HAVING prediction_drift > 0.1
```

### 3. Grading Audit Log

Create audit table to track all grading operations:

```sql
CREATE TABLE nba_predictions.grading_audit_log (
  audit_id STRING NOT NULL,
  grading_timestamp TIMESTAMP NOT NULL,
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,
  records_processed INT64,
  records_written INT64,
  avg_predicted_points FLOAT64,
  source_table STRING,
  invoker STRING,  -- 'cloud_function', 'manual_script', etc.
  validation_passed BOOL
);
```

### 4. Alerting on Anomalies

Add Cloud Monitoring alert for:
- MAE spike > 50% vs 7-day average
- Hit rate drop > 10% vs 7-day average
- Prediction value drift between tables > 0.1

### 5. Idempotent Grading

Ensure grading is fully idempotent:
- Use MERGE instead of DELETE+INSERT
- Include all source fields in merge key
- Log hash of input data for verification

---

## Detection Checklist for Future Issues

If you suspect data corruption:

1. **Compare Tables**
   ```sql
   SELECT pp.predicted_points, pa.predicted_points, ABS(pp.predicted_points - pa.predicted_points) as diff
   FROM player_prop_predictions pp
   JOIN prediction_accuracy pa USING (player_lookup, game_date, system_id)
   WHERE pp.game_date = 'SUSPECT_DATE'
   ORDER BY diff DESC
   ```

2. **Check for Duplicates**
   ```sql
   SELECT player_lookup, game_date, system_id, COUNT(*) as dupes
   FROM prediction_accuracy
   WHERE game_date = 'SUSPECT_DATE'
   GROUP BY 1,2,3
   HAVING COUNT(*) > expected_count
   ```

3. **Verify Grading Timestamp**
   ```sql
   SELECT DISTINCT graded_at
   FROM prediction_accuracy
   WHERE game_date = 'SUSPECT_DATE'
   -- Should be a single grading run
   ```

4. **Cross-validate with Experiments**
   - Run evaluation script directly on feature_store + player_game_summary
   - Compare results with prediction_accuracy metrics
   - Discrepancy indicates data corruption

---

## Lessons Learned

1. **Multiple Sources of Truth are Risky**: Having predictions in one table and graded results in another creates opportunity for drift
2. **Validation Must Be Pre-Write**: Post-hoc validation catches issues too late
3. **Experiments Bypass Production Data**: This is both good (clean evaluation) and bad (doesn't catch production issues)
4. **MAE is Sensitive to Outliers**: A few corrupted records can dramatically inflate MAE

---

*Created: 2026-01-30 Session 28*
*Status: Investigation complete, fix pending*
