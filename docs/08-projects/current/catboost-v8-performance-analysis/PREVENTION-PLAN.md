# CatBoost V8 Bug Prevention Plan

**Created:** 2026-01-29 Session 24
**Status:** PLANNING
**Priority:** HIGH

---

## Root Cause Analysis

### Why Did This Bug Happen?

| Factor | Description | Impact |
|--------|-------------|--------|
| **Training/Inference Gap** | Model trained on 33 features from 4 tables, inference only had 25 from 1 table | Critical |
| **Silent Fallbacks** | Missing features defaulted to 0.0 or 0.4 without alerts | Critical |
| **No Contract Enforcement** | Model contract exists but wasn't used during inference | High |
| **Separate Code Paths** | Training uses SQL JOINs, inference uses feature store only | High |
| **No Feature Drift Detection** | No monitoring for feature distribution changes | Medium |

### The Specific Failure

```
Training:     feature_store + bettingpros + player_game_summary → 33 features
                                    ↓
Inference:    feature_store only → 25 features + 8 defaults
                                    ↓
Result:       has_vegas_line=0.0, ppm=0.4 → predictions inflated by +29 points
```

---

## Prevention Strategy: Defense in Depth

### Layer 1: Feature Completeness (Prevent the Gap)

**Option A: Expand Feature Store (Recommended)**

Store all 33 features in `ml_feature_store_v2` during Phase 4 processing:

```sql
-- Add columns for Vegas/opponent/PPM features
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN vegas_points_line FLOAT64,
ADD COLUMN vegas_opening_line FLOAT64,
ADD COLUMN vegas_line_move FLOAT64,
ADD COLUMN has_vegas_line FLOAT64,
ADD COLUMN avg_points_vs_opponent FLOAT64,
ADD COLUMN games_vs_opponent INT64,
ADD COLUMN minutes_avg_last_10 FLOAT64,
ADD COLUMN ppm_avg_last_10 FLOAT64;
```

**Pros:** Single source of truth, no inference-time enrichment
**Cons:** Requires Phase 4 processor update, schema migration

**Option B: Feature Enrichment Service**

Create a dedicated service that enriches features at inference time:

```python
class FeatureEnricher:
    def enrich_for_catboost_v8(self, base_features: Dict, prop_line: float) -> Dict:
        features = base_features.copy()
        features['vegas_points_line'] = prop_line
        features['ppm_avg_last_10'] = self._calculate_ppm(features)
        # ... etc
        return features
```

**Pros:** Flexible, can be updated without schema changes
**Cons:** Another code path to maintain, can drift from training

---

### Layer 2: Contract Enforcement (Catch the Gap)

**Action: Activate Model Contract Validation**

The contract system exists (`ml/model_contract.py`) but isn't used. Activate it:

```python
# In catboost_v8.py predict() method
from ml.model_contract import ModelContract

class CatBoostV8:
    def __init__(self):
        self.contract = ModelContract.load("models/ensemble_v8_contract.json")

    def predict(self, player_lookup, features, betting_line):
        # Validate features against contract BEFORE prediction
        issues = self.contract.validate_features(features)
        if issues:
            logger.error("feature_contract_violation", extra={"issues": issues})
            # Option 1: Refuse to predict
            raise FeatureContractViolation(issues)
            # Option 2: Predict but mark as degraded
            # return self._degraded_prediction(features, issues)
```

**Contract JSON to Generate:**
```json
{
  "model_id": "catboost_v8",
  "feature_count": 33,
  "required_features": [
    {"name": "vegas_points_line", "index": 25, "nullable": false},
    {"name": "has_vegas_line", "index": 28, "must_be_1_when_line_exists": true},
    {"name": "ppm_avg_last_10", "index": 32, "min": 0.2, "max": 2.0}
  ],
  "training_stats": {
    "vegas_points_line": {"mean": 15.2, "std": 7.1, "p5": 5.5, "p95": 28.5}
  }
}
```

---

### Layer 3: Loud Failures (Don't Hide the Gap)

**Current Problem:** Silent fallbacks hide data issues

**Solution: Fallback Classification System**

```python
class FallbackSeverity(Enum):
    NONE = "none"           # All features present
    MINOR = "minor"         # Non-critical feature missing (e.g., games_vs_opponent)
    MAJOR = "major"         # Important feature missing (e.g., ppm_avg_last_10)
    CRITICAL = "critical"   # Critical feature missing (e.g., has_vegas_line wrong)

def classify_fallback_severity(features: Dict, used_defaults: List[str]) -> FallbackSeverity:
    critical_features = {'vegas_points_line', 'has_vegas_line', 'ppm_avg_last_10'}
    major_features = {'avg_points_vs_opponent', 'minutes_avg_last_10'}

    if any(f in critical_features for f in used_defaults):
        return FallbackSeverity.CRITICAL
    elif any(f in major_features for f in used_defaults):
        return FallbackSeverity.MAJOR
    elif used_defaults:
        return FallbackSeverity.MINOR
    return FallbackSeverity.NONE
```

**Action on Severity:**

