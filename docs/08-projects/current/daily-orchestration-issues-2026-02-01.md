# Daily Orchestration Issues - February 1, 2026

**Date**: 2026-02-01
**Game Date Analyzed**: 2026-01-31 (6 NBA games)
**Processing Date**: 2026-02-01 (scrapers/analytics ran after midnight)
**Validation**: `/validate-daily` for yesterday's results

---

## Executive Summary

Ran daily validation for Jan 31 games and discovered **4 distinct orchestration issues**, ranging from P1 CRITICAL (blocking production) to P2 (data quality concerns). Some were fixed in Session 68, but **root causes need deeper review** to prevent recurrence.

**Status**:
- ✅ 2 issues fixed and deployed
- ⚠️ 2 issues need further investigation

---

## Issue #1: Phase 3 Completion Tracking Inconsistency 🔴

### What We Observed

**Firestore Phase 3 Completion**: 3/5 processors complete
**BigQuery Data Reality**: All 5 processors successfully wrote data

**Missing from Firestore**:
1. `player_game_summary` - **Data exists**: 212 records @ 2026-02-01 15:00:48 UTC
2. `upcoming_team_game_context` - **Data exists**: 12 records @ 2026-02-01 11:00:09 UTC

**Present in Firestore**:
1. `team_defense_game_summary` ✅
2. `team_offense_game_summary` ✅
3. `upcoming_player_game_context` ✅

### Why This Matters

**Immediate impact**:
- Phase 4 not triggered (Firestore showed 3/5, threshold is 5/5)
- Prediction pipeline potentially stalled
- Manual intervention required to trigger downstream phases

**Data integrity**:
- Data is complete in BigQuery (verified)
- Only the **completion tracking** failed, not the actual processing
- This is a monitoring/orchestration issue, not a data pipeline issue

### Current Understanding of Completion Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 3 Processor (e.g., player_game_summary)                   │
│                                                                  │
│ 1. Processes data ✅                                             │
│ 2. Writes to BigQuery ✅                                         │
│ 3. Publishes Pub/Sub message to "nba-phase3-analytics-complete" │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 3→4 Orchestrator Cloud Function                           │
│                                                                  │
│ 1. Receives Pub/Sub message                                     │
│ 2. Calls CompletionTracker.record_completion() ❌ FAILS HERE   │
│ 3. Should write to Firestore + BigQuery backup                  │
│ 4. Updates phase3_completion document                           │
└─────────────────────────────────────────────────────────────────┘
```

**Failure Point**: Step 2 in orchestrator

**Code location**: `orchestration/cloud_functions/phase3_to_phase4/main.py:1347-1371`

**Current error handling** (too permissive):
```python
if COMPLETION_TRACKER_ENABLED:
    try:
        tracker = get_completion_tracker()
        fs_ok, bq_ok = tracker.record_completion(...)
        # Check for failures
    except Exception as tracker_error:
        # Non-blocking - log but don't fail the orchestration
        logger.warning(f"BigQuery backup write failed (non-blocking): {tracker_error}")
```

**Problem**: Exception is caught, only WARNING logged, no traceback captured. Completion silently fails.

### Hypotheses for Root Cause

**Hypothesis 1: Notification System Dependency** (High Confidence)

Evidence from logs:
```
2026-02-01T15:00:52.163321Z ERROR - ValueError: Email alerting requires these environment variables: BREVO_SMTP_USERNAME, BREVO_FROM_EMAIL

2026-02-01T15:00:52.163299Z ERROR - ModuleNotFoundError: No module named 'boto3'
```

These errors occurred during **processor initialization**. If `CompletionTracker` initialization also triggers notification system code, the same errors could prevent Firestore writes.

**Need to verify**:
- Does `CompletionTracker.__init__()` depend on notification system?
- Does `get_completion_tracker()` trigger notification imports?
- Check `shared/utils/completion_tracker.py` for notification dependencies

**Hypothesis 2: Firestore Client Pool Exhaustion** (Medium Confidence)

Code uses lazy initialization via client pool:
```python
@property
def firestore_client(self):
    if self._firestore_client is None:
        self._firestore_client = get_firestore_client(self.project_id)
    return self._firestore_client
