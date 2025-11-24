# Phase 5 Predictions - Testing Strategy

**Created:** 2025-11-23
**Status:** Active - Deployment in Progress
**Testing Approach:** E2E First → Unit Tests → Continuous Monitoring

---

## Overview

This document outlines the testing strategy for Phase 5 Predictions deployment. We're following a pragmatic approach optimized for our current situation:

1. **Complete Cloud Run deployment** (in progress)
2. **Run comprehensive end-to-end tests** (immediate validation)
3. **Create unit test suite** (based on e2e findings)
4. **Establish continuous testing** (ongoing confidence)

---

## Testing Philosophy

### Why E2E Testing First?

**Context:**
- Phase 5 code marked as "100% complete" in codebase
- Deployment already initiated when testing discussion started
- XGBoost using mock model (4/5 systems are production-ready)
- Cloud Run allows instant rollback if issues found
- Time-efficient to validate working system quickly

**Benefits:**
- Validates full system integration immediately
- Tests real production environment (not just mocks)
- Identifies infrastructure issues early
- Provides confidence before deeper testing
- Allows quick rollback if critical issues found

**Risks:**
- May discover bugs in production (mitigated by thorough e2e tests)
- Less granular error debugging (mitigated by Cloud Run logs)

### Why Unit Tests After?

**Reasoning:**
- Can target specific areas revealed by e2e testing
- Write tests for actual failure modes observed
- No delay in getting system operational
- Better understanding of system behavior in production

---

## Phase 1: End-to-End Testing (Immediate)

**When:** Immediately after deployment completes
**Duration:** ~30 minutes
**Goal:** Validate complete prediction pipeline works

### Test 1: Service Health Checks (5 min)

**What:**
- Verify both services deployed successfully
- Check health endpoints return 200 OK
- Validate environment variables configured

**Commands:**
```bash
# Get service URLs
WORKER_URL=$(gcloud run services describe prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --format="value(status.url)")

COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
  --project=nba-props-platform \
  --region=us-west2 \
  --format="value(status.url)")

# Test health endpoints
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "${WORKER_URL}/health"

curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "${COORDINATOR_URL}/health"
```

**Success Criteria:**
- ✅ Both endpoints return `{"status": "healthy"}`
- ✅ Response time <200ms
- ✅ No errors in Cloud Run logs

---

### Test 2: Single Prediction Request (10 min)

**What:**
- Test worker processes a single prediction request
- Verify all 5 prediction systems execute
- Check BigQuery output written correctly

**Commands:**
```bash
# Publish single prediction request
gcloud pubsub topics publish prediction-request-prod \
  --project=nba-props-platform \
  --message='{
    "player_lookup": "lebron-james",
    "game_date": "2024-11-22",
    "game_id": "20241122_LAL_GSW",
    "line_values": [25.5, 26.5, 27.5]
  }'

# Wait 30 seconds for processing
sleep 30

# Check BigQuery for prediction
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT
  player_lookup,
  game_date,
  prediction_points,
  confidence_score,
  systems_used,
  ensemble_used,
  created_at
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE player_lookup = 'lebron-james'
  AND game_date = '2024-11-22'
ORDER BY created_at DESC
LIMIT 1;
"

# Check Cloud Run logs for processing
gcloud run services logs read prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --limit=20 | grep -A5 "Processing prediction"
```

**Success Criteria:**
- ✅ Worker processes message within 30 seconds
- ✅ Prediction written to BigQuery
- ✅ All systems execute (check `systems_used` field)
- ✅ Confidence score reasonable (40-90 range)
- ✅ No errors in worker logs

---

### Test 3: Coordinator Batch Processing (15 min)

**What:**
- Test coordinator fans out work for multiple players
- Verify worker auto-scaling handles load
- Check batch completion tracking

**Commands:**
```bash
# Trigger coordinator for a game date
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  "${COORDINATOR_URL}/start" \
  -d '{
    "game_date": "2024-11-22"
  }'

# Monitor batch progress
watch -n 5 "curl -s -H 'Authorization: Bearer $(gcloud auth print-identity-token)' \
  '${COORDINATOR_URL}/status?game_date=2024-11-22'"

# After completion, check prediction count
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  AVG(confidence_score) as avg_confidence,
  COUNTIF(ensemble_used) as ensemble_count
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2024-11-22'
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE);
"

# Check worker auto-scaling
gcloud run services describe prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --format="value(status.traffic[0].latestRevision.instances)"
```

