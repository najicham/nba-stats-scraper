# Pipeline Robustness Improvements Plan

**Created:** 2026-01-09 (Post-incident analysis)
**Updated:** 2026-01-09 (Quick wins implemented)
**Status:** In Progress

---

## Incident Summary (Jan 9, 2026)

Five separate issues combined to cause 0% actionable predictions:
1. Timing race: UPGC ran before props scraped
2. Missing env var: V8 model path not configured
3. Missing library: catboost not in requirements.txt
4. Feature mismatch: Processor wrote v1, model expected v2
5. Silent fallback: Model used placeholder predictions without alerting

---

## Quick Wins Completed (2026-01-09)

| Item | Status | Commit |
|------|--------|--------|
| Feature version assertion in catboost_v8.py | ✅ Done | 8030007 |
| Startup model path validation in worker.py | ✅ Done | 8030007 |
| Daily health monitoring queries (Query 9-13) | ✅ Done | 8030007 |

---

## Priority 1: Fail-Fast Validation

### 1.1 Startup Environment Validation
**Status:** ✅ IMPLEMENTED (worker.py:56-105)
**Validates:** Model path format, local model existence

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
**Status:** ✅ IMPLEMENTED (catboost_v8.py:210-217)
**Validates:** feature_version == 'v2_33features'

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

## Implementation Timeline (Updated)

| Priority | Item | Effort | Impact | Status |
|----------|------|--------|--------|--------|
| P1 | Startup validation | Low | High | ✅ Done |
| P1 | Feature version assertion | Low | High | ✅ Done |
| P1 | Health monitoring queries | Low | High | ✅ Done |
| P2 | Feature count validation (33) | Low | High | 🔲 Todo |
| P2 | Props availability Cloud Function | Medium | High | 🔲 Todo |
| P2 | Dependency health checks | Medium | High | 🔲 Todo |
| P3 | Structured logging (model_type) | Low | Medium | 🔲 Todo |
| P3 | AlertManager integration | Medium | Medium | 🔲 Todo |
| P3 | Degraded mode flag | Low | Medium | 🔲 Todo |
| P4 | Event-driven pipeline | High | High | 🔲 Todo |
| P4 | Feature store config | Medium | Medium | 🔲 Todo |
| P5 | E2E integration tests | Medium | Medium | 🔲 Todo |
| P5 | Deployment validation | Low | Medium | 🔲 Todo |

---

## Remaining Improvements (Detailed)

### P2: High Priority, Medium Effort

#### 2.1 Feature Count Validation
**File:** `predictions/worker/prediction_systems/catboost_v8.py`
**Why:** Feature version check alone doesn't catch truncated feature arrays

```python
# Add after feature_version check (line 217)
features_array = features.get('features_array', [])
if len(features_array) != 33:
    raise ValueError(
        f"CatBoost V8 requires 33 features, got {len(features_array)}. "
        f"Check ml_feature_store_processor.py feature extraction."
    )
```

#### 2.2 Props Availability Cloud Function
**File:** `orchestration/cloud_functions/props_availability_monitor/main.py`
**Why:** Detect when props scraper fails before UPGC runs

```python
# Trigger: Cloud Scheduler at 1:00 PM ET (after expected props scrape)
# Action:
# 1. Query upcoming_player_game_context for today
# 2. Count players with points_prop_line IS NOT NULL
# 3. If < 20 players have props:
#    - Send CRITICAL alert
#    - Optionally trigger re-scrape
```

#### 2.3 Dependency Health Checks
**File:** `predictions/worker/dependency_health.py`
**Why:** Fail fast if infrastructure is unhealthy before processing predictions

```python
def check_dependencies() -> Dict[str, bool]:
    """Pre-flight check before prediction batch."""
    return {
        'bigquery': _check_bigquery_connection(),
        'pubsub': _check_pubsub_topic_exists(),
        'feature_store': _check_feature_store_has_today(),
        'props': _check_props_available_today(),
    }

# Call from coordinator before starting batch
health = check_dependencies()
if not all(health.values()):
    raise DependencyError(f"Dependencies unhealthy: {health}")
```

### P3: Medium Priority

#### 3.1 Structured Logging with model_type
**File:** `predictions/worker/prediction_systems/catboost_v8.py`
**Why:** Enable log-based detection of fallback predictions

```python
# In predict() and _fallback_prediction() methods
logger.info(
    "prediction_generated",
    extra={
        "player_lookup": player_lookup,
        "system_id": self.system_id,
        "model_type": "real",  # or "fallback"
        "confidence": confidence,
        "recommendation": recommendation,
        "feature_version": features.get('feature_version'),
    }
)
```

#### 3.2 AlertManager Integration
**File:** `monitoring/health_alerts/prediction_health_alert.py`
**Why:** Turn health queries into actionable PagerDuty alerts

```python
# Run as Cloud Function hourly after predictions complete
from shared.alerts.alert_manager import AlertManager

def check_prediction_health():
    results = run_health_query()  # Query 13 from pipeline_health_queries.sql

    if results['health_status'].startswith('CRITICAL'):
        AlertManager.send(
            severity='critical',
            title='Prediction System Failure',
            message=results['health_status'],
            channel='pagerduty'
        )
```

