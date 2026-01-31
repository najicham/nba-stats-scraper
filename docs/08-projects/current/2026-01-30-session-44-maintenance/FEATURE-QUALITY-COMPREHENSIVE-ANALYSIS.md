# Feature Quality Comprehensive Analysis

**Date:** 2026-01-30
**Session:** 44 (Continuation)
**Focus:** Root cause analysis, feature health audit, prevention mechanisms

---

## Executive Summary

After comprehensive investigation using 5 parallel agents, we found:

1. **The fatigue bug was preventable** - lacked range validation on write
2. **6 other features have issues** - team_win_pct, back_to_back, usage_spike_score, vegas lines, pace_score, shot_zone_mismatch_score
3. **Validation exists but is POST-storage** - we detect problems after they're already in BigQuery
4. **Prediction tracking exists** - but we don't surface it in daily validation

---

## Part 1: How The Fatigue Bug Happened

### Timeline

| Date | Event |
|------|-------|
| Jan 18 | Last correct data (avg_fatigue = 95.29) |
| Jan 25 | Commit ef1b38a4 deployed - bug introduced |
| Jan 25-30 | 5 days of broken data (65% zeros, negatives appeared) |
| Jan 30 | Bug discovered and fixed (commit cec08a99) |

### Root Cause

**Semantic confusion in the refactor:**

```python
# BEFORE refactor - inline calculation
fatigue_score = self._calculate_fatigue_score(player_row)  # Returns 0-100
fatigue_adj = self._fatigue_score_to_adjustment(fatigue_score)  # Returns -5 to 0
record['fatigue_score'] = fatigue_score  # Stored 0-100 ✓

# AFTER refactor - extracted to factor class
class FatigueFactor:
    def calculate(self, ...):
        """Calculate fatigue adjustment (-5.0 to 0.0)."""  # <-- Returns ADJUSTMENT
        fatigue_score = self._calculate_fatigue_score(...)
        return self._score_to_adjustment(fatigue_score)  # Returns -5 to 0!

# Processor then stored the wrong value
fatigue_score = int(factor_scores['fatigue_score'])  # This is -5 to 0, NOT 0-100!
record['fatigue_score'] = fatigue_score  # Stored adjustment, not score ✗
```

### Why It Wasn't Caught

1. **Massive commit** - 48 files, 6,265 insertions, bundled unrelated changes
2. **No range validation on write** - code didn't check 0 <= fatigue_score <= 100
3. **Silent failure** - no error, just wrong values
4. **Delayed detection** - only noticed when model performance degraded

### The Fix Applied

```python
# Fixed: Use context which has correct 0-100 value
fatigue_score = factor_contexts['fatigue_context_json']['final_score']
```

---

## Part 2: Feature Health Audit Results

### CRITICAL Issues (Broken Features)

| Feature | Issue | Days Affected | Impact |
|---------|-------|---------------|--------|
| **fatigue_score** | 65% zeros, negatives | Jan 25+ | HIGH - Used in all prediction systems |
| **vegas_opening_line** | 67-100% zeros | Jan 30-31 | HIGH - Key prediction input |
| **vegas_points_line** | 67-100% zeros | Jan 30-31 | HIGH - Key prediction input |

### HIGH Priority Issues (Always Wrong)

| Feature | Issue | Days Affected | Impact |
|---------|-------|---------------|--------|
| **team_win_pct** | Always 0.5, no variance | All days | MEDIUM - Team context missing |
| **back_to_back** | Always 0 | All days | MEDIUM - Fatigue signal lost |
| **usage_spike_score** | Always 0 | All days | LOW - Deferred factor |

### MODERATE Issues (Intermittent Failures)

| Feature | Issue | Days Affected |
|---------|-------|---------------|
| **pace_score** | 100% zeros | Jan 24, 29, 31 |
| **shot_zone_mismatch_score** | 100% zeros | Jan 23, 24, 29, 31 |
| **rest_advantage** | 99% zeros | Jan 26 only |
| **games_in_last_7_days** | 87% zeros | Jan 26 only |

### Day-by-Day fatigue_score Breakdown

