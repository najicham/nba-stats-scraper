# Comprehensive Safeguards and Observability Plan

**Date:** 2026-01-29
**Status:** PLANNING
**Purpose:** Prevent future CatBoost V8-type regressions through systematic safeguards

---

## Executive Summary

The CatBoost V8 regression revealed critical gaps in our validation and observability systems. This document outlines a comprehensive plan to add safeguards at every level of the ML pipeline.

---

## Problem Statement

The CatBoost V8 bug went undetected for **21 days** (Jan 8-29) because:

1. **No feature value logging** - Couldn't see which features were wrong
2. **No training distribution validation** - No baseline to compare against
3. **No prediction anomaly detection** - 60-point predictions weren't flagged
4. **Silent fallbacks** - Wrong values used without warnings
5. **No model-feature contract** - Model expected params, code didn't pass them

---

## Proposed Architecture: Defense in Depth

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         TRAINING TIME                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Feature Statistics Capture                                           │  │
│  │  - Mean, StdDev, Min, Max, P5, P25, P50, P75, P95 per feature        │  │
│  │  - Missing rate, distribution type, outlier thresholds               │  │
│  │  - Save to models/{version}_feature_statistics.json                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Model Contract Generation                                            │  │
│  │  - Required feature names and order                                   │  │
│  │  - Expected value ranges per feature                                  │  │
│  │  - Feature importance weights                                         │  │
│  │  - Save to models/{version}_contract.json                             │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                       FEATURE STORE (BigQuery)                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Enhanced Metadata Fields                                             │  │
│  │  - target_model_versions: ['catboost_v8', 'xgboost_v1']              │  │
│  │  - feature_quality_by_index: [100, 100, 87, 40, ...]                 │  │
│  │  - feature_source_by_index: ['phase4', 'phase4', 'phase3', ...]      │  │
│  │  - suspicious_values: [{'idx': 5, 'val': -5, 'reason': 'negative'}]  │  │
│  │  - processor_commit_sha: 'abc123'                                    │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                       PREDICTION TIME                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Feature Validation Layer (NEW)                                       │  │
│  │  1. Load model contract                                               │  │
│  │  2. Validate all features present                                     │  │
│  │  3. Check values within expected ranges                               │  │
│  │  4. Log warnings for suspicious values                                │  │
│  │  5. Block prediction if critical features invalid                     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Enhanced Logging                                                     │  │
│  │  - Log ALL feature values with each prediction                        │  │
│  │  - Log feature sources (param vs dict vs default)                     │  │
│  │  - Log per-system predictions before ensemble                         │  │
│  │  - Log execution time per system                                      │  │
│  │  - Log model file hash for reproducibility                            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Prediction Anomaly Detection                                         │  │
│  │  - Flag predictions at clamp boundaries (0, 60)                       │  │
│  │  - Flag predictions > 2 std from Vegas line                           │  │
│  │  - Flag when model disagrees with ensemble by > 10 points             │  │
│  │  - Alert if > 5% of daily predictions are extreme                     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                       POST-PREDICTION MONITORING                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Daily Health Checks                                                  │  │
│  │  - Prediction distribution analysis (histogram)                       │  │
│  │  - Feature drift detection vs training baseline                       │  │
│  │  - System agreement metrics                                           │  │
│  │  - MAE trend monitoring                                               │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Immediate Fixes (P0 - This Week)

### 1.1 Fix the Root Cause Bug

**File:** `predictions/worker/prediction_systems/catboost_v8.py`

```python
# In _prepare_feature_vector(), change:

# FROM (current - uses params that are never passed):
vegas_line if vegas_line is not None else season_avg,

# TO (reads from features dict):
vegas_line if vegas_line is not None else features.get('vegas_points_line', season_avg),
```

**Full fix for features 25-32:**
```python
# Vegas features (4)
vegas_line if vegas_line is not None else features.get('vegas_points_line', season_avg),
vegas_opening if vegas_opening is not None else features.get('vegas_opening_line', season_avg),
(vegas_line - vegas_opening) if vegas_line and vegas_opening else features.get('vegas_line_move', 0),
1.0 if vegas_line is not None else (1.0 if features.get('vegas_points_line') is not None else 0.0),

# Opponent history (2)
opponent_avg if opponent_avg is not None else features.get('avg_points_vs_opponent', season_avg),
float(games_vs_opponent) if games_vs_opponent else features.get('games_vs_opponent', 0.0),

# Minutes/PPM (2)
minutes_avg_last_10 if minutes_avg_last_10 is not None else features.get('minutes_avg_last_10', 25),
ppm_avg_last_10 if ppm_avg_last_10 is not None else features.get('ppm_avg_last_10', 0.4),
```

