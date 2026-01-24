# Session 10 - Comprehensive Resilience TODO

**Date:** 2026-01-24
**Session:** 10 (Continuation of Session 7-9)
**Status:** In Progress
**Agents Deployed:** 21 parallel agents

---

## Executive Summary

Session 10 deployed 21 parallel agents to analyze and fix resilience issues across the codebase. This document consolidates all findings into actionable TODOs.

---

## P0 - CRITICAL (Fix Immediately)

### 1. Prediction Worker - No Crash Recovery
**Risk:** HIGH - Data loss on restart
**Files:**
- `predictions/worker/worker.py`

**Issues:**
- No state persistence - in-memory progress lost on restart
- No heartbeat during prediction processing
- No timeout handling for individual predictions
- 4-hour Cloud Run timeout before restart

**Fix:**
- [ ] Add Firestore state persistence for batch progress
- [ ] Add ProcessorHeartbeat to worker.process_prediction()
- [ ] Add per-system timeout with fallback

### 2. SQL Injection Vulnerabilities - FIXED
**Risk:** HIGH - Security
**Files:**
- `orchestration/cloud_functions/auto_backfill_orchestrator/main.py` (lines 148-151) - FIXED
- `orchestration/cloud_functions/prediction_health_alert/main.py` - TODO

**Fix:**
- [x] Use BigQuery ScalarQueryParameter for all user inputs (auto_backfill_orchestrator)
- [ ] Create Pydantic models for request validation

### 3. Silent Publishing Failures - FIXED
**Risk:** HIGH - Message loss
**Files:**
- `shared/publishers/unified_pubsub_publisher.py` (lines 256-302) - FIXED

**Issue:** Pub/Sub publishing failures logged but suppressed, no guarantee messages reach topic

**Fix:**
- [ ] Add DLQ routing for failed publishes
- [ ] Implement error classification (transient vs permanent)

### 4. Bare Exception Handler - FIXED
**Risk:** HIGH - Hidden failures
**File:** `shared/processors/components/writers.py:149` - FIXED

**Pattern:** `except: pass`

**Fix:**
- [x] Add debug logging for cleanup failures

---

## P1 - HIGH PRIORITY (Fix Soon)

### 5. BigQuery Queries Without Timeouts (10 instances) - FIXED
**Files:**
- `bin/bdl_latency_report.py` - FIXED
- `bin/alerts/daily_summary/main.py` (4 instances) - FIXED
- `bin/validate_historical_completeness.py` - FIXED
- `bin/scraper_completeness_check.py` - FIXED
- `bin/validation/validate_feature_store_v33.py` - FIXED

**Fix:**
- [x] Add `.result(timeout=60)` to all BigQuery queries

### 6. Cloud Functions Without Request Validation (22 functions)
**Files:**
- `orchestration/cloud_functions/auto_backfill_orchestrator/main.py`
- `orchestration/cloud_functions/prediction_health_alert/main.py`
- `orchestration/cloud_functions/pipeline_dashboard/main.py`
- `orchestration/cloud_functions/transition_monitor/main.py`
- `orchestration/cloud_functions/phase2_to_phase3/main.py`
- 17+ others

**Fix:**
- [ ] Create Pydantic models for all request parameters
- [ ] Make validation mandatory (remove try-except fallbacks)

### 7. Missing Dead Letter Queues (10+ topics)
**Topics without DLQ:**
- `phase3-trigger`
- `phase4-trigger`
- `phase3-analytics-complete`
- `phase4-precompute-complete`
- `phase5-predictions-complete`
- `phase6-export-trigger`
- `phase6-export-complete`

**Fix:**
- [ ] Configure DLQ for all critical pipeline topics
- [ ] Add error classification for transient vs permanent failures
- [ ] Update DLQ Monitor to cover all topics

### 8. Fresh BigQuery Clients (145 files)
**High-Priority Files:**
- `predictions/coordinator/shared/utils/bigquery_utils.py` (6 functions)
- `predictions/coordinator/shared/utils/odds_preference.py` (global client)
- `predictions/worker/shared/utils/bigquery_utils.py` (6 functions)
- `predictions/coordinator/player_loader.py:59`
- `predictions/worker/data_loaders.py:62`

**Fix:**
- [ ] Replace module-level clients with `get_bigquery_client()` from pool
- [ ] Update utility functions to use pooled client

### 9. Direct HTTP Requests Without Pooling (187 instances)
**High-Priority Files:**
- `shared/utils/notification_system.py`
- `shared/utils/processor_alerting.py`
- `shared/utils/slack_retry.py`
- `shared/utils/rate_limiter.py`
- `shared/utils/external_service_circuit_breaker.py`

**Fix:**
- [ ] Replace `requests.post/get()` with `get_http_session()` from http_pool

---

## P2 - MEDIUM PRIORITY (Fix in Next Sprint)

### 10. Error Logs Missing Stack Traces (40+ files)
**Pattern:** `logger.error(f"Error: {e}")` without `exc_info=True`

**Files:**
- `bin/bdl_latency_report.py` (lines 226, 445)
- `bin/validate_pipeline.py` (line 273)
- `bin/scraper_completeness_check.py` (lines 83, 158, 210, 366)
- `bin/testing/replay_pipeline.py` (lines 274, 461)
- `bin/backfill/verify_phase*.py` (multiple)
- `predictions/coordinator/batch_staging_writer.py` (lines 213, 223)

**Fix:**
- [ ] Replace `logger.error()` with `logger.exception()` in except blocks
- [ ] Or add `exc_info=True` to all error logs

### 11. Silent Failure Patterns (53+ locations)
**Critical Files:**
- `shared/processors/components/writers.py:149` (bare except)
- `backfill_jobs/scrapers/odds_api_lines/odds_api_lines_scraper_backfill.py:408`
- `bin/spot_check_features.py:139`
- `scrapers/bettingpros/bp_mlb_player_props.py:532`
- `scrapers/mlb/external/mlb_umpire_stats.py:204,231`