```
Jan 18: mean=95.2, zeros=0%    ✓ Correct
Jan 19: mean=94.8, zeros=0%    ✓ Correct
Jan 20: mean=95.1, zeros=0%    ✓ Correct
...
Jan 24: mean=50.0, zeros=0%    ⚠️ All stuck at 50
Jan 25: mean=12.4, zeros=56%   ✗ BROKEN
Jan 26: mean=0.7,  zeros=88%   ✗ BROKEN
Jan 27: mean=0.5,  zeros=100%  ✗ BROKEN
Jan 28: mean=0.4,  zeros=99%   ✗ BROKEN
Jan 29: mean=50.0, zeros=0%    ⚠️ All stuck at 50
Jan 30: mean=5.2,  zeros=78%   ✗ BROKEN
```

---

## Part 3: What Validation Exists Today

### Current Validation Layers

| Layer | File | What It Does | When It Runs |
|-------|------|--------------|--------------|
| Range Validation | `predictions/worker/data_loaders.py` | Validates feature ranges | At prediction time |
| Factor Validator | `validation/validators/precompute/player_composite_factors_validator.py` | Validates bounds 0-100 | Post-storage |
| ML Feature Validator | `validation/validators/precompute/ml_feature_store_validator.py` | Comprehensive bounds | Post-storage |
| Drift Detector | `shared/validation/feature_drift_detector.py` | Monitors distributions | On-demand |
| Pre-commit Hooks | `.pre-commit-hooks/validate_schema_fields.py` | Schema consistency | Before commit |

### The Gap: No PRE-WRITE Validation

```
Current flow:
  Calculate → Write to BigQuery → Validate (POST-storage) → Alert
                    ↓
              Bad data already in!

Needed flow:
  Calculate → Validate (PRE-write) → Reject if bad → Write to BigQuery
                    ↓
              Bad data blocked!
```

---

## Part 4: Prediction-Feature Tracking (Already Exists!)

### What's Already Tracked Per Prediction

The system ALREADY stores feature quality metadata in `player_prop_predictions`:

```sql
-- These fields exist in player_prop_predictions
completeness_percentage FLOAT64       -- 0-100% of expected data present
is_production_ready BOOLEAN           -- TRUE if completeness >= 90%
data_quality_issues ARRAY<STRING>     -- Specific issues detected
backfill_bootstrap_mode BOOLEAN       -- TRUE if early season
missing_games_count INT64             -- How many games missing
```

### Query to Find Predictions Made With Bad Data

```sql
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNTIF(completeness_percentage < 90) as low_completeness,
  COUNTIF(is_production_ready = FALSE) as not_prod_ready,
  COUNTIF(ARRAY_LENGTH(data_quality_issues) > 0) as has_issues
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-01-25'
GROUP BY game_date
ORDER BY game_date;
```

### The Gap: Not Surfaced in Daily Validation

We track this data but don't show it in `/validate-daily`. Adding this would immediately surface feature quality issues.

---

## Part 5: Prevention Mechanisms (Proposed)

### Solution 1: Pre-Write Range Validation

Add validation in the processor BEFORE writing to BigQuery:

```python
# In player_composite_factors_processor.py
FEATURE_RANGES = {
    'fatigue_score': (0, 100),
    'shot_zone_mismatch_score': (-10, 10),
    'pace_score': (-5, 5),
    'usage_spike_score': (-5, 5),
}

def _validate_before_write(self, record: dict) -> List[str]:
    """Validate all features are in expected ranges BEFORE writing."""
    violations = []

    for feature, (min_val, max_val) in FEATURE_RANGES.items():
        value = record.get(feature)
        if value is not None:
            if value < min_val or value > max_val:
                violations.append(f"{feature}={value} outside [{min_val}, {max_val}]")

    if violations:
        # Log and optionally REJECT the write
        logger.error(f"Feature validation failed: {violations}")
        # Option A: Reject write entirely
        # Option B: Clamp values to valid ranges
        # Option C: Flag but allow write

    return violations
```

**Impact:** Would have caught fatigue bug IMMEDIATELY on Jan 25.

### Solution 2: Daily Feature Health Table

Create a table that tracks feature statistics daily:

