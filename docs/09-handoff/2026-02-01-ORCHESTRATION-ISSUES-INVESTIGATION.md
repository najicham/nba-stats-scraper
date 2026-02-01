# Daily Orchestration Issues - Feb 1, 2026 Investigation

**Date**: February 1, 2026 (Session 68)
**Game Date**: Jan 31, 2026 (6 games played)
**Processing Date**: Feb 1, 2026 (overnight processing)
**Status**: 🟡 Data exists but orchestration tracking inconsistent

---

## Executive Summary

Daily validation revealed **orchestration tracking issues** - data was processed correctly, but completion tracking is inconsistent between Firestore and actual BigQuery data.

### Critical Finding

**Phase 3 Firestore Completion: 3/5 processors** ⚠️

| Processor | Firestore Status | Heartbeat Status | BigQuery Data | Issue |
|-----------|------------------|------------------|---------------|-------|
| team_offense_game_summary | ✅ Registered | ✅ completed | ✅ 24 records | OK |
| team_defense_game_summary | ✅ Registered | ✅ completed | ✅ 12 records | OK |
| upcoming_player_game_context | ✅ Registered | ✅ completed | ✅ 326 records | OK |
| **player_game_summary** | ❌ NOT registered | ✅ completed | ✅ 212 records | **SYNC ISSUE** |
| **upcoming_team_game_context** | ❌ NOT registered | ✅ completed | ❓ Unknown | **SYNC ISSUE** |

**Impact**: Low severity (data exists) but indicates **Firestore sync problem** that could affect Phase 4 auto-trigger.

---

## Issue 1: Phase 3 Firestore Completion Discrepancy

### What We Observed

**Firestore Document** (`phase3_completion/2026-02-01`):
```python
{
  'team_defense_game_summary': {
    'correlation_id': '1b45dedf',
    'completed_at': 2026-02-01 15:00:13 UTC,
    'record_count': 0,  # ⚠️ Shows 0 but table has 12 records
    'status': 'success'
  },
  'team_offense_game_summary': {
    'correlation_id': '1c3cfaf5',
    'completed_at': 2026-02-01 15:00:12 UTC,
    'record_count': 0,  # ⚠️ Shows 0 but table has 24 records
    'status': 'success'
  },
  'upcoming_player_game_context': {
    'correlation_id': '0a807a75',
    'completed_at': 2026-02-01 15:04:29 UTC,
    'record_count': 326,
    'status': 'success'
  }
  # ❌ Missing: player_game_summary
  # ❌ Missing: upcoming_team_game_context
}
```

**Heartbeat Status** (Firestore `processor_heartbeats`):
```python
# PlayerGameSummaryProcessor
{
  'processor_name': 'PlayerGameSummaryProcessor',
  'status': 'completed',
  'last_heartbeat': 2026-02-01 15:01:02 UTC,
  'data_date': '2026-01-31',
  'progress': 0,
  'error_message': None
}

# UpcomingTeamGameContextProcessor
{
  'processor_name': 'UpcomingTeamGameContextProcessor',
  'status': 'completed',
  'last_heartbeat': 2026-02-01 11:00:23 UTC,
  'data_date': '2026-01-31',
  'error_message': None
}
```

**BigQuery Data** (Actual results):
```sql
-- player_game_summary
SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = '2026-01-31'
-- Result: 212 records (processed_at: 2026-02-01 15:00:48 UTC)

-- team_offense_game_summary
SELECT COUNT(*) FROM nba_analytics.team_offense_game_summary WHERE game_date = '2026-01-31'
-- Result: 24 records

-- team_defense_game_summary
SELECT COUNT(*) FROM nba_analytics.team_defense_game_summary WHERE game_date = '2026-01-31'
-- Result: 12 records
```

### Analysis

**Data Pipeline Flow**:
```
1. Processors run (Cloud Run invocations)
   ├─> Write to BigQuery ✅ (all 5 processors wrote data)
   ├─> Update heartbeat ✅ (all 5 processors updated)
   └─> Write to phase3_completion ❌ (only 3 of 5 wrote)

2. Phase 4 auto-trigger checks phase3_completion
   ├─> Sees 3/5 complete
   └─> May not trigger? (needs investigation)
```

**Possible Root Causes**:

#### Hypothesis 1: Race Condition in Firestore Write ⭐ MOST LIKELY
- Processors complete and write to Firestore simultaneously
- Firestore document update may be getting overwritten
- Transaction conflict or missing merge operation

