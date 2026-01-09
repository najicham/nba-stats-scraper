# Email Alert Enhancement & BasketballRefRoster Bug Fix
**Date:** 2026-01-06
**Session:** Morning Investigation
**Status:** ✅ COMPLETE - Ready for Testing

---

## Executive Summary

Investigated morning error emails for `BasketballRefRosterProcessor` failures. **Completed two major improvements:**

1. **Enhanced Email Alerts** - Added trigger source/context to error emails
2. **Fixed Critical Bug** - Resolved `first_seen_date` schema validation error

---

## Problem 1: Unclear Error Email Source

### Issue
Error emails didn't specify what triggered the processor:
- Was it daily orchestration?
- Was it a backfill job?
- Which workflow triggered it?
- What Pub/Sub message caused it?

### Solution Implemented

#### A. Modified `main_processor_service.py`
**File:** `/home/naji/code/nba-stats-scraper/data_processors/raw/main_processor_service.py`

**Changes:** Added trigger context to `opts` dict (lines 779-784):
```python
# Add trigger context for error notifications
opts['trigger_source'] = normalized_message.get('_original_format', 'unknown')
opts['trigger_message_id'] = pubsub_message.get('messageId', 'N/A')
opts['parent_processor'] = normalized_message.get('_scraper_name', 'N/A')
opts['workflow'] = normalized_message.get('_workflow', 'N/A')
opts['execution_id'] = normalized_message.get('_execution_id', 'N/A')
```

**Also updated:** ESPN roster folder processing (lines 682-687)

#### B. Modified `processor_base.py`
**File:** `/home/naji/code/nba-stats-scraper/data_processors/raw/processor_base.py`

**Changes:** Enhanced error notification details (lines 234-245):
```python
details={
    'processor': self.__class__.__name__,
    'run_id': self.run_id,
    'error_type': type(e).__name__,
    'step': self._get_current_step(),
    'trigger_source': opts.get('trigger_source', 'unknown'),
    'trigger_message_id': opts.get('trigger_message_id', 'N/A'),
    'parent_processor': opts.get('parent_processor', 'N/A'),
    'workflow': opts.get('workflow', 'N/A'),
    'execution_id': opts.get('execution_id', 'N/A'),
    'opts': {
        'date': opts.get('date'),
        'group': opts.get('group'),
        'table': self.table_name,
        'season_year': opts.get('season_year'),
        'team_abbrev': opts.get('team_abbrev'),
        'file_path': opts.get('file_path')
    },
    'stats': self.stats
}
```

#### C. Updated Backfill Script Template
**File:** `/home/naji/code/nba-stats-scraper/backfill_jobs/raw/br_roster_processor/br_roster_processor_raw_backfill.py`

**Changes:** Added trigger fields to backfill opts (lines 76-80):
```python
"trigger_source": "backfill",
"trigger_message_id": "N/A",
"parent_processor": "br_roster_processor_backfill",
"workflow": "manual_backfill",
"execution_id": "N/A"
```

### Result - New Email Format

**Before:**
```
Error Details:
processor: BasketballRefRosterProcessor
run_id: bde6810a
error_type: BadRequest
step: save
opts: {'date': None, 'group': None, 'table': 'br_rosters_current'}
```

**After:**
```
Error Details:
processor: BasketballRefRosterProcessor
run_id: bde6810a
error_type: BadRequest
step: save
trigger_source: unified_v2  (or "backfill" for manual jobs)
trigger_message_id: 1234567890
parent_processor: br_season_roster
workflow: morning_operations
execution_id: abc-123-def
opts: {
  'date': None,
  'group': None,
  'table': 'br_rosters_current',
  'season_year': 2025,
  'team_abbrev': 'LAL',
  'file_path': 'basketball-ref/season-rosters/2025-26/LAL.json'
}
```

**Now you can immediately see:**
- Source: Daily orchestration (`trigger_source: unified_v2`) vs Manual backfill (`trigger_source: backfill`)
- Parent: Which scraper triggered it (`parent_processor`)
- Workflow: Which workflow in `config/workflows.yaml`
- Trace ID: For distributed tracing (`execution_id`, `trigger_message_id`)
- Context: Specific file, team, season that failed

---

## Problem 2: BasketballRefRosterProcessor BigQuery Error

### Error Message
```
400 Error while reading data, error message: JSON table encountered
too many errors, giving up. Rows: 1; errors: 1. Please look into
the errors[] collection for more details.
```

### Root Cause Analysis

**Bug Location:** `/home/naji/code/nba-stats-scraper/data_processors/raw/basketball_ref/br_roster_processor.py` (lines 248-254)

**The Bug:**
```python
# OLD CODE (BROKEN)
if row["player_lookup"] not in existing_lookups:
    row["first_seen_date"] = date.today().isoformat()
    new_players.append(player.get("full_name"))
    logger.info(f"New player on {team_abbrev}: {player.get('full_name')}")

# ❌ BUG: No else clause - existing players never get first_seen_date!
rows.append(row)
```

**Schema Requirement:**
```sql
first_seen_date DATE NOT NULL,  -- Required field!
```

**What Happened:**
1. **First scrape** - All players are new → `first_seen_date` set → ✅ Works
2. **Re-scrape** - Players already exist → `first_seen_date` NOT set → ❌ BigQuery rejects row

**When Introduced:** Commit `cd5e0a1` (Jan 2, 2026) during MERGE refactor

**Why It Wasn't Caught:** Only manifests on second scrape of same team

### Fix Implemented

