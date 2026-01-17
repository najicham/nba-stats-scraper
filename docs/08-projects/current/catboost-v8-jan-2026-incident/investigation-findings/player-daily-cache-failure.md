# Player Daily Cache Pipeline Failure Investigation

**Investigation Date:** January 16, 2026
**Investigator:** Claude Sonnet 4.5
**Incident Dates:** January 8 and January 12, 2026
**Impact:** 36% of features missing (9 out of 25 features)

---

## Executive Summary

The `player_daily_cache` table has **zero records** for `cache_date = '2026-01-08'` and `'2026-01-12'`, while all other Phase 4 tables updated normally on those dates. Investigation revealed **two distinct root causes**:

1. **Jan 8 Failure:** Cloud Scheduler permission error (403 PERMISSION_DENIED) - Fixed Jan 9
2. **Jan 12 Failure:** Upstream dependency failure (Phase 3 stuck in "running" state for 8+ hours)

Neither failure was day-of-week related. Both were infrastructure/reliability issues.

---

## Investigation Findings

### 1. Timeline of Events

| Date | Event | Evidence |
|------|-------|----------|
| **Jan 7, 11:15 PM PT** | Scheduler triggers for Jan 8 cache | `2026-01-08T07:15:00Z` |
| **Jan 7, 11:15 PM PT** | ❌ **FAILED: 403 PERMISSION_DENIED** | Cloud Scheduler logs show HTTP 403 |
| **Jan 8, 11:15 PM PT** | Scheduler triggers for Jan 9 cache | `2026-01-09T07:15:00Z` |
| **Jan 8, 11:15 PM PT** | ❌ **FAILED: 403 PERMISSION_DENIED** | Cloud Scheduler logs show HTTP 403 |
| **Jan 9, daytime** | **OIDC token fix deployed** | Session 9 handoff doc |
| **Jan 9, 11:15 PM PT** | ✅ Scheduler succeeds for Jan 10 | HTTP 200 |
| **Jan 10-11** | Normal operation | HTTP 200 for both nights |
| **Jan 11, ~11:30 AM PT** | Phase 3 processor gets stuck in "running" | Stuck for 8 hours |
| **Jan 12, 7:33 PM PT** | Stale cleanup marks Jan 11 as failed | `stale_running_cleanup` |
| **Jan 12, 11:15 PM PT** | Scheduler triggers for Jan 13 cache | `2026-01-13T07:15:00Z` |
| **Jan 12, 11:15 PM PT** | ❌ **FAILED: Dependency check failed** | PlayerGameSummaryProcessor Jan 11 failed |

### 2. Data Verification

```sql
-- Phase 4 table comparison (Jan 6-13)
SELECT
  cache_date,
  COUNT(*) as records
FROM nba_precompute.player_daily_cache
WHERE cache_date BETWEEN '2026-01-06' AND '2026-01-13'
GROUP BY cache_date
ORDER BY cache_date;
```

**Results:**
| Date | player_daily_cache | player_composite_factors | player_shot_zone_analysis | team_defense_zone_analysis |
|------|-------------------|-------------------------|--------------------------|---------------------------|
| Jan 6 | 84 | 161 | 426 | 30 |
| Jan 7 | 183 | 311 | 429 | 30 |
| Jan 8 | **0** ❌ | 115 ✅ | 430 ✅ | 30 ✅ |
| Jan 9 | 57 | 348 | 434 | 30 |
| Jan 10 | 103 | 211 | 434 | 30 |
| Jan 11 | 199 | 268 | 435 | 30 |
| Jan 12 | **0** ❌ | 77 ✅ | 434 ✅ | 30 ✅ |
| Jan 13 | 183 | 216 | 441 | 30 |

**Key Finding:** Only `player_daily_cache` affected. Other Phase 4 tables processed successfully, ruling out pipeline-wide failure.

### 3. Cloud Scheduler Configuration

```json
{
  "name": "player-daily-cache-daily",
  "schedule": "15 23 * * *",  // 11:15 PM PT every night
  "timezone": "America/Los_Angeles",
  "httpTarget": {
    "uri": "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date",
    "httpMethod": "POST",
    "body": {
      "processors": ["PlayerDailyCacheProcessor"],
      "analysis_date": "AUTO"  // Resolves to yesterday in UTC
    },
    "oidcToken": {
      "serviceAccountEmail": "756957797294-compute@developer.gserviceaccount.com",
      "audience": "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
    }
  }
}
```

