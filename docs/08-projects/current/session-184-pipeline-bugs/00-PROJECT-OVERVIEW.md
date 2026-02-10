# Session 184: Pipeline Bug Investigation & Fixes

**Date:** 2026-02-10
**Scope:** Daily validation uncovered 6 pipeline issues. Deep investigation, root cause analysis, and fixes for 3 code bugs.

## Summary

| # | Issue | Severity | Status | Fix |
|---|-------|----------|--------|-----|
| 1 | `SourceCoverageSeverity.ERROR` enum crash | P2 | FIXED | Changed to `.CRITICAL` |
| 2 | Phase 2→3 orchestrator name mapping typos | P1 | FIXED | Added correct `NbacGamebookProcessor` entry |
| 3 | Coordinator Content-Type 415 errors | P2 | FIXED | Added `force=True, silent=True` to `get_json()` |
| 4 | Phase 3/4 timing cascade | P3 | DOCUMENTED | Architecture anti-pattern; recommend scheduler adjustment |
| 5 | Breakout classifier feature mismatch | P3 | DOCUMENTED | Shadow mode only; needs model/feature reconciliation |
| 6 | Jan 24-25 "missing" games | INFO | RESOLVED | Games were postponed (Minneapolis unrest, winter storm) |

## Bug Details

### Bug 1: SourceCoverageSeverity.ERROR Enum Crash

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py:835`

**Root Cause:** Line 835 used `SourceCoverageSeverity.ERROR` but the enum (`shared/config/source_coverage/__init__.py:33`) only has `INFO`, `WARNING`, `CRITICAL`. The developer confused `SourceCoverageSeverity` with `SourceStatus` (which has `.ERROR`). Introduced in Session 119 commit `15a0f9ab5`.

**Impact:** When team stats dependency validation fails (common timing race), the processor crashes with `AttributeError: ERROR` instead of raising a clean `ValueError` with actionable instructions. This was visible in Phase 3 error logs at 4:19 AM and 10:46/11:00 AM on Feb 9-10.

**Fix:** Changed to `SourceCoverageSeverity.CRITICAL` — matches the intent (blocking validation failure) and is the highest severity available.

**Prevention:** The enum only has 3 values. A unit test asserting that all `track_source_coverage_event()` calls use valid enum members would catch this.

### Bug 2: Phase 2→3 Orchestrator Name Mapping Typos

**File:** `orchestration/cloud_functions/phase2_to_phase3/main.py:149-169`

**Root Cause:** The `CLASS_TO_CONFIG_MAP` dictionary had typos for the gamebook processor:
- `NbacGambookProcessor` (missing 'e')
- `NbacGamébookProcessor` (accented é)

The actual processor reports as `NbacGamebookProcessor`. When it reports completion, the orchestrator can't match it, so Firestore completion tracking is broken and the Phase 2→3 trigger never fires.

**Impact:** Event-driven Phase 2→3 trigger is non-functional. Phase 3 relies entirely on fallback scheduler jobs (6:30 AM, 10:30 AM UTC). Firestore `phase2_completion` shows `_triggered: False` even when all processors complete.

**Fix:** Added correct `NbacGamebookProcessor` and `NbacGamebookPlayerStatsProcessor` entries. Kept legacy typo variants for backward compatibility.

**Prevention:** Add integration test that verifies all known processor class names exist in the mapping. Log processor names from production Pub/Sub messages and compare to mapping.

### Bug 3: Coordinator Content-Type 415 Errors

**File:** `predictions/coordinator/coordinator.py` — lines 859, 1701, 1861, 2821, 2908, 2996, 3092, 3197

**Root Cause:** Flask's `request.get_json()` requires `Content-Type: application/json` header. Cloud Scheduler jobs call coordinator endpoints without this header, causing `415 Unsupported Media Type` before the endpoint handler even executes.

**Impact:** `/start` (prediction trigger) and `/cleanup_staging_tables` (maintenance) fail silently when called by Cloud Scheduler. Predictions may not start on schedule.

**Fix:** Added `force=True, silent=True` parameters to all 8 scheduler-callable endpoints. Left 2 Pub/Sub envelope handlers (`envelope = request.get_json()`) unchanged since Pub/Sub always sends correct headers.

**Prevention:** Standard pattern for Cloud Run services called by Cloud Scheduler. Consider creating a utility `parse_request_data()` function that always applies these parameters.

### Bug 4: Phase 3/4 Timing Cascade (Not a Bug — Architecture Anti-Pattern)

**Pattern:** Phase 3 schedulers fire at 6:00-6:30 AM UTC before raw data is available, producing "No data extracted" errors. Phase 4 schedulers at 7:00-7:30 AM UTC then fail with dependency errors because Phase 3 hasn't completed.

**Why it works anyway:** Later retry runs (same-day-phase3 at 10:30 UTC) succeed because all data is available by then. The system is resilient but noisy.

**Recommendations:**
1. **Short-term:** Delay overnight Phase 3 schedulers from 6:00→8:00 AM ET (after BDL catch-up at 7:30 AM)
2. **Medium-term:** Add dependency pre-checks to scheduler endpoints
3. **Long-term:** Eliminate scheduler duplication and rely on Pub/Sub event-driven triggers (which have built-in retry)

### Bug 5: Breakout Classifier Feature Mismatch (Shadow Mode)

**Error:** `Feature points_avg_season is present in model but not in pool`

**Root Cause:** The breakout classifier V1 has a hardcoded 8-feature list in `breakout_classifier_v1.py:478-487` that doesn't match the trained model's feature expectations. The model was likely trained with a different feature set (V2/V3 from `ml/features/breakout_features.py`).

**Impact:** Shadow mode only — no production predictions affected. But errors fire every hour, wasting compute and polluting logs.

**Fix needed:** Reconcile the trained model's expected features with the prediction-time feature vector. Use the shared feature module (`ml/features/breakout_features.py`) instead of hardcoded lists, per Session 134b lessons.

### Bug 6: Jan 24-25 "Missing" Games — Postponed Games

**Finding:** All 3 "missing" games were real NBA games that were postponed:

| Game | Original Date | Reason | Rescheduled To |
|------|--------------|--------|---------------|
| GSW @ MIN | Jan 24 | Minneapolis civil unrest (ICE shooting) | Jan 25 (played) |
| DEN @ MEM | Jan 25 | Massive winter storm | Mar 18 |
| DAL @ MIL | Jan 25 | Winter storm (team plane stranded on tarmac) | Mar 31 |

**Schedule table issue:** The `nba_reference.nba_schedule` table shows `game_status = 3` (Final) for the original postponed dates — this is incorrect. 6 game_ids total appear on multiple dates in the schedule.

**Orphaned predictions:** 808 predictions (366 active) exist for games that never happened on those dates. These can never be graded and pollute signal calculations.

**Recommendations:**
1. Clean up schedule entries for postponed dates (set game_status to a postponed value, or remove)
2. Deactivate orphaned predictions for postponed game dates
3. Add postponement detection to schedule scraper (detect when game_id moves to new date)

## Files Changed

| File | Change |
|------|--------|
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | Line 835: `.ERROR` → `.CRITICAL` |
| `orchestration/cloud_functions/phase2_to_phase3/main.py` | Lines 162-165: Added correct gamebook processor name entries |
| `predictions/coordinator/coordinator.py` | 8 endpoints: Added `force=True, silent=True` to `get_json()` |

## Follow-Up Items

- [ ] Deploy all 3 services after merge (auto-deploy on push to main)
- [ ] Verify Phase 2→3 trigger fires correctly after deployment
- [ ] Clean up postponed game schedule entries (Jan 8, 24, 25)
- [ ] Deactivate 808 orphaned predictions for postponed games
- [ ] Fix breakout classifier feature mismatch (separate task)
- [ ] Consider delaying Phase 3/4 overnight schedulers to 8:00 AM ET
- [ ] Monitor for recurrence of all 6 issues