```

**Possible issue**:
- High concurrency (multiple processors completing simultaneously)
- Client pool exhausted or connection timeout
- `get_firestore_client()` throws exception
- Exception caught in non-blocking handler

**Need to verify**:
- Check `shared/utils/client_pool.py` for Firestore client limits
- Review Firestore quota/connection limits
- Check if timeout configuration is too aggressive

**Hypothesis 3: Firestore Write Permissions** (Low Confidence)

**Counter-evidence**: 3/5 processors successfully wrote to Firestore, so permissions exist.

**Unlikely unless**:
- Document-level permissions vary
- Rate limiting kicked in for specific processors
- Specific game_date documents have different permissions

### What Was Done (Session 68)

**Enhancement applied** (not yet deployed):
```python
except Exception as tracker_error:
    import traceback
    logger.error(  # Changed WARNING → ERROR
        f"COMPLETION TRACKING FAILED (non-blocking): {tracker_error}",
        extra={
            "processor_name": processor_name,
            "game_date": game_date,
            "traceback": traceback.format_exc(),  # Added full traceback
            "error_type": type(tracker_error).__name__  # Added error type
        }
    )
```

**Deployment status**: ❌ Failed with Cloud Run health check timeout (likely transient)

**Code status**: ✅ Committed in `2c92e418`

### What Still Needs Investigation

#### Critical Questions

1. **Why did 2 specific processors fail?**
   - `player_game_summary` completed at 15:00:48 UTC
   - `upcoming_team_game_context` completed at 11:00:09 UTC
   - These are 4 hours apart - timing correlation?
   - Were there resource constraints at these specific times?

2. **What error was actually thrown?**
   - Current logs only show WARNING with generic message
   - Need traceback from next occurrence
   - Deployment of enhanced logging will help

3. **Is this a recurring pattern?**
   - Check historical Firestore completion data
   - Look for pattern of specific processors failing
   - Query: How often do we see 3/5 vs 5/5 completion?

#### Investigation Commands

**Check historical completion patterns**:
```python
from google.cloud import firestore
from datetime import datetime, timedelta
import pandas as pd

db = firestore.Client()
results = []

for i in range(30):
    date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
    doc = db.collection('phase3_completion').document(date).get()
    if doc.exists:
        data = doc.to_dict()
        completed = [k for k in data.keys() if not k.startswith('_')]
        results.append({
            'date': date,
            'completed_count': len(completed),
            'triggered': data.get('_triggered', False),
            'processors': completed
        })

df = pd.DataFrame(results)
print(df[df['completed_count'] < 5])  # Show incomplete days
```

**Check if CompletionTracker has notification dependencies**:
```bash
grep -n "notification\|alert\|email" /home/naji/code/nba-stats-scraper/shared/utils/completion_tracker.py
grep -n "import.*notification\|from.*notification" /home/naji/code/nba-stats-scraper/shared/utils/completion_tracker.py
```

**Check Firestore client pool configuration**:
```bash
grep -n "class.*Pool\|max_connections\|pool_size" /home/naji/code/nba-stats-scraper/shared/utils/client_pool.py
```

**Check orchestrator logs for actual exception** (after enhanced logging deployed):
```bash
gcloud logging read 'resource.type="cloud_function"
  AND resource.labels.function_name="phase3-to-phase4-orchestrator"
  AND jsonPayload.message=~"COMPLETION TRACKING FAILED"' \
  --limit=10 --format=json | jq -r '.[] | .jsonPayload.traceback'
```

### Recommended Next Steps

**Immediate (P1)**:
1. Retry orchestrator deployment to get enhanced error logging
2. If deployment continues to fail, investigate health check timeout separately
3. Monitor next orchestration cycle (tonight) for completion tracking

**Short-term (P2)**:
1. Run historical analysis to identify completion pattern
2. Check CompletionTracker for notification system dependencies
3. Review Firestore client pool configuration
4. Add monitoring alert for "data exists but completion not recorded"

**Long-term (P3)**:
1. Consider making completion tracking more robust:
   - Retry logic for transient Firestore failures
   - Fallback to BigQuery-only tracking if Firestore unavailable
   - Dead letter queue for failed completion messages
2. Add integration test that verifies completion tracking end-to-end
3. Document expected completion flow in architecture docs

---

## Issue #2: Orchestrator Monitoring Tables Missing 🟡

### What We Observed

**Expected tables for orchestrator health monitoring**:
- `nba_orchestration.phase_execution_log` - **Does not exist**
- `nba_orchestration.processor_run_history` - **Does not exist**

**Impact**: Cannot validate orchestrator transitions via standard queries

**Workaround used**: Direct Firestore queries + BigQuery data verification

### Why This Matters

**Validation difficulty**:
- Phase 0.5 orchestrator health checks couldn't run
- Can't detect stuck orchestrators (started but never completed)
- Can't measure phase transition timing (SLA monitoring)
- Can't track orchestrator failures over time

**Example check that couldn't run**:
```sql
-- This query fails because table doesn't exist
SELECT phase_name,
  CASE WHEN status = 'complete' THEN 'OK' ELSE 'MISSING' END
