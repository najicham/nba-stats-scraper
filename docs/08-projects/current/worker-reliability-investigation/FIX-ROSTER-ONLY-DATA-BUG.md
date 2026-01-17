# Fix Plan: Roster-Only Data Bug (R-009)

**Date**: 2026-01-16
**Severity**: HIGH
**Status**: Analysis Complete, Implementation Pending

---

## Problem Summary

When NBA.com gamebook PDFs are scraped before the boxscore data is available (games just finished), the scraper captures roster/DNP data only. This partial data is marked as "success" and blocks subsequent re-scrapes with complete data.

**Impact on Jan 15, 2026**: 3 games (BOS_MIA, MIL_SAS, UTA_DAL) had incomplete data, causing:
- 0 active player stats in gamebook
- Missing Phase 3 analytics records
- 1337 ungraded predictions (out of 2804)

---

## Root Cause Analysis

### Chain of Failures

```
[1] TIMING: early_game_window_3 ran ~3 AM UTC
    - Games ended ~3-4 AM UTC
    - NBA.com PDFs not yet updated with boxscore data

[2] SCRAPER: No "partial" status for incomplete data
    - Detects "No active players found" (line 732)
    - Sends WARNING notification
    - But returns status=SUCCESS anyway

[3] PROCESSOR: Counts roster as "records_processed"
    - 14-18 DNP/inactive records counted
    - Run marked SUCCESS

[4] IDEMPOTENCY: Retry blocked
    - Only retries when records_processed == 0
    - 14-18 > 0, so retry blocked

[5] RESULT: Second scrape with full data SKIPPED
```

---

## Fix Plan

### Fix 1: Scraper - Return `status=partial` for incomplete data

**File**: `scrapers/nbacom/nbac_gamebook_pdf.py`
**Location**: Lines 731-749

**Current Behavior**:
```python
if len(active_players) == 0:
    logger.warning("No active players found in game %s", self.opts["game_code"])
    # ... sends notification but continues as SUCCESS
```

**Proposed Fix**:
```python
if len(active_players) == 0:
    logger.warning("No active players found in game %s", self.opts["game_code"])
    # ... notification code ...

    # Mark as partial - this allows retry when full data available
    self.data['_data_status'] = 'partial'
    self.data['_partial_reason'] = 'no_active_players'
```

**Also update** the scraper's status reporting to respect `_data_status`:
- If `_data_status == 'partial'`, publish message with `status=partial` instead of `status=success`

---

### Fix 2: Processor - Track active vs roster records separately

**File**: `data_processors/raw/nbacom/nbac_gamebook_processor.py`

**Proposed Changes**:
1. Add `active_records_processed` field to stats tracking
2. Include in run history metadata
3. Log separately from total `rows_processed`

```python
# In process_and_load():
stats = {
    'rows_processed': total_rows,
    'active_records': active_player_count,
    'roster_records': dnp_count + inactive_count,
    'has_meaningful_data': active_player_count > 0
}
```

---

### Fix 3: Idempotency - Retry when no active players

**File**: `shared/processors/mixins/run_history_mixin.py`
**Location**: Lines 661-678

**Current Behavior**:
```python
if records_processed == 0:
    logger.warning("... allowing retry")
    return False  # Allow retry
```

**Proposed Fix**:
```python
# Get metadata from previous run
metadata = getattr(row, 'metadata', {}) or {}
active_records = metadata.get('active_records', records_processed)

if records_processed == 0 or active_records == 0:
    logger.warning(
        f"Processor {processor_name} previously processed {identifier} "
        f"with {records_processed} total records but {active_records} active records. "
        f"Allowing retry for better data."
    )
    return False  # Allow retry
```

---

### Fix 4: Add morning recovery workflow

**File**: `orchestration/config/workflow_config.yaml` (or equivalent)

**Proposed Addition**:
```yaml
morning_data_recovery:
  type: recovery
  schedule: "0 10 * * *"  # 10 AM UTC (6 AM ET)
  description: "Re-check games with 0 active players from previous day"
  actions:
    - query_games_with_zero_active:
        sql: |
          SELECT DISTINCT game_id
          FROM nba_raw.nbac_gamebook_player_stats
          WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
          GROUP BY game_id
          HAVING COUNTIF(player_status = 'active') = 0
    - for_each_game:
        trigger: nbac_gamebook_pdf
        params:
          pdf_source: download  # Re-download from NBA.com
```

---

### Fix 5: Reconciliation alert for zero-active games

**File**: `orchestration/cloud_functions/pipeline_reconciliation/main.py`

**Add check**:
```python
def check_gamebook_completeness(game_date: str) -> List[Dict]:
    """Check for games with 0 active players."""
    query = f"""
    SELECT
        game_id,
        COUNTIF(player_status = 'active') as active_count,
        COUNT(*) as total_records
    FROM nba_raw.nbac_gamebook_player_stats
    WHERE game_date = '{game_date}'
    GROUP BY game_id
    HAVING active_count = 0
    """
    # ... alert if any found ...
```

---

## Implementation Priority

| Priority | Fix | Effort | Impact |
|----------|-----|--------|--------|
| 1 | Fix 3: Idempotency retry | Low | HIGH - prevents all similar issues |
| 2 | Fix 1: Scraper partial status | Medium | HIGH - proper status signaling |
| 3 | Fix 5: Reconciliation alert | Low | MEDIUM - early detection |
| 4 | Fix 2: Processor tracking | Medium | MEDIUM - better observability |
| 5 | Fix 4: Morning recovery | Medium | LOW - safety net |

---

## Immediate Backfill Steps

1. Delete incorrect gamebook records (47 rows)
2. Clear run history for 3 games (6 rows)
3. Trigger re-processing via Pub/Sub with full-data files
4. Monitor for Phase 2 completion
5. Trigger Phase 3 analytics
6. Trigger prediction grading

---

## Verification Queries

```sql
-- Check gamebook now has active players
SELECT game_id,
       COUNTIF(player_status = 'active') as active,
       COUNT(*) as total
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2026-01-15'
GROUP BY game_id
ORDER BY game_id;

-- Check Phase 3 has all 9 games
SELECT COUNT(DISTINCT game_id) as games
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-15';

-- Check prediction grading complete
SELECT COUNT(*) as total,
       COUNTIF(graded_at IS NOT NULL) as graded
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-15';
```
