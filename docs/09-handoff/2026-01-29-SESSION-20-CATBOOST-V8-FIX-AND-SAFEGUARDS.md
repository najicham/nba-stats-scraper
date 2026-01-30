# Session 20 Handoff - CatBoost V8 Fix and Comprehensive Safeguards

**Date:** 2026-01-29
**Author:** Claude Opus 4.5
**Status:** ROOT CAUSE IDENTIFIED - READY FOR IMPLEMENTATION
**Priority:** CRITICAL

---

## Executive Summary

This session identified the **root cause** of the CatBoost V8 regression that caused 21 days of bad predictions (Jan 8-29). The model predicted 60+ points for players scoring 20-30 because the worker doesn't pass Vegas/opponent/PPM features as separate parameters, causing fallbacks to wrong default values.

**Key Finding:** The `_prepare_feature_vector()` method expects `vegas_line`, `opponent_avg`, `ppm_avg_last_10` as function parameters, but the worker only passes the features dict. This causes features 25-32 to use wrong fallback values.

---

## Root Cause Analysis

### The Bug

**Location:** `predictions/worker/prediction_systems/catboost_v8.py:_prepare_feature_vector()`

**Problem:** The method expects these as function parameters:
```python
def predict(
    player_lookup, features, betting_line,
    vegas_line=None,        # Never passed by worker!
    vegas_opening=None,     # Never passed by worker!
    opponent_avg=None,      # Never passed by worker!
    games_vs_opponent=0,    # Never passed by worker!
    minutes_avg_last_10=None,  # Never passed by worker!
    ppm_avg_last_10=None,   # Never passed by worker!
)
```

**But worker calls:**
```python
catboost.predict(
    player_lookup=player_lookup,
    features=features,
    betting_line=line_value
    # No vegas_line, opponent_avg, etc.!
)
```

### Impact on Features

| Feature | Index | Production Uses | Should Be | Error |
|---------|-------|-----------------|-----------|-------|
| vegas_line | 25 | season_avg (30.1) | 29.68 | -0.4 |
| vegas_opening | 26 | season_avg (30.1) | 31.50 | -1.4 |
| vegas_line_move | 27 | 0.0 | -1.82 | +1.8 |
| **has_vegas_line** | 28 | **0.0** | **1.0** | **-1.0** |
| opponent_avg | 29 | season_avg (30.1) | 25.0 | +5.1 |
| games_vs_opponent | 30 | 0.0 | 14.0 | -14.0 |
| minutes_avg | 31 | 35.0 (from dict) | 35.0 | OK |
| **ppm_avg** | 32 | **0.4** | **0.868** | **-0.47** |

### Result

Tested with Anthony Edwards' Jan 28 features:
- **Production prediction:** 64.48 points → clamped to 60
- **Correct prediction:** 34.96 points
- **Error:** +29.52 points!

---

## Implementation Tasks

### Phase 1: Critical Fixes (P0 - Day 1)

#### Task 1.1: Fix Feature Dict Fallback
**File:** `predictions/worker/prediction_systems/catboost_v8.py`
**Lines:** 382-392

**Change FROM:**
```python
# Vegas features (4) - use season avg as fallback
vegas_line if vegas_line is not None else season_avg,
vegas_opening if vegas_opening is not None else season_avg,
(vegas_line - vegas_opening) if vegas_line and vegas_opening else 0,
1.0 if vegas_line is not None else 0.0,
# Opponent history (2)
opponent_avg if opponent_avg is not None else season_avg,
float(games_vs_opponent),
# Minutes/PPM history (2)
minutes_avg_last_10 if minutes_avg_last_10 is not None else features.get('minutes_avg_last_10', 25),
ppm_avg_last_10 if ppm_avg_last_10 is not None else 0.4,
```

**Change TO:**
```python
# Vegas features (4) - use features dict, then season avg as fallback
vegas_line if vegas_line is not None else features.get('vegas_points_line', season_avg),
vegas_opening if vegas_opening is not None else features.get('vegas_opening_line', season_avg),
(vegas_line - vegas_opening) if vegas_line and vegas_opening else features.get('vegas_line_move', 0),
1.0 if (vegas_line is not None or features.get('vegas_points_line') is not None) else 0.0,
# Opponent history (2)
opponent_avg if opponent_avg is not None else features.get('avg_points_vs_opponent', season_avg),
float(games_vs_opponent) if games_vs_opponent else features.get('games_vs_opponent', 0.0),
# Minutes/PPM history (2)
minutes_avg_last_10 if minutes_avg_last_10 is not None else features.get('minutes_avg_last_10', 25),
ppm_avg_last_10 if ppm_avg_last_10 is not None else features.get('ppm_avg_last_10', 0.4),
```

