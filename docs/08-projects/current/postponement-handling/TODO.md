# Postponement Handling - Comprehensive TODO List

**Created:** 2026-01-25
**Last Updated:** 2026-01-25 (Session 4 In Progress)
**Handoff Doc:** `docs/09-handoff/2026-01-25-POSTPONEMENT-HANDLING-HANDOFF.md`

---

## Immediate (Today/Next Session)

### P0 - Critical: Production Cloud Function Gap (COMPLETED)
- [x] **Add postponement detection to `daily_health_summary` Cloud Function**
  - Added `check_postponements()` method to `HealthChecker` class
  - Checks yesterday and today for anomalies
  - CRITICAL postponements → issues list
  - HIGH anomalies → warnings list
  - Done: 2026-01-25

### P0 - Data Integrity (COMPLETED)
- [x] Fix GSW@MIN schedule status (changed to "Postponed")
- [x] Record postponement in tracking table
- [x] Invalidated 55 predictions (with new invalidation columns)
- [x] Integrated postponement detection into local daily health check

---

## Short-Term (This Week)

### P1 - Detection Integration
- [x] **Add postponement detection to local daily health check**
  - File: `bin/validation/daily_data_completeness.py`
  - Uses dynamic import (won't work in cloud functions)
  - Done: 2026-01-25

- [x] **Add Slack alerting for postponements**
  - Added `--slack` flag to `detect_postponements.py`
  - Sends alerts for CRITICAL and HIGH severity findings
  - Uses `SLACK_WEBHOOK_URL_WARNING` (→ #nba-alerts channel)
  - Done: 2026-01-25

- [x] **Fix dynamic import for cloud function compatibility**
  - Created `shared/utils/postponement_detector.py` as reusable module
  - `bin/validation/detect_postponements.py` now imports from shared module
  - Cloud function can import the same module
  - Done: 2026-01-25

- [ ] **Schedule detection to run multiple times daily**
  - Before first game of day
  - After last game scheduled start time
  - When schedule scraper completes

### P1 - Prediction Management
- [x] **Add invalidation columns to predictions table**
  ```sql
  ALTER TABLE nba_predictions.player_prop_predictions
  ADD COLUMN invalidation_reason STRING,
  ADD COLUMN invalidated_at TIMESTAMP;
  ```
  - Columns added 2026-01-25
  - Schema file updated: `schemas/bigquery/predictions/01_player_prop_predictions.sql`
  - 55 GSW@MIN predictions invalidated

- [x] **Update grading to skip invalidated predictions**
  - Modified `prediction_accuracy_processor.py` (lines 350-367)
  - Added `AND invalidation_reason IS NULL` to WHERE clause
  - Added `invalidation_reason` to SELECT clause
  - Done: 2026-01-25

- [x] **Fix fix_postponed_game.py to actually invalidate predictions**
  - Original script only counted predictions, never invalidated them!
  - Added `invalidate_predictions()` function
  - Uses BigQuery UPDATE with partition filter
  - Fixed deprecation warning: `datetime.utcnow()` → `datetime.now(timezone.utc)`
  - Done: 2026-01-25

- [ ] **Create prediction regeneration trigger**
  - When postponed game gets new date
  - Automatically trigger prediction coordinator for new date
  - Track that predictions were regenerated

### P2 - Schedule Management
- [ ] **Detect schedule changes more frequently**
  - Schedule scraper runs daily - may miss same-day postponements
  - Consider running schedule scraper every 2-4 hours on game days

- [ ] **Track schedule version/changes**
  - Log when schedule changes (new games, status changes)
  - Alert on unexpected status transitions (Scheduled → Final without going through Live)

---

## Medium-Term (This Month)

### P2 - Automated Cascade
- [ ] **Trigger full pipeline when rescheduled game plays**
  - Detect when postponed game completes (status = Final with scores)
  - Trigger: Boxscores → Analytics → Features → Grading
  - Update postponement record to "resolved"

- [ ] **Handle rolling window updates**
  - Player's L5D/L10D may need recalculation
  - Feature quality scores affected
  - Document impact on downstream data

### P2 - News Integration
- [ ] **Smarter news parsing**
  - Extract team names from postponement articles
  - Match to schedule automatically
  - Provide reason extraction (e.g., "weather", "COVID", "safety")

- [ ] **Real-time news monitoring**
  - Poll news more frequently on game days
  - Immediate alert on postponement keywords

### P3 - Dashboard & Reporting
- [ ] **Postponement tracking dashboard**
  - View all postponements by status (detected/confirmed/resolved)
  - See affected predictions count
  - Track resolution time

- [ ] **Weekly postponement report**
  - Summary of postponements in past week
  - Predictions affected
  - Data recovery status

---

## Long-Term (This Quarter)

### P3 - MLB Extension
- [ ] **Adapt detection for MLB**
  - Different status codes (rain delay, suspended, etc.)
  - Different schedule patterns (doubleheaders)
  - Weather-related postponements more common

- [ ] **Create sport-agnostic detection framework**
  - Configurable status codes per sport
  - Configurable news keywords per sport
  - Shared tracking table (already has `sport` column)

### P3 - Historical Analysis
- [ ] **Backfill past postponements**
  - Scan historical schedule data for anomalies
  - Document known postponements (COVID era, etc.)
  - Validate prediction accuracy excluding postponed games

### P4 - Advanced Features
- [ ] **Predictive postponement detection**
  - Weather API integration
  - Civil unrest / safety indicators
  - Historical patterns (certain venues, times)

- [ ] **Automated betting market monitoring**
  - Odds movement can indicate postponement rumors
  - Sudden line removal = strong postponement signal

---

## Session 4 Completed (2026-01-25)

- [x] **Fix logger bug in daily_health_summary/main.py**
  - Line 58 used `logger` before it was defined
  - Moved logging config above import try/except
  - Done: 2026-01-25

- [x] **Add missing symlink for postponement_detector.py**
  - Cloud function couldn't import PostponementDetector
  - Created symlink in `daily_health_summary/shared/utils/`
  - Done: 2026-01-25

- [x] **Investigate CHI@MIA reschedule**
  - Confirmed: Jan 30 → Jan 31 (game_id=0022500692)
  - Already tracked in game_postponements table
  - No predictions existed, nothing to invalidate
  - System working correctly
  - Done: 2026-01-25

---

## Resilience Improvements (Identified Session 4)

### P1 - High Impact

- [ ] **Cloud Function Deployment Validation Script**
  - Pre-deploy check that verifies:
    - All symlinks resolve correctly
    - No undefined variable references
    - Import statements work
  - Create `bin/deploy/validate_cloud_function.sh`

- [ ] **Automated Symlink Management**
  - Script to sync shared module symlinks to all cloud functions
  - Prevents missing symlink bugs like we just fixed
  - Consider: `bin/shared/sync_cloud_function_symlinks.sh`

- [ ] **Detection Before Prediction Generation**
  - Check postponement status in prediction coordinator
  - Skip generating predictions for postponed games
  - Prevents wasted computation

### P2 - Medium Impact

- [ ] **Duplicate Schedule Entry Cleanup**
  - When game rescheduled, update original date's status
  - Currently both dates remain with "Scheduled" status
  - Should mark original as "Rescheduled" or "Moved"

- [ ] **Automated Prediction Regeneration**
  - Auto-trigger predictions for new date when game moves
  - Currently requires manual intervention

- [ ] **Multi-Source Postponement Verification**
  - Cross-check NBA.com schedule with ESPN/BDL
  - Reduces false positives

---

## Technical Debt

### Code Quality
- [x] Fix deprecation warning in `fix_postponed_game.py`
  - Changed `datetime.utcnow()` → `datetime.now(timezone.utc)`
  - Done: 2026-01-25

- [ ] **Standardize Slack implementations**
  - Currently 3 different patterns:
    1. `detect_postponements.py` → `send_to_slack()` from shared.utils.slack_channels
    2. `daily_data_completeness.py` → `requests.post()` directly
    3. `daily_health_summary/main.py` → `send_slack_webhook_with_retry()`
  - Should use single retry-enabled approach everywhere

- [x] **Activate `get_affected_predictions()` in detect_postponements.py**
  - Now called for each CRITICAL and HIGH anomaly
  - Prediction count included in alerts and Slack messages
  - Done: 2026-01-25

- [x] **Log all anomaly types to BigQuery**
  - Now logs ALL anomaly types including NEWS_POSTPONEMENT_MENTIONED
  - Provides complete audit trail
  - Done: 2026-01-25

- [x] Add unit tests for detection script
  - Test each detection method
  - Test with mock BigQuery data
  - Created: `shared/utils/tests/test_postponement_detector.py`
  - 27 tests covering all detection methods, severity classification, error handling
  - Done: 2026-01-25

- [ ] Add integration tests
  - Full flow: detect → fix → verify

### Documentation
- [x] Create project README
- [x] Create design document
- [x] Create implementation log
- [x] Create runbook
- [ ] Add to main project docs (link from MASTER-PROJECT-TRACKER.md)
- [ ] Create architecture diagram

---

## Dependencies

| Task | Depends On |
|------|------------|
| Grading skip invalidated | Invalidation columns added |
| Cascade trigger | Detection integrated |
| MLB extension | NBA system validated |
| Dashboard | Tracking data accumulated |

---

## Success Metrics

| Metric | Current | Target | Timeline |
|--------|---------|--------|----------|
| Detection time | 24+ hours | < 30 min | This week |
| False positive rate | Unknown | < 5% | This month |
| Prediction recovery | 0% | 100% | This week |
| Automated resolution | 0% | 80% | This month |

---

## Notes

- GSW@MIN was the trigger for this project (Jan 24 postponed, fixed with 55 predictions invalidated)
- CHI@MIA rescheduled (Jan 30 → Jan 31) - **RESOLVED**: Detected before predictions generated, no action needed
- News articles captured postponement but weren't acted on initially
- Rate limiting on prediction coordinator - **FIXED** with retry logic in `force_predictions.sh`
  - Added `curl_with_retry()` function with exponential backoff (30s, 60s, 120s)
  - Handles HTTP 429 (rate limited) and 503 (service unavailable)
  - Applied to all Cloud Run API calls in pipeline scripts
- Cloud function symlinks must be manually created - **potential for bugs** (see Resilience Improvements)