```sql
CREATE TABLE nba_monitoring.feature_health_daily (
  report_date DATE NOT NULL,
  feature_name STRING NOT NULL,

  -- Distribution stats
  mean FLOAT64,
  stddev FLOAT64,
  min_value FLOAT64,
  max_value FLOAT64,
  p5 FLOAT64,
  p50 FLOAT64,
  p95 FLOAT64,

  -- Quality metrics
  null_count INT64,
  zero_count INT64,
  negative_count INT64,
  out_of_range_count INT64,
  total_count INT64,

  -- Drift detection
  mean_vs_7d_baseline FLOAT64,  -- % change from 7-day baseline
  zero_pct_vs_7d_baseline FLOAT64,

  -- Status
  health_status STRING,  -- 'healthy', 'warning', 'critical'
  alert_reasons ARRAY<STRING>
);
```

**Populate daily with:**

```sql
INSERT INTO nba_monitoring.feature_health_daily
SELECT
  CURRENT_DATE() as report_date,
  'fatigue_score' as feature_name,
  AVG(fatigue_score) as mean,
  STDDEV(fatigue_score) as stddev,
  MIN(fatigue_score) as min_value,
  MAX(fatigue_score) as max_value,
  APPROX_QUANTILES(fatigue_score, 100)[OFFSET(5)] as p5,
  APPROX_QUANTILES(fatigue_score, 100)[OFFSET(50)] as p50,
  APPROX_QUANTILES(fatigue_score, 100)[OFFSET(95)] as p95,
  COUNTIF(fatigue_score IS NULL) as null_count,
  COUNTIF(fatigue_score = 0) as zero_count,
  COUNTIF(fatigue_score < 0) as negative_count,
  COUNTIF(fatigue_score < 0 OR fatigue_score > 100) as out_of_range_count,
  COUNT(*) as total_count,
  -- Calculate drift vs 7-day baseline...
FROM nba_precompute.player_composite_factors
WHERE game_date = CURRENT_DATE() - 1
```

**Impact:** Would have caught fatigue bug within 24 hours via zero_count spike.

### Solution 3: Enhanced Daily Validation Skill

Update `/validate-daily` to include:

```bash
=== Feature Health Check ===
Feature           | Mean   | Zeros | Status
------------------|--------|-------|--------
fatigue_score     | -0.07  | 65.2% | 🔴 CRITICAL
vegas_points_line | 6.75   | 27.7% | 🟡 WARNING
team_win_pct      | 0.50   | 0.0%  | 🟡 WARNING (no variance)
back_to_back      | 0.00   | 100%  | 🟡 WARNING (always zero)
pace_score        | 0.45   | 29.9% | ✅ OK
shot_zone_mismatch| 1.23   | 15.2% | ✅ OK

=== Predictions with Quality Issues ===
Date       | Total | Low Quality | Not Prod Ready
-----------|-------|-------------|---------------
2026-01-30 | 141   | 23 (16%)    | 45 (32%)
2026-01-29 | 156   | 18 (12%)    | 38 (24%)
```

### Solution 4: Feature Quality Flag in Predictions

Add explicit quality classification:

```sql
-- Add to player_prop_predictions schema
feature_quality_tier STRING  -- 'gold', 'silver', 'bronze', 'suspect'

-- Classification logic:
CASE
  WHEN completeness_percentage >= 95
       AND is_production_ready = TRUE
       AND ARRAY_LENGTH(data_quality_issues) = 0 THEN 'gold'
  WHEN completeness_percentage >= 90 THEN 'silver'
  WHEN completeness_percentage >= 80 THEN 'bronze'
  ELSE 'suspect'
END as feature_quality_tier
```

**Impact:** Every prediction would be tagged, making it easy to filter/analyze.

### Solution 5: Pre-Commit Feature Test

Add a pre-commit hook that runs feature validation on test data:

```python
# .pre-commit-hooks/validate_feature_ranges.py
def test_feature_ranges():
    """Run processor on sample data and verify output ranges."""

    # Process a known test case
    result = process_player(TEST_PLAYER_DATA)

    # Assert ranges
    assert 0 <= result['fatigue_score'] <= 100, \
        f"fatigue_score {result['fatigue_score']} out of range"
    assert -10 <= result['shot_zone_mismatch_score'] <= 10
    # ... etc
```

