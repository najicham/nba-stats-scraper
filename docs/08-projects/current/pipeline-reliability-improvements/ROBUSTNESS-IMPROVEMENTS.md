# Pipeline Robustness Improvements Plan

**Created:** 2026-01-09 (Post-incident analysis)
**Status:** Planning

---

## Incident Summary (Jan 9, 2026)

Five separate issues combined to cause 0% actionable predictions:
1. Timing race: UPGC ran before props scraped
2. Missing env var: V8 model path not configured
3. Missing library: catboost not in requirements.txt
4. Feature mismatch: Processor wrote v1, model expected v2
5. Silent fallback: Model used placeholder predictions without alerting

---

## Priority 1: Fail-Fast Validation

### 1.1 Startup Environment Validation
**Status:** Partially exists (env_validation.py)
**Gap:** Doesn't validate ML model paths

```python
# predictions/worker/startup_checks.py
def validate_ml_model_availability():
    """Fail fast if V8 model not accessible."""
    model_path = os.environ.get('CATBOOST_V8_MODEL_PATH')
    if not model_path:
        raise RuntimeError("CATBOOST_V8_MODEL_PATH not set - cannot start worker")

    # Verify model is accessible
    try:
        from google.cloud import storage
        # ... verify file exists in GCS
    except Exception as e:
        raise RuntimeError(f"Cannot access V8 model: {e}")
```

### 1.2 Feature Version Assertion
**Status:** Not implemented
**Gap:** Model silently receives wrong features

```python
# predictions/worker/prediction_systems/catboost_v8.py
def predict(self, features: Dict) -> Dict:
    # ASSERT correct feature version
    version = features.get('feature_version')
    if version != 'v2_33features':
        raise ValueError(f"CatBoost V8 requires v2_33features, got {version}")

    # ASSERT correct feature count
    if len(features.get('features_array', [])) != 33:
        raise ValueError(f"CatBoost V8 requires 33 features")
```

---

## Priority 2: Self-Healing Automation

### 2.1 Props Availability Monitor
**Status:** Alert added (today)
**Gap:** No automatic recovery

```yaml
# Cloud Function: props-availability-monitor
# Trigger: 1 PM ET (after expected props scrape)
# Action: If <20 players have props, trigger re-scrape + re-UPGC
```

### 2.2 Prediction Quality Monitor
**Status:** Not implemented
**Gap:** No detection of fallback predictions

```sql
-- Alert if avg confidence = 50 (fallback indicator)
SELECT system_id, AVG(confidence_score) as avg_conf
FROM predictions
WHERE game_date = CURRENT_DATE()
GROUP BY system_id
HAVING AVG(confidence_score) = 50.0  -- Indicates fallback
```

### 2.3 Automatic Re-run on Failure
**Status:** Partial (Pub/Sub retries individual players)
**Gap:** No batch-level retry

```yaml
# If >50% players fail, trigger full batch re-run
# Instead of individual retries that mask systemic issues
```

---

## Priority 3: Observability Improvements

### 3.1 Daily Health Dashboard
**Status:** Not implemented
**Metrics to track:**
- Props coverage % (target: >40%)
- Prediction coverage % (target: >80%)
- Feature version consistency
- Model loading success rate
- Avg confidence by system (alert if 50.0)
- OVER/UNDER ratio (alert if 0)

### 3.2 Structured Logging
**Status:** Partial
**Gap:** No unified log format for monitoring

```python
# Standard log format for monitoring
logger.info(
    "prediction_generated",
    extra={
        "player_lookup": player,
        "system_id": "catboost_v8",
        "feature_version": "v2_33features",
        "feature_count": 33,
        "confidence": 0.87,
        "recommendation": "OVER",
        "model_type": "real"  # vs "fallback"
    }
)
```

### 3.3 Alerting Rules
```yaml
# Critical Alerts (PagerDuty)
- prop_coverage < 10%
- avg_confidence = 50.0 (fallback detection)
- 0 OVER/UNDER recommendations
- model_load_failed = true

# Warning Alerts (Email)
- prop_coverage < 30%
- player_failure_rate > 20%
- feature_version mismatch detected
```

