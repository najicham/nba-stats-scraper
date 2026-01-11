# Schedule Processor MERGE Fix Handoff

**Date:** 2026-01-11
**Session:** Schedule Processor Fix
**Status:** COMPLETED

---

## Summary

Fixed the `nbac_schedule_processor` to use proper SQL MERGE instead of DELETE + WRITE_APPEND. This prevents duplicate rows with conflicting game statuses.

---

## Changes Made

### 1. Created Deduplication View

**File:** `schemas/bigquery/raw/nbac_schedule_tables.sql`

Added `nba_raw.v_nbac_schedule_latest` view that:
- Returns only one row per game_id
- Orders by `game_status DESC` (Final=3 wins over Scheduled=1)
- Orders by `processed_at DESC` as tiebreaker
- Limited to 90 days past / 30 days future for partition elimination

```sql
CREATE OR REPLACE VIEW `nba_raw.v_nbac_schedule_latest` AS
SELECT * EXCEPT(rn)
FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY game_id
      ORDER BY game_status DESC, processed_at DESC
    ) as rn
  FROM `nba_raw.nbac_schedule`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 30 DAY)
)
WHERE rn = 1
```

**View deployed:** ✅ Yes (created in BigQuery)

### 2. Fixed Schedule Processor

**File:** `data_processors/raw/nbacom/nbac_schedule_processor.py`

Changes:
- Added imports: `io`, `uuid`
- Added `PRIMARY_KEY_FIELDS = ['game_id', 'game_date']`
- Replaced `save_data()` method with proper MERGE implementation:
  1. Create temp table with unique name
  2. Load data into temp table (WRITE_TRUNCATE)
  3. Execute SQL MERGE on primary keys with partition filter
  4. Cleanup temp table in finally block
- Added `_sanitize_row_for_bq()` helper method

**Key differences from old implementation:**

| Aspect | Before (Buggy) | After (Fixed) |
|--------|---------------|---------------|
| Strategy | DELETE entire season + WRITE_APPEND | SQL MERGE on game_id + game_date |
| Atomicity | Non-atomic (race conditions) | Atomic (single MERGE statement) |
| Duplicates | Could create duplicates | Prevents duplicates via MERGE |
| Partition handling | Coarse (whole season) | Fine-grained (per game_date range) |

### 3. Updated Operations Documentation

**File:** `docs/02-operations/daily-validation-checklist.md`

- Step 0.4: Updated to use `v_nbac_schedule_latest` view
- Added duplicate detection query as alternative check
- Updated Known Issues section with fix details and when to use view

---

## Files Changed

| File | Change Type |
|------|-------------|
| `schemas/bigquery/raw/nbac_schedule_tables.sql` | Added view definition |
| `data_processors/raw/nbacom/nbac_schedule_processor.py` | Replaced save_data() with MERGE |
| `docs/02-operations/daily-validation-checklist.md` | Updated with view usage |

---

## Validation Commands

```bash
# 1. Verify view exists and works
bq query --use_legacy_sql=false "
SELECT game_id, game_status, game_status_text
FROM nba_raw.v_nbac_schedule_latest
WHERE game_date = '2026-01-10'
ORDER BY game_id"

# 2. Check for existing duplicates (should decrease over time)
bq query --use_legacy_sql=false "
SELECT game_id, COUNT(*) as rows
FROM nba_raw.nbac_schedule
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_id
HAVING COUNT(*) > 1"

# 3. Test processor import
python3 -c "from data_processors.raw.nbacom.nbac_schedule_processor import NbacScheduleProcessor; print('OK')"
```

---

## Testing the Fix

The processor fix will take effect on the next schedule scraper run. To verify:

1. Wait for next `morning_operations` workflow (runs hourly at :05)
2. Or manually trigger: `gcloud scheduler jobs run execute-workflows --location=us-west2`
3. After processing, check for duplicates - should be 0 new duplicates

---

## Downstream Impact

### What uses `nba_raw.nbac_schedule`?

- **504 references** across the codebase
- Key files: completeness_checker.py, upcoming_*_game_context processors
- 8 existing views on the table
- 70+ validation queries

### When to use the view?

| Use Case | Table to Use |
|----------|-------------|
| Current game status | `v_nbac_schedule_latest` |
| Historical analysis | `nbac_schedule` (base table) |
| Validation queries checking `game_status = 3` | Either (both work) |
| Queries needing all records | `nbac_schedule` (base table) |

---

## Remaining Work

1. **Clean up existing duplicates** (optional): Run a one-time DELETE to remove old duplicate rows
2. **Monitor next run**: Verify MERGE is working correctly
3. **Post-game refresh**: Still needed - schedule scraper doesn't run after games finish (separate issue)

---

## Related Documentation

- Original handoff: `docs/09-handoff/2026-01-11-SCHEDULE-FIX-HANDOFF.md`
- Operations checklist: `docs/02-operations/daily-validation-checklist.md`
- Architecture: `docs/01-architecture/data-flow.md`

---

**End of Handoff**