**Impact:** Would have caught fatigue bug BEFORE it was committed.

---

## Part 6: Implementation Priority

### Immediate (This Session)

1. ✅ Fix applied (commit cec08a99) - needs deployment
2. Add pre-write validation to processor
3. Update `/validate-daily` to show feature health

### Short-Term (This Week)

4. Create `feature_health_daily` table
5. Add scheduled query to populate daily
6. Add feature quality tier to predictions

### Medium-Term (Next Sprint)

7. Add pre-commit feature range tests
8. Create alerting on feature health degradation
9. Build dashboard for feature monitoring

---

## Part 7: Feature-Specific Expected Ranges

For reference when implementing validation:

| Feature | Expected Range | Notes |
|---------|---------------|-------|
| fatigue_score | 0-100 | Higher = more rested |
| shot_zone_mismatch_score | -10 to +10 | Positive = favorable matchup |
| pace_score | -5 to +5 | Difference from player's normal |
| usage_spike_score | -5 to +5 | Change in expected usage |
| vegas_points_line | 0-60 | Typical NBA scoring range |
| vegas_opening_line | 0-60 | Same as points line |
| team_win_pct | 0-1 | Should vary by team |
| back_to_back | 0 or 1 | Binary flag |
| rest_advantage | -3 to +3 | Days rest difference |
| games_in_last_7_days | 1-4 | Typical range |
| points_avg_season | 0-60 | Season average |
| points_avg_last_5 | 0-80 | Can spike higher |
| points_avg_last_10 | 0-80 | Can spike higher |

---

## Part 8: Queries for Immediate Use

### 1. Check All Feature Health (Run Now)

```sql
SELECT
  'fatigue_score' as feature,
  ROUND(AVG(fatigue_score), 2) as mean,
  COUNTIF(fatigue_score = 0) as zeros,
  COUNTIF(fatigue_score < 0) as negatives,
  COUNTIF(fatigue_score > 100) as over_max,
  COUNT(*) as total
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25'
UNION ALL
SELECT
  'pace_score', ROUND(AVG(pace_score), 2),
  COUNTIF(pace_score = 0), COUNTIF(pace_score < -5), COUNTIF(pace_score > 5), COUNT(*)
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25'
UNION ALL
SELECT
  'shot_zone_mismatch_score', ROUND(AVG(shot_zone_mismatch_score), 2),
  COUNTIF(shot_zone_mismatch_score = 0), COUNTIF(shot_zone_mismatch_score < -10),
  COUNTIF(shot_zone_mismatch_score > 10), COUNT(*)
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25';
```

### 2. Check Predictions with Bad Features

```sql
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNTIF(completeness_percentage < 90) as low_completeness,
  COUNTIF(is_production_ready = FALSE) as not_prod_ready,
  ROUND(AVG(completeness_percentage), 1) as avg_completeness
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-01-25'
GROUP BY game_date
ORDER BY game_date;
```

### 3. Track Feature Trends Over Time

```sql
SELECT
  game_date,
  ROUND(AVG(fatigue_score), 2) as avg_fatigue,
  ROUND(100.0 * COUNTIF(fatigue_score = 0) / COUNT(*), 1) as pct_zeros,
  ROUND(100.0 * COUNTIF(fatigue_score < 0) / COUNT(*), 1) as pct_negative
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-18'
GROUP BY game_date
ORDER BY game_date;
```

---

## Summary

The fatigue bug exposed a systemic weakness: **we validate features after they're stored, not before**.

The investigation found:
1. 1 critical bug (fatigue) + 5 other features with issues
2. Validation exists but runs too late
3. Prediction tracking exists but isn't surfaced

The solution is layered defense:
1. **Pre-write validation** - Reject bad data before storage
2. **Daily health tracking** - Detect drift within 24 hours
3. **Enhanced validation skill** - Surface issues to operators
4. **Feature quality flags** - Mark predictions made with suspect data

---

*Analysis completed 2026-01-30 Session 44*