### 1.2 Add Feature Source Logging

**File:** `predictions/worker/prediction_systems/catboost_v8.py`

```python
def _prepare_feature_vector(...) -> Tuple[Optional[np.ndarray], Dict[str, str]]:
    """Returns (feature_vector, feature_sources_dict)"""

    feature_sources = {}

    # Track where each feature came from
    def get_with_source(idx: int, param_val, dict_key: str, default_val):
        if param_val is not None:
            feature_sources[f"f{idx}_{dict_key}"] = "param"
            return param_val
        elif features.get(dict_key) is not None:
            feature_sources[f"f{idx}_{dict_key}"] = "features_dict"
            return features.get(dict_key)
        else:
            feature_sources[f"f{idx}_{dict_key}"] = "default"
            logger.warning(f"Feature {idx} ({dict_key}) using default: {default_val}")
            return default_val

    # Use for vegas, opponent, etc.
    vegas_line_val = get_with_source(25, vegas_line, 'vegas_points_line', season_avg)
    ...

    return vector, feature_sources
```

### 1.3 Add Prediction Anomaly Warnings

**File:** `predictions/worker/prediction_systems/catboost_v8.py`

```python
# After prediction, before clamping:
raw_prediction = float(self.model.predict(feature_vector)[0])

# Log warning if prediction is extreme
if raw_prediction >= 55 or raw_prediction <= 5:
    logger.warning(
        "extreme_prediction_detected",
        extra={
            "player_lookup": player_lookup,
            "raw_prediction": raw_prediction,
            "will_clamp_to": max(0, min(60, raw_prediction)),
            "vegas_line": features.get('vegas_points_line'),
            "season_avg": features.get('points_avg_season'),
        }
    )

predicted_points = max(0, min(60, raw_prediction))
```

---

## Phase 2: Training Pipeline Enhancements (P1 - Next Week)

### 2.1 Capture Feature Statistics During Training

**File:** `ml/train_final_ensemble_v8.py` (add new section)

```python
# After preparing features (line 147):
X = pd.concat([X_base, X_new], axis=1).fillna(X_base.median())

# NEW: Calculate and save feature statistics
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

# Save to file
stats_path = MODEL_OUTPUT_DIR / f"ensemble_{version}_{timestamp}_feature_stats.json"
with open(stats_path, 'w') as f:
    json.dump(feature_stats, f, indent=2)
```

### 2.2 Generate Model Contract

**New file:** `ml/model_contract.py`

```python
@dataclass
class ModelContract:
    model_id: str
    model_version: str
    feature_names: List[str]
    feature_count: int
    feature_stats: Dict[str, Dict]  # From training
    expected_ranges: Dict[str, Tuple[float, float]]  # Min, max allowed
    training_date_range: Tuple[str, str]
    training_samples: int
    model_file_hash: str  # SHA256 of model file

    def validate_features(self, features: Dict) -> List[str]:
        """Returns list of validation warnings/errors"""
        issues = []

        for i, name in enumerate(self.feature_names):
            val = features.get(name)
            if val is None:
                issues.append(f"MISSING: Feature {i} ({name}) not provided")
                continue

            stats = self.feature_stats.get(name, {})
            expected_min, expected_max = self.expected_ranges.get(name, (None, None))

            # Check if outside expected range
            if expected_min is not None and val < expected_min:
                issues.append(f"RANGE: Feature {i} ({name}) = {val} < min {expected_min}")
            if expected_max is not None and val > expected_max:
                issues.append(f"RANGE: Feature {i} ({name}) = {val} > max {expected_max}")

            # Check if > 3 sigma from training mean
            mean, std = stats.get('mean'), stats.get('std')
            if mean is not None and std is not None and std > 0:
                z_score = abs(val - mean) / std
                if z_score > 3:
                    issues.append(f"OUTLIER: Feature {i} ({name}) = {val}, z-score = {z_score:.1f}")

        return issues
```

### 2.3 Save Model File Hash

