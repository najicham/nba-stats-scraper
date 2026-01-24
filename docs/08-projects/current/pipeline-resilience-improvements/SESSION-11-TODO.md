# Session 11 - Pipeline Resilience Implementation

**Date:** 2026-01-23
**Session:** 11 (Continuation of Session 10)
**Status:** In Progress
**Focus:** P0/P1 Resilience Fixes

---

## Executive Summary

Session 11 implements the P0 and P1 fixes identified in Session 10's exploration phase. Focus areas:
1. Add retry patterns to BigQuery queries in data_loaders.py
2. Add circuit breaker to GCS model loading
3. Add GCS retry to storage_client.py
4. Add HTTP retry/pooling to processor_alerting.py

---

## P0 - CRITICAL (This Session)

### 1. Add BigQuery Retry to data_loaders.py (5 locations)
**Status:** [ ] Pending
**Risk:** HIGH - Transient BQ errors cause prediction failures
**File:** `predictions/worker/data_loaders.py`

**Lines needing `@retry_on_serialization` or transient error handling:**
- Line 343: `load_historical_games()` - individual player query
- Line 539: `load_game_context_batch()` - batch context query
- Line 682: `load_historical_games_batch()` - batch history query
- Line 825: `load_features_batch_for_date()` - batch features query
- Line 973: `_get_players_for_date()` - player list query

**Approach:**
- Add retry wrapper for transient errors (ServiceUnavailable, DeadlineExceeded)
- Keep existing specific exception handling
- Add structured logging for retry attempts

### 2. Add Circuit Breaker to GCS Model Loading
**Status:** [ ] Pending
**Risk:** HIGH - GCS failures cascade to all predictions
**Files:**
- `predictions/worker/prediction_systems/catboost_v8.py`
- `predictions/worker/prediction_systems/xgboost_v1.py`

**Approach:**
- Use `ExternalServiceCircuitBreaker` from `shared/utils/external_service_circuit_breaker.py`
- Add circuit breaker around GCS model download in `_load_model_from_path()`
- Fallback behavior already exists (uses fallback prediction)

---

## P1 - HIGH PRIORITY (This Session)

### 3. Add GCS Retry to storage_client.py
**Status:** [ ] Pending
**Risk:** MEDIUM - GCS transient failures cause data loss
**File:** `shared/utils/storage_client.py`

**Methods needing retry:**
- `upload_json()` - line 50, 53
- `download_json()` - line 81
- `upload_raw_bytes()` - line 106

**Approach:**
- Add `@retry_on_gcs_error` decorator using google-api-core retry
- Handle 429 (rate limit), 503 (service unavailable), 504 (timeout)

### 4. Add HTTP Retry to processor_alerting.py
**Status:** [ ] Pending
**Risk:** MEDIUM - Alert failures are silent
**File:** `shared/utils/processor_alerting.py`

**Issues:**
- Line 224: Direct `requests.post()` without retry/pooling
- SendGrid API calls lack retry

**Approach:**
- Use `get_http_session()` from http_pool for connection reuse
- Add retry for transient HTTP errors (429, 500, 502, 503, 504)

### 5. Commit Uncommitted Test Changes
**Status:** [ ] Pending
**Files:**
- `tests/processors/precompute/ml_feature_store/test_unit.py`
- `tests/processors/analytics/upcoming_player_game_context/conftest.py`
- `tests/processors/analytics/upcoming_player_game_context/test_integration.py`
- `predictions/shared/mock_data_generator.py`
- `validation/validators/raw/odds_api_props_validator.py`
- `backfill_jobs/raw/bdl_active_players/deploy.sh`

**Approach:**
- Review changes
- Commit if they're complete/valid

---

## P2 - MEDIUM PRIORITY (If Time Permits)

### 6. Add exc_info=True to Error Logs (High Impact Files)
**Status:** [ ] Pending
**Files (prioritized):**
- `bin/bdl_latency_report.py` (lines 226, 445)
- `bin/validate_pipeline.py` (line 273)
- `bin/scraper_completeness_check.py` (lines 83, 158, 210, 366)
- `predictions/coordinator/batch_staging_writer.py` (lines 213, 223)

### 7. Replace Direct requests with http_pool (High Impact Files)
**Status:** [ ] Pending
**Files:**
- `shared/utils/notification_system.py`
- `shared/utils/rate_limiter.py`

---

## Implementation Order

1. [ ] Review and commit uncommitted changes (cleanup)
2. [ ] Add BigQuery retry to data_loaders.py (P0)
3. [ ] Add circuit breaker to catboost_v8.py (P0)
4. [ ] Add circuit breaker to xgboost_v1.py (P0)
5. [ ] Add GCS retry to storage_client.py (P1)
6. [ ] Add HTTP retry to processor_alerting.py (P1)
7. [ ] Add exc_info=True to error logs (P2)
8. [ ] Update documentation

---

## Key Files to Modify

```
predictions/worker/data_loaders.py
predictions/worker/prediction_systems/catboost_v8.py
predictions/worker/prediction_systems/xgboost_v1.py
shared/utils/storage_client.py
shared/utils/processor_alerting.py
```

---

## Available Utilities

### Retry Utilities
- `shared/utils/bigquery_retry.py`
  - `@retry_on_serialization` - For BQ serialization conflicts
  - `@retry_on_quota_exceeded` - For BQ quota errors
  - `SERIALIZATION_RETRY` - Retry config object

### Circuit Breaker
- `shared/utils/external_service_circuit_breaker.py`
  - `ExternalServiceCircuitBreaker` - Main class
  - `get_service_circuit_breaker()` - Get singleton
  - `@circuit_breaker_protected()` - Decorator
  - `call_with_circuit_breaker()` - Wrapper function

### HTTP Pool
- `shared/clients/http_pool.py`
  - `get_http_session()` - Get pooled session with retry

---

## Testing Strategy

1. Unit tests for new retry/circuit breaker behavior
2. Verify existing tests still pass
3. Test graceful degradation scenarios

---

## Related Documents

- [Session 10 Comprehensive TODO](./SESSION-10-COMPREHENSIVE-TODO.md)
- [Session 10 Handoff](./SESSION-10-HANDOFF.md)
- [Self-Healing Pipeline Design](./SELF-HEALING-PIPELINE-DESIGN.md)