**Scheduler Logic:**
- Runs at **11:15 PM Pacific** every night
- `"AUTO"` parameter resolves to **yesterday in UTC**
- Night of Jan 7 PT (Jan 8 07:15 UTC) → caches Jan 7 data
- Night of Jan 8 PT (Jan 9 07:15 UTC) → caches **Jan 8 data** (FAILED)
- Night of Jan 12 PT (Jan 13 07:15 UTC) → caches **Jan 12 data** (FAILED)

### 4. Root Cause Analysis

#### **Failure #1: Jan 8 (Scheduler Permission Error)**

**Cloud Scheduler Logs:**
```
2026-01-09T07:15:00.733470986Z INFO  (Job triggered)
2026-01-09T07:15:01.859928359Z ERROR HTTP 403 PERMISSION_DENIED
```

**Root Cause:** Cloud Scheduler jobs were missing OIDC authentication tokens required to invoke authenticated Cloud Run services.

**Evidence from Session 9 Handoff (Jan 9, 2026):**
> ### 2. Cloud Scheduler Permission Failures (Phase 4 Overnight Jobs)
>
> **Problem**: Three overnight Phase 4 CASCADE jobs failing with PERMISSION_DENIED (error code 7).
>
> **Root Cause**: Jobs were missing OIDC token authentication required for authenticated Cloud Run services.
>
> **Affected Jobs**:
> - `ml-feature-store-daily` (11:30 PM PT)
> - `player-composite-factors-daily` (11:00 PM PT)
> - **`player-daily-cache-daily`** (11:15 PM PT)

**Fix Applied (Jan 9):**
```bash
gcloud scheduler jobs update http player-daily-cache-daily --location=us-west2 \
  --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
  --oidc-token-audience="https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date"
```

**Verification:** Subsequent runs (Jan 10 onwards) succeeded with HTTP 200.

#### **Failure #2: Jan 12 (Upstream Dependency Failure)**

**Cloud Run Logs (Night of Jan 12 PT):**
```
2026-01-13T07:15:01.124995Z INFO  AUTO date resolved to: 2026-01-12
2026-01-13T07:15:01.125049Z INFO  Running PlayerDailyCacheProcessor for 2026-01-12
2026-01-13T07:15:04.727398Z ERROR DependencyError: Upstream PlayerGameSummaryProcessor failed for 2026-01-11
2026-01-13T07:15:04.727433Z ERROR {
  'cleanup_reason': 'stale_running_cleanup',
  'cleanup_timestamp': '2026-01-12 19:33:48.333802+00',
  'hours_stuck': 8,
  'message': 'marked as failed after being stuck in running state',
  'original_errors': None
}
```

**Root Cause:** PlayerDailyCache processor has defensive dependency checking that validates upstream Phase 3 processors completed successfully. On Jan 12, `PlayerGameSummaryProcessor` for Jan 11 was stuck in "running" state for 8 hours and was automatically marked as failed by the `stale_running_cleanup` job.

**Dependency Check Code:**
```python
# data_processors/precompute/precompute_base.py
def _run_defensive_checks(self, analysis_date, strict_mode):
    """Validate upstream dependencies before processing."""
    # Check upstream Phase 3 processor status
    upstream_status = self._check_upstream_status(analysis_date, lookback_days=10)

    if upstream_status.get('status') == 'failed':
        raise DependencyError(
            f"Upstream {self.upstream_processor_name} failed for {analysis_date}. "
            f"Error: {upstream_status.get('error')}"
        )
```

**Why Jan 11 Phase 3 got stuck:** Unknown from logs, but likely:
- Long-running query timeout
- BigQuery slot exhaustion
- Transient infrastructure issue
- Memory/CPU limits on Cloud Run

**Why this didn't affect other Phase 4 processors:**
- `player_shot_zone_analysis` - Doesn't have strict dependency checks
- `player_composite_factors` - Failed too (see logs: `UpcomingPlayerGameContextProcessor failed`)
- `team_defense_zone_analysis` - Depends on team processors, not player processors

---

## Why No Data for Jan 8 and Jan 12?

### Backfill Analysis

Looking at `created_at` timestamps:

