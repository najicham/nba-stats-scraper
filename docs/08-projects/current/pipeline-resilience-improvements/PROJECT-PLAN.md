# Pipeline Resilience Improvements - Project Plan

## Executive Summary

This project addresses critical pipeline reliability issues discovered in Session 9:
- 6.6% Phase 3 success rate (target: 95%+)
- 26.8% Phase 4 success rate (target: 95%+)
- 5 services with deployment drift
- 2/7 games missing PBP data
- 4-24 hour issue detection delay

**Last Updated:** Session 11 (2026-01-29)

## Timeline

### Week 1: Critical Fixes (Complete)
| Task | Status | Owner | Notes |
|------|--------|-------|-------|
| Fix `track_source_coverage_event` | ✅ Done | Claude | Commit c7c1e999 |
| Push to origin | ✅ Done | Claude | |
| Create auto-deploy workflow | ✅ Done | Claude | `.github/workflows/auto-deploy.yml` |
| Create deploy-all-stale script | ✅ Done | Claude | `bin/deploy-all-stale.sh` |
| Deploy stale services | ⏳ Pending | User | Requires GCP_SA_KEY secret |
| Create project documentation | ✅ Done | Claude | This directory |

### Week 2: Validation Improvements (Session 10)
| Task | Status | Priority | Notes |
|------|--------|----------|-------|
| Create `validate-all.sh` unified command | ⏳ Pending | High | |
| Add phase boundary data quality checks | ✅ Done | High | Phase boundary validation |
| Add minutes coverage alerting | ✅ Done | Medium | Minutes coverage alerting |
| Add deployment health gate | ⏳ Pending | Medium | |
| Pre-extraction data check | ✅ Done | High | Validates data before extraction |
| Empty game detection | ✅ Done | High | Detects missing game data |
| Phase success monitor created | ✅ Done | High | Monitors phase success rates |

### Week 3: Auto-Recovery (Session 10)
| Task | Status | Priority | Notes |
|------|--------|----------|-------|
| Add BDB scraper retry logic | ✅ Done | High | 95%+ PBP coverage |
| Add NBA.com PBP fallback | ✅ Done | Medium | 99%+ coverage |
| Implement exponential backoff | ⏳ Pending | Medium | Better rate limit handling |
| Add betting data timeout | ⏳ Pending | Low | Graceful degradation |

### Session 10 Completed Tasks
| Task | Status | Notes |
|------|--------|-------|
| Pub/Sub backlog purge | ✅ Done | Stopped retry storm (7,160 retries/day → 0) |
| Retry queue SQL fix | ✅ Done | Parameterized queries already in place |
| Soft dependencies enablement | ✅ Done | All 5 Phase 4 processors use 80% threshold |
| BigQuery migration for data_source column | ✅ Done | 282,562 rows backfilled |
| Circuit breaker batching | ✅ Done | Already uses streaming inserts |
| Deploy all services | ✅ Done | All 5 services deployed with latest code |

### Session 11 Tasks
| Task | Status | Priority | Notes |
|------|--------|----------|-------|
| Reprocess Jan 27 missing games | ✅ Done | P0 | 1,077 rows (2 games: DET@DEN, BKN@PHX) |
| Verify pipeline health | ✅ Done | P0 | Retry storm resolved, only 2 errors today |
| Fix CleanupProcessor table name bug | ✅ Done | P0 | Was checking wrong table `bigdataball_pbp` |
| Update data_gaps table for resolved games | ✅ Done | P1 | Marked Jan 27 as resolved |
| Schedule phase_success_monitor | ⏳ Pending | P1 | Add Cloud Scheduler cron |
| Test NBA.com fallback end-to-end | ⏳ Pending | P2 | Verify fallback works |
| Add lineup reconstruction | ⏳ Pending | P2 | Long-term enhancement |

## Session 11 Root Cause Findings

### Why Jan 27 Games Weren't Auto-Processed

**Problem:** 2 games (DET@DEN, BKN@PHX) had files in GCS but weren't loaded to BigQuery.

**Root Cause:** Bug in `orchestration/cleanup_processor.py` line 265:
```python
# Was checking wrong table name
'bigdataball_pbp',  # WRONG - table doesn't exist

# Fixed to:
'bigdataball_play_by_play',  # CORRECT - actual table name
```

**Detection Gap:**
- The `scraper_execution_log` correctly logged all 7 games as "success"
- The `pipeline_reconciliation` Cloud Function correctly detected the gap at 5:15 AM
- The `data_gaps` table correctly tracked the missing games
- BUT: The `CleanupProcessor` couldn't find the files to republish because it was querying the wrong table

**Fix Applied:** Updated `cleanup_processor.py` to use correct table name `bigdataball_play_by_play`.

### Reconciliation Architecture (Working)

The reconciliation system has multiple layers that are working correctly:

| Component | Schedule | Status | Notes |
|-----------|----------|--------|-------|
| `pipeline_reconciliation` | 6 AM ET daily | ✅ Working | Detected Jan 27 gaps correctly |
| `data_gaps` table | N/A | ✅ Working | Tracking gaps correctly |
| `CleanupProcessor` | Hourly | ⚠️ Fixed | Table name bug fixed in Session 11 |
| `daily_health_check` | 8 AM ET daily | ✅ Working | Checks overall health |
| `scraper_gap_backfiller` | Every 4 hours | ✅ Working | Auto-backfills scraper gaps |