**Evidence**:
- All processors show "completed" in heartbeats (separate documents)
- Only some show in phase3_completion (single document with multiple fields)
- Heartbeats use individual documents (no conflicts)
- phase3_completion uses one document with multiple fields (potential conflicts)

**Code to investigate**:
- `shared/monitoring/phase_completion.py` - How completion is written
- Check if using Firestore transactions
- Check if using merge vs set operations

#### Hypothesis 2: Completion Write Failure (Silent)
- Processor completes but Firestore write fails
- Error is swallowed/logged but not raised
- Processor reports success despite failed completion write

**Evidence**:
- No errors in heartbeat status
- Data was written successfully to BigQuery
- Completion write may have failed after data write

**Code to investigate**:
- Error handling in completion write logic
- Check if exceptions are caught and ignored

#### Hypothesis 3: Timing-Based Issue
- `upcoming_team_game_context` completed at 11:00 UTC (4 hours earlier than others)
- `player_game_summary` completed at 15:01 UTC (with others)
- Different completion times may affect Firestore sync

**Evidence**:
- Time gap between processors (4 hours)
- Earlier processor missing, later processors present

---

## Issue 2: Record Count Discrepancy in Completion

### What We Observed

Firestore completion document shows `record_count: 0` for team processors:

```python
'team_offense_game_summary': {
  'record_count': 0,  # ⚠️ BigQuery has 24 records
  'status': 'success'
},
'team_defense_game_summary': {
  'record_count': 0,  # ⚠️ BigQuery has 12 records
  'status': 'success'
}
```

But BigQuery has data:
- `team_offense_game_summary`: 24 records
- `team_defense_game_summary`: 12 records

### Analysis

**Possible Causes**:

1. **Record count tracking bug**: Processor doesn't increment count
2. **Empty batch writes**: Writes succeed but count not tracked
3. **Count vs entities_changed**: Using wrong metric

**Impact**: Low - completion still marked success, but inaccurate metrics

**Code to investigate**:
- How processors track `record_count`
- Check if batch writes update count correctly

---

## Issue 3: DNP Player Coverage Confusion (False Alarm)

### What We Observed

Initial validation showed:
- **Minutes played coverage**: 55.7% (118 out of 212 players)
- **Appeared to be**: Data quality issue

### Actual Reality

This is **correct behavior**:
- 118 players played (100% have minutes)
- 94 players DNP (Did Not Play) - correctly flagged as `is_dnp = TRUE`
- Total: 212 players (all correctly classified)

**Verification**:
```sql
SELECT is_dnp, COUNT(*), COUNTIF(minutes_played > 0)
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-31'
GROUP BY is_dnp

-- Result:
-- is_dnp=true: 94 players, 0 with minutes ✅ Correct
-- is_dnp=false: 118 players, 118 with minutes ✅ Correct
```

### Lesson Learned

**Validation False Positive**: The 55.7% coverage metric was misleading because it included DNP players in the denominator.

**Fix for Validation**:
```sql
-- CORRECT: Filter DNP players when checking minutes coverage
SELECT
  COUNT(*) as active_players,
  COUNTIF(minutes_played > 0) as has_minutes,
  ROUND(100.0 * COUNTIF(minutes_played > 0) / COUNT(*), 1) as coverage
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-31'
  AND is_dnp = FALSE  -- ✅ Only check active players
```

**Update Needed**: Validation script should filter `is_dnp = FALSE` before checking coverage.

---

## Issue 4: Phase Execution Log Empty

### What We Observed

The `nba_orchestration.phase_execution_log` table had **0 records** for Jan 31:

```sql
SELECT COUNT(*) FROM nba_orchestration.phase_execution_log WHERE game_date = '2026-01-31'
-- Result: 0
```

**Expected**: Should have 3 records (phase2→3, phase3→4, phase4→5)

### Analysis

This table tracks orchestrator transitions between phases. Empty table suggests:

1. **Orchestrators didn't log**: Phase orchestrators ran but didn't write to execution log
2. **Table not being used**: Newer system may use different tracking
3. **Logging not enabled**: Feature may be disabled or not deployed

**Impact**: Medium - loses visibility into phase transition timing and health

**Fallback Check**: Used `processor_run_history` instead:
```sql
SELECT phase, COUNT(DISTINCT processor_name) as processors
FROM nba_orchestration.processor_run_history
WHERE data_date = '2026-01-31'
  AND phase IN ('phase_3_analytics', 'phase_4_precompute', 'phase_5_predictions')
GROUP BY phase
```