**Test Command:**
```bash
python3 << 'EOF'
import catboost as cb
import numpy as np
model = cb.CatBoostRegressor()
model.load_model("models/catboost_v8_33features_20260108_211817.cbm")

# Anthony Edwards correct features
features = np.array([
    33.6, 31.2, 30.1, 10.15, 3.0, 0.0, -2.7, -0.1, 0.0, 2.0, 0.0, 2.0, 0.0,
    110.81, 103.74, 0.0, 0.0, 0.0, 0.1736, 0.1806, 0.6458, 0.1193, 94.9, 108.06, 0.5,
    29.68, 31.5, -1.82, 1.0, 25.0, 14.0, 35.0, 0.868
]).reshape(1, -1)
print(f"Prediction: {model.predict(features)[0]:.2f} (should be ~35)")
EOF
```

#### Task 1.2: Add Feature Source Logging
**File:** `predictions/worker/prediction_systems/catboost_v8.py`

Add logging to track where each feature value came from:
```python
# Log when using fallback values
if vegas_line is None and features.get('vegas_points_line') is None:
    logger.warning(
        "feature_using_default",
        extra={
            "feature": "vegas_points_line",
            "default_value": season_avg,
            "player_lookup": player_lookup,
        }
    )
```

#### Task 1.3: Add Extreme Prediction Warnings
**File:** `predictions/worker/prediction_systems/catboost_v8.py`

After model.predict(), before clamping:
```python
raw_prediction = float(self.model.predict(feature_vector)[0])

if raw_prediction >= 55 or raw_prediction <= 5:
    logger.warning(
        "extreme_prediction_detected",
        extra={
            "player_lookup": player_lookup,
            "raw_prediction": raw_prediction,
            "vegas_line": features.get('vegas_points_line'),
            "season_avg": features.get('points_avg_season'),
        }
    )

predicted_points = max(0, min(60, raw_prediction))
```

#### Task 1.4: Deploy and Verify
```bash
# Build and deploy
docker build -t us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest -f predictions/worker/Dockerfile .
docker push us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest
gcloud run deploy prediction-worker --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest --region=us-west2

# Verify predictions are reasonable
bq query --use_legacy_sql=false "
SELECT game_date, player_lookup, predicted_points, current_points_line
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8' AND game_date = CURRENT_DATE()
ORDER BY predicted_points DESC LIMIT 10
"
```

---

### Phase 2: Training Pipeline Enhancements (P1 - Week 1)

#### Task 2.1: Capture Feature Statistics During Training
**File:** `ml/train_final_ensemble_v8.py`

Add after line 147 (after preparing features):
```python
# Calculate and save feature statistics for production validation
feature_stats = {}
for col in X.columns:
    feature_stats[col] = {
        "mean": float(X[col].mean()),
        "std": float(X[col].std()),
        "min": float(X[col].min()),
        "max": float(X[col].max()),
        "p5": float(X[col].quantile(0.05)),
        "p25": float(X[col].quantile(0.25)),
        "p50": float(X[col].quantile(0.50)),
        "p75": float(X[col].quantile(0.75)),
        "p95": float(X[col].quantile(0.95)),
        "missing_rate": float(X[col].isna().mean()),
    }

stats_path = MODEL_OUTPUT_DIR / f"ensemble_{version}_{timestamp}_feature_stats.json"
with open(stats_path, 'w') as f:
    json.dump(feature_stats, f, indent=2)
print(f"Saved feature statistics to {stats_path}")
```

#### Task 2.2: Create Model Contract Class
**New file:** `ml/model_contract.py`

