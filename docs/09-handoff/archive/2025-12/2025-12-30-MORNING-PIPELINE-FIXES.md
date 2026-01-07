# Morning Pipeline Fixes: December 30, 2025

**Date:** December 30, 2025 8:00 AM - 10:00 AM PT
**Status:** Resolved
**Impact:** Dec 29 grading was blocked until analytics were fixed

---

## Summary

Morning validation discovered that Dec 29 grading could not complete because Phase 3 analytics (specifically `player_game_summary`) had not run for Dec 29's games. This document tracks the issues found, root causes, and fixes applied.

---

## Issues Found and Fixed

### Issue 1: Phase 3 Analytics Not Running for Yesterday's Games

**Symptom:** Dec 29 `player_game_summary` had 0 rows, blocking grading.

**Root Cause:** The same-day schedulers only trigger forward-looking processors:
- `same-day-phase3`: Only runs `UpcomingPlayerGameContextProcessor`
- There was NO scheduler to run backward-looking analytics (`PlayerGameSummaryProcessor`, etc.) for yesterday's completed games

**Impact:** Grading depends on `player_game_summary` to get actual results, so Dec 29 grading was blocked.

**Fix Needed:** Create a new scheduler `daily-yesterday-analytics` at ~6:30 AM ET to run full Phase 3 analytics for yesterday.

### Issue 2: BigQuery Array Index Out of Bounds

**Symptom:** `PlayerGameSummaryProcessor` failed with "Array index 1 is out of bounds".

**Root Cause:** The query used `SPLIT(game_id, '_')[OFFSET(1)]` to extract team abbreviations. This fails when game_id is in NBA.com format (`0022500447`) instead of our standard format (`YYYYMMDD_AWY_HOM`).

**Fix Applied:** Changed `OFFSET()` to `SAFE_OFFSET()` which returns NULL instead of erroring.

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py:473-487`

### Issue 3: JSON Serialization Error in Analytics Base

**Symptom:** After fixing array index issue, got "JSON table encountered too many errors".

**Root Cause:** `analytics_base.py` was not sanitizing data before JSON serialization, unlike `prediction_accuracy_processor.py` which had sanitization.

**Fix Applied:** Added `_sanitize_row_for_json()` method to `analytics_base.py` and updated `save_analytics()` to use it.

**File:** `data_processors/analytics/analytics_base.py:143-183`

### Issue 4: Required Field opponent_team_abbr Set to NULL

**Symptom:** Even with sanitization, load failed with "Only optional fields can be set to NULL. Field: opponent_team_abbr".

**Root Cause:** For data from `nbac_gamebook_player_stats` (NBA.com format game_ids), we couldn't extract opponent_team_abbr from game_id. The schema requires this field.

**Fix Applied:**
1. Added `source_home_team` and `source_away_team` columns from nbac_gamebook source data
2. Updated query to use COALESCE - prefer source data, fall back to game_id parsing

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py:333-506`

---

## Timeline

| Time (PT) | Event |
|-----------|-------|
| 7:55 AM | Morning validation started, discovered Dec 29 grading not done |
| 8:00 AM | Triggered manual Dec 29 grading - failed due to no actuals |
| 8:10 AM | Investigation started - found Phase 3 only ran 1/5 processors |
| 8:20 AM | Identified root cause: same-day-phase3 only runs UpcomingPlayerGameContext |
| 8:30 AM | First manual attempt to run PlayerGameSummary - Array index error |
| 8:35 AM | Fixed with SAFE_OFFSET, redeployed |
| 8:40 AM | Second attempt - JSON serialization error |
| 9:00 AM | Added JSON sanitization to analytics_base, redeployed |
| 9:15 AM | Third attempt - opponent_team_abbr NULL error |
| 9:35 AM | Added source team data extraction, redeployed |
| 9:55 AM | Fourth attempt - SUCCESS! 368 rows loaded |
| 9:56 AM | Triggered Dec 29 grading - SUCCESS! 1,500 predictions graded |

---

## Recommendations for Automation Improvements

### High Priority

1. **Add daily-yesterday-analytics scheduler**
   - Schedule: 6:30 AM ET daily
   - Runs: PlayerGameSummaryProcessor, TeamGameSummaryProcessor, RollingAveragesProcessor, ContextualMetricsProcessor
   - Target: YESTERDAY (completed games)

2. **Standardize game_id format**
   - All data sources should use `YYYYMMDD_AWY_HOM` format
   - Add normalization to ingestion processors
   - Current inconsistency:
     - bdl_player_boxscores: `20251229_ATL_OKC` (correct)
     - nbac_gamebook_player_stats: `0022500447` (NBA.com format)
     - bdl_live_boxscores: `18447269` (API ID)

3. **Add better error logging**
   - Already added BigQuery error details logging to analytics_base
   - Consider adding to other processors

### Medium Priority

4. **Add pre-grading validation**
   - Before grading runs, check that player_game_summary has data for the target date
   - Auto-trigger analytics if missing