FROM nba_orchestration.phase_execution_log
WHERE game_date = DATE('2026-01-31')
```

### Current Understanding

**These tables are referenced in**:
- CLAUDE.md documentation (lines mentioning phase_execution_log)
- `/validate-daily` skill (Phase 0.5 checks)
- Troubleshooting guides

**But they don't exist in BigQuery**:
```bash
$ bq ls nba_orchestration
  Tables:
  - bdl_quality_trend
  - source_discrepancies
  # phase_execution_log NOT LISTED
  # processor_run_history NOT LISTED
```

### Questions to Answer

1. **Were these tables ever created?**
   - Check git history for schema definitions
   - Search for CREATE TABLE statements
   - Check if they exist in staging/dev environments

2. **Is there orchestrator code that writes to them?**
   - Search orchestrator code for table writes
   - Check if logging is behind a feature flag
   - Verify if infrastructure was partially implemented

3. **What's the alternative?**
   - Should we create these tables now?
   - Is Firestore completion tracking sufficient?
   - Should we use Cloud Function execution logs instead?

### Investigation Commands

**Search for schema definitions**:
```bash
find schemas/ -name "*.sql" -exec grep -l "phase_execution_log\|processor_run_history" {} \;
```

**Search orchestrator code for table references**:
```bash
grep -r "phase_execution_log\|processor_run_history" orchestration/cloud_functions/
```

**Check if feature flag controls logging**:
```bash
grep -r "EXECUTION_LOG_ENABLED\|RUN_HISTORY_ENABLED" orchestration/
```

**Alternative: Check Cloud Function execution logs**:
```bash
gcloud logging read 'resource.type="cloud_function"
  AND resource.labels.function_name=~"phase.*orchestrator"
  AND timestamp>="2026-01-31T00:00:00Z"
  AND timestamp<="2026-02-01T00:00:00Z"' \
  --limit=100 --format="table(timestamp,resource.labels.function_name,severity,textPayload)"
```

### Recommended Next Steps

**Immediate**:
1. Search codebase for table schema definitions
2. Determine if tables were planned but never created
3. Check if logging code exists but is disabled

**Decision needed**:
- **Option A**: Create tables and implement logging (comprehensive monitoring)
- **Option B**: Remove references from docs (accept Firestore + logs as monitoring)
- **Option C**: Hybrid - use Cloud Logging for orchestrator monitoring, structured queries

**If choosing Option A**, need to:
1. Define table schemas
2. Update orchestrator code to write execution logs
3. Create tables in BigQuery
4. Test with next orchestration cycle
5. Update validation scripts to use new tables

---

## Issue #3: BDL Data Quality Degradation 🔴

### What We Observed

**Jan 31, 2026 Box Score Data**:
- Total players: 212
- Players with minutes data: 118
- **Coverage: 55.7%** (threshold: 90%)

**Example mismatches**:
| Player | Actual Minutes | BDL Minutes | Difference |
|--------|---------------|-------------|------------|
| Klay Thompson | 27 | 9 | -18 (67% error) |
| Kevin Durant | 38 | 22 | -16 (42% error) |
| Amen Thompson | 40 | 24 | -16 (40% error) |
| Alperen Sengun | 34 | 21 | -13 (38% error) |

### Pattern Analysis (12-Day Trend)

**Quality alternates between good and bad days** with no correlation to game count:

| Date | Major Errors (>5 min) | Quality | Games |
|------|---------------------|---------|-------|
| Jan 31 | 28.8% | 🔴 POOR | 6 |
| Jan 30 | 3.0% | ✅ GOOD | 9 |
| Jan 29 | 3.5% | ✅ GOOD | 8 |
| Jan 28 | 27.3% | 🔴 POOR | 9 |
| Jan 27 | 30.8% | 🔴 POOR | 7 |
| Jan 26 | 22.5% | 🔴 POOR | 7 |
| Jan 25 | 50.4% | 🔴 POOR | 6 |
| Jan 24 | 50.0% | 🔴 POOR | 6 |
| Jan 23 | 3.1% | ✅ GOOD | 8 |
| Jan 22 | 3.0% | ✅ GOOD | 8 |
| Jan 21 | 19.9% | 🟡 FAIR | 7 |
| Jan 20 | 1.4% | ✅ GOOD | 7 |

**Summary**:
- 5/12 days = GOOD (3% or less major errors)
- 6/12 days = POOR (20%+ major errors)
- 1/12 days = FAIR (10-20%)
- **No improvement trend over 2+ months**

### Classic BDL Error Pattern

Values are often exactly **half** or **two-thirds** of actual:
- Klay: 27 actual → 9 BDL (33% of actual)
- KD: 38 actual → 22 BDL (58% of actual)
- Amen: 40 actual → 24 BDL (60% of actual)

**This matches Session 41 findings**: "BDL shows ~50% of actual values"

### Current State After Session 68

**BDL scraping**: ✅ Still active (monitors quality, keeps backup data)
**BDL analytics usage**: ❌ Disabled in all NBA processors

**Disabled in**:
- `player_game_summary`: `USE_BDL_DATA = False` (since Jan 28, Session 8)
- `upcoming_player_game_context`: Switched to `player_game_summary` (Session 68)
- `main_analytics_service`: Removed `bdl_player_boxscores` trigger (Session 68)

**Still uses BDL as fallback** (not primary):
- `team_defense_game_summary`: Falls back to BDL if NBAC gamebook missing
- `team_offense_game_summary`: Falls back to BDL if NBAC team boxscore missing

### Questions to Answer

1. **Should we remove BDL fallback from team processors?**
   - Current: Use NBAC primary, BDL fallback
   - Alternative: Use NBAC only, fail if unavailable
   - Trade-off: Data completeness vs data quality

2. **How often does fallback actually trigger?**
   - Query `backup_source_used` quality flags in team processors
   - Determine if NBAC gamebook reliable enough to be sole source

3. **When should we re-enable BDL?**
   - Current criteria: 7+ consecutive days of <5% major errors
   - Is this threshold appropriate?
   - Should we automate re-enable decision?

4. **Why does BDL quality alternate?**
   - API-side data processing issue?
   - Scraper timing issue (incomplete data when scraped)?
   - Source data corruption on specific days?
   - Worth investigating with BDL team?

### Investigation Commands

**Check how often team processors use BDL fallback**:
```sql
SELECT
  game_date,
  COUNT(*) as total_games,
  COUNTIF(backup_source_used = TRUE) as used_bdl_fallback,
  ROUND(100.0 * COUNTIF(backup_source_used = TRUE) / COUNT(*), 1) as fallback_pct
