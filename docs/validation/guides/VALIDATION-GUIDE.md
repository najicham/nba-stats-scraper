# Validation Framework - Complete User Guide

**Purpose**: End-to-end guide for using the NBA Stats Scraper validation framework
**Audience**: Developers and operators
**Last Updated**: January 4, 2026

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Phase-by-Phase Validation](#phase-by-phase-validation)
4. [Common Workflows](#common-workflows)
5. [Understanding Results](#understanding-results)
6. [Troubleshooting](#troubleshooting)

---

## Overview

The validation framework ensures data quality across the entire NBA stats pipeline:
- Validates data completeness and correctness
- Detects quality degradation
- Enforces critical feature thresholds
- Prevents bad data from reaching ML models

---

## Quick Start

### Validate a Backfill

```bash
# 1. Navigate to project root
cd /home/naji/code/nba-stats-scraper

# 2. Check if backfill complete
ps aux | grep backfill | grep -v grep

# 3. Run validation (example: Phase 2)
./scripts/validation/validate_player_summary.sh \
  --start-date 2024-05-01 \
  --end-date 2026-01-02 \
  --config scripts/config/backfill_thresholds.yaml

# 4. Check exit code
if [ $? -eq 0 ]; then
  echo "✅ PASS"
else
  echo "❌ FAIL"
fi
```

### Validate with Python

```python
from shared.validation.validators.phase3_validator import Phase3Validator
from datetime import date

# Initialize
validator = Phase3Validator()

# Validate a single date
result = validator.validate_table(
    table_name='player_game_summary',
    game_date=date(2025, 12, 25),
    expected_scope='all_rostered'
)

# Check results
if result.passes_validation:
    print(f"✅ PASS: {result.coverage_pct}% coverage")
else:
    print(f"❌ FAIL: {result.issues}")
```

---

## Phase-by-Phase Validation

### Phase 1: GCS Raw Files

**What**: Validates JSON files in `gs://nba-scraped-data/`

**Shell Script**:
```bash
./scripts/validation/validate_gcs_files.sh \
  --date 2025-12-25 \
  --bucket nba-scraped-data
```

**Python**:
```python
from shared.validation.validators.phase1_validator import Phase1Validator

validator = Phase1Validator()
result = validator.validate_date(date(2025, 12, 25))

print(f"Files found: {result.files_found}")
print(f"Critical sources: {result.critical_sources_present}")
```

**Pass Criteria**:
- ✅ All critical source files present
- ✅ File sizes reasonable (>100 bytes)
- ✅ JSON parseable

---

### Phase 2: Raw BigQuery Data

**What**: Validates `nba_raw` dataset tables

**Shell Script**:
```bash
./scripts/validation/validate_raw_data.sh \
  --start-date 2024-05-01 \
  --end-date 2026-01-02 \
  --table nbac_gamebook_player_stats
```

**Python**:
```python
from shared.validation.validators.phase2_validator import Phase2Validator

validator = Phase2Validator()
result = validator.validate_table(
    table_name='nbac_gamebook_player_stats',
    game_date=date(2025, 12, 25)
)

print(f"Records: {result.record_count}")
print(f"Fallback used: {result.fallback_used}")
```

**Pass Criteria**:
- ✅ Expected record counts
- ✅ Fallback coverage if primary missing
- ✅ No corrupted data

---

### Phase 3: Analytics Tables

**What**: Validates `nba_analytics` dataset (MOST CRITICAL)

**Shell Script**:
```bash
./scripts/validation/validate_player_summary.sh \
  --start-date 2024-05-01 \
  --end-date 2026-01-02 \
  --config scripts/config/backfill_thresholds.yaml
```

**Python**:
```python
from shared.validation.validators.phase3_validator import Phase3Validator

validator = Phase3Validator()
result = validator.validate_date_range(
    table_name='player_game_summary',
    start_date=date(2024, 5, 1),
    end_date=date(2026, 1, 2)
)

print(f"Total records: {result.total_records}")
print(f"minutes_played: {result.feature_coverage['minutes_played']}%")
print(f"usage_rate: {result.feature_coverage['usage_rate']}%")
print(f"Quality: {result.quality_distribution}")
```

**Pass Criteria** (CRITICAL):
- ✅ **minutes_played: ≥99%** (blocks ML training)
- ✅ **usage_rate: ≥95%** (blocks ML training)
- ✅ shot_zones: ≥40% (2024+), ≥80% (historical)
- ✅ Gold + Silver quality: ≥80%
- ✅ Zero duplicates

---

### Phase 4: Precompute Tables

**What**: Validates `nba_precompute` dataset (bootstrap-aware)

**Shell Script**:
```bash
./scripts/validation/validate_precompute.sh \
  --start-date 2024-10-15 \  # Skip first 14 days (bootstrap)
  --end-date 2026-01-02 \
  --table player_composite_factors
```

**Python**:
```python
from shared.validation.validators.phase4_validator import Phase4Validator

validator = Phase4Validator()
result = validator.validate_table(
    table_name='player_composite_factors',
    game_date=date(2025, 12, 25)
)

print(f"Status: {result.status}")  # May be BOOTSTRAP_SKIP for early season
print(f"Coverage: {result.coverage_pct}%")  # Max ~88%, not 100%
```

**Pass Criteria**:
- ✅ Coverage: ≥88% (accounting for bootstrap)
- ✅ All composite factors populated
- ✅ Value ranges realistic
- ⚠️ First 14 days of season: BOOTSTRAP_SKIP (OK)

**Important**: Maximum coverage is ~88% (not 100%) due to intentional bootstrap period skips.

---

### Phase 5: Predictions

**What**: Validates `nba_predictions` dataset

**Python**:
```python
from shared.validation.validators.phase5_validator import Phase5Validator

validator = Phase5Validator()
result = validator.validate_predictions(
    game_date=date(2025, 12, 25)
)

print(f"Predictions per player: {result.predictions_per_player}")
print(f"Expected systems: {result.expected_systems}")
print(f"Actual systems: {result.actual_systems}")
```

**Pass Criteria**:
- ✅ 5 predictions per active player
- ✅ All expected systems present
- ✅ Quality scores reasonable

---

## Common Workflows

### Workflow 1: After Phase 2 Backfill

```bash
# 1. Wait for backfill to complete
while ps aux | grep -q "player_game_summary_analytics_backfill.py"; do
  echo "Waiting for backfill..."
  sleep 60
done

# 2. Check backfill log
tail -100 logs/player_game_summary_backfill.log | grep -i "summary"

# 3. Run validation
./scripts/validation/validate_player_summary.sh \
  --start-date 2024-05-01 \
  --end-date 2026-01-02

# 4. Make decision
if [ $? -eq 0 ]; then
  echo "✅ Phase 2 validated - ready for Phase 4 or ML training"
else
  echo "❌ Phase 2 validation failed - check logs"
  tail -50 logs/validation_*.log
fi
```

### Workflow 2: Before ML Training

```python
from shared.validation.validators.feature_validator import check_ml_readiness

# Check if training data is ready
result = check_ml_readiness(
    training_start='2021-10-01',
    training_end='2024-05-01',
    required_features=[
        'minutes_played',
        'usage_rate',
        'fg_attempts',
        'three_pt_attempts',
        'points'
    ]
)

if result.ready:
    print("✅ Ready for ML training")
    print(f"Training samples: {result.total_samples}")
    print(f"Feature coverage: {result.feature_coverage}")

    # Proceed with training
    import subprocess
    subprocess.run([
        "PYTHONPATH=.",
        "python",
        "ml/train_real_xgboost.py"
    ], shell=True)
else:
    print("❌ NOT ready for ML training")
    print(f"Missing features: {result.missing_features}")
    print(f"Issues: {result.issues}")
```

### Workflow 3: Daily Health Check

```bash
# Run daily (cron: 0 8 * * 0)
./scripts/monitoring/weekly_pipeline_health.sh

# Validates:
# - Last 7 days of data
# - All phases complete
# - No quality degradation
# - No gaps
```

### Workflow 4: Regression Detection

```python
from shared.validation.validators.regression_detector import RegressionDetector

# Compare new data vs historical baseline
detector = RegressionDetector()
result = detector.detect_regression(
    table='nba_analytics.player_game_summary',
    new_data_range=('2024-05-01', '2026-01-02'),
    baseline_range=('2024-02-01', '2024-04-30'),  # 3 months before
    features=['minutes_played', 'usage_rate', 'paint_attempts']
)

for feature, status in result.items():
    if status.is_regression:
        print(f"❌ REGRESSION: {feature} is {status.delta_pct:+.1f}% worse")
    elif status.is_degradation:
        print(f"⚠️ DEGRADATION: {feature} is {status.delta_pct:+.1f}% worse")
    else:
        print(f"✅ OK: {feature} is {status.delta_pct:+.1f}%")
```

---

## Understanding Results

### Validation Statuses

| Status | Meaning | Action |
|--------|---------|--------|
| `COMPLETE` | All expected data present | ✅ Proceed |
| `PARTIAL` | Some data missing | ⚠️ Investigate, may be OK |
| `MISSING` | No data found | ❌ Check backfill/pipeline |
| `BOOTSTRAP_SKIP` | Expected empty (first 14 days) | ✅ Normal for Phase 4 |
| `NOT_APPLICABLE` | Date not relevant (e.g., All-Star) | ✅ Normal |
| `ERROR` | Validation error | ❌ Check logs |

### Quality Tiers

| Tier | Score | Production Ready | Symbol |
|------|-------|------------------|--------|
| Gold | 95-100 | ✅ Yes | G |
| Silver | 75-94 | ✅ Yes | S |
| Bronze | 50-74 | ✅ Yes | B |
| Poor | 25-49 | ❌ No | P |
| Unusable | 0-24 | ❌ No | U |

**Target**: Gold + Silver ≥80%

### Exit Codes (Shell Scripts)

- `0`: PASS (all criteria met)
- `1`: FAIL (critical criteria not met)
- `2`: WARNING (non-critical issues)

### Python Return Values

```python
@dataclass
class ValidationResult:
    status: ValidationStatus
    passes_validation: bool
    record_count: int
    expected_count: int
    coverage_pct: float
    quality_distribution: Dict[str, int]
    issues: List[str]
    feature_coverage: Dict[str, float]
```

---

## Troubleshooting

### Issue: usage_rate is 0%

**Symptom**:
```
❌ usage_rate: 0.0% (threshold: 95.0%)
```

**Cause**: Phase 1 (team_offense) not run or incomplete

**Solution**:
1. Check if Phase 1 backfill completed
2. Verify `team_offense_game_summary` has data
3. Re-run Phase 2 backfill (depends on Phase 1)

### Issue: minutes_played <99%

**Symptom**:
```
❌ minutes_played: 27.3% (threshold: 99.0%)
```

**Cause**: Bug fix not applied (pd.to_numeric coercion issue)

**Solution**:
1. Verify commit 83d91e2 is deployed
2. Re-run Phase 2 backfill
3. Check for "MM:SS" format parsing

### Issue: Phase 4 coverage only 88%

**Symptom**:
```
⚠️ Coverage: 88.1% (expected: 100%)
```

**Cause**: This is **NORMAL** - bootstrap periods intentionally skipped

**Solution**: No action needed. Maximum possible coverage is ~88%.

### Issue: Duplicates found

**Symptom**:
```
❌ Found 150 duplicate records
```

**Cause**: Backfill run multiple times without cleanup

**Solution**:
```sql
-- Delete duplicates (keep most recent)
DELETE FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE _row_number > 1;  -- Assuming ROW_NUMBER() added
```

### Issue: Shot zones 0% for 2024-2026

**Symptom**:
```
⚠️ paint_attempts: 0.0% (threshold: 40.0%)
```

**Cause**: BigDataBall format change (player_lookup prefix)

**Solution**: Verify commit 390caba deployed (REGEXP_REPLACE fix)

---

## Best Practices

### 1. Always Validate Before Proceeding

```bash
# Don't do this:
./backfill_phase1.sh && ./backfill_phase2.sh

# Do this:
./backfill_phase1.sh
./scripts/validation/validate_phase1.sh
if [ $? -eq 0 ]; then
  ./backfill_phase2.sh
fi
```

### 2. Use Orchestrator for Multi-Phase

```bash
# Let orchestrator handle validation automatically
./scripts/backfill_orchestrator.sh \
  --phase1-pid <PID> \
  --phase1-log logs/phase1.log \
  --phase1-dates "2021-10-19 2026-01-02" \
  --phase2-dates "2024-05-01 2026-01-02"
```

### 3. Check Validation Logs

```bash
# Validation logs are separate from backfill logs
tail -100 logs/validation_player_summary.log
```

### 4. Understand Bootstrap Periods

```python
# Phase 4 validators are bootstrap-aware
from shared.validation.context.schedule_context import is_bootstrap_period

if is_bootstrap_period(date(2024, 10, 22)):  # Within first 14 days
    print("BOOTSTRAP_SKIP is expected")
```

### 5. Compare vs Baseline

```python
# Always compare new data vs historical baseline
from shared.validation.validators.regression_detector import compare_periods

result = compare_periods(
    table='nba_analytics.player_game_summary',
    period1='baseline',  # 3 months before
    period2='new_data',
    features=['minutes_played', 'usage_rate']
)
```

---

## Integration Examples

### Backfill Script Integration

```python
# At end of backfill script
from shared.validation.validators.phase3_validator import Phase3Validator

print("Running validation...")
validator = Phase3Validator()
result = validator.validate_date_range(
    table_name='player_game_summary',
    start_date=args.start_date,
    end_date=args.end_date
)

if not result.passes_validation:
    print(f"❌ Validation failed: {result.issues}")
    sys.exit(1)

print("✅ Validation passed")
```

### ML Training Integration

```python
# Before training
from shared.validation.validators.feature_validator import check_ml_readiness

result = check_ml_readiness(
    training_start='2021-10-01',
    training_end='2024-05-01'
)

if not result.ready:
    raise ValueError(f"Training data not ready: {result.issues}")

# Proceed with training...
```

---

## Reference

### Shell Scripts Location
- `scripts/validation/validate_team_offense.sh`
- `scripts/validation/validate_player_summary.sh`
- `scripts/validation/validate_precompute.sh`
- `scripts/validation/common_validation.sh`

### Python Validators Location
- `shared/validation/validators/phase1_validator.py`
- `shared/validation/validators/phase2_validator.py`
- `shared/validation/validators/phase3_validator.py`
- `shared/validation/validators/phase4_validator.py`
- `shared/validation/validators/phase5_validator.py`
- `shared/validation/validators/feature_validator.py`
- `shared/validation/validators/regression_detector.py`

### Configuration Location
- `scripts/config/backfill_thresholds.yaml`
- `shared/validation/config.py`
- `shared/validation/feature_thresholds.py`

---

**Next**: See [BACKFILL-VALIDATION.md](./BACKFILL-VALIDATION.md) for backfill-specific procedures