```python
import hashlib

def get_model_hash(model_path: str) -> str:
    """Calculate SHA256 hash of model file for reproducibility"""
    sha256_hash = hashlib.sha256()
    with open(model_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()
```

---

## Phase 3: Feature Store Enhancements (P1 - Next Week)

### 3.1 New BigQuery Fields

**File:** `schemas/bigquery/nba_predictions/ml_feature_store_v2.sql`

```sql
-- Add after existing fields:

-- Model compatibility tracking
target_model_versions ARRAY<STRING>,  -- ['catboost_v8', 'xgboost_v1']
model_contract_version STRING,         -- 'v8_20260108_211817'

-- Per-feature quality tracking
feature_quality_by_index ARRAY<NUMERIC(5,2)>,  -- Quality score per feature
feature_source_by_index ARRAY<STRING>,          -- 'phase4', 'phase3', 'default'
features_using_defaults ARRAY<INT64>,           -- Indices using default values

-- Validation results
validation_warnings ARRAY<STRING>,     -- Warnings from contract validation
validation_passed BOOLEAN,             -- TRUE if all critical checks passed
suspicious_feature_indices ARRAY<INT64>,  -- Features outside expected ranges

-- Reproducibility
processor_commit_sha STRING,           -- Git commit that generated features
processor_version STRING,              -- ml_feature_store_processor version
```

### 3.2 Enhanced Feature Processor

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
# Add to feature generation:

def _validate_features_against_contract(
    self,
    features: List[float],
    feature_names: List[str]
) -> Tuple[List[str], List[int]]:
    """Validate features against model contract"""

    # Load contract
    contract = self._load_model_contract('catboost_v8')

    features_dict = dict(zip(feature_names, features))
    warnings = contract.validate_features(features_dict)
    suspicious_indices = [
        i for i, name in enumerate(feature_names)
        if any(f"Feature {i}" in w for w in warnings)
    ]

    return warnings, suspicious_indices
```

---

## Phase 4: Enhanced Logging (P1 - Next Week)

### 4.1 Log All Feature Values

**File:** `predictions/worker/execution_logger.py`

```python
# Add to log_prediction_run():

# Feature values (sampled to avoid log bloat)
if include_feature_values:
    log_data['feature_values'] = {
        'points_avg_last_5': features.get('points_avg_last_5'),
        'points_avg_last_10': features.get('points_avg_last_10'),
        'vegas_points_line': features.get('vegas_points_line'),
        'ppm_avg_last_10': features.get('ppm_avg_last_10'),
        # ... key features only, not all 33
    }
    log_data['feature_sources'] = feature_sources  # From _prepare_feature_vector
```

### 4.2 Log Per-System Predictions

**File:** `predictions/worker/worker.py`

```python
# After all systems run, before ensemble:

logger.info(
    "system_predictions_comparison",
    extra={
        "player_lookup": player_lookup,
        "moving_average": system_predictions.get('moving_average_baseline_v1', {}).get('predicted_points'),
        "zone_matchup": system_predictions.get('zone_matchup_v1', {}).get('predicted_points'),
        "similarity": system_predictions.get('similarity_balanced_v1', {}).get('predicted_points'),
        "catboost_v8": system_predictions.get('catboost_v8', {}).get('predicted_points'),
        "xgboost_v1": system_predictions.get('xgboost_v1', {}).get('predicted_points'),
        "ensemble": system_predictions.get('ensemble_v1_1', {}).get('predicted_points'),
        "vegas_line": features.get('vegas_points_line'),
        "spread": max_pred - min_pred,  # System disagreement
    }
)
```

### 4.3 Log Execution Timing

```python
import time

system_timings = {}

# For each system:
start = time.time()
result = catboost.predict(...)
system_timings['catboost_v8'] = time.time() - start

