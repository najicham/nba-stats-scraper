# Session 9 Handoff - January 11, 2026

**Session:** Schedule Processor MERGE Fix
**Status:** COMPLETED - All fixes deployed and tested
**Time:** Morning session

---

## What Was Done This Session

### 1. Fixed Schedule Processor MERGE Bug (CRITICAL)

The `nbac_schedule_processor.py` was using DELETE (entire season) + WRITE_APPEND instead of proper MERGE, causing duplicate rows with conflicting game statuses.

**Changes Made:**
- Added `PRIMARY_KEY_FIELDS = ['game_id', 'game_date']`
- Replaced `save_data()` with atomic SQL MERGE (temp table → MERGE → cleanup)
- Added `_sanitize_row_for_bq()` helper method

**File:** `data_processors/raw/nbacom/nbac_schedule_processor.py`

### 2. Created Deduplication View

**View:** `nba_raw.v_nbac_schedule_latest`
- Returns only one row per game_id (highest game_status wins)
- 90-day past / 30-day future range for partition elimination

**File:** `schemas/bigquery/raw/nbac_schedule_tables.sql`

### 3. Added Post-Game Schedule Refresh

Added `nbac_schedule_api` to post-game workflows so schedule refreshes after games finish:
- `post_game_window_2` (1 AM ET)
- `post_game_window_3` (4 AM ET)

**File:** `config/workflows.yaml`

### 4. Added Monitoring and Tests

- Duplicate detection query: `validation/queries/raw/nbac_schedule/duplicate_detection_check.sql`
- 19 unit tests: `tests/processors/raw/nbacom/nbac_schedule/test_unit.py`

### 5. Deployment

- Revision: `nba-phase2-raw-processors-00084-znv`
- Status: Serving 100% traffic, health check passed
- Commit: `772bb73`

---

## How to Use Agents

This codebase benefits from using agents for exploration. Use these patterns:

### For Code Exploration
```
Use the Task tool with subagent_type=Explore:
"Read all files in docs/01-architecture/ and summarize the pipeline architecture"
"Find all processors that use MERGE_UPDATE strategy and show implementation"
"Search for files that query nba_raw.nbac_schedule"
```

### For Multi-File Changes
```
Use the Task tool with subagent_type=Plan:
"Plan the implementation for adding a new validation layer"
```

### Run Multiple Agents in Parallel
When exploring, launch multiple agents simultaneously:
- One to read architecture docs
- One to search code patterns
- One to check recent handoffs

---

## Documentation to Study

### Priority 1: Recent Context
```
docs/09-handoff/2026-01-11-SCHEDULE-MERGE-FIX-HANDOFF.md  # Today's detailed handoff
docs/09-handoff/2026-01-11-SCHEDULE-FIX-HANDOFF.md        # Original problem description
docs/09-handoff/2026-01-11-SESSION-8-HANDOFF.md           # Previous session context
```

### Priority 2: Architecture
```
docs/01-architecture/                    # 6-phase pipeline, processors, BigQuery strategies
docs/02-operations/daily-validation-checklist.md  # Updated with new view
```

### Priority 3: Project Status
```
docs/08-projects/current/pipeline-reliability-improvements/README.md  # Updated with Jan 11 session
```

---

## Code to Study

### The Fixed Processor
```python
# Main fix - understand the MERGE pattern
data_processors/raw/nbacom/nbac_schedule_processor.py

# Key sections:
# - Line 46-48: PRIMARY_KEY_FIELDS definition
# - Line 594-755: save_data() with MERGE implementation
# - Line 741-755: _sanitize_row_for_bq() helper
```

### Reference Implementation
```python
# The proper MERGE pattern used by analytics processors
data_processors/analytics/analytics_base.py  # Lines 1651-1781: _save_with_proper_merge()
```

### Tests
```python
tests/processors/raw/nbacom/nbac_schedule/test_unit.py  # 19 tests for MERGE logic
```

---

## Verification Commands

### Check Deployment Health
```bash
# Verify service is healthy
curl -s "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq

# Check current revision
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"
```

### Check Schedule Data
```bash
# Use the new view for clean data
bq query --use_legacy_sql=false "
SELECT game_id, game_status, game_status_text
FROM nba_raw.v_nbac_schedule_latest
WHERE game_date = CURRENT_DATE()
ORDER BY game_id"

# Check for duplicates (should be 0)
bq query --use_legacy_sql=false "
SELECT game_id, COUNT(*) as copies
FROM nba_raw.nbac_schedule
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_id
HAVING COUNT(*) > 1"
```

### Run Tests
```bash
PYTHONPATH=. python -m pytest tests/processors/raw/nbacom/nbac_schedule/test_unit.py -v
```

---

## Next Steps / Priorities

### Monitor Tonight's Games
After games finish, verify:
1. Schedule shows "Final" status (via `post_game_window_2` at 1 AM ET)
2. No new duplicates created
3. MERGE is working correctly

### Potential Follow-Up Work

1. **Clean up historical duplicates** (if any exist beyond 3-day window)
   ```sql
   -- Check for historical duplicates
   SELECT game_date, game_id, COUNT(*)
   FROM nba_raw.nbac_schedule
   WHERE game_date >= '2025-10-01'
   GROUP BY game_date, game_id
   HAVING COUNT(*) > 1
   ```

2. **Consider PRIMARY_KEY_FIELDS simplification**
   - Current: `['game_id', 'game_date']`
   - Could be just `['game_id']` since game_id is globally unique
   - Risk: If a game gets rescheduled to different date, MERGE might miss old row

3. **Add integration tests** for full MERGE flow with mocked BigQuery

---

## Git Status

All changes committed and pushed to main:
```
8762286 fix(schedule): Replace WRITE_APPEND with proper SQL MERGE
9afe84a fix(workflows): Add schedule refresh to post-game windows
55034d2 feat(monitoring): Add schedule duplicate detection query
772bb73 test(schedule): Add unit tests for MERGE logic + update project docs
```

---

## Key Learnings

1. **MERGE vs DELETE + APPEND**: The schedule processor claimed MERGE_UPDATE but actually used DELETE (entire season) + APPEND. Other raw processors have properly-scoped DELETEs or use true MERGE.

2. **Partition Awareness**: BigQuery tables with `require_partition_filter = true` need special handling in views - the filter must be inside the subquery for partition elimination.

3. **Atomic Operations**: The proper pattern is: temp table → MERGE → cleanup (in finally block). This prevents race conditions and duplicates.

4. **Root Cause vs Symptom**: The view fixes the symptom (duplicates visible). The MERGE fix prevents future duplicates. The workflow fix addresses root cause (schedule not refreshing after games).

---

## Agent Commands to Start Next Session

```
1. "Read docs/09-handoff/2026-01-11-SESSION-9-HANDOFF.md for context on what was done"

2. "Check if tonight's games show Final status:
    bq query --use_legacy_sql=false 'SELECT game_id, game_status_text
    FROM nba_raw.v_nbac_schedule_latest WHERE game_date = CURRENT_DATE()'"

3. "Check for any duplicates created overnight:
    bq query --use_legacy_sql=false 'SELECT game_id, COUNT(*)
    FROM nba_raw.nbac_schedule WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    GROUP BY game_id HAVING COUNT(*) > 1'"

4. "Read docs/08-projects/current/pipeline-reliability-improvements/README.md for project status"
```

---

**End of Handoff**