**Questions for Investigation**:
1. Is `phase_execution_log` still being used?
2. Are orchestrators deployed with logging enabled?
3. Should validation use different table for phase tracking?

---

## Investigation Plan

### Priority 1: Firestore Sync Issue (P1 - CRITICAL)

**Goal**: Understand why 2 processors don't register in phase3_completion

**Steps**:

1. **Review Completion Write Code**:
   ```bash
   # Find completion write logic
   grep -r "phase3_completion" --include="*.py" | grep -v test | grep -v ".pyc"

   # Likely location: shared/monitoring/phase_completion.py
   ```

2. **Check Firestore Transaction Usage**:
   - Does it use `set(merge=True)` or `set()`?
   - Are there concurrent writes to same document?
   - Is there error handling around Firestore writes?

3. **Review Processor Completion Logic**:
   ```bash
   # Check base processor class
   cat data_processors/base_processor.py | grep -A 20 "def finalize\|def complete"
   ```

4. **Check Cloud Run Logs for Errors**:
   ```bash
   # Look for Firestore errors during processor completion
   gcloud logging read 'resource.type="cloud_run_revision"
     AND resource.labels.service_name="nba-phase3-analytics-processors"
     AND timestamp>="2026-02-01T14:00:00Z"
     AND timestamp<="2026-02-01T16:00:00Z"
     AND (severity>=WARNING OR jsonPayload.message=~"phase3_completion|completion|firestore")' \
     --limit=100 --format=json
   ```

5. **Test Concurrent Writes**:
   - Simulate multiple processors completing simultaneously
   - Check if Firestore document gets corrupted
   - Verify merge behavior

**Expected Findings**:
- Likely missing `merge=True` in Firestore write
- Or transaction conflict when multiple processors write simultaneously

**Fix**:
- Use `set(merge=True)` to prevent overwrites
- Or use Firestore transactions for atomic updates
- Add error handling and retry logic

---

### Priority 2: Record Count Tracking (P2 - MEDIUM)

**Goal**: Understand why `record_count: 0` in completion document

**Steps**:

1. **Check How Record Count is Tracked**:
   ```python
   # Find where record_count is set
   grep -r "record_count" shared/monitoring/ data_processors/base_processor.py
   ```

2. **Review Team Processor Code**:
   ```bash
   # Check team offense/defense processors
   cat data_processors/analytics/team_offense_game_summary_processor.py | grep -A 10 "record_count\|write_batch"
   cat data_processors/analytics/team_defense_game_summary_processor.py | grep -A 10 "record_count\|write_batch"
   ```

3. **Compare Working vs Non-Working**:
   - Why does `upcoming_player_game_context` show 326 records correctly?
   - What's different about team processors?

**Expected Findings**:
- Team processors may not increment record count
- Or batch write doesn't update count correctly

**Fix**:
- Ensure all processors properly track and report record count
- Or remove field if not reliably tracked

---

### Priority 3: Phase Execution Log (P3 - LOW)

**Goal**: Determine if this table is still used or if validation should use different source

**Steps**:

1. **Check Orchestrator Code**:
   ```bash
   # Find orchestrator services
   find orchestration/ -name "*.py" | xargs grep "phase_execution_log"
   ```

2. **Check Recent Deployments**:
   ```bash
   # When was orchestrator last deployed?
   gcloud run revisions list --service="nba-orchestrator" --region=us-west2 --limit=5
   ```

3. **Decide on Tracking Source**:
   - Use `processor_run_history` instead?
   - Re-enable `phase_execution_log` logging?
   - Create new tracking table?

**Expected Findings**:
- Table may be legacy/unused
- Validation should use `processor_run_history` as primary source

**Fix**:
- Update validation to use `processor_run_history`
- Or re-enable orchestrator logging if desired

---

### Priority 4: Validation Coverage Metric (P2 - MEDIUM)

**Goal**: Fix false positive on minutes coverage check

**Steps**:

1. **Update Validation Script**:
   ```bash
   # Find validation script
   cat scripts/validate_tonight_data.py | grep -A 20 "minutes_played"
   ```

2. **Add DNP Filter**:
   - Update queries to filter `is_dnp = FALSE`
   - Recalculate expected coverage thresholds

3. **Update Validation Skill**:
   - Update `.claude/skills/validate-daily/SKILL.md`
   - Add note about DNP players in coverage checks

**Expected Findings**:
- Current validation checks all players (including DNP)
- Should only check active players

**Fix**:
- Add `WHERE is_dnp = FALSE` to coverage queries
- Update threshold expectations (should be 95%+ for active players)