```python
"""
Model Contract - Defines expected feature names, ranges, and validation rules
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import json
import hashlib

@dataclass
class ModelContract:
    model_id: str
    model_version: str
    feature_names: List[str]
    feature_count: int
    feature_stats: Dict[str, Dict]
    training_date_range: Tuple[str, str]
    training_samples: int
    model_file_hash: str
    created_at: str

    def validate_features(self, features: Dict) -> List[str]:
        """Validate feature values against training statistics"""
        issues = []

        for i, name in enumerate(self.feature_names):
            val = features.get(name)

            if val is None:
                issues.append(f"MISSING: Feature {i} ({name}) not provided")
                continue

            stats = self.feature_stats.get(name, {})

            # Check if outside expected range
            p5, p95 = stats.get('p5'), stats.get('p95')
            if p5 is not None and val < p5:
                issues.append(f"LOW: Feature {i} ({name}) = {val} < p5 ({p5})")
            if p95 is not None and val > p95:
                issues.append(f"HIGH: Feature {i} ({name}) = {val} > p95 ({p95})")

            # Check if > 3 sigma from training mean
            mean, std = stats.get('mean'), stats.get('std')
            if mean and std and std > 0:
                z_score = abs(val - mean) / std
                if z_score > 3:
                    issues.append(f"OUTLIER: Feature {i} ({name}) z={z_score:.1f}")

        return issues

    @classmethod
    def load(cls, path: str) -> 'ModelContract':
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    def save(self, path: str):
        with open(path, 'w') as f:
            json.dump(self.__dict__, f, indent=2)


def get_model_hash(model_path: str) -> str:
    """Calculate SHA256 hash of model file"""
    sha256_hash = hashlib.sha256()
    with open(model_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()
```

#### Task 2.3: Generate Contract During Training
**File:** `ml/train_final_ensemble_v8.py`

Add at the end after saving models:
```python
from ml.model_contract import ModelContract, get_model_hash
from datetime import datetime

contract = ModelContract(
    model_id=f"ensemble_v8_{timestamp}",
    model_version="v8",
    feature_names=all_features,
    feature_count=len(all_features),
    feature_stats=feature_stats,
    training_date_range=("2021-11-01", "2024-06-01"),
    training_samples=len(df),
    model_file_hash=get_model_hash(str(catboost_path)),
    created_at=datetime.now().isoformat(),
)
contract.save(MODEL_OUTPUT_DIR / f"ensemble_v8_{timestamp}_contract.json")
```

---

### Phase 3: Enhanced Logging (P1 - Week 1)

#### Task 3.1: Log All Feature Values
**File:** `predictions/worker/execution_logger.py`

Add to `log_prediction_run()`:
```python
# Add key feature values for debugging
if features:
    log_data['key_features'] = {
        'points_avg_last_5': features.get('points_avg_last_5'),
        'points_avg_season': features.get('points_avg_season'),
        'vegas_points_line': features.get('vegas_points_line'),
        'ppm_avg_last_10': features.get('ppm_avg_last_10'),
        'fatigue_score': features.get('fatigue_score'),
    }
```

#### Task 3.2: Log Per-System Predictions
**File:** `predictions/worker/worker.py`

Add after all systems run (around line 1290):
```python
# Log system predictions for comparison
if system_predictions:
    logger.info(
        "system_predictions_comparison",
        extra={
            "player_lookup": player_lookup,
            "catboost_v8": system_predictions.get('catboost_v8', {}).get('predicted_points'),
            "xgboost_v1": system_predictions.get('xgboost_v1', {}).get('predicted_points'),
            "ensemble_v1_1": system_predictions.get('ensemble_v1_1', {}).get('predicted_points'),
            "moving_average": system_predictions.get('moving_average_baseline_v1', {}).get('predicted_points'),
            "vegas_line": features.get('vegas_points_line'),
        }
    )
```

#### Task 3.3: Log Execution Timing Per System
**File:** `predictions/worker/worker.py`

Wrap each system call with timing:
```python
import time

system_timings = {}

# For CatBoost:
start = time.time()
result = catboost.predict(...)
system_timings['catboost_v8'] = time.time() - start

# At end, log all timings
logger.info("prediction_timing", extra={"timings": system_timings})
```

---

### Phase 4: Feature Store Enhancements (P2 - Week 2)

#### Task 4.1: Add Validation Fields to Schema
**File:** `schemas/bigquery/nba_predictions/ml_feature_store_v2.sql`