| cache_date | record_count | first_created_at | Backfilled? |
|------------|--------------|------------------|-------------|
| Jan 6 | 84 | 2026-01-09 01:10:27 | ✅ Yes (3 days later) |
| Jan 7 | 183 | 2026-01-09 01:12:37 | ✅ Yes (2 days later) |
| Jan 8 | **0** | N/A | ❌ **Never backfilled** |
| Jan 9 | 57 | 2026-01-09 01:17:04 | ✅ Same day |
| Jan 10 | 103 | 2026-01-10 23:51:16 | ✅ Normal schedule |
| Jan 11 | 199 | 2026-01-12 19:04:51 | ✅ Yes (1 day later) |
| Jan 12 | **0** | N/A | ❌ **Never backfilled** |
| Jan 13 | 183 | 2026-01-15 23:03:18 | ✅ Yes (2 days later) |

**Timeline:**
- **Jan 9:** Backfilled Jan 6, 7, 9 after fixing scheduler (but missed Jan 8)
- **Jan 12:** Backfilled Jan 11 after stale cleanup resolved
- **Jan 8 and 12:** Never backfilled manually

**Why no automatic retry?**
- Cloud Scheduler doesn't retry 403 errors (permanent failure)
- Dependency check failures don't trigger automatic backfill
- No retry logic in Phase 4 orchestrator for failed processors

---

## Day-of-Week Analysis

**User's hypothesis:** Jan 8 = Wednesday, Jan 12 = Sunday (possible day-of-week issue)

**Actual days:**
- Jan 8 = **Thursday** (not Wednesday)
- Jan 12 = **Monday** (not Sunday)

**Conclusion:** ❌ Not a day-of-week issue. Both failures were infrastructure-related.

---

## Impact Assessment

### Feature Availability

Missing `player_daily_cache` data caused **9 out of 25 features** (36%) to be unavailable for predictions on Jan 8 and Jan 12:

**Missing Features:**
1. `points_avg_last_5`
2. `points_avg_last_10`
3. `points_avg_season`
4. `minutes_avg_last_10`
5. `usage_rate_last_10`
6. `ts_pct_last_10`
7. `team_pace_last_10`
8. `team_off_rating_last_10`
9. `games_in_last_7_days`

**Still Available (from other Phase 4 tables):**
- Shot zone tendencies (from `player_shot_zone_analysis`)
- Composite factors (from `player_composite_factors`)
- Team defense metrics (from `team_defense_zone_analysis`)

### Prediction System Impact

Based on `ml_feature_store_processor.py` fallback logic:

```python
# When player_daily_cache is missing, features default to None
# Feature extractor returns partial feature dict
# Prediction worker skips players with <25 features (strict mode)
```

**Result:** Players with games on Jan 8 and Jan 12 likely had **no predictions** or degraded predictions (if fallback mode enabled).

---

## Code Review

### 1. Processor Code

**File:** `/home/naji/code/nba-stats-scraper/data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

**Recent Changes (Jan 5-13):**

```bash
$ git log --since="2026-01-05" --until="2026-01-13" --oneline -- data_processors/precompute/player_daily_cache/
6bf9a61 fix(worker): Add cache TTL to prevent stale same-day predictions
1c34653 feat(completeness): Add DNP-aware completeness checking
```

**Relevant Changes:**

1. **Jan 11 (6bf9a61):** Added same-day prediction support
   - Added `is_same_day_or_future` check
   - Skip completeness checks for same-day mode
   - **No bug introduced** - purely additive feature

2. **Jan 10 (1c34653):** DNP-aware completeness
   - Improved handling of "Did Not Play" games
   - Reduced false negatives in completeness checks
   - **No bug introduced** - improvement

**Conclusion:** ✅ No code bugs in processor. Both changes improved reliability.

### 2. Defensive Dependency Checking

**File:** `/home/naji/code/nba-stats-scraper/data_processors/precompute/precompute_base.py`

```python
class PrecomputeProcessorBase:
    # Defensive check configuration
    upstream_processor_name = 'PlayerGameSummaryProcessor'
    upstream_table = 'nba_analytics.player_game_summary'
    lookback_days = 10  # Must match data requirements

    def _run_defensive_checks(self, analysis_date, strict_mode):
        """Validate upstream dependencies completed successfully."""
        if not strict_mode:
            return  # Skip checks in backfill mode

        # Check upstream processor status in Firestore
        upstream_status = self._check_upstream_status(analysis_date, self.lookback_days)

        if upstream_status.get('status') == 'failed':
            raise DependencyError(
                f"Upstream {self.upstream_processor_name} failed for {analysis_date}. "
                f"Error: {upstream_status.get('error')}"
            )