#### 3.3 Degraded Mode Flag
**File:** `predictions/worker/prediction_systems/catboost_v8.py`
**Why:** Make fallback status explicit in prediction output

```python
# In prediction output dict
return {
    'system_id': self.system_id,
    'predicted_points': predicted,
    'confidence_score': confidence,
    'recommendation': recommendation,
    'degraded_mode': self.model is None,  # NEW: explicit flag
    'model_type': 'fallback' if self.model is None else 'catboost_v8_real',
}
```

### P4: Architectural Improvements

#### 4.1 Event-Driven Pipeline
**Why:** Eliminate timing races completely
**Approach:**
1. Props scraper publishes completion event to `props-complete` topic
2. UPGC processor subscribes and triggers on event
3. Add Pub/Sub topic and subscription for orchestration
4. Update Cloud Scheduler to not run UPGC on fixed schedule

```yaml
# pubsub_topics.yaml
- name: props-complete
  subscribers:
    - upgc-processor  # Triggers Phase 3 UPGC

# props_scraper completion:
publisher.publish('props-complete', {'game_date': date, 'players': count})
```

#### 4.2 Feature Store Configuration
**File:** `config/feature_store_config.yaml`
**Why:** Centralize version management, prevent mismatches

```yaml
feature_store:
  current_version: v2_33features
  feature_count: 33
  table: nba_predictions.ml_feature_store_v2

consumers:
  catboost_v8:
    required_version: v2_33features
    required_count: 33
  moving_average:
    compatible_versions: [v1_baseline_25, v2_33features]
  zone_matchup:
    compatible_versions: [v1_baseline_25, v2_33features]
```

### P5: Testing Improvements

#### 5.1 E2E Integration Test
**File:** `tests/integration/test_prediction_pipeline.py`

```python
@pytest.mark.integration
def test_full_prediction_flow():
    """E2E: features → predictions → BigQuery"""
    test_date = date.today()
    test_player = 'lebron-james'

    # 1. Verify features exist
    features = load_features(test_player, test_date)
    assert features['feature_version'] == 'v2_33features'
    assert len(features['features_array']) == 33

    # 2. Generate prediction
    system = CatBoostV8()
    result = system.predict(test_player, features, betting_line=25.5)

    # 3. Validate output
    assert result['confidence_score'] != 50.0  # Not fallback
    assert result['recommendation'] in ['OVER', 'UNDER', 'PASS']
    assert result['model_type'] == 'catboost_v8_real'
```

#### 5.2 Deployment Validation Script
**File:** `bin/validate-deployment.sh`

```bash
#!/bin/bash
# Run after Cloud Run deployment

SERVICE_URL=$(gcloud run services describe prediction-worker --format='value(status.url)')

# 1. Health check
curl -f "$SERVICE_URL/health" || exit 1

# 2. Test prediction (dry run)
curl -X POST "$SERVICE_URL/test-predict" \
  -H "Content-Type: application/json" \
  -d '{"player_lookup": "test-player", "dry_run": true}' || exit 1

# 3. Check model loaded
RESPONSE=$(curl -s "$SERVICE_URL/")
echo "$RESPONSE" | jq '.systems.xgboost' | grep -q "CatBoostV8" || exit 1

echo "✅ Deployment validation passed"
```

---

## New Improvements Identified (Beyond Original Plan)

### Circuit Breaker Enhancements
**Current:** Per-system circuit breakers (5 independent)
**Improvement:** Add global circuit breaker for infrastructure failures

```python
# If BigQuery or Pub/Sub is down, open global breaker
# Prevents wasting compute on doomed requests
```

### Data Lineage Tracking
**Why:** For debugging, track which feature store rows fed predictions

```python
# Add to prediction output
'lineage': {
    'feature_store_row_id': row_id,
    'props_scrape_time': scrape_timestamp,
    'correlation_id': correlation_id,
}
```

### Model Staleness Detection
**Why:** Alert if model hasn't been retrained recently

```python
# Check model metadata for training date
# Alert if > 30 days old or if accuracy degrading
```

### Feature Drift Detection
**Why:** Detect when production features diverge from training distribution

```python
# Compare current feature distributions to training baseline
# Alert on significant drift in key features
```

---

## Lessons Learned

1. **Silent fallbacks are dangerous** - Better to fail loudly than produce garbage
2. **Timing dependencies need explicit contracts** - Don't rely on "usually works"
3. **Feature versions must be validated end-to-end** - From processor to model
4. **Backfill ≠ production fix** - Must update daily processors too
5. **Monitoring gaps compound** - Multiple missing alerts let issues cascade
6. **Assertions at boundaries** - Validate at every system interface
7. **Existing infrastructure helps** - Circuit breakers and AlertManager already available

---

## Priority 6: Retry Storm Prevention (Added 2026-01-10)

### Problem Statement