5. **Add alerting for Phase 3 incomplete**
   - Alert if phase3_completion < 5 processors after expected time
   - Alert if player_game_summary is empty for yesterday

6. **Admin dashboard integration**
   - Display processor failures prominently
   - Show coverage metrics
   - Show orchestration state

### Low Priority

7. **Self-heal enhancement**
   - Self-heal should check analytics completeness before grading
   - Auto-trigger analytics backfill if needed

---

## Files Changed

```
data_processors/analytics/analytics_base.py
  - Added _sanitize_row_for_json() method
  - Updated save_analytics() with sanitization and better error logging

data_processors/analytics/player_game_summary/player_game_summary_processor.py
  - Changed OFFSET to SAFE_OFFSET
  - Added source_home_team, source_away_team extraction from nbac_gamebook
  - Updated games_context CTE to use source data with COALESCE
```

---

## Verification

```bash
# Dec 29 analytics
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = '2025-12-29' GROUP BY 1"
# Result: 368 rows

# Dec 29 grading
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*), ROUND(AVG(absolute_error), 2) FROM nba_predictions.prediction_accuracy WHERE game_date = '2025-12-29' GROUP BY 1"
# Result: 1,500 graded, MAE: 6.1
```

---

## Follow-up Implementation (Afternoon Session)

All recommended improvements have been implemented:

### Completed Improvements

| Task | Status | Description |
|------|--------|-------------|
| **daily-yesterday-analytics scheduler** | DONE | Created `bin/orchestrators/setup_yesterday_analytics_scheduler.sh`, deploys 6:30 AM ET scheduler |
| **game_id_converter utility** | DONE | Created `shared/utils/game_id_converter.py` with format detection, conversion, parsing |
| **Fix NbacGamebookProcessor** | DONE | Now outputs standardized `YYYYMMDD_AWAY_HOME` format, stores NBA.com ID as `nba_game_id` |
| **PlayerGameSummaryProcessor docs** | DONE | Added comments explaining SAFE_OFFSET as backward compatibility measure |
| **Pre-grading validation** | DONE | Added `validate_grading_prerequisites()` to grading function with auto-heal capability |
| **Phase 3 alerting** | DONE | Added `check_player_game_summary_for_yesterday()` to transition monitor |
| **Admin dashboard: Processor failures** | DONE | Added `/api/processor-failures` endpoint and "Processor Failures" tab |
| **Admin dashboard: Coverage metrics** | DONE | Added `/api/coverage-metrics` endpoint and "Coverage Metrics" tab |

### New Files Created

```
bin/orchestrators/setup_yesterday_analytics_scheduler.sh
  - Creates daily-yesterday-analytics scheduler at 6:30 AM ET
  - Runs PlayerGameSummaryProcessor, TeamDefenseGameSummaryProcessor, TeamOffenseGameSummaryProcessor

shared/utils/game_id_converter.py
  - GameIdConverter class with format detection and conversion
  - Convenience functions: to_standard_game_id(), parse_game_id(), is_standard_game_id()

services/admin_dashboard/templates/components/processor_failures.html
  - Displays recent processor failures with error messages

services/admin_dashboard/templates/components/coverage_metrics.html
  - Shows player_game_summary coverage and grading status for last 7 days
```

### Files Modified

```
data_processors/raw/nbacom/nbac_gamebook_processor.py
  - Now uses to_standard_game_id() for game_id normalization
  - Stores original NBA.com ID as nba_game_id

orchestration/cloud_functions/grading/main.py
  - Added validate_grading_prerequisites() - checks predictions/actuals exist
  - Added trigger_phase3_analytics() - auto-heal when actuals missing

orchestration/cloud_functions/transition_monitor/main.py
  - Added check_player_game_summary_for_yesterday() - critical grading dependency check
  - Enhanced send_alerts() with actionable recovery commands

services/admin_dashboard/services/bigquery_service.py
  - Added get_processor_failures() method
  - Added get_player_game_summary_coverage() method
  - Added get_grading_status() method

services/admin_dashboard/main.py
  - Added /api/processor-failures and /partials/processor-failures endpoints
  - Added /api/coverage-metrics and /partials/coverage-metrics endpoints

services/admin_dashboard/templates/dashboard.html
  - Added "Processor Failures" tab
  - Added "Coverage Metrics" tab

shared/utils/__init__.py
  - Added game_id_converter exports
```

### Prevention Measures Now in Place

1. **Scheduler-based prevention**: `daily-yesterday-analytics` will run at 6:30 AM ET daily, ensuring player_game_summary exists before grading (7 AM)

2. **Pre-grading validation**: Grading function now validates prerequisites and can auto-trigger Phase 3 if actuals are missing

3. **Proactive alerting**: Transition monitor checks player_game_summary coverage for yesterday and sends critical alerts if empty

4. **Visibility**: Admin dashboard now shows processor failures and coverage metrics prominently

---

*Document updated: December 30, 2025 (afternoon improvements)*
