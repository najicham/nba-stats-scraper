# Phase 3 Manual Recovery - Blocking Issues Found

**Date**: 2026-01-26
**Status**: 🔴 BLOCKED - Multiple systemic issues preventing recovery
**Impact**: Cannot complete manual pipeline recovery for today

---

## Investigation Summary

Attempted manual recovery of Phase 3→4→5 pipeline after fixing SQLAlchemy and dependency validation issues. Discovery: Phase 3 has multiple cascading problems preventing completion.

---

## Blocker #1: BigQuery Quota Exceeded

**Error**:
```
403 Quota exceeded: Your table exceeded quota for Number of partition modifications
to a column partitioned table

Table: nba_orchestration.pipeline_event_log
```

**Impact**:
- Cannot write pipeline events to BigQuery
- Cannot write circuit breaker state
- Cannot queue retry attempts
- Logs show ~100+ partition write attempts in short time

**Root Cause**:
- Backlog of old Pub/Sub messages being processed
- Each message writes to pipeline_event_log (partitioned by date)
- Too many writes to too many partitions too quickly

**Quota Limit**:
- BigQuery partition modifications: 5,000 per table per day
- Likely hit due to backlog processing + retries

**Fix Options**:
1. Request quota increase from GCP (24-48 hour turnaround)
2. Batch pipeline event writes instead of individual inserts
3. Purge old Pub/Sub messages causing backlog
4. Temporarily disable pipeline_event_log writes (risky - lose audit trail)

---

## Blocker #2: SQL Syntax Error in Retry Queue

**Error**:
```
WARNING:shared.utils.pipeline_logger:Failed to queue for retry:
400 Syntax error: concatenated string literals must be separated by whitespace
or comments at [4:73]
```

**Impact**:
- Failed processors cannot be queued for retry
- Manual recovery requires manual retriggers
- Auto-retry mechanism broken

**Location**: Likely in shared/utils/pipeline_logger.py or retry queue SQL

**Example of Bad SQL**:
```sql
-- Python string concatenation without space
INSERT INTO table VALUES ('value1''value2')  -- SYNTAX ERROR
-- Should be:
INSERT INTO table VALUES ('value1' 'value2')  -- OK (needs space)
-- Or better:
INSERT INTO table VALUES ('value1', 'value2')  -- OK (proper format)
```

**Fix**: Find and fix SQL string concatenation in retry queue logic

---

## Blocker #3: Pub/Sub Message Backlog

**Context**:
Phase 3 service has two trigger mechanisms:
1. **Scheduler** (`same-day-phase3`): Triggers `/process-date-range` with "TODAY"
2. **Pub/Sub** (`nba-phase2-raw-complete`): Triggers `/process` with specific dates

**Problem**:
Pub/Sub subscription `nba-phase3-analytics-sub` has backlog of old messages from when Phase 3 was failing (due to dependency validation false positives).

**Evidence from Logs**:
```
Processing date: 2026-01-02  (24 days old)
Processing date: 2026-01-03  (23 days old)
Processing date: 2026-01-05  (21 days old)
Processing date: 2026-01-06  (20 days old)
```

**Why It's Failing**:
- Data for these old dates IS actually stale (legitimately >400h old)
- Each retry hits BigQuery quota limit
- Each retry fails SQL syntax error
- Creates infinite retry loop

**Subscription Details**:
```yaml
name: nba-phase3-analytics-sub
topic: nba-phase2-raw-complete
endpoint: https://nba-phase3-analytics-processors-...us-west2.run.app/process
deadLetterPolicy:
  deadLetterTopic: nba-phase2-raw-complete-dlq
  maxDeliveryAttempts: 5
```

**Fix Options**:
1. Purge old messages from subscription (loses backlog data)
2. Let them fail to DLQ and move on
3. Adjust maxDeliveryAttempts to 0 (stop retries)
4. Temporarily disable subscription, process TODAY, re-enable

---

## Blocker #4: Scheduler Job vs Pub/Sub Confusion

**Problem**: Scheduler job seems to trigger but doesn't process TODAY.

**Scheduler Config** (Correct):
```yaml
job: same-day-phase3
schedule: 30 10 * * *  # 10:30 AM ET
body: {"start_date": "TODAY", "end_date": "TODAY", ...}
endpoint: /process-date-range
```

**Logs**: No evidence of "TODAY resolved to 2026-01-26" in logs

