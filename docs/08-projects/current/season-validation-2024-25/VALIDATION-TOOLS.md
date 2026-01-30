# Data Validation Tools Reference

**Created:** 2026-01-30
**Purpose:** Document all validation tools created for catching data quality issues

---

## Overview

This document describes the validation tools created during Sessions 27-30 to catch data quality issues like the L5/L10 bug, DNP voiding problems, and feature drift.

---

## Validation Modules

### 1. Feature Store Validator

**Location:** `shared/validation/feature_store_validator.py`

**Purpose:** Validates ML feature store data integrity

**Checks:**
| Check | What It Catches | Threshold |
|-------|-----------------|-----------|
| L5/L10 Consistency | Data leakage (wrong rolling averages) | >= 95% match |
| Duplicates | Duplicate (player, date) records | 0 |
| Array Integrity | NULL arrays, wrong length, NaN/Inf | 0 |
| Feature Bounds | Values outside reasonable ranges | < 1% violations |
| Prop Line Coverage | Missing or placeholder prop lines | >= 50% coverage |

**Usage:**
```bash
# CLI
python -m shared.validation.feature_store_validator --days 7

# With date range
python -m shared.validation.feature_store_validator \
    --start-date 2025-11-01 --end-date 2025-11-30

# JSON output for automation
python -m shared.validation.feature_store_validator --json --ci
```

**In Code:**
```python
from shared.validation.feature_store_validator import validate_feature_store

result = validate_feature_store(
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 30),
)

if not result.passed:
    print(result.summary)
    # Handle failure
```

---

### 2. Prediction Quality Validator

**Location:** `shared/validation/prediction_quality_validator.py`

**Purpose:** Validates prediction grading integrity

**Checks:**
| Check | What It Catches | Threshold |
|-------|-----------------|-----------|
| DNP Voiding | actual_points=0 incorrectly graded | 0 graded |
| Placeholder Lines | line_value=20.0 being graded | 0 graded |
| Stale Cache | Cache data > 24h old | < 10% stale |
| Player Consistency | Players missing between phases | < 5% mismatch |
| Prediction Bounds | Predictions outside 0-70 range | < 1% outliers |
| Confidence Calibration | High-confidence low-accuracy | >= 52% accuracy |

**Usage:**
```bash
python -m shared.validation.prediction_quality_validator --days 7
```

**In Code:**
```python
from shared.validation.prediction_quality_validator import validate_prediction_quality

result = validate_prediction_quality(days=7)
if not result.passed:
    print(f"Issues: {result.issues}")
```

---

### 3. Cross-Phase Validator

**Location:** `shared/validation/cross_phase_validator.py`

**Purpose:** Validates data consistency across pipeline phases

**Checks:**
| Check | What It Catches | Threshold |
|-------|-----------------|-----------|
| Row Count Consistency | Data lost between phases | < 10% variance |
| Grading Completeness | Predictions not graded | >= 95% graded |
| Player Flow | Players missing in downstream phases | >= 95% complete |

**Usage:**
```bash
python -m shared.validation.cross_phase_validator --days 7
```

**In Code:**
```python
from shared.validation.cross_phase_validator import validate_cross_phase

result = validate_cross_phase(days=7)
print(result.summary)
```

---

### 4. Feature Drift Detector

**Location:** `shared/validation/feature_drift_detector.py`

**Purpose:** Detects feature distribution changes week-over-week

**What It Monitors:**
- Mean changes > 15% = MEDIUM drift
- Mean changes > 30% = HIGH drift
- Mean changes > 50% = CRITICAL drift

**Key Features Monitored (12 by default):**
- points_l5_avg, points_l10_avg
- minutes_l5_avg, minutes_l10_avg
- usage_rate_l5, usage_rate_l10
- opp_def_rating, opp_pace
- season_games_played, career_ppg
- points_variance_l10, line_value

**Usage:**
```bash
# Compare last 7 days to previous 7 days
python -m shared.validation.feature_drift_detector --days 7

# Check all 34 features
python -m shared.validation.feature_drift_detector --all-features

# JSON output
python -m shared.validation.feature_drift_detector --json
```

---

## Pre-Commit Hooks

### Date Comparison Hook

**Location:** `.pre-commit-hooks/check_date_comparisons.py`

**Purpose:** Flags `<=` date patterns that may cause data leakage