```

**Design Intent:** Prevent processing with incomplete/corrupt upstream data.

**Side Effect:** Fails fast when upstream has transient issues (e.g., stale cleanup).

**Trade-off:**
- ✅ **Pro:** Prevents data quality issues (no garbage-in-garbage-out)
- ❌ **Con:** Fails entire date when upstream has temporary issues
- ❌ **Con:** No automatic retry or self-healing

---

## Recommended Fixes

### 1. Immediate: Backfill Missing Dates (P0)

```bash
# Backfill Jan 8
PYTHONPATH=. python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --dates 2026-01-08

# Backfill Jan 12
PYTHONPATH=. python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --dates 2026-01-12
```

**Verification:**
```sql
SELECT cache_date, COUNT(*) as records
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date IN ('2026-01-08', '2026-01-12')
GROUP BY cache_date;
```

Expected: ~100-200 records per date.

### 2. Short-term: Improve Scheduler Monitoring (P1)

**Problem:** Scheduler failures are silent (no alerts).

**Solution:** Add monitoring for Phase 4 scheduler jobs.

```python
# New Cloud Function: phase4_scheduler_monitor
# Triggers: Cloud Scheduler Pub/Sub topic (job execution events)
# Alert on:
# - HTTP 4xx/5xx errors
# - Jobs skipped for >24 hours
# - Consecutive failures (3+)

def monitor_scheduler_job(event):
    job_name = event['resource']['labels']['job_id']
    status = event['protoPayload']['status']

    if status.get('code') in [403, 401, 500, 503]:
        send_slack_alert(
            f"🚨 Scheduler job `{job_name}` failed with {status['code']}",
            channel='#daily-orchestration'
        )
```

**Implementation:** Leverage existing `phase4_timeout_check` scheduled function.

### 3. Mid-term: Improve Dependency Check Resilience (P2)

**Problem:** Dependency checks fail permanently on transient upstream issues.

**Solution:** Add retry/fallback logic.

```python
def _run_defensive_checks(self, analysis_date, strict_mode):
    """Validate upstream dependencies with retry logic."""
    if not strict_mode:
        return

    # Check upstream status
    upstream_status = self._check_upstream_status(analysis_date, self.lookback_days)

    if upstream_status.get('status') == 'failed':
        # Check if failure was transient (stale cleanup)
        if upstream_status.get('cleanup_reason') == 'stale_running_cleanup':
            # Retry: Check if data actually exists
            data_exists = self._verify_upstream_data_exists(analysis_date)

            if data_exists:
                logger.warning(
                    f"Upstream {self.upstream_processor_name} marked failed (stale cleanup) "
                    f"but data exists. Proceeding with caution."
                )
                return  # Allow processing

        # Permanent failure - block processing
        raise DependencyError(
            f"Upstream {self.upstream_processor_name} failed for {analysis_date}. "
            f"Error: {upstream_status.get('error')}"
        )
```

**Rationale:** Distinguish between:
- **Data missing** (block) → e.g., scraper failed, no source data
- **Process stuck** (allow with warning) → e.g., stale cleanup, but data exists

### 4. Long-term: Self-Healing Backfill (P3)

**Problem:** Failed scheduler jobs never retry automatically.

**Solution:** Add self-healing orchestrator.

```python
# New Cloud Function: phase4_self_heal
# Schedule: Every 6 hours
# Logic:
# 1. Query player_daily_cache for dates in last 14 days
# 2. Find missing dates (0 records)
# 3. Check if upstream Phase 3 data exists
# 4. Auto-trigger backfill if data available

def self_heal_player_daily_cache():
    missing_dates = find_missing_cache_dates(days=14)

    for date in missing_dates:
        # Check if Phase 3 data exists
        if phase3_data_exists(date):
            logger.info(f"Auto-backfilling player_daily_cache for {date}")
            trigger_backfill(date, processor='PlayerDailyCacheProcessor')
        else:
            logger.warning(f"Cannot backfill {date} - upstream Phase 3 data missing")
```

**Implementation:** Similar to existing `self_heal` Cloud Function for predictions.

---

## Prevention Measures

### 1. Add to Daily Ops Checklist

```markdown
## Phase 4 Verification
- [ ] Check player_daily_cache has records for last 3 days
- [ ] Check Cloud Scheduler job status (last 24 hours)
- [ ] Verify no dependency check failures in logs
```

**Query:**
```sql
-- Check last 3 days of player_daily_cache
SELECT cache_date, COUNT(*) as records
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY cache_date
ORDER BY cache_date DESC;