Add after existing fields:
```sql
-- Validation tracking
validation_warnings ARRAY<STRING>,
validation_passed BOOLEAN,
features_using_defaults ARRAY<INT64>,

-- Reproducibility
processor_commit_sha STRING,
processor_version STRING,
```

#### Task 4.2: Migrate Schema
```bash
bq query --use_legacy_sql=false "
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS validation_warnings ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS validation_passed BOOLEAN,
ADD COLUMN IF NOT EXISTS features_using_defaults ARRAY<INT64>,
ADD COLUMN IF NOT EXISTS processor_commit_sha STRING
"
```

#### Task 4.3: Update Feature Processor
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

Add validation tracking in `_build_feature_record()`:
```python
# Track which features used defaults
features_using_defaults = []
for i, val in enumerate(features):
    if val is None or (isinstance(val, float) and val == self.DEFAULT_VALUES.get(i)):
        features_using_defaults.append(i)

record['features_using_defaults'] = features_using_defaults
record['validation_passed'] = len(features_using_defaults) < 5  # Allow some defaults
record['processor_commit_sha'] = os.environ.get('GIT_COMMIT_SHA', 'unknown')
```

---

### Phase 5: Daily Monitoring (P2 - Week 2)

#### Task 5.1: Create Daily Quality Check Script
**New file:** `monitoring/daily_prediction_quality.py`

```python
"""
Daily prediction quality checks - run after each game day
"""
from google.cloud import bigquery
from datetime import date, timedelta

def check_daily_quality(game_date: date) -> dict:
    client = bigquery.Client()

    checks = {}

    # Check 1: Extreme predictions
    query = f"""
    SELECT COUNT(*) as count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
      AND (predicted_points >= 55 OR predicted_points <= 5)
    """
    result = list(client.query(query))[0]
    checks['extreme_predictions'] = {
        'count': result.count,
        'status': 'ERROR' if result.count > 10 else 'OK',
    }

    # Check 2: Clamped at 60
    query = f"""
    SELECT COUNT(*) as count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
      AND predicted_points = 60.0
    """
    result = list(client.query(query))[0]
    checks['clamped_predictions'] = {
        'count': result.count,
        'status': 'ERROR' if result.count > 5 else 'OK',
    }

    # Check 3: Average diff from Vegas
    query = f"""
    SELECT AVG(ABS(predicted_points - current_points_line)) as avg_diff
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
      AND current_points_line IS NOT NULL
    """
    result = list(client.query(query))[0]
    checks['vegas_diff'] = {
        'avg_diff': result.avg_diff,
        'status': 'WARNING' if result.avg_diff > 8 else 'OK',
    }

    return checks

if __name__ == '__main__':
    import sys
    game_date = date.today() - timedelta(days=1)
    if len(sys.argv) > 1:
        game_date = date.fromisoformat(sys.argv[1])

    results = check_daily_quality(game_date)
    for check, data in results.items():
        status = data.pop('status')
        print(f"[{status}] {check}: {data}")
```

#### Task 5.2: Add to Daily Validation Skill
**File:** Update `/validate-daily` skill to include prediction quality checks

---

### Phase 6: Model Metadata in BigQuery (P2 - Week 3)

#### Task 6.1: Create Model Registry Table
**New file:** `schemas/bigquery/nba_predictions/model_registry.sql`

```sql
CREATE TABLE IF NOT EXISTS nba_predictions.model_registry (
    model_id STRING NOT NULL,
    model_version STRING NOT NULL,
    model_type STRING,  -- 'catboost', 'xgboost', 'ensemble'

    -- Training metadata
    training_start_date DATE,
    training_end_date DATE,
    training_samples INT64,
    training_mae FLOAT64,

    -- Feature contract
    feature_names ARRAY<STRING>,
    feature_count INT64,
    feature_stats JSON,  -- Mean, std, min, max per feature

    -- Versioning
    model_file_hash STRING,
    model_file_path STRING,

    -- Lifecycle
    status STRING,  -- 'development', 'challenger', 'champion', 'retired'
    promoted_at TIMESTAMP,
    retired_at TIMESTAMP,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    created_by STRING,
)
PARTITION BY DATE(created_at)
```

#### Task 6.2: Register Models During Training
**File:** `ml/train_final_ensemble_v8.py`