The prediction worker returns HTTP 500 for **all** empty predictions, triggering Pub/Sub automatic retries. This works for transient failures (data not ready yet) but causes **infinite retry storms** for permanent failures (data will never exist).

**Example:** Players `treymurphyiii` and `jaimejaquezjr` missing from `ml_feature_store_v2` for Jan 4:
- Every retry queries the same empty result
- Retries continue for 7 days until Pub/Sub gives up
- Wastes compute resources and pollutes logs

### Solution: Failure Classification + DLQ

**Two-pronged approach:**

1. **Worker-level classification:** Distinguish transient vs permanent failures, return appropriate HTTP status
2. **Pub/Sub DLQ:** Safety net for edge cases, moves failed messages to dead-letter topic after max retries

### 6.1 Failure Classification (worker.py)

**Status:** ✅ IMPLEMENTED

```python
# Permanent failures - data won't magically appear, don't retry
PERMANENT_SKIP_REASONS = {
    'no_features',           # Player not in feature store
    'player_not_found',      # Player lookup invalid
    'no_prop_lines',         # No betting lines scraped for player
    'game_not_found',        # Game doesn't exist
    'player_inactive',       # Player not playing
}

# Transient failures - might resolve on retry
TRANSIENT_SKIP_REASONS = {
    'feature_store_timeout', # Temporary connectivity issue
    'model_load_error',      # Model loading failed (might be transient)
    'bigquery_timeout',      # Temporary BQ issue
    'rate_limited',          # External API rate limit
}

# In handle_prediction_request():
if not predictions:
    skip_reason = metadata.get('skip_reason', 'unknown')

    if skip_reason in PERMANENT_SKIP_REASONS:
        # Don't retry - publish to DLQ for investigation
        logger.warning(f"Permanent failure for {player_lookup}: {skip_reason}")
        return ('', 204)  # Ack message, stop retries
    else:
        # Transient - trigger retry
        logger.error(f"Transient failure for {player_lookup}: {skip_reason}")
        return ('Transient failure - triggering retry', 500)
```

### 6.2 Pub/Sub DLQ Configuration

**Status:** ✅ IMPLEMENTED

Infrastructure created:
- **DLQ Topic:** `prediction-request-dlq`
- **DLQ Subscription:** `prediction-request-dlq-sub`
- **Max retries:** 5 attempts before moving to DLQ (Pub/Sub minimum is 5)

```bash
# Create DLQ topic
gcloud pubsub topics create prediction-request-dlq

# Create DLQ subscription (for monitoring/recovery)
gcloud pubsub subscriptions create prediction-request-dlq-sub \
    --topic prediction-request-dlq \
    --ack-deadline=60 \
    --message-retention-duration=7d

# Grant Pub/Sub SA permission to publish to DLQ
PROJECT_NUMBER=$(gcloud projects describe nba-props-platform --format="value(projectNumber)")
gcloud pubsub topics add-iam-policy-binding prediction-request-dlq \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
    --role="roles/pubsub.publisher"

# Update main subscription with dead-letter policy
gcloud pubsub subscriptions update prediction-request-prod \
    --dead-letter-topic=projects/nba-props-platform/topics/prediction-request-dlq \
    --max-delivery-attempts=5
```

### 6.3 DLQ Monitoring

**Status:** ✅ IMPLEMENTED

Added `prediction-request-dlq-sub` to `dlq_monitor.py`:

```python
DLQ_SUBSCRIPTIONS = {
    # ... existing DLQs ...

    # Phase 5: Prediction worker failures
    'prediction-request-dlq-sub': {
        'description': 'Prediction Worker Failures',
        'phase_from': 'Coordinator',
        'phase_to': 'Prediction Worker',
        'severity': 'warning',
        'recovery_command': 'Check feature store for missing players, verify player_lookup mappings',
    },
}
```

### 6.4 Recovery Workflow

When messages appear in the prediction DLQ:

1. **Investigate:** Check `prediction_worker_runs` for `skip_reason`
2. **Common causes:**
   - `no_features`: Player missing from feature store (pipeline gap)
   - `player_not_found`: Invalid player_lookup (mapping issue)
   - `no_prop_lines`: Props not scraped (timing issue)
3. **Resolution:**
   - For pipeline gaps: Run backfill for missing date
   - For mapping issues: Fix player lookup in source
   - For timing issues: Usually already resolved, discard message
4. **Replay (if needed):** Pull message, fix root cause, republish to main topic

### 6.5 Metrics to Track

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| Permanent failures/hour | `prediction_worker_runs` WHERE `skip_reason` IN permanent | > 50 |
| DLQ message count | Pub/Sub monitoring | > 0 |
| Retry storm detection | Same player+date > 3 executions | Any occurrence |

### Design Rationale

**Why classify at worker level?**
- Immediate feedback - no wasted retries
- Clear logging of failure type
- Worker has context (skip_reason) to make decision

**Why also have DLQ?**
- Safety net for unclassified errors
- Investigation queue for edge cases
- Prevents 7-day message backlog

**Why 3 max retries?**
- Enough for transient issues to resolve
- Fast enough to not waste resources
- Matches existing DLQ patterns in codebase