**Patterns Flagged:**
- `game_date <= @game_date` (should usually be `<`)
- `cache_date <= @cache_date`
- `ROWS BETWEEN X PRECEDING AND CURRENT ROW`

**Usage:**
```bash
# Manual run
python .pre-commit-hooks/check_date_comparisons.py

# Runs automatically on commit via .pre-commit-config.yaml
```

---

## BigQuery Views

### Daily Validation Summary

**Location:** `schemas/bigquery/predictions/views/v_daily_validation_summary.sql`

**Purpose:** Automated daily validation checks

**Query:**
```sql
-- Check yesterday's validation status
SELECT * FROM `nba_predictions.v_daily_validation_summary`
WHERE check_date = CURRENT_DATE() - 1;

-- Find failures in last 7 days
SELECT * FROM `nba_predictions.v_daily_validation_summary`
WHERE status = 'FAIL'
ORDER BY check_date DESC;
```

**Checks Included:**
- `feature_cache_match` - L5/L10 consistency
- `duplicate_count` - Duplicate records
- `invalid_arrays` - Array integrity
- `nan_inf_count` - NaN/Inf values
- `cache_miss_rate` - Cache lookup success

---

## When to Run Validation

### After Backfill Operations

```bash
# Feature store backfill
python -m shared.validation.feature_store_validator \
    --start-date <backfill-start> --end-date <backfill-end>

# Cross-phase validation
python -m shared.validation.cross_phase_validator \
    --start-date <backfill-start> --end-date <backfill-end>
```

### Daily Monitoring

```bash
# Run all validators for last 7 days
python -m shared.validation.feature_store_validator --days 7
python -m shared.validation.prediction_quality_validator --days 7
python -m shared.validation.cross_phase_validator --days 7
python -m shared.validation.feature_drift_detector --days 7
```

### Before Model Training

```bash
# Ensure training data is clean
python -m shared.validation.feature_store_validator \
    --start-date 2024-11-01 --end-date 2025-06-30 \
    --ci  # Exit code 1 if fails
```

---

## Validation Skill

The `/validate-lineage` skill provides an interactive interface:

```bash
# Feature store validation
/validate-lineage feature-store

# With date range
/validate-lineage feature-store --start-date 2025-11-01 --end-date 2025-11-30

# Interactive mode
/validate-lineage interactive
```

See `.claude/skills/validate-lineage.md` for full documentation.

---

## Alert Thresholds Summary

| Metric | PASS | WARN | FAIL |
|--------|------|------|------|
| L5/L10 match rate | >= 95% | 50-95% | < 50% |
| Duplicates | 0 | - | > 0 |
| Array integrity | 0 invalid | - | > 0 |
| Prediction bounds | < 1% outliers | 1-5% | > 5% |
| Confidence calibration | >= 52% accuracy | < 52% but >= 0 gap | < 52% |
| Row count variance | < 10% | - | >= 10% |
| Grading completeness | >= 95% | 80-95% | < 80% |
| Player flow | >= 95% | 80-95% | < 80% |
| Feature drift | < 15% mean change | 15-30% | > 50% |

---

## Troubleshooting

### "L5/L10 match rate is low"

1. Check if data was created from cache or fallback:
```sql
SELECT data_source, source_daily_cache_rows_found
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = @date
LIMIT 10;
```

2. If `source_daily_cache_rows_found = NULL`, backfill used fallback path

3. Re-run feature store backfill to fix

### "DNP predictions incorrectly graded"

1. Check affected predictions:
```sql
SELECT player_lookup, game_date, actual_points, prediction_correct
FROM `nba_predictions.prediction_accuracy`
WHERE actual_points = 0 AND prediction_correct IS NOT NULL;
```

2. Run grading processor with voiding fix

### "Feature drift detected"

1. Check specific features that drifted:
```python
result = detect_feature_drift(days=7)
for drift in result.drifted_features:
    print(f"{drift.feature_name}: {drift.mean_change_pct:+.1f}%")
```

2. Investigate upstream data sources for changes

---

## Related Documentation

- Handoff: `docs/09-handoff/2026-01-29-VALIDATION-IMPROVEMENTS-PLAN.md`
- Bug investigation: `FEATURE-STORE-BUG-INVESTIGATION.md`
- Skill: `.claude/skills/validate-lineage.md`
