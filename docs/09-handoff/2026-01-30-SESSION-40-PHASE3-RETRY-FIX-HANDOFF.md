# Session 40 Handoff - Phase 3 Retry Loop Fix

**Date:** 2026-01-30
**Status:** Complete

---

## Executive Summary

Fixed the Phase 3 retry loop that was causing Pub/Sub to retry messages every ~15 seconds indefinitely. The root cause was processors failing with `KeyError: 'player_lookup'` when processing empty data during incremental runs.

---

## Problem

Phase 3 processors were failing with:
```
KeyError: 'player_lookup'
File "player_game_summary_processor.py", line 1039, in calculate_analytics
    unique_players = self.raw_data['player_lookup'].dropna().unique().tolist()
```

This happened when:
1. Incremental mode filtered to specific "changed" players
2. Those players weren't in the source data for the date being processed
3. The query returned 0 rows, creating a DataFrame without the expected columns
4. `calculate_analytics()` tried to access columns that didn't exist

The HTTP 500 response caused Pub/Sub to retry indefinitely every ~15 seconds.

---

## Fixes Applied

### 1. PlayerGameSummaryProcessor - Add Empty Data Guard

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

Added guard at start of `calculate_analytics()`:
```python
if self.raw_data is None or self.raw_data.empty or 'player_lookup' not in self.raw_data.columns:
    logger.info("⏭️  No data to process - raw_data is empty or missing columns.")
    self.transformed_data = []
    self.stats['skipped_reason'] = 'no_data_to_process'
    return
```

### 2. UpcomingTeamGameContextProcessor - Add Empty Data Guard

**File:** `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

Added same guard for `schedule_data`:
```python
if self.schedule_data is None or self.schedule_data.empty or 'game_date' not in self.schedule_data.columns:
    logger.info("⏭️  No data to process - schedule_data is empty or missing columns.")
    self.transformed_data = []
    self.stats['skipped_reason'] = 'no_data_to_process'
    return
```

### 3. BigQuerySaveOpsMixin - Handle Intentional Skips

**File:** `data_processors/analytics/operations/bigquery_save_ops.py`

Updated `save_analytics()` to check for `skipped_reason`:
```python
if not self.transformed_data:
    skip_reason = self.stats.get('skipped_reason')
    if skip_reason:
        logger.info(f"⏭️  No data to save (intentional skip: {skip_reason})")
        self.stats['rows_processed'] = 0
        return True  # Return success for intentional skips
    # ... existing warning notification logic ...
```

---

## Commits

| Commit | Description |
|--------|-------------|
| `d73ebb7a` | fix: Handle empty data gracefully in Phase 3 processors to stop retry loops |
| `3380868b` | fix: Define transform_seconds and save_seconds when skip_processing is True |

---

## Deployment

Deployed to Cloud Run:
- Service: `nba-phase3-analytics-processors`
- Revision: `nba-phase3-analytics-processors-00152-hql`
- Commit: `3380868b`

---

## Verification

### Before Fix
```
2026-01-30T22:56:22 POST /process HTTP/1.1 500 343
KeyError: 'player_lookup'
```
Retrying every ~15 seconds indefinitely.

### After Fix
```
2026-01-30T23:09:57 POST /process HTTP/1.1 200 351
2026-01-30T23:09:55 POST /process HTTP/1.1 200 351
```
All requests returning 200, Pub/Sub messages ACKed, no more retries.

---

## Root Cause Analysis

The issue occurred because:

1. **Change detection** identified 117 "changed" players from the previous run
2. **Incremental query filter** added `AND player_lookup IN ('player1', 'player2', ...)`
3. **No matching data** - none of those 117 players had records for Jan 29
4. **Empty DataFrame** returned by BigQuery without the expected column schema
5. **KeyError** when accessing `raw_data['player_lookup']`
6. **HTTP 500** returned to Pub/Sub
7. **Pub/Sub retry** every 15 seconds indefinitely

---

## Processors Checked

| Processor | Status | Notes |
|-----------|--------|-------|
| PlayerGameSummaryProcessor | ✅ Fixed | Added empty data guard |
| UpcomingTeamGameContextProcessor | ✅ Fixed | Added empty data guard |
| TeamOffenseGameSummaryProcessor | ✅ OK | Already has implicit guard |
| TeamDefenseGameSummaryProcessor | ✅ OK | Already has proper guard |
| UpcomingPlayerGameContextProcessor | ✅ OK | Uses entity-based pattern |
| DefenseZoneAnalyticsProcessor | ✅ OK | Uses entity-based pattern |

---

## Prevention Mechanisms

### Pattern 1: Triple-Check Guard (Recommended)
```python
if self.raw_data is None or self.raw_data.empty or 'required_column' not in self.raw_data.columns:
    self.transformed_data = []
    self.stats['skipped_reason'] = 'no_data_to_process'
    return
```

### Pattern 2: Skip Reason in Stats
Setting `stats['skipped_reason']` signals to `save_analytics()` that this is an intentional skip, preventing warning notifications.

---

## Known Issues Still to Address

1. **Jan 22-23 cannot be backfilled** - `nbac_gamebook_player_stats` has 0 records for these dates
2. **Email alerting not configured** - Missing `BREVO_SMTP_USERNAME`, `BREVO_FROM_EMAIL` env vars
3. **service_errors table missing** - `nba_orchestration.service_errors` doesn't exist

---

## Next Session Checklist

1. [ ] Monitor Phase 3 for any new retry loop issues
2. [ ] Investigate Jan 22-23 missing source data (re-run NBAC scraper?)
3. [ ] Consider adding alternative source support for PlayerGameSummaryProcessor
4. [ ] Create `nba_orchestration.service_errors` table if needed
5. [ ] Configure email alerting environment variables if needed

---

## Key Learnings

1. **Check for empty data EARLY** - Before accessing any columns, verify the DataFrame exists and has expected schema
2. **Use skip_reason pattern** - Set `stats['skipped_reason']` for intentional skips to prevent noisy warnings
3. **Return 200 for expected cases** - When upstream has no data, return success to ACK the Pub/Sub message
4. **Incremental mode edge cases** - Changed entity filters can result in 0 matching records

---

*Session 40 complete. Phase 3 retry loops fixed and deployed.*