# Log timings
logger.info(
    "prediction_timing",
    extra={
        "player_lookup": player_lookup,
        "timings": system_timings,
        "total_ms": sum(system_timings.values()) * 1000,
    }
)
```

---

## Phase 5: Monitoring & Alerting (P2 - Week 3)

### 5.1 Daily Prediction Quality Check

**New file:** `monitoring/daily_prediction_quality.py`

```python
def check_daily_prediction_quality(game_date: date) -> Dict:
    """Run daily quality checks on predictions"""

    checks = {
        "extreme_predictions": {
            "query": """
                SELECT COUNT(*) as count
                FROM nba_predictions.player_prop_predictions
                WHERE game_date = @date
                  AND system_id = 'catboost_v8'
                  AND (predicted_points >= 55 OR predicted_points <= 5)
            """,
            "threshold": 10,  # Alert if > 10 extreme predictions
            "severity": "ERROR",
        },
        "clamped_predictions": {
            "query": """
                SELECT COUNT(*) as count
                FROM nba_predictions.player_prop_predictions
                WHERE game_date = @date
                  AND system_id = 'catboost_v8'
                  AND predicted_points = 60.0
            """,
            "threshold": 5,
            "severity": "ERROR",
        },
        "prediction_vs_vegas_diff": {
            "query": """
                SELECT AVG(ABS(predicted_points - current_points_line)) as avg_diff
                FROM nba_predictions.player_prop_predictions
                WHERE game_date = @date
                  AND system_id = 'catboost_v8'
                  AND current_points_line IS NOT NULL
            """,
            "threshold": 8.0,  # Alert if avg diff > 8 points from Vegas
            "severity": "WARNING",
        },
    }

    return run_checks(checks, game_date)
```

### 5.2 Feature Drift Detection

```python
def check_feature_drift(game_date: date) -> Dict:
    """Compare production features to training baseline"""

    # Load training statistics
    training_stats = load_model_contract('catboost_v8').feature_stats

    # Get production feature means for the date
    production_means = query_feature_means(game_date)

    drift_warnings = []
    for feature, prod_mean in production_means.items():
        train_mean = training_stats[feature]['mean']
        train_std = training_stats[feature]['std']

        # Check if production mean is > 2 sigma from training mean
        z_score = abs(prod_mean - train_mean) / train_std
        if z_score > 2:
            drift_warnings.append({
                "feature": feature,
                "production_mean": prod_mean,
                "training_mean": train_mean,
                "z_score": z_score,
            })

    return {"drift_warnings": drift_warnings}
```

---

## Implementation Priority

| Priority | Item | Impact | Effort | Timeline |
|----------|------|--------|--------|----------|
| **P0** | Fix root cause bug (feature dict fallback) | Critical | Low | Day 1 |
| **P0** | Add feature source logging | High | Low | Day 1 |
| **P0** | Add extreme prediction warnings | High | Low | Day 1 |
| **P1** | Capture feature stats during training | High | Medium | Week 1 |
| **P1** | Generate model contracts | High | Medium | Week 1 |
| **P1** | Log all feature values | Medium | Low | Week 1 |
| **P1** | Log per-system predictions | Medium | Low | Week 1 |
| **P2** | Enhanced feature store schema | Medium | Medium | Week 2 |
| **P2** | Daily quality checks | Medium | Medium | Week 2 |
| **P2** | Feature drift detection | Medium | High | Week 3 |

---

## Success Criteria

1. **No silent fallbacks** - All default value usage is logged as WARNING
2. **Immediate detection** - Extreme predictions (>50 or <5) trigger alerts
3. **Traceability** - Can trace any prediction back to exact features used
4. **Reproducibility** - Model hash + processor commit = reproducible results
5. **Early warning** - Feature drift detected within 24 hours

---

## Files to Modify

| File | Changes |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v8.py` | Fix bug, add logging, add warnings |
| `predictions/worker/worker.py` | Add system timing, prediction comparison logging |
| `predictions/worker/execution_logger.py` | Add feature values to logs |
| `ml/train_final_ensemble_v8.py` | Capture feature statistics |
| `ml/model_contract.py` | NEW: Model contract generation |
| `schemas/bigquery/nba_predictions/ml_feature_store_v2.sql` | Add validation fields |
| `monitoring/daily_prediction_quality.py` | NEW: Daily quality checks |

---

## Appendix: Specific Feature Ranges to Validate

Based on domain knowledge and training data analysis:

| Feature | Expected Range | Alert If |
|---------|----------------|----------|
| points_avg_last_5 | 0-50 | > 55 or < 0 |
| points_avg_season | 0-40 | > 45 or < 0 |
| fatigue_score | 0-100 | < 0 or > 100 |
| vegas_points_line | 5-45 | < 3 or > 50 |
| ppm_avg_last_10 | 0.2-1.5 | < 0.1 or > 2.0 |
| minutes_avg_last_10 | 10-40 | < 5 or > 45 |
| games_vs_opponent | 0-100 | < 0 |
| team_win_pct | 0-1.0 | < 0 or > 1 |