---

## Priority 4: Architectural Improvements

### 4.1 Explicit Scheduler Dependencies
**Current:** Implicit timing (hope props finish before UPGC)
**Proposed:** Event-driven pipeline

```yaml
# Option A: Scheduler ordering via delay
bettingpros-props-scrape:  10:00 AM ET
phase3-processors:         11:00 AM ET  # +1 hour buffer
upgc-processor:            12:00 PM ET  # +2 hour buffer

# Option B: Event-driven (better)
bettingpros-props-scrape:
  on_complete: trigger phase3-processors
phase3-processors:
  on_complete: trigger upgc-processor
```

### 4.2 Feature Store Version Management
**Current:** Hardcoded version in processor
**Proposed:** Configuration-driven

```yaml
# feature_store_config.yaml
current_version: v2_33features
feature_count: 33
consumers:
  - catboost_v8: requires v2_33features
  - moving_average: compatible with v1_baseline_25, v2_33features
  - similarity: compatible with v1_baseline_25, v2_33features
```

### 4.3 Model Registry Integration
**Current:** Model path in env var
**Proposed:** Model registry with version tracking

```python
# ml/model_registry.py
class ModelRegistry:
    def get_production_model(self, system_id: str) -> Model:
        """Get production model with version validation."""
        config = self._get_model_config(system_id)

        # Validate feature compatibility
        if config.required_feature_version != FEATURE_VERSION:
            raise VersionMismatchError(...)

        return self._load_model(config.path)
```

---

## Priority 5: Testing Improvements

### 5.1 Integration Tests
**Gap:** No end-to-end test for prediction pipeline

```python
# tests/integration/test_prediction_pipeline.py
def test_full_prediction_flow():
    """E2E test: features → predictions → BigQuery"""
    # 1. Generate features for test date
    # 2. Run prediction worker
    # 3. Verify predictions in BigQuery
    # 4. Assert feature version, count, confidence range
```

### 5.2 Deployment Validation
**Gap:** No smoke test after deployment

```bash
# bin/validate-deployment.sh
# Run after every Cloud Run deployment

# 1. Trigger health check endpoint
# 2. Run single test prediction
# 3. Verify model loaded correctly
# 4. Check feature version in output
```

### 5.3 Feature Parity Testing
**Gap:** No validation that processor output matches model expectations

```python
def test_feature_count_matches_model():
    features = generate_features_for_date(...)
    assert len(features['features_array']) == 33
    assert features['feature_version'] == 'v2_33features'

    # Validate specific features exist
    for feature_name in CATBOOST_V8_REQUIRED_FEATURES:
        assert feature_name in features['feature_names']
```

---

## Implementation Timeline

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| P1 | Startup validation | Low | High - prevents silent failures |
| P1 | Feature version assertion | Low | High - catches mismatches |
| P2 | Self-healing Cloud Function | Medium | High - auto-recovers |
| P2 | Prediction quality monitor | Low | High - early detection |
| P3 | Daily health dashboard | Medium | Medium - visibility |
| P3 | Structured logging | Medium | Medium - observability |
| P4 | Event-driven pipeline | High | High - eliminates timing issues |
| P4 | Model registry | High | Medium - better management |
| P5 | Integration tests | Medium | Medium - confidence |
| P5 | Deployment validation | Low | Medium - catch regressions |

---

## Quick Wins (Can Do Immediately)

1. **Add feature version check in catboost_v8.py** (~5 lines)
2. **Add startup model path validation** (~10 lines)
3. **Add daily health query to monitoring** (~SQL only)
4. **Document scheduler ordering requirements** (~docs only)

---

## Lessons Learned

1. **Silent fallbacks are dangerous** - Better to fail loudly than produce garbage
2. **Timing dependencies need explicit contracts** - Don't rely on "usually works"
3. **Feature versions must be validated end-to-end** - From processor to model
4. **Backfill ≠ production fix** - Must update daily processors too
5. **Monitoring gaps compound** - Multiple missing alerts let issues cascade
