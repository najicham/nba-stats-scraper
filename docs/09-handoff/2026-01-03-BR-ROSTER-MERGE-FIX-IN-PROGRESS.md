# BR Roster MERGE Fix - Deployment In Progress

**Date**: 2026-01-03 (started 2026-01-02)
**Status**: 🚧 Deploying (fresh build in progress)
**Priority**: P0
**Objective**: Fix Basketball Reference roster concurrency bug

---

## Quick Status

✅ Code written and tested (commit cd5e0a1)
✅ Test script passed (test_br_roster_merge.py)
✅ Documentation created
🚧 Fresh deployment in progress (using --no-cache)
⏳ Validation pending

---

## What Was Done

### 1. Ultrathink Analysis
Analyzed the concurrency problem and evaluated solutions:
- Current: 30 teams × UPDATE = 30 concurrent DML → exceeds BigQuery limit
- Solution: Replace UPDATE with MERGE (atomic, better BigQuery optimization)
- Alternative considered: Single MERGE for all teams (requires architecture change)

### 2. Code Implementation
**File**: `data_processors/raw/basketball_ref/br_roster_processor.py`
**Lines**: 281-426 (save_data method completely rewritten)

**Old Pattern**:
```python
# Batch load for new players
load_job = bq_client.load_table_from_json(new_rows, table_id)

# UPDATE for existing players
UPDATE `table` SET last_scraped_date = CURRENT_DATE() WHERE ...
```

**New Pattern** (MERGE):
```python
# 1. Load all data to temp table
load_job = bq_client.load_table_from_json(all_data, temp_table)

# 2. Single atomic MERGE
MERGE `table` AS target
USING `temp_table` AS source
ON target.team_abbrev = source.team_abbrev ...
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...

# 3. Clean up temp table
bq_client.delete_table(temp_table)
```

### 3. Testing
Created `test_br_roster_merge.py`:
- Tests both INSERT (new players) and UPDATE (existing) scenarios
- Validates temp table creation/cleanup
- Verifies MERGE DML statistics
- ✅ ALL TESTS PASSED

### 4. Deployment Issue
First deployment attempt deployed old code (cached Docker layers):
- Intended commit: cd5e0a1 (our MERGE fix)
- Actually deployed: 6f8a781 (old code)
- Evidence: Logs show "Updating X existing players" and line 353/355 errors

Redeploying with `--no-cache` flag to force fresh build.

---

## Current Deployment

### Command
```bash
gcloud run deploy nba-phase2-raw-processors \
  --source . \
  --region us-west2 \
  --no-cache \
  --memory 2Gi \
  --timeout 3600
```

### Monitoring
```bash
# Check deployment progress
tail -f /tmp/fresh_deploy.log

# Or check task output
cat /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b6d7893.output
```

---

## Validation Steps (After Deployment)

### 1. Verify Correct Code Deployed
```bash
# Check for MERGE in recent logs (should see this)
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND textPayload=~"MERGE complete"' \
  --limit=10

# Check for OLD pattern (should NOT see this)
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND textPayload=~"Updating.*existing players"' \
  --limit=10
```

### 2. Monitor for Errors
```bash
# Should see ZERO concurrent update errors after fix
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND severity=ERROR
  AND textPayload=~"concurrent update"' \
  --limit=10 \
  --freshness=1d
```

### 3. Verify All Teams Process Successfully
```bash
# Check all 30 teams have recent roster data
bq query --use_legacy_sql=false '
SELECT
  team_abbrev,
  COUNT(*) as roster_size,
  MAX(last_scraped_date) as last_update
FROM `nba-props-platform.nba_raw.br_rosters_current`
WHERE season_year = 2024
GROUP BY team_abbrev
ORDER BY team_abbrev
'

# Expected: 30 teams, each with 12-18 players, recent last_update
```

### 4. 48-Hour Monitoring
Monitor production for 48 hours to confirm:
- ✅ Zero concurrent update errors
- ✅ All 30 teams process successfully
- ✅ MERGE operations complete within expected timeframes
- ✅ No manual intervention needed

---

## Files Changed

| File | Status | Description |
|------|--------|-------------|
| `data_processors/raw/basketball_ref/br_roster_processor.py` | ✅ Committed | MERGE pattern implementation |
| `test_br_roster_merge.py` | ✅ Committed | Test script (all tests passed) |
| `docs/08-projects/current/pipeline-reliability-improvements/2026-01-02-BR-ROSTER-CONCURRENCY-FIX.md` | ✅ Created | Comprehensive technical documentation |
| `docs/09-handoff/2026-01-03-BR-ROSTER-MERGE-FIX-IN-PROGRESS.md` | ✅ Created | This handoff doc |

**Commit**: cd5e0a1
**Commit Message**: "fix: Replace batch load + UPDATE with atomic MERGE in BR roster processor"

---

## Expected Outcome

### Before Fix
- Concurrent DML: 30 UPDATEs
- Error rate: 30-50% of runs
- Error: "Could not serialize access... concurrent update"
- Manual intervention: Required daily

### After Fix
- Concurrent DML: 30 MERGEs (better optimized)
- Error rate: 0% expected
- Error: None
- Manual intervention: None needed

---

## If Issues Persist

### Option 1: Add Semaphore (Rate Limiting)
If 30 concurrent MERGEs still cause issues, add rate limiting:

```python
from threading import Semaphore

MAX_CONCURRENT = 15  # Process max 15 teams at once
semaphore = Semaphore(MAX_CONCURRENT)

def save_with_rate_limit():
    with semaphore:
        # MERGE logic here
        pass
```

This guarantees we never exceed BigQuery's lower limit (20).

### Option 2: Rollback
If critical issues discovered:

```bash
# Revert code
git revert cd5e0a1
git push origin main

# Redeploy old code
gcloud run deploy nba-phase2-raw-processors --source . --region us-west2

# Or use previous revision
gcloud run services update-traffic nba-phase2-raw-processors \
  --to-revisions=PREVIOUS_REVISION=100 \
  --region=us-west2
```

---

## Next Steps

1. **Wait for deployment to complete** (~10-15 minutes)
2. **Verify correct code deployed** (check logs for "MERGE complete")
3. **Monitor next BR roster run** (should be today)
4. **Validate zero errors** for 48 hours
5. **Mark as complete** if successful

---

## Evidence of Problem (Before Fix)

From production logs (2026-01-03 01:02 UTC):
```
ERROR:processor_base:ProcessorBase Error: Timeout of 120.0s exceeded,
last exception: 400 Could not serialize access to table
nba-props-platform:nba_raw.br_rosters_current due to concurrent update

File "/app/data_processors/raw/basketball_ref/br_roster_processor.py",
line 353, in execute_with_retry
```

This is the EXACT error we're fixing!

---

## Documentation

**Comprehensive Technical Doc**:
`docs/08-projects/current/pipeline-reliability-improvements/2026-01-02-BR-ROSTER-CONCURRENCY-FIX.md`

Contains:
- Root cause analysis
- Ultrathink evaluation of solutions
- Complete MERGE implementation details
- Testing results
- Deployment instructions
- Monitoring and validation steps

---

**Status**: 🚧 Fresh deployment in progress (--no-cache)
**Next Check**: Verify deployment completed and correct code is running
**ETA**: 10-15 minutes for deployment

**Owner**: Claude Sonnet 4.5
**Date**: 2026-01-03