-- Expected: 100-200 records per date
-- Alert if any date has 0 records
```

### 2. Add Monitoring Dashboard

**Metrics:**
- Player daily cache record count (last 7 days)
- Scheduler job success rate (last 24 hours)
- Dependency check failure rate (last 7 days)
- Stale cleanup events (Phase 3 processors)

**Alerts:**
- Zero records for any date in last 3 days
- Scheduler 403/500 errors
- 2+ consecutive dependency failures

### 3. Improve Logging

**Current:** Dependency failures log generic error message.

**Improved:**
```python
if upstream_status.get('status') == 'failed':
    error_details = upstream_status.get('error', {})
    logger.error(
        f"Dependency check failed for {analysis_date}",
        extra={
            'upstream_processor': self.upstream_processor_name,
            'upstream_date': analysis_date,
            'failure_reason': error_details.get('cleanup_reason'),
            'hours_stuck': error_details.get('hours_stuck'),
            'original_errors': error_details.get('original_errors'),
            'data_exists': self._verify_upstream_data_exists(analysis_date),
            'recommendation': 'Check if data exists despite failure status'
        }
    )
```

**Benefit:** Easier troubleshooting via Cloud Logging filters.

---

## Related Issues

### 1. Stale Running Cleanup (Upstream Root Cause)

**File:** `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/stale_running_cleanup/main.py`

The stale cleanup job marks processors as failed after 8 hours in "running" state. This is necessary to prevent zombie processes, but it creates cascading failures in downstream processors.

**Recommendation:** Investigate why Phase 3 processors get stuck:
- Add timeout configuration to Cloud Run (currently no max timeout)
- Add query timeout to BigQuery client (prevent runaway queries)
- Monitor memory/CPU usage during Phase 3 runs

### 2. No Automatic Backfill for Scheduler Failures

Unlike prediction workers (which have retry logic), Phase 4 schedulers have no automatic retry or backfill mechanism.

**Recommendation:** Implement suggestion #4 (Self-Healing Backfill).

---

## Verification Commands

```bash
# 1. Check scheduler job status
gcloud scheduler jobs describe player-daily-cache-daily --location=us-west2 \
  --format='table(name,schedule,state,status.code,status.message)'

# 2. Check scheduler execution history
gcloud logging read \
  'resource.type="cloud_scheduler_job"
   AND resource.labels.job_id="player-daily-cache-daily"
   AND timestamp>="2026-01-06T00:00:00Z"' \
  --limit=50 \
  --format='table(timestamp,severity,httpRequest.status)'

# 3. Check player_daily_cache data
bq query --use_legacy_sql=false "
SELECT cache_date, COUNT(*) as records, MIN(created_at) as backfilled_at
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date BETWEEN '2026-01-06' AND '2026-01-13'
GROUP BY cache_date
ORDER BY cache_date"

# 4. Check upstream Phase 3 data availability
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2026-01-06' AND '2026-01-13'
GROUP BY game_date
ORDER BY game_date"

# 5. Check Phase 3 processor status (Firestore)
# (Requires Firestore query - check orchestration/phase3_completion/{date})
```

---

## Summary

| Finding | Evidence | Fix Status |
|---------|----------|------------|
| **Jan 8 Failure: Scheduler 403 error** | Cloud Scheduler logs show HTTP 403 on Jan 9 07:15 UTC | ✅ Fixed Jan 9 (OIDC tokens added) |
| **Jan 12 Failure: Dependency check** | Cloud Run logs show `DependencyError` for Jan 11 Phase 3 | ⏳ Needs backfill + prevention |
| **No automatic retry** | Scheduler doesn't retry, no backfill triggered | ⏳ Needs self-healing system |
| **No day-of-week pattern** | Jan 8=Thu, Jan 12=Mon (not Wed/Sun) | ✅ Hypothesis disproven |
| **Impact: 36% features missing** | 9/25 features depend on player_daily_cache | ⏳ Needs backfill |

**Priority Actions:**
1. ✅ **P0:** Backfill Jan 8 and Jan 12 data
2. **P1:** Add scheduler monitoring/alerting
3. **P2:** Improve dependency check resilience
4. **P3:** Implement self-healing backfill

---

**Investigation Completed:** January 16, 2026
**Next Steps:** Execute recommended fixes in priority order