| Severity | Action |
|----------|--------|
| NONE | Normal prediction |
| MINOR | Predict, log INFO |
| MAJOR | Predict, log WARNING, mark `prediction_quality='degraded'` |
| CRITICAL | Refuse to predict OR use fallback model, log ERROR, alert |

---

### Layer 4: Monitoring & Alerting

**Metrics to Add:**

```python
# In catboost_v8.py
from prometheus_client import Counter, Histogram, Gauge

# Feature completeness
feature_fallback_total = Counter(
    'catboost_v8_feature_fallback_total',
    'Count of predictions using fallback values',
    ['feature_name', 'severity']
)

# Prediction distribution
prediction_value_histogram = Histogram(
    'catboost_v8_prediction_points',
    'Distribution of predicted points',
    buckets=[5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]
)

# Extreme predictions
extreme_prediction_total = Counter(
    'catboost_v8_extreme_prediction_total',
    'Count of predictions at clamp boundaries',
    ['boundary']  # 'high_60' or 'low_0'
)
```

**Alerts to Configure:**

| Alert | Condition | Severity |
|-------|-----------|----------|
| High Fallback Rate | >10% predictions use CRITICAL fallbacks in 1 hour | P1 |
| Extreme Predictions | >5% predictions clamped at 60 in 1 hour | P1 |
| Feature Drift | Mean prediction differs from historical by >2 std | P2 |
| Model Load Failure | CatBoost model fails to load | P1 |

---

### Layer 5: Testing

**Add These Tests:**

```python
# tests/prediction_tests/test_feature_parity.py

def test_training_inference_feature_order_matches():
    """Verify V8_FEATURES matches training feature order exactly"""
    training_features = [...]  # From train_final_ensemble_v8.py
    inference_features = V8_FEATURES
    assert training_features == inference_features

def test_inference_features_populated():
    """Verify all 33 features are populated at inference time"""
    features = simulate_inference_feature_loading(player_lookup, game_date)
    for i, name in enumerate(V8_FEATURES):
        assert name in features, f"Feature {i} ({name}) missing from inference"
        assert features[name] is not None, f"Feature {i} ({name}) is None"

def test_has_vegas_line_correct():
    """Verify has_vegas_line=1.0 when prop line exists"""
    features = simulate_inference_feature_loading(player_lookup, game_date, prop_line=25.5)
    assert features['has_vegas_line'] == 1.0

def test_prediction_reasonable_range():
    """Verify predictions stay in reasonable range"""
    result = catboost.predict(player_lookup, features, betting_line=25.5)
    assert 5 <= result['predicted_points'] <= 50, "Prediction outside reasonable range"
```

---

### Layer 6: Daily Validation

**Add to `/validate-daily` skill:**

```python
def validate_catboost_v8_health(game_date: date) -> Dict:
    """Daily health check for CatBoost V8 predictions"""

    checks = {}

    # Check 1: Extreme predictions
    query = f"""
    SELECT COUNT(*) as extreme_count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}' AND system_id = 'catboost_v8'
      AND (predicted_points >= 55 OR predicted_points <= 5)
    """
    extreme_count = run_query(query)
    checks['extreme_predictions'] = {
        'count': extreme_count,
        'status': 'ERROR' if extreme_count > 10 else 'OK'
    }

    # Check 2: Clamped at boundaries
    query = f"""
    SELECT
      SUM(CASE WHEN predicted_points = 60 THEN 1 ELSE 0 END) as clamped_high,
      SUM(CASE WHEN predicted_points = 0 THEN 1 ELSE 0 END) as clamped_low
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}' AND system_id = 'catboost_v8'
    """
    # ...

    # Check 3: Feature fallback rate (requires new column)
    # ...

    return checks
```

---

## Implementation Roadmap

### Phase 1: Immediate (This Week)

- [x] Fix feature passing bug (Session 24) ✓
- [ ] Add `prediction_quality` column to track degraded predictions
- [ ] Add logging for feature fallbacks with severity
- [ ] Create model contract JSON for V8

### Phase 2: Short-term (Next 2 Weeks)

- [ ] Implement fallback severity classification
- [ ] Add Prometheus metrics for feature completeness
- [ ] Configure Cloud Monitoring alerts
- [ ] Add feature parity tests
- [ ] Update `/validate-daily` with CatBoost health checks

### Phase 3: Medium-term (Next Month)

- [ ] Expand `ml_feature_store_v2` to include all 33 features
- [ ] Activate model contract validation during inference
- [ ] Implement canary deployment for model updates
- [ ] Add feature drift detection

### Phase 4: Long-term

- [ ] Build model registry with version management
- [ ] Implement A/B testing infrastructure
- [ ] Add automatic rollback on performance degradation

---

## Key Principles Going Forward

1. **No Silent Fallbacks**: Every default value must be logged with severity
2. **Contract First**: Model contract must be generated during training and validated during inference
3. **Single Source of Truth**: All features should come from one place (expanded feature store)
4. **Monitor Everything**: Every prediction should have observability
5. **Fail Loudly**: Critical issues should refuse to predict, not produce garbage

---

*Document created: 2026-01-29 Session 24*