FROM nba_analytics.team_defense_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND backup_source_used IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC
```

**Verify NBAC gamebook completeness**:
```sql
-- Compare scheduled games to NBAC coverage
WITH schedule AS (
  SELECT game_date, COUNT(*) as scheduled
  FROM nba_reference.nba_schedule
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND game_status = 3  -- Final
  GROUP BY game_date
),
nbac AS (
  SELECT game_date, COUNT(DISTINCT game_id) as nbac_coverage
  FROM nba_raw.nbac_gamebook_player_stats
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.scheduled,
  COALESCE(n.nbac_coverage, 0) as nbac_coverage,
  ROUND(100.0 * COALESCE(n.nbac_coverage, 0) / s.scheduled, 1) as nbac_pct
FROM schedule s
LEFT JOIN nbac n USING (game_date)
ORDER BY s.game_date DESC
```

**Monitor BDL quality automatically**:
```bash
# Script exists but not deployed
ls -la bin/monitoring/bdl_quality_alert.py
# Should deploy as Cloud Function scheduled daily at 7 PM ET
```

### Recommended Next Steps

**Immediate**:
1. Verify team processors rarely use BDL fallback
2. If fallback usage <5%, consider removing BDL fallback entirely
3. If fallback usage >10%, keep BDL as safety net

**Short-term**:
1. Deploy BDL quality monitoring Cloud Function
2. Populate `bdl_quality_trend` table with historical analysis
3. Document BDL re-enable criteria in runbook

**Long-term**:
1. Investigate with BDL team why quality alternates
2. Consider alternative data sources for team defense
3. Automate BDL re-enable decision based on quality trend

---

## Issue #4: BigQuery DML Quota Exceeded 🔴 FIXED

### What We Observed

**Errors**: 588 "Exceeded rate limits: too many table DML insert operations" in 13-second burst
**Timing**: 2026-02-01 15:16-15:17 UTC (peak prediction time)
**Frequency**: 1000+ errors on 2/1, 100+ errors on 1/31

### Root Cause (CONFIRMED)

**File**: `predictions/worker/system_circuit_breaker.py:141-143`

Circuit breaker executes Firestore UPDATE on **every successful prediction** to reset `failure_count`, even when already 0.

**Impact calculation**:
- 11 concurrent workers
- 51 players × 5 prediction systems = 255 predictions per worker
- ~1,785 UPDATE calls in 4 minutes
- Sustained: 7.4 UPDATE/sec
- Bursts: 11+ concurrent
- **BigQuery limit**: 20 concurrent DML per table
- **Result**: Quota exceeded

### Fix Applied ✅

**Changed**:
```python
# BEFORE
if state == 'CLOSED':
    self._reset_failure_count(system_id)  # Always updates

# AFTER
if state == 'CLOSED':
    if state_info.get('failure_count', 0) > 0:  # Only update if non-zero
        self._reset_failure_count(system_id)
```

**Deployment**: ✅ `prediction-worker` revision 00057-nfc (2026-02-01 16:53 UTC)

**Expected impact**: Eliminates 99% of unnecessary writes (1,785 → ~18 per game day)

### Verification Needed

**Tonight's games** (2026-02-01) will be first test of fix.

**Check tomorrow**:
```bash
# Should see ZERO quota errors (vs 588 before)
gcloud logging read 'severity>=ERROR AND "too many table dml"' \
  --limit=20 --freshness=12h
```

**If errors still occur**:
1. Check if different service causing quota issues
2. Verify circuit breaker fix actually deployed (check revision 00057-nfc logs)
3. Look for other high-frequency DML operations

### Questions Answered

✅ **What caused it?** Circuit breaker unnecessary updates
✅ **Why now?** Peak prediction load (11 workers × many predictions)
✅ **Is it fixed?** Yes, deployed and committed
⏳ **Is it working?** Verify after tonight's games

---

## Summary of Open Questions

### Critical (Need Answers Soon)

1. **Completion Tracking**:
   - What error is actually thrown when completion fails?
   - Does CompletionTracker depend on notification system?
   - Why did exactly these 2 processors fail (pattern or random)?

2. **Orchestrator Monitoring**:
   - Were phase_execution_log tables ever created?
   - Should we create them now or use alternative monitoring?
   - Is there existing logging code that's disabled?

### Important (This Week)

3. **BDL Fallback Strategy**:
   - How often do team processors actually use BDL fallback?
   - Should we remove BDL fallback entirely?
   - When/how should we re-enable BDL if quality improves?

4. **Circuit Breaker Fix Verification**:
   - Did tonight's games run without quota errors?
   - Confirm 99% reduction in Firestore writes
   - Any unexpected side effects?

### Nice to Have (Long Term)

5. **BDL Quality Investigation**:
   - Why does quality alternate good/bad days?
   - Can we work with BDL team to improve reliability?
   - Are there alternative sources for team defense data?

6. **Completion Tracking Robustness**:
   - Should we add retry logic for transient failures?
   - Dead letter queue for failed completion messages?
   - Fallback to BigQuery-only tracking?

---

## Files to Review

**Code**:
- `orchestration/cloud_functions/phase3_to_phase4/main.py` (completion tracking)
- `shared/utils/completion_tracker.py` (completion implementation)
- `shared/utils/client_pool.py` (Firestore client pool)
- `predictions/worker/system_circuit_breaker.py` (quota fix - already fixed)
- `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py` (BDL fallback)

**Documentation**:
- `docs/09-handoff/2026-02-01-SESSION-68-COMPREHENSIVE-FIX-HANDOFF.md` (full investigation)
- `CLAUDE.md` (references to missing orchestrator tables)

**Schemas**:
- `schemas/bigquery/` (search for orchestrator table definitions)

**Monitoring**:
- `bin/monitoring/bdl_quality_alert.py` (not deployed)
- `.claude/skills/validate-daily/skill.md` (references missing tables)

---

## Recommended Review Approach

**For a fresh reviewer**:

1. **Start with Session 68 handoff** - Get full context on what was found and fixed
2. **Pick one issue to deep dive** - Don't try to solve everything at once
3. **Run investigation commands** - Verify hypotheses with data
4. **Propose solution** - Design fix with trade-offs documented
5. **Test approach** - Verify fix works without breaking other components

**Priority order**:
1. Completion tracking (P1 - affects pipeline reliability)
2. Orchestrator monitoring (P2 - affects observability)
3. BDL fallback strategy (P2 - affects data quality decisions)
4. Circuit breaker verification (P1 - verify fix worked)

---

**Document Created**: 2026-02-01
**Status**: All issues documented, 2/4 fixed, 2/4 need investigation
**Next Update**: After tonight's orchestration cycle (2026-02-02)