Add model registration to BigQuery:
```python
def register_model(model_id, model_version, feature_stats, training_info):
    from google.cloud import bigquery
    client = bigquery.Client()

    row = {
        'model_id': model_id,
        'model_version': model_version,
        'model_type': 'ensemble',
        'training_start_date': training_info['start_date'],
        'training_end_date': training_info['end_date'],
        'training_samples': training_info['samples'],
        'training_mae': training_info['mae'],
        'feature_names': list(feature_stats.keys()),
        'feature_count': len(feature_stats),
        'feature_stats': json.dumps(feature_stats),
        'model_file_hash': get_model_hash(...),
        'status': 'development',
        'created_by': 'training_script',
    }

    client.insert_rows_json('nba_predictions.model_registry', [row])
```

---

## Validation Queries

### Verify Fix Worked
```sql
-- After deploying fix, predictions should be reasonable
SELECT
  game_date,
  COUNT(*) as total,
  SUM(CASE WHEN predicted_points >= 55 THEN 1 ELSE 0 END) as extreme_high,
  SUM(CASE WHEN predicted_points = 60 THEN 1 ELSE 0 END) as clamped_at_60,
  AVG(predicted_points) as avg_prediction,
  AVG(current_points_line) as avg_vegas_line
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND game_date >= CURRENT_DATE() - 3
GROUP BY game_date
ORDER BY game_date DESC
```

### Compare Before/After Fix
```sql
-- Compare Jan 28 (before fix) vs after fix date
SELECT
  game_date,
  AVG(predicted_points - current_points_line) as avg_bias,
  AVG(ABS(predicted_points - current_points_line)) as avg_abs_diff
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND current_points_line IS NOT NULL
  AND game_date IN ('2026-01-28', CURRENT_DATE())
GROUP BY game_date
```

---

## Files Modified/Created Summary

| File | Action | Description |
|------|--------|-------------|
| `predictions/worker/prediction_systems/catboost_v8.py` | MODIFY | Fix feature dict fallback, add logging |
| `predictions/worker/worker.py` | MODIFY | Add per-system timing and prediction logging |
| `predictions/worker/execution_logger.py` | MODIFY | Add feature value logging |
| `ml/train_final_ensemble_v8.py` | MODIFY | Capture feature statistics, register model |
| `ml/model_contract.py` | CREATE | Model contract class |
| `monitoring/daily_prediction_quality.py` | CREATE | Daily quality checks |
| `schemas/bigquery/nba_predictions/model_registry.sql` | CREATE | Model metadata table |
| `schemas/bigquery/nba_predictions/ml_feature_store_v2.sql` | MODIFY | Add validation fields |

---

## Testing Plan

1. **Local Test** - Run prediction with Anthony Edwards features, verify ~35 points
2. **Staging Deploy** - Deploy to staging, run predictions, verify no extreme values
3. **Production Deploy** - Deploy, monitor logs for warnings
4. **Post-Deploy Validation** - Run daily quality check, verify no errors

---

## Commits to Make

1. `fix: Read Vegas/opponent/PPM features from dict, not params`
2. `feat: Add feature source and extreme prediction logging`
3. `feat: Capture feature statistics during training`
4. `feat: Add model contract class for validation`
5. `feat: Add daily prediction quality checks`
6. `feat: Add model registry table for tracking`

---

## Related Documentation

- **Root Cause Analysis:** `docs/08-projects/current/grading-validation/2026-01-29-catboost-v8-root-cause-identified.md`
- **Comprehensive Safeguards Plan:** `docs/08-projects/current/grading-validation/2026-01-29-comprehensive-safeguards-plan.md`
- **Champion-Challenger Framework:** `docs/08-projects/current/ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md`

---

## Session Summary

### What Was Done
- Identified root cause of CatBoost V8 regression
- Verified locally that fix produces correct predictions (34.96 vs 60)
- Created comprehensive safeguards plan
- Documented all implementation tasks

### What Remains
- [ ] Implement P0 fixes (feature dict fallback, logging, warnings)
- [ ] Deploy and verify fix
- [ ] Implement P1 enhancements (training stats, model contracts, logging)
- [ ] Implement P2 enhancements (schema updates, daily monitoring, model registry)

---

*Created: 2026-01-29*
*Author: Claude Opus 4.5*