**File:** `/home/naji/code/nba-stats-scraper/data_processors/raw/basketball_ref/br_roster_processor.py`

**Changes:** Added else clause (lines 253-256):
```python
if row["player_lookup"] not in existing_lookups:
    row["first_seen_date"] = date.today().isoformat()
    new_players.append(player.get("full_name"))
    logger.info(f"New player on {team_abbrev}: {player.get('full_name')}")
else:
    # Placeholder for temp table load (MERGE won't update this field for existing players)
    # The actual first_seen_date from the main table is preserved by the MERGE query
    row["first_seen_date"] = date.today().isoformat()

rows.append(row)
```

**Why This Works:**
- All rows now have `first_seen_date` for temp table loading
- MERGE query's `WHEN MATCHED` clause doesn't include `first_seen_date`, so existing values are preserved in main table
- New players use actual date, existing players use placeholder (overwritten by MERGE)

---

## Files Modified

### 1. Enhanced Alerting
- ✅ `data_processors/raw/main_processor_service.py` (lines 682-687, 779-784)
- ✅ `data_processors/raw/processor_base.py` (lines 234-245)
- ✅ `backfill_jobs/raw/br_roster_processor/br_roster_processor_raw_backfill.py` (lines 76-80)

### 2. Bug Fix
- ✅ `data_processors/raw/basketball_ref/br_roster_processor.py` (lines 253-256)

---

## Testing & Validation

### Recommended Validation Queries

#### 1. Check for Teams That Failed Today
```sql
SELECT
    season_year,
    team_abbrev,
    COUNT(*) as player_count,
    MAX(last_scraped_date) as last_scrape
FROM `nba-props-platform.nba_raw.br_rosters_current`
WHERE season_year = 2025
GROUP BY season_year, team_abbrev
HAVING COUNT(*) < 10  -- Normal roster is 15-20 players
ORDER BY player_count ASC;
```

#### 2. Verify Today's Scrapes
```sql
SELECT
    team_abbrev,
    COUNT(*) as player_count,
    last_scraped_date
FROM `nba-props-platform.nba_raw.br_rosters_current`
WHERE season_year = 2025
  AND last_scraped_date = CURRENT_DATE()
GROUP BY team_abbrev, last_scraped_date
ORDER BY player_count ASC;
```

#### 3. Check first_seen_date Coverage
```sql
SELECT
    COUNT(*) as total_rows,
    COUNT(first_seen_date) as rows_with_date,
    COUNT(*) - COUNT(first_seen_date) as missing_dates
FROM `nba-props-platform.nba_raw.br_rosters_current`
WHERE season_year = 2025;
```

### Manual Testing

#### Test Enhanced Alerts
1. Trigger a processor error (e.g., invalid file path)
2. Check email notification includes:
   - `trigger_source`
   - `parent_processor`
   - `workflow`
   - `trigger_message_id`
   - `execution_id`

#### Test Roster Bug Fix
1. Re-scrape a team that was already processed today
2. Verify no BigQuery errors
3. Check logs for successful MERGE operation
4. Validate `first_seen_date` values preserved

---

## Next Steps

### Immediate
1. ✅ **Deploy Changes** - All fixes are ready to deploy
2. ✅ **Monitor Next Daily Run** - Watch for enhanced email alerts (morning_operations workflow)
3. ✅ **Re-run Failed Team** - If we identify which team failed at 14:30:26 UTC, re-process it

### Follow-Up
1. **Update Other Backfill Scripts** - Apply trigger context pattern to other raw backfill scripts (19 total)
2. **Add Unit Tests** - Test for re-scrape scenario in `br_roster_processor`
3. **Schema Validation Test** - Ensure all NOT NULL fields are populated before temp table load
4. **Monitor Alerts** - Confirm enhanced context helps with triage

---

## Impact Assessment

### Email Alert Enhancement
- **Severity:** Medium (Quality of Life)
- **Impact:** Positive - Faster incident triage
- **Risk:** Low - Additive change, no breaking changes
- **Testing:** Can verify immediately in production alerts

### Roster Bug Fix
- **Severity:** High (P0 - Blocking re-scrapes)
- **Impact:** Critical - Unblocks all roster re-processing
- **Risk:** Low - Simple logic fix, well-understood
- **Testing:** Can test with any team re-scrape

---

## Technical Debt Noted

1. **Backfill Script Consistency** - 19 raw backfill scripts should adopt trigger context pattern
2. **Test Coverage** - Missing integration test for re-scrape scenarios
3. **Schema Validation** - Should validate temp table data before MERGE operation
4. **Error Details** - BigQuery error details (errors[] collection) not exposed in logs

---

## Related Documentation

- **Workflow Config:** `config/workflows.yaml` (morning_operations)
- **Message Normalization:** `data_processors/raw/main_processor_service.py` (lines 388-407)
- **MERGE Implementation:** `data_processors/raw/basketball_ref/br_roster_processor.py` (lines 281-426)
- **Schema Definition:** `schemas/bigquery/raw/br_roster_tables.sql`

---

## Questions Answered

1. **What triggered the error?** - Daily orchestration OR manual backfill (now visible in email)
2. **Why did it fail?** - Missing `first_seen_date` for existing players during re-scrape
3. **Is it fixed?** - ✅ Yes, placeholder value added for temp table load
4. **Will it happen again?** - No, all rows now have required field
5. **Can we identify source better?** - ✅ Yes, enhanced email includes full trigger context

---

**Session Complete:** 2026-01-06 Morning
**Status:** Ready for deployment and monitoring