**Fix:**
- [ ] Add logging before silent returns
- [ ] Replace broad `except Exception` with specific types

### 12. Duplicated Pool Implementations (14 copies)
**Directories with copies:**
- `orchestration/cloud_functions/daily_health_summary/shared/clients/`
- `orchestration/cloud_functions/phase2_to_phase3/shared/clients/`
- `orchestration/cloud_functions/phase3_to_phase4/shared/clients/`
- `orchestration/cloud_functions/phase4_to_phase5/shared/clients/`
- `orchestration/cloud_functions/phase5_to_phase6/shared/clients/`
- `orchestration/cloud_functions/self_heal/shared/clients/`

**Fix:**
- [ ] Consolidate to import from shared library

### 13. Missing Structured Logging
**Missing Fields:**
- `run_id` / `correlation_id`
- `entity_id` (game_date, player_id)
- `operation` (download, transform, export)
- `error_category` (connection, timeout, validation)

**Fix:**
- [ ] Create centralized error logging utility
- [ ] Add structured fields to all error logs

### 14. BigQuery/GCS Pool Health Checks
**Files:**
- `shared/clients/bigquery_pool.py`
- `shared/clients/storage_pool.py`

**Missing:**
- Automatic reconnection on stale connections
- Health checks for connection validity
- Timeout configuration

**Fix:**
- [ ] Add health check methods
- [ ] Implement automatic reconnection

---

## P3 - LOW PRIORITY (Technical Debt)

### 15. Data Processor Input Validation (40+ processors)
**Base Class:** `data_processors/raw/processor_base.py`

**Fix:**
- [ ] Create Pydantic models for processor inputs
- [ ] Add validation to `run()` and `process_date()` methods

### 16. Circuit Breaker Coverage Gaps
**Not Protected:**
- Prediction worker model loading
- Database connection retries
- Scraper proxy rotation

**Fix:**
- [ ] Add circuit breaker to prediction worker GCS calls
- [ ] Add circuit breaker to scraper proxy endpoints

### 17. Checkpointing for Live Processing
**Currently Only:** Backfill jobs have checkpointing

**Missing:**
- Live Phase 2/3/4/5 processing
- Orchestration state transitions
- Prediction batch processing
- BigQuery query streaming

**Fix:**
- [ ] Add row-level checkpointing for large queries
- [ ] Persist orchestration state to Firestore

### 18. Idempotency for Phase Transitions
**Issue:** If `trigger_phase3()` called twice, might double-process

**Fix:**
- [ ] Add idempotency keys to prevent duplicate processing

### 19. Global Module-Level Clients (4 files)
**Files:**
- `predictions/coordinator/shared/utils/odds_preference.py:35`
- `predictions/coordinator/shared/utils/odds_player_props_preference.py:34`
- `predictions/worker/shared/utils/odds_preference.py:32`
- `predictions/worker/shared/utils/odds_player_props_preference.py:31`

**Issue:** Created at import, never cleaned up

**Fix:**
- [ ] Use lazy initialization with cleanup

---

## Statistics Summary

| Category | Count | Priority |
|----------|-------|----------|
| Prediction Worker Crash Recovery | 1 service | P0 |
| SQL Injection Vulnerabilities | 2 files | P0 |
| Silent Publishing Failures | 1 file | P0 |
| Bare Exception Handler | 1 location | P0 |
| BigQuery Queries Without Timeout | 10 instances | P1 |
| Cloud Functions Without Validation | 22 functions | P1 |
| Missing Dead Letter Queues | 10+ topics | P1 |
| Fresh BigQuery Clients | 145 files | P1 |
| Direct HTTP Without Pooling | 187 instances | P1 |
| Error Logs Missing Stack Traces | 40+ files | P2 |
| Silent Failure Patterns | 53+ locations | P2 |
| Duplicated Pool Implementations | 14 copies | P2 |
| Missing Structured Logging | Codebase-wide | P2 |
| BigQuery/GCS Pool Health Checks | 2 files | P2 |
| Data Processor Input Validation | 40+ processors | P3 |
| Circuit Breaker Coverage Gaps | 3 areas | P3 |
| Checkpointing for Live Processing | Multiple areas | P3 |
| Idempotency for Phase Transitions | Multiple areas | P3 |
| Global Module-Level Clients | 4 files | P3 |

---

## Session 10 Progress

### Agents Deployed
- 4 fixing agents (bare exceptions, project IDs)
- 17 exploration agents (completed findings above)

### Completed Exploration
- [x] Timeout configurations audit
- [x] Input validation gaps analysis
- [x] Dead letter queue coverage
- [x] Error recovery patterns
- [x] Connection pooling analysis
- [x] Error logging patterns
- [x] Silent failure patterns

### Pending Completion
- [ ] Fix bare exceptions in priority files
- [ ] Fix hardcoded project IDs
- [ ] Retry pattern gaps analysis
- [ ] Circuit breaker coverage
- [ ] Rate limiting patterns
- [ ] Graceful degradation patterns
- [ ] Health check patterns
- [ ] Idempotency patterns
- [ ] Memory/resource issues
- [ ] Concurrency issues
- [ ] Config management
- [ ] Monitoring gaps

---

## Next Steps

1. Wait for fixing agents to complete
2. Commit changes from fixing agents
3. Create targeted agents for P0 issues
4. Document all changes in handoff

---

## Related Documents

- [Session 7 Handoff](./SESSION-7-RESILIENCE-HANDOFF.md)
- [Self-Healing Pipeline Design](./SELF-HEALING-PIPELINE-DESIGN.md)