**Hypothesis**:
- Scheduler job IS triggering
- But `/process-date-range` endpoint might be failing silently
- OR requests are being queued behind Pub/Sub backlog
- OR there's an auth/routing issue

**Verification Needed**:
- Check if scheduler requests are even reaching the service
- Check for 403/401 errors in Cloud Run request logs
- Verify OIDC token is valid

---

## Blocker #5: Dependency Validation Still Failing

**Even with fix**, seeing stale dependency errors:

**For OLD dates (expected to fail)**:
```
ERROR: bigdataball_play_by_play: 467.0h old (max: 24h)
       - Date: 2026-01-02 (legitimate - IS stale)

ERROR: team_offense_game_summary: 92.8h old (max: 72h)
       - Date: 2026-01-02 (legitimate - IS stale)
```

**For TODAY (should NOT fail)**:
- No logs found for TODAY's UpcomingPlayerGameContext run
- Can't verify if dependency fix works for current date

---

## Current State

**Phase 3 Completion** (2026-01-26):
```
✅ team_offense_game_summary (1/5) - Only one complete
❌ player_game_summary
❌ team_defense_game_summary
❌ upcoming_player_game_context
❌ upcoming_team_game_context
```

**Phase 4**: Not triggered (waiting for 5/5 Phase 3 completion)

**Predictions**: Still 0

---

## Recommended Recovery Path

### Option A: Nuclear - Purge and Restart (30 min)
1. Purge old Pub/Sub messages: `gcloud pubsub subscriptions seek nba-phase3-analytics-sub --time=2026-01-26T00:00:00Z`
2. Fix SQL syntax error in retry queue
3. Temporarily disable pipeline_event_log writes
4. Manually trigger scheduler: `gcloud scheduler jobs run same-day-phase3`
5. Monitor for completion
6. Re-enable pipeline_event_log once quota resets

**Risk**: Lose backlog data, might break other things

### Option B: Targeted - Fix Root Causes (4-8 hours)
1. Fix SQL syntax error in retry queue (1 hour)
2. Request BigQuery quota increase (24-48 hour wait)
3. Implement batched pipeline event writes (2 hours)
4. Let old messages fail to DLQ naturally
5. Verify scheduler job for TODAY works
6. Manual trigger once fixes deployed

**Risk**: Takes time, predictions delayed

### Option C: Workaround - Skip Phase 3 (1 hour)
1. Manually load minimal data to Phase 3 completion tables
2. Mark 5/5 complete in Firestore
3. Trigger Phase 4 directly
4. Generate predictions with degraded data quality

**Risk**: Predictions may be inaccurate

---

## Files Needing Investigation

1. **Retry Queue SQL**:
   - shared/utils/pipeline_logger.py
   - Look for string concatenation in SQL INSERT statements

2. **Pipeline Event Logging**:
   - shared/utils/bigquery_utils.py
   - Consider batching writes instead of individual inserts

3. **Pub/Sub Handling**:
   - data_processors/analytics/main_analytics_service.py
   - /process endpoint logic

4. **Scheduler Auth**:
   - Check Cloud Run invoker permissions
   - Verify OIDC token audience

---

## Questions for Next Session

1. **BigQuery Quota**: Can we increase it? Or batch writes?
2. **Backlog Strategy**: Purge old messages or let fail to DLQ?
3. **Retry Queue**: Where is the SQL syntax error?
4. **Scheduler**: Is it reaching the service? Check request logs.
5. **Priority**: Continue debugging or implement preventive measures first?

---

## Recommendation

**DEFER manual recovery**. Focus on:
1. Implement Quick Win resilience improvements (prevent future incidents)
2. Fix underlying issues (SQL syntax, BigQuery quota, batching)
3. Come back to manual recovery with better tooling

**Rationale**:
- Manual recovery is blocked by multiple systemic issues
- Fixes will take 4-8 hours minimum
- Resilience improvements prevent THIS from happening again
- Better to spend time on prevention than fighting fires

**Today's games**: Already missed (7 PM games, now 8 PM ET)

**Tomorrow's games**: Will benefit from:
- Betting timing fix (already deployed)
- Resilience improvements (prevent similar issues)
- Proper debugging with better tooling

---

**Status**: Documented blockers, recommending pivot to resilience improvements
**Next**: Implement Quick Win improvements, then return to recovery with better foundation
