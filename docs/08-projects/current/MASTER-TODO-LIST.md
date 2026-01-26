# Master TODO List - System Hardening & Optimization
**Created:** January 21, 2026
**Updated:** January 27, 2026
**Source:** 6 Agent Deep-Dive Investigations + Tier 0-3 Audit
**Total Items:** 132.5 hours remaining (9.5h complete)
**Strategy:** Robustness FIRST, Cost Savings BONUS

---

## 🚨 ACTIVE REMINDERS

### ⏸️ CloudFront IP Block Recovery - Check Periodically
**Priority:** 🟡 MEDIUM | **Type:** Data Completeness | **Check:** Every 6-12 hours

**Quick Check:**
```bash
curl -I "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0022500651.json" | head -1
# Waiting for: HTTP/2 200 (currently: HTTP/2 403)
```

**Full Details:** `docs/02-operations/ML-MONITORING-REMINDERS.md` → "CloudFront IP Block Recovery"

---

## QUICK REFERENCE

**Status Legend:**
- ✅ COMPLETE
- 🚧 IN PROGRESS
- ⏸️ BLOCKED
- 📋 READY
- 🔴 CRITICAL
- 🟠 HIGH
- 🟡 MEDIUM

**Current Focus:** Week 1 High-Value Quick Wins (18-20 hours)

---

## TIER 0: COMPLETE ✅ (8.5 hours)

| Item | Status | Time | Savings | Type |
|------|--------|------|---------|------|
| Query Caching Enabled | ✅ | 1h | $15-20/month | BOTH |
| SQL Injection Fixed | ✅ | 2h | Security | ROBUSTNESS |
| Bare Except Blocks Fixed | ✅ | 3h | Debugging | ROBUSTNESS |
| Secrets Verified | ✅ | 0.5h | Security | ROBUSTNESS |
| Timeout Additions (Partial) | ✅ | 2h | Reliability | ROBUSTNESS |

**Achievements:** $15-20/month savings, 8 CRITICAL security issues fixed, 7 error masking patterns eliminated

---

## TIER 1.1: ADD MISSING TIMEOUTS (3h remaining) 🚧

### Status: PARTIALLY COMPLETE (1h of 4h done)

**Completed:**
- ✅ `completeness_checker.py` (3 methods, 60s timeout)
- ✅ `odds_preference.py` (4 methods, 60s timeout)
- ✅ `odds_player_props_preference.py` (5 methods, 60s timeout)
- ✅ Verified: `batch_staging_writer.py`, `data_loaders.py`, `bigquery_utils.py` already have timeouts

**Remaining Work:**
- 📋 Search scrapers/ for missing timeouts
- 📋 Search bin/ scripts for missing timeouts
- 📋 Integration testing
- 📋 Documentation completion

**Priority:** 🔴 CRITICAL (prevents worker hangs, cascade failures)

**Checklist:**
```
[ ] Search scrapers/**/*.py for .result() without timeout
[ ] Search bin/**/*.py for .result() without timeout
[ ] Add timeout constants/configuration (QUERY_TIMEOUT_SECONDS = 60, 120, 300, 600)
[ ] Test timeout behavior (mock BigQuery timeout)
[ ] Document timeout standards in README
```

---

## TIER 1.2: PARTITION FILTERS (4h) 📋

### Expected Savings: $22-27/month + prevents full table scans

**Priority:** 🔴 CRITICAL (highest single cost optimization)

**Key Tables Needing `require_partition_filter=true`:**
1. predictions.player_prop_predictions
2. nba_reference.processor_run_history
3. nba_raw.* (18+ tables)

**Implementation Steps:**
```
[ ] 1. Audit all table schemas for partitioning
      - Find partitioned tables: grep -r "PARTITION BY" schemas/bigquery/
      - Check if require_partition_filter is set

[ ] 2. Add require_partition_filter=true to table OPTIONS
      - Update schemas/bigquery/predictions/*.sql
      - Update schemas/bigquery/nba_raw/*.sql
      - Update schemas/bigquery/nba_reference/*.sql

[ ] 3. Update health check queries to use date filters
      - bin/alerts/health_checks/*.py
      - Add WHERE game_date/cache_date filters

[ ] 4. Update daily summary queries
      - bin/alerts/daily_summary/main.py
      - Add WHERE clauses to prevent full scans

[ ] 5. Test all queries don't break
      - Run health checks manually
      - Verify no errors from missing partition filters

[ ] 6. Deploy schema changes
      - Apply ALTER TABLE statements to prod
      - Monitor for query failures

[ ] 7. Validate savings
      - Check BigQuery bytes scanned before/after
      - Calculate actual cost reduction
```