**Success Criteria:**
- ✅ Coordinator accepts batch request
- ✅ Worker scales up to handle load (2-10 instances)
- ✅ Predictions for ~450 players completed
- ✅ Batch completes within 10 minutes
- ✅ No failed predictions
- ✅ Worker scales back down after completion

---

## Phase 2: Unit Test Development (Post-E2E)

**When:** After e2e tests pass
**Duration:** ~4-6 hours
**Goal:** Comprehensive unit test coverage

### Testing Framework

```python
# Use existing test infrastructure
# Location: predictions/worker/tests/
# predictions/coordinator/tests/

# Framework: pytest
# Coverage: pytest-cov
```

### Unit Tests to Create

#### 1. Prediction Systems Tests

**File:** `predictions/worker/tests/test_prediction_systems.py`

**Tests:**
```python
class TestMovingAverageBaseline:
    def test_predict_with_valid_features()
    def test_predict_with_missing_features()
    def test_confidence_score_calculation()
    def test_handles_edge_cases()

class TestZoneMatchupV1:
    def test_predict_with_zone_data()
    def test_predict_without_zone_data()
    def test_confidence_based_on_data_quality()
    def test_matchup_weighting()

class TestSimilarityBalancedV1:
    def test_predict_with_similar_games()
    def test_predict_with_no_similar_games()
    def test_similarity_scoring()
    def test_balancing_factors()

class TestXGBoostV1:
    def test_predict_with_mock_model()
    def test_predict_with_trained_model()
    def test_feature_validation()
    def test_model_loading()

class TestEnsembleV1:
    def test_combine_all_systems()
    def test_combine_partial_systems()
    def test_confidence_weighting()
    def test_fallback_behavior()
```

#### 2. Data Loader Tests

**File:** `predictions/worker/tests/test_data_loaders.py`

**Tests:**
```python
class TestFeatureLoader:
    def test_load_player_features()
    def test_load_batch_features()
    def test_handle_missing_data()
    def test_cache_behavior()
    def test_query_optimization()

class TestHistoricalDataLoader:
    def test_load_player_history()
    def test_load_opponent_data()
    def test_date_range_filtering()
    def test_aggregation_logic()
```

#### 3. Worker Request Handling Tests

**File:** `predictions/worker/tests/test_worker.py`

**Tests:**
```python
class TestWorkerEndpoints:
    def test_health_endpoint()
    def test_predict_endpoint_valid_request()
    def test_predict_endpoint_invalid_request()
    def test_predict_endpoint_missing_features()
    def test_pubsub_message_parsing()
    def test_error_handling()
    def test_bigquery_writes()
    def test_pubsub_completion_messages()
```

#### 4. Coordinator Logic Tests

**File:** `predictions/coordinator/tests/test_coordinator.py`

**Tests:**
```python
class TestCoordinator:
    def test_start_batch()
    def test_load_players_for_date()
    def test_fan_out_to_workers()
    def test_track_completion()
    def test_batch_status_reporting()
    def test_error_handling()
    def test_duplicate_request_handling()

class TestPlayerLoader:
    def test_load_active_players()
    def test_filter_by_game_date()
    def test_handle_no_games()

class TestProgressTracker:
    def test_track_completion()
    def test_concurrent_completions()
    def test_thread_safety()
    def test_batch_summary()
```

### Test Execution

```bash
# Run all tests
cd /home/naji/code/nba-stats-scraper
pytest predictions/ -v --cov=predictions --cov-report=html

# Run specific test suite
pytest predictions/worker/tests/test_prediction_systems.py -v

# Run with coverage report
pytest predictions/ --cov=predictions --cov-report=term-missing
```

---

## Phase 3: Integration Tests (Optional)

**When:** After unit tests complete
**Goal:** Test component interactions

### Integration Test Scenarios

1. **Worker → BigQuery Integration**
   - Test actual BigQuery writes
   - Verify schema compatibility
   - Check transaction handling

2. **Coordinator → Worker Integration**
   - Test Pub/Sub message flow
   - Verify request/response cycle
   - Check error propagation