### What's Still Needed

#### 1. Error Logging & Visibility (HIGH PRIORITY)

Currently when a game isn't processed, we can't easily tell WHY. Need:

| Enhancement | Description | Status |
|-------------|-------------|--------|
| **File Processing Log** | Log every GCS file arrival with processing status | ⏳ Needed |
| **Phase 2 Pub/Sub Tracking** | Track message receipt vs processing success | ⏳ Needed |
| **Gap Root Cause Field** | Add `failure_reason` to `data_gaps` table | ⏳ Needed |
| **Real-time Gap Alerting** | Slack alert when gap detected (not just logged) | ⏳ Needed |
| **Processing Journey View** | Dashboard showing file → Pub/Sub → Phase 2 → BQ status | ⏳ Needed |

**Root Cause of Visibility Gap:**

| Phase | Logs to pipeline_event_log? | Visibility |
|-------|----------------------------|------------|
| Phase 1 (Scrapers) | ❌ Only scraper_execution_log | File uploaded status |
| Phase 2 (Raw) | ❌ No logging | **BLIND SPOT** |
| Phase 3 (Analytics) | ✅ Yes | Full visibility |
| Phase 4 (Precompute) | ✅ Yes | Full visibility |
| Phase 5 (Predictions) | ✅ Yes | Full visibility |

**Proposed Implementation (High Priority):**

1. **Add Phase 2 processor logging** (`data_processors/raw/base_raw_processor.py`):
```python
# Add to RawProcessorBase
def process_with_logging(self, gcs_path: str):
    self._log_event('processor_start', gcs_path=gcs_path)
    try:
        result = self._process_file(gcs_path)
        self._log_event('processor_complete', gcs_path=gcs_path, rows=result.rows)
        return result
    except Exception as e:
        self._log_event('error', gcs_path=gcs_path, error=str(e))
        raise
```

2. **Add failure_reason to data_gaps table**:
```sql
ALTER TABLE nba_orchestration.data_gaps ADD COLUMN IF NOT EXISTS
  failure_reason STRING OPTIONS(description='pubsub_missed, processor_error, quota_exceeded, etc.');
```

3. **Add real-time gap alerting** in `pipeline_reconciliation`:
```python
# When gap detected, send immediate Slack alert
if gaps_found:
    send_slack_alert(f"🚨 {len(gaps)} games missing from {source}")
```

#### 2. Auto-Remediation for Detected Gaps

When `pipeline_reconciliation` detects a gap:
- Currently: Logs to `data_gaps` table
- Needed: Auto-trigger backfill OR alert for manual intervention

#### 3. CleanupProcessor Coverage Test

Add test to verify all table names in `cleanup_processor.py` are valid BigQuery tables.

## Architecture Changes

### Current State
```
Scraper fails → Silent failure → Cascade through phases → Detected 12h later
```

### Target State
```
Scraper fails → Inline validation → Immediate alert → Auto-retry → Fallback if needed
```

### Key Components to Add

1. **Inline Validation** (at each phase boundary)
   - Check record counts
   - Validate NULL rates
   - Verify field completeness
   - Alert if thresholds breached

2. **Auto-Retry with Backoff**
   - 3 retry attempts
   - Exponential delays: 10s, 20s, 40s
   - Circuit breaker after max retries

3. **Fallback Sources**
   - NBA.com PBP when BDB unavailable
   - Basketball Reference for boxscores
   - NBA API as second backup

4. **Unified Monitoring**
   - Single `validate-all.sh` command
   - Real-time alerts (not just morning check)
   - Deployment health integration

## Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Issue detection time | 4-24h | <15min | Time from failure to alert |
| Auto-recovery rate | 0% | 80% | Issues fixed without manual intervention |
| PBP coverage | 71% | 98%+ | Games with PBP data / total games |
| Deployment drift | Common | Rare | Stale services detected by drift check |
| Phase 3 success | 6.6% | 95%+ | Successful runs / total runs |
| Phase 4 success | 26.8% | 95%+ | Successful runs / total runs |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Auto-deploy breaks prod | Medium | High | Add health check gate, rollback on 5xx |
| Retry storms | Low | Medium | Exponential backoff, circuit breaker |
| Fallback data quality | Low | Medium | Mark source, validate critical fields |
| Monitoring fatigue | Medium | Low | Deduplicate alerts, severity tiers |

## Dependencies

1. **GCP_SA_KEY secret** - Required for auto-deploy workflow
2. **Slack webhook** - For alerting (optional but recommended)
3. **Cloud Run permissions** - Service account needs deployer role

## Files Created/Modified

### Created This Session
- `shared/processors/patterns/quality_mixin.py` - Added `track_source_coverage_event`
- `.github/workflows/auto-deploy.yml` - Auto-deploy on push to main
- `bin/deploy-all-stale.sh` - Manual deploy script
- `docs/08-projects/current/pipeline-resilience-improvements/` - This project

### Created Session 10
- BDB scraper retry logic
- NBA.com PBP fallback implementation
- Phase boundary validation
- Minutes coverage alerting
- Pre-extraction data check
- Empty game detection
- Phase success monitor

### To Create Next Session
- `bin/validate-all.sh` - Unified validation (consolidate existing monitors)
- Pub/Sub backlog purge mechanism
- Retry queue SQL fix
- Soft dependencies enablement
- BigQuery schema migration for data_source column
- Circuit breaker batching implementation