---

## Verification Queries

### Check Phase 3 Completion Status

```python
from google.cloud import firestore

db = firestore.Client(project='nba-props-platform')

# Get completion document
doc = db.collection('phase3_completion').document('2026-02-01').get()
if doc.exists:
    data = doc.to_dict()
    print(f"Processors registered: {len([k for k in data.keys() if not k.startswith('_')])}/5")
    print("\nCompleted processors:")
    for key, value in data.items():
        if not key.startswith('_'):
            print(f"  {key}: {value}")
    print("\nMissing processors:")
    expected = ['player_game_summary', 'team_offense_game_summary', 'team_defense_game_summary',
                'upcoming_player_game_context', 'upcoming_team_game_context']
    registered = [k for k in data.keys() if not k.startswith('_')]
    missing = set(expected) - set(registered)
    for proc in missing:
        print(f"  {proc}")
```

### Check Heartbeat vs Completion Discrepancy

```python
from google.cloud import firestore

db = firestore.Client(project='nba-props-platform')

# Check heartbeats
heartbeats = db.collection('processor_heartbeats').stream()
print("Heartbeat Status:")
for doc in heartbeats:
    data = doc.to_dict()
    if data.get('data_date') == '2026-01-31':
        print(f"  {doc.id}: {data.get('status')} at {data.get('last_heartbeat')}")

# Check completion
completion = db.collection('phase3_completion').document('2026-02-01').get()
if completion.exists:
    print("\nCompletion Document:")
    data = completion.to_dict()
    for key in data.keys():
        if not key.startswith('_'):
            print(f"  {key}: registered")
```

### Verify BigQuery Data Exists

```sql
-- Check all Phase 3 tables for Jan 31
SELECT 'player_game_summary' as table_name, COUNT(*) as records,
       MIN(processed_at) as first, MAX(processed_at) as last
FROM nba_analytics.player_game_summary WHERE game_date = '2026-01-31'
UNION ALL
SELECT 'team_offense_game_summary', COUNT(*), MIN(processed_at), MAX(processed_at)
FROM nba_analytics.team_offense_game_summary WHERE game_date = '2026-01-31'
UNION ALL
SELECT 'team_defense_game_summary', COUNT(*), MIN(processed_at), MAX(processed_at)
FROM nba_analytics.team_defense_game_summary WHERE game_date = '2026-01-31'
UNION ALL
SELECT 'upcoming_player_game_context', COUNT(*), MIN(created_at), MAX(created_at)
FROM nba_analytics.upcoming_player_game_context WHERE game_date = '2026-02-01'
UNION ALL
SELECT 'upcoming_team_game_context', COUNT(*), MIN(created_at), MAX(created_at)
FROM nba_analytics.upcoming_team_game_context WHERE game_date = '2026-02-01'
```

---

## Questions for Next Session

1. **Firestore Completion Strategy**:
   - Should we use single document with merge, or separate documents per processor?
   - Should completion writes be transactional?

2. **Phase 4 Auto-Trigger**:
   - Does it check `phase3_completion` or `processor_run_history`?
   - Did Phase 4 trigger successfully despite 3/5 completion?

3. **Record Count Reliability**:
   - Is `record_count` critical for orchestration decisions?
   - Should we remove it if not reliably tracked?

4. **Validation Data Source**:
   - Should validation use `processor_run_history` instead of `phase_execution_log`?
   - Should we add fallback checks for multiple data sources?

---

## Success Metrics

After fixes are implemented:

| Issue | Before | Target |
|-------|--------|--------|
| Phase 3 completion | 3/5 processors | **5/5 processors** |
| Record count accuracy | 0 for team tables | Actual count |
| Minutes coverage false alarm | 55.7% (misleading) | 95%+ (DNP filtered) |
| Phase execution log | 0 records | Logged or validation uses alt source |

---

## Related Documents

- **Session handoff**: `docs/09-handoff/2026-02-01-SESSION-68-VALIDATION-V9-ANALYSIS.md`
- **Grading gap prevention**: `docs/08-projects/current/catboost-v9-experiments/GRADING-BACKFILL-GAP-PREVENTION.md`
- **Heartbeat system**: `CLAUDE.md` Section on Heartbeat System

---

**Status**: 📋 Investigation Required
**Priority**: P1 (Firestore sync), P2 (Record count, Validation), P3 (Phase log)
**Owner**: Next Investigation Session
**Data Status**: ✅ All data exists correctly, tracking is inconsistent

---

*Document created: Session 68, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