3. **Feature Loading Integration**
   - Test against actual BigQuery tables
   - Verify data transformations
   - Check performance under load

---

## Phase 4: Continuous Testing

**When:** Ongoing after deployment
**Goal:** Maintain system health

### Daily Monitoring Tests

**Script:** `bin/predictions/test_prediction_health.sh`

```bash
#!/bin/bash
# Daily health check for prediction system

# 1. Test single prediction
# 2. Check recent prediction volume
# 3. Verify average confidence scores
# 4. Check for errors in logs
# 5. Monitor latency metrics
```

### Weekly Load Tests

- Simulate 1000 player batch
- Measure end-to-end latency
- Check auto-scaling behavior
- Verify cost efficiency

### Accuracy Tracking (Future)

- Compare predictions to actual outcomes
- Track system accuracy over time
- Identify drift in model performance
- Trigger retraining when needed

---

## Success Criteria

### E2E Testing Complete When:
- ✅ All 3 e2e tests pass
- ✅ No critical errors in logs
- ✅ Predictions written to BigQuery
- ✅ Worker auto-scaling works
- ✅ Coordinator batch completes successfully

### Unit Testing Complete When:
- ✅ Test coverage >80% for all modules
- ✅ All prediction systems have unit tests
- ✅ Data loaders tested with mocks
- ✅ Worker and coordinator logic tested
- ✅ CI/CD pipeline runs tests automatically

### Production-Ready When:
- ✅ E2E tests pass consistently
- ✅ Unit test suite comprehensive
- ✅ Monitoring in place
- ✅ Runbook created for common issues
- ✅ Performance benchmarks established

---

## Test Data Requirements

### For E2E Testing:
- Game date with real data: `2024-11-22`
- Test player: `lebron-james` (known to have data)
- Feature store has data for this date

### For Unit Testing:
- Mock BigQuery responses
- Sample feature vectors
- Historical game data snapshots
- Edge case scenarios

---

## Known Limitations

### Current Testing Gaps:

1. **XGBoost Mock Model:**
   - Using placeholder predictions
   - Can't test real model inference yet
   - Will update tests after model training

2. **Load Testing:**
   - Haven't tested max throughput yet
   - Unknown behavior at 1000+ concurrent predictions
   - Will perform after unit tests

3. **Accuracy Validation:**
   - No ground truth data yet
   - Can't measure prediction accuracy
   - Will implement after NBA season starts

---

## Next Steps After Deployment

1. **Immediate (Today):**
   - ✅ Complete deployment
   - ⏳ Run all e2e tests
   - ⏳ Document any issues found
   - ⏳ Create GitHub issues for unit test tasks

2. **This Week:**
   - Create unit test suite (4-6 hours)
   - Set up pytest CI/CD integration
   - Write test documentation
   - Create test data fixtures

3. **This Month:**
   - Integration tests for BigQuery
   - Load testing (1000+ players)
   - Performance benchmarking
   - Train XGBoost model and update tests

---

## Rollback Plan

If e2e tests reveal critical issues:

```bash
# 1. Check Cloud Run revisions
gcloud run revisions list \
  --service=prediction-worker \
  --project=nba-props-platform \
  --region=us-west2

# 2. Rollback to previous revision (or delete service)
gcloud run services delete prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --quiet

# 3. Document issues in GitHub
# 4. Create unit tests to reproduce issues
# 5. Fix code locally
# 6. Re-deploy with fixes
```

---

## Documentation Updates

### Files Updated:
- ✅ `/docs/deployment/07-phase5-testing-strategy.md` (this file)
- ⏳ `/docs/deployment/06-phase5-prediction-deployment-plan.md` (add testing reference)
- ⏳ `predictions/worker/README.md` (add testing section)
- ⏳ `predictions/coordinator/README.md` (add testing section)

### Files to Create:
- `predictions/worker/tests/README.md` - Test suite documentation
- `predictions/coordinator/tests/README.md` - Test suite documentation
- `bin/predictions/test_prediction_health.sh` - Daily health check script

---

**Testing Strategy:** Pragmatic and efficient
**Current Status:** Deployment in progress, ready for e2e testing
**Next Action:** Run e2e tests immediately after deployment completes

**Last Updated:** 2025-11-23