**Files to Modify:**
- schemas/bigquery/predictions/player_prop_predictions.sql
- schemas/bigquery/nba_raw/*.sql (18 tables)
- bin/alerts/health_checks/*.py
- bin/alerts/daily_summary/main.py

**Estimated Time:** 4 hours
**Risk:** Low (additive, doesn't change query logic)

---

## TIER 1.3: MATERIALIZED VIEWS (8h) 📋

### Expected Savings: $14-18/month + faster queries

**Priority:** 🟠 HIGH

**Views to Create:**

### 1. odds_api_game_lines_preferred_mv ($6-8/month savings)
```sql
CREATE MATERIALIZED VIEW `nba_raw.odds_api_game_lines_preferred_mv`
PARTITION BY game_date
OPTIONS(
  enable_refresh = true,
  refresh_interval_minutes = 60
) AS
SELECT
  game_id,
  game_date,
  -- DraftKings preference logic
  COALESCE(dk.home_spread, fd.home_spread) as home_spread,
  COALESCE(dk.home_total, fd.home_total) as home_total,
  ...
FROM nba_raw.odds_api_game_lines
```

**Checklist:**
```
[ ] Create DDL for odds_api_game_lines_preferred_mv
[ ] Update coordinator to query MV instead of base table
[ ] Test refresh schedule (60 min appropriate?)
[ ] Monitor refresh costs vs query savings
[ ] Add MV health check
```

### 2. current_season_players_mv ($4-6/month savings)
```sql
CREATE MATERIALIZED VIEW `nba_reference.current_season_players_mv`
OPTIONS(
  enable_refresh = true,
  refresh_interval_minutes = 1440  -- Daily
) AS
SELECT ...
FROM nba_raw.espn_team_rosters
WHERE season = EXTRACT(YEAR FROM CURRENT_DATE())
```

**Checklist:**
```
[ ] Create DDL for current_season_players_mv
[ ] Update processors to query MV
[ ] Test daily refresh
[ ] Monitor refresh costs
```

### 3. data_quality_summary_mv ($4-6/month savings)
```sql
CREATE MATERIALIZED VIEW `nba_analytics.data_quality_summary_mv`
PARTITION BY summary_date
OPTIONS(
  enable_refresh = true,
  refresh_interval_minutes = 360  -- Every 6 hours
) AS
SELECT
  summary_date,
  -- Complex window functions
  ...
FROM ...
```

**Checklist:**
```
[ ] Create DDL for data_quality_summary_mv
[ ] Update daily summary script to query MV
[ ] Test 6-hour refresh
[ ] Monitor refresh costs
```

**Estimated Time:** 8 hours (3h + 2h + 3h)
**Risk:** Medium (must test refresh schedules carefully)

---

## AGENT FINDINGS: CRITICAL FIXES (18h) 🔴

### Priority: IMMEDIATE (Do before TIER 1.2-1.3)

These items were discovered by the 6 agent investigations and should be fixed ASAP:

### 1. FIX SILENT FAILURES (4h) 🔴
**Agent:** Error Handling
**Issue:** Functions return None/False on error without propagating
**Impact:** Data loss, pipeline doesn't know tasks failed

**Files to Fix:**
```
[ ] bin/backfill/verify_phase2_for_phase3.py:78-80
    - Add result objects (status, data, error)
    - Re-raise exceptions instead of swallowing

[ ] shared/utils/bigquery_utils.py:92-95
    - Return Result(success=False, error=e) instead of empty list
    - Update 8 callsites to check .success

[ ] bin/validate_pipeline.py:268-272
    - Propagate validation failures

[ ] predictions/coordinator/missing_prediction_detector.py:120-122
    - Don't continue on error
```

### 2. ADD DISTRIBUTED LOCK TESTS (4h) 🔴
**Agent:** Race Conditions + Testing
**Issue:** Session 92 fix is UNTESTED, could regress
**Impact:** Duplicate rows, data corruption

**Tests to Add:**
```
[ ] test_batch_staging_writer_race_conditions.py
    - Two concurrent consolidations for same game_date
    - Verify only one succeeds, other waits
    - Lock timeout exhaustion (60 retries × 5s)
    - Stale lock cleanup

[ ] test_distributed_lock_timeout.py
    - Lock held for exactly 300 seconds
    - Lock held for 301 seconds (expired)
    - TTL not yet fired

[ ] test_lock_deadlock_scenarios.py
    - Two operations acquire simultaneously
    - Firestore unavailable during acquisition
```

### 3. ADD ARRAYUNION BOUNDARY TESTS (3h) 🔴
**Agent:** Race Conditions + Testing
**Issue:** Batches >1000 players silently fail, predictions stuck forever
**Impact:** Complete loss of batch

**Tests to Add:**
```
[ ] test_firestore_arrayunion_limits.py
    - Batch with exactly 1000 players (should work)
    - Batch with 1001 players (tracking breaks)
    - Verify subcollection fallback works

[ ] test_subcollection_migration_safety.py
    - Dual-write mode consistency (both structures in sync)
    - Validation sampling (10% sampling isn't missing issues)
    - Feature flag combinations (all 8: 2^3)
```

### 4. CREATE PROCESSOR_EXECUTION_LOG TABLE (2h) 🔴
**Agent:** Monitoring & Observability
**Issue:** Phase 2-5 logs expire after 30 days, can't debug production
**Impact:** Can't answer "Did Phase 3 complete?" after 30 days

**Implementation:**
```
[ ] Create BigQuery table schema
    CREATE TABLE nba_monitoring.processor_execution_log (
      execution_id STRING NOT NULL,
      processor_name STRING NOT NULL,
      execution_start_timestamp TIMESTAMP NOT NULL,
      execution_end_timestamp TIMESTAMP,
      status STRING NOT NULL,  -- 'started', 'completed', 'failed'
      duration_seconds FLOAT64,
      rows_processed INT64,
      error_message STRING,
      ...
    )
    PARTITION BY DATE(execution_start_timestamp)

[ ] Add logging utility function (like log_scraper_step)
    log_processor_execution(logger, processor_name, status, ...)

[ ] Update Phase 2-3 processors
    - processors/raw/nbacom/*.py
    - processors/analytics/*.py
    - processors/precompute/*.py

[ ] Create Grafana dashboard
    - Processor execution duration over time
    - Success rate by processor
    - Errors by processor
```

### 5. ADD SCHEMA CONSTRAINTS (2h) 🔴
**Agent:** Data Quality
**Issue:** Bad data can be stored (negative confidence, wrong recommendations)
**Impact:** Grading metrics invalid, API responses broken

**Schema Updates:**
```sql
[ ] ALTER TABLE predictions.player_prop_predictions
    ADD CONSTRAINT check_confidence_range
    CHECK (confidence_score BETWEEN 0 AND 100)

[ ] ALTER TABLE predictions.player_prop_predictions
    ADD CONSTRAINT check_predicted_points_positive
    CHECK (predicted_points >= 0)

[ ] ALTER TABLE predictions.player_prop_predictions
    ADD CONSTRAINT check_recommendation_valid
    CHECK (recommendation IN ('OVER', 'UNDER', 'PASS', 'NO_LINE'))

[ ] Test constraint enforcement
    - Try to INSERT bad data
    - Verify rejection with clear error message
```

### 6. BATCH NAME LOOKUPS (Quick Win, 2h) 🟠
**Agent:** Performance
**Issue:** 200 individual queries daily instead of 4 batched queries
**Impact:** 2.5 minutes wasted daily

**Implementation:**
```python
[ ] Update shared/utils/player_name_resolver.py
    def resolve_names_batch(self, names: List[str]) -> Dict[str, str]:
        # Single query with IN clause
        query = """
        SELECT alias_lookup, nba_canonical_display
        FROM `nba_reference.player_aliases`
        WHERE alias_lookup IN UNNEST(@names)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("names", "STRING", names)
            ]
        )
        results = self.bq_client.query(query, job_config=job_config).to_dataframe()
        return dict(zip(results['alias_lookup'], results['nba_canonical_display']))

[ ] Update call sites to use batch function
    - Collect 50-100 names
    - Call resolve_names_batch once
    - Cache results
```

### 7. ADD BIGQUERY INDEXES (Quick Win, 1h) 🟠
**Agent:** Performance
**Issue:** Missing indexes cause full table scans (50-150 seconds per run)
**Impact:** Slow queries, unnecessary costs

**Indexes to Add:**
```sql
[ ] Index on player_aliases.alias_lookup
    -- Check if exists, add if missing

[ ] Index on nba_players_registry.player_lookup
    -- Check if exists, add if missing

[ ] Index on player_daily_cache.(player_lookup, cache_date)
    -- Composite index for common query pattern

[ ] Verify indexes are used
    - Run EXPLAIN on queries
    - Check "Index Scan" in execution plan
```

---

## TIER 1.4-1.6: TESTS + SECURITY (18h) 📋

**Priority:** 🟠 HIGH (after critical fixes above)

### TIER 1.4: Critical Tests (12h)

**Files Needing Tests:**
```
[ ] test_batch_staging_writer.py (4h)
    - Race condition scenarios (covered in Agent Findings #2 above)
    - Cleanup failures
    - Schema mismatch
    - MERGE deduplication

[ ] test_distributed_lock.py (3h)
    - Covered in Agent Findings #2 above

[ ] test_data_freshness_validator.py (3h)
    - Validation logic edge cases
    - Stale data detection
    - Threshold calculations

[ ] test_prediction_accuracy_processor.py (2h)
    - Accuracy calculations
    - Grading logic
    - Edge cases (no games, missing data)
```

### TIER 1.5: Fix SSL Verification (2h)

**Priority:** 🟠 HIGH (security)

```
[ ] Fix scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py
    - Remove session.verify = False
    - Remove urllib3.disable_warnings()
    - Use proper certificates or proxy certs
    - Test with valid certificates
```

### TIER 1.6: Add Security Headers (4h)

**Priority:** 🟡 MEDIUM (security hardening)

**Headers to Add:**
```
[ ] CORS headers to all Flask apps
    Access-Control-Allow-Origin: https://trusted-domain.com
    Access-Control-Allow-Methods: GET, POST
    Access-Control-Allow-Headers: Content-Type, Authorization

[ ] CSP (Content Security Policy)
    Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'

[ ] X-Frame-Options
    X-Frame-Options: DENY

[ ] X-Content-Type-Options
    X-Content-Type-Options: nosniff

[ ] Strict-Transport-Security
    Strict-Transport-Security: max-age=31536000; includeSubDomains
```

**Files to Update:**
```
[ ] scrapers/main_scraper_service.py
[ ] data_processors/raw/main_processor_service.py
[ ] data_processors/analytics/main_analytics_service.py
[ ] data_processors/precompute/main_precompute_service.py
[ ] predictions/coordinator/coordinator.py
[ ] predictions/worker/worker.py
```

---

## TIER 2: PERFORMANCE OPTIMIZATIONS (58h) 📋

**Priority:** 🟡 MEDIUM (high value but not blocking)

### Performance Quick Wins (20h)

**Priority Order:**

1. **.to_dataframe() Optimization (16h)** 🟠
   - **Impact:** 15-30 seconds saved per run
   - **Agent Finding:** 836 calls materialize full results
   ```
   [ ] Enable DataFrame streaming (4h)
       - Use to_arrow() or streaming results
       - Update feature_extractor.py
       - Update ml_feature_store_processor.py

   [ ] Add batch flushing (4h)
       - Stream writes to BigQuery in batches of 50-100 rows
       - Don't accumulate all 400 players in memory

   [ ] Clear memory caches between phases (1h)
       - Add cleanup() method to feature_extractor.py
       - Call after each extraction phase

   [ ] Test memory usage improvements (2h)
       - Profile before/after
       - Measure GC overhead reduction

   [ ] Replace .iterrows() with vectorization (5h)
       - 26 files to update
       - upcoming_player_game_context_processor.py (16 calls)
       - player_composite_factors_processor.py (22 calls)
       - Others
   ```

2. **N+1 Query Fixes (8h)** 🟠
   - **Impact:** 5-10 minutes saved per day
   ```
   [ ] Batch resolution cache lookups (4h)
       - shared/utils/player_registry/resolution_cache.py:115
       - Single query with IN clause instead of 50-100 individual SELECTs

   [ ] Connection pooling for BigQuery (4h)
       - Implement pool using shared/clients/http_pool.py
       - Reuse clients across processor instances
       - Save 5-10 seconds × 500 processors = 5-15 minutes daily
   ```

3. **Registry Cache Optimization (2h)** 🟡
   - **Impact:** $6-8/month savings
   ```
   [ ] Implement distributed cache for player name resolution
       - Prevent duplicate AI resolution calls ($15/day wasted)
       - Use Redis or Firestore for centralized cache
       - Save $200-300/month
   ```

### Integration Tests (20h)

```
[ ] End-to-end pipeline tests (12h)
    - Scraper → Processor → Prediction flow
    - Mock external APIs
    - Verify data consistency

[ ] Data loader tests (4h)
    - Query timeout edge cases
    - Empty results handling
    - Partial batch loads
    - Cache TTL edge cases

[ ] Prediction system validation tests (4h)
    - Feature validation (None, missing fields, NaN)
    - Confidence boundary cases
    - Output validation
    - Model loading failures
```

### Grading Tests (12h)

```
[ ] Accuracy calculation tests (6h)
    - Edge cases (no games, missing data)
    - Grading logic verification
    - Confidence vs accuracy correlation

[ ] Coverage monitor tests (3h)
    - Boundary cases (exactly 90%, 89.9%, 85%)
    - Coverage calculation accuracy
    - Missing predictions detection

[ ] Performance regression tests (3h)
    - Ensure optimizations don't break functionality
    - Benchmark key operations
```

---

## TIER 3: INFRASTRUCTURE (32h) 📋

**Priority:** 🟡 MEDIUM (long-term improvements)

### Cost Optimizations (20h)

1. **Clustering Optimization (4h)** - $5-7/month savings
   ```
   [ ] Add clustering to frequently queried tables
   [ ] Test query performance improvements
   [ ] Monitor cost reduction
   ```

2. **Partition Requirements (4h)** - $4-6/month savings
   ```
   [ ] Enforce partition requirements on all queries
   [ ] Update query templates
   [ ] Test enforcement
   ```

3. **Schedule Cache (4h)** - $3-5/month savings
   ```
   [ ] Implement schedule caching layer
   [ ] Reduce repeated schedule queries
   [ ] Monitor cache hit rate
   ```

4. **Validation Filters (4h)** - $5-7/month savings
   ```
   [ ] Add partition filters to validation queries
   [ ] Update validation scripts
   [ ] Test performance improvements
   ```

5. **Various View Materializations (4h)** - $3-4/month savings
   ```
   [ ] Identify additional views to materialize
   [ ] Create DDL
   [ ] Monitor refresh costs
   ```

### Monitoring Tests (16h)

```
[ ] Processor execution logging tests (6h)
    - Test log writes succeed
    - Test correlation ID preservation
    - Test error logging

[ ] End-to-end tracing tests (6h)
    - Verify correlation IDs thread through all stages
    - Test trace queries return correct data

[ ] Alert integration tests (4h)
    - Test alert triggering
    - Test alert deduplication
    - Test severity routing
```

---

## SUMMARY BY PRIORITY

### 🔴 CRITICAL (Must Do First) - 18 hours
1. Fix Silent Failures (4h)
2. Add Distributed Lock Tests (4h)
3. Add ArrayUnion Boundary Tests (3h)
4. Create processor_execution_log Table (2h)
5. Add Schema Constraints (2h)
6. Batch Name Lookups (2h)
7. Add BigQuery Indexes (1h)

**Impact:** Prevents 9 CRITICAL failure modes, saves 2-3 minutes/day

### 🟠 HIGH (Do Next) - 37 hours
1. Complete TIER 1.1 Timeouts (3h)
2. TIER 1.2 Partition Filters (4h) → $22-27/month
3. TIER 1.3 Materialized Views (8h) → $14-18/month
4. TIER 1.4 Critical Tests (12h)
5. .to_dataframe() Optimization (8h) → 15-30 sec/run
6. N+1 Query Fixes (8h) → 5-10 min/day

**Impact:** $36-45/month savings, 15-20 minutes/day faster, 70% test coverage

### 🟡 MEDIUM (Do After High) - 77.5 hours
1. TIER 1.5-1.6 Security (6h)
2. Performance Optimizations remaining (10h)
3. Integration + Grading Tests (32h)
4. TIER 3 Infrastructure (32h)

**Impact:** $17-25/month additional savings, comprehensive monitoring

---

## PROGRESS TRACKING

**Total Hours:** 132.5
**Completed:** 9.5 (7%)
**Remaining:** 123 (93%)

**Week 1 Target:** Complete CRITICAL items (18h) + HIGH priority Tier 1.2-1.3 (12h) = 30h
**Week 2-3 Target:** Complete remaining HIGH items (25h) + start MEDIUM (15h) = 40h
**Week 4 Target:** Complete MEDIUM items (40h)

**Monthly Target:** 110-130 hours completed
**Expected Outcomes:**
- Cost Savings: $80-120/month ($960-1,440/year)
- Performance: 40-107 min/day faster
- Test Coverage: 0% → 70%+
- Security: All CRITICAL issues resolved
- Reliability: Timeouts, error handling, monitoring complete

---

**Last Updated:** 2026-01-21 19:10 PT
**Next Session:** Start with CRITICAL fixes (18 hours)
**Current Branch:** week-1-improvements
