# Code Quality Initiative - Progress Tracker

**Last Updated:** 2026-01-24

---

## Task Status Overview

| Status | Count |
|--------|-------|
| Completed | 0 |
| In Progress | 0 |
| Pending | 15 |
| Blocked | 0 |

---

## Detailed Task Status

### Task #1: Fix SQL Injection Vulnerabilities
**Status:** Pending
**Priority:** P0 - CRITICAL
**Estimated Effort:** 2-3 hours

**Files to Fix:**
- [ ] `scripts/validate_historical_season.py` (Lines 55, 57, 61-66, 75-77, 81, 101-103, 121-125, 147-154, 172-179)
- [ ] `scripts/smoke_test.py` (Lines 46-96)
- [ ] `predictions/coordinator/shared/utils/data_freshness_checker.py` (Line 202)
- [ ] `shared/utils/player_registry/resolution_cache.py` (Line 290)
- [ ] `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` (Lines 813-831)

**Solution:** Use BigQuery parameterized queries (`@parameter` syntax)

**Notes:**


---

### Task #2: Consolidate Duplicate Utility Files
**Status:** Pending
**Priority:** P1 - HIGH
**Estimated Effort:** 8-12 hours

**Duplicate Files (9-10 copies each):**
- [ ] `slack_channels.py` (10 copies)
- [ ] `rate_limiter.py` (9 copies)
- [ ] `backfill_progress_tracker.py` (9 copies)
- [ ] `checkpoint.py` (9 copies)
- [ ] `schedule_utils.py` (9 copies)
- [ ] `bigquery_retry.py` (9 copies)
- [ ] `email_alerting.py` (9 copies)
- [ ] `travel_team_info.py` (9 copies)
- [ ] `mlb_team_mapper.py` (9 copies)
- [ ] `alert_types.py` (9 copies)
- [ ] `metrics_utils.py` (9 copies)
- [ ] `storage_client.py` (9 copies)
- [ ] `auth_utils.py` (9 copies)
- [ ] `mlb_game_id_converter.py` (9 copies)
- [ ] `sentry_config.py` (9 copies)
- [ ] `game_id_converter.py` (9 copies)
- [ ] `nba_team_mapper.py` (9 copies)

**Strategy:**
1. Verify shared/ has canonical version
2. Update imports in cloud functions
3. Delete duplicates
4. Test deployments

**Notes:**


---

### Task #3: Add Tests for Scrapers Module
**Status:** Pending
**Priority:** P2 - HIGH
**Estimated Effort:** 20+ hours

**Scope:** 147 files, currently ~1 test

**Priority Files:**
- [ ] `scrapers/scraper_base.py` (2394 lines - core framework)
- [ ] `scrapers/main_scraper_service.py`
- [ ] `scrapers/registry.py`
- [ ] `scrapers/exporters.py`
- [ ] Individual scrapers (balldontlie, nbacom, espn, etc.)

**Test Location:** `tests/scrapers/`

**Notes:**


---

### Task #4: Add Tests for Monitoring Module
**Status:** Pending
**Priority:** P2 - HIGH
**Estimated Effort:** 10 hours

**Files Needing Tests:**
- [ ] `monitoring/pipeline_latency_tracker.py`
- [ ] `monitoring/firestore_health_check.py`
- [ ] `monitoring/resolution_health_check.py`
- [ ] `monitoring/processor_slowdown_detector.py`
- [ ] `monitoring/gap_detection/`
- [ ] `monitoring/execution/`
- [ ] `monitoring/stall_detection/`

**Test Location:** `tests/monitoring/`

**Notes:**


---

### Task #5: Add Tests for Services Module
**Status:** Pending
**Priority:** P2 - MEDIUM
**Estimated Effort:** 6 hours

**Files Needing Tests:**
- [ ] `services/admin_dashboard/main.py`
- [ ] `services/admin_dashboard/services/firestore_service.py`
- [ ] `services/admin_dashboard/services/bigquery_service.py`
- [ ] `services/admin_dashboard/services/logging_service.py`
- [ ] `services/nba_grading_alerts/main.py`

**Test Location:** `tests/services/`

**Notes:**


---

### Task #6: Extract Hardcoded Cloud Run URLs
**Status:** Pending
**Priority:** P1 - MEDIUM
**Estimated Effort:** 2 hours

**Files to Fix:**
- [ ] `bin/testing/replay_pipeline.py` (lines 71-91)
- [ ] `bin/scraper_catchup_controller.py` (line 67)
- [ ] `orchestration/cloud_functions/line_quality_self_heal/main.py` (lines 63-66)
- [ ] `bin/testing/mlb/replay_mlb_pipeline.py` (lines 72-76)
- [ ] `orchestration/cloud_functions/self_heal/main.py` (lines 50-52)
- [ ] `predictions/coordinator/shared/utils/processor_alerting.py` (line 206)
- [ ] `data_processors/publishing/live_grading_exporter.py` (line 40)

**Solution:** Create `shared/config/service_urls.py` or use env vars

**Notes:**


---

### Task #7: Refactor Files Over 1000 Lines
**Status:** Pending
**Priority:** P3 - MEDIUM
**Estimated Effort:** 16 hours

**Files (sorted by size):**
- [ ] `upcoming_player_game_context_processor.py` (4039 lines)
- [ ] `analytics_base.py` (2951 lines)
- [ ] `precompute_base.py` (2628 lines)
- [ ] `player_composite_factors_processor.py` (2604 lines)
- [ ] `scraper_base.py` (2394 lines)
- [ ] `player_daily_cache_processor.py` (2269 lines)
- [ ] `upcoming_team_game_context_processor.py` (2263 lines)
- [ ] `roster_registry_processor.py` (2230 lines)
- [ ] `player_game_summary_processor.py` (1909 lines)
- [ ] `nbac_gamebook_processor.py` (1818 lines)
- [ ] `player_shot_zone_analysis_processor.py` (1774 lines)
- [ ] `completeness_checker.py` (1759 lines)

**Notes:**


---

### Task #8: Add Missing Request Timeouts
**Status:** Pending
**Priority:** P0 - HIGH
**Estimated Effort:** 1 hour

**Files to Fix:**
- [ ] `predictions/coordinator/shared/utils/processor_alerting.py` (Line 219)
- [ ] `tools/health/bdl_data_analysis.py` (Line 49)

**Solution:** Add `timeout=30` (or appropriate value) to all requests calls

**Notes:**


---

### Task #9: Address TODO Comments
**Status:** Pending
**Priority:** P3 - LOW
**Estimated Effort:** 4 hours

**Total TODOs:** 47+

**Key Areas:**
- [ ] `upcoming_player_game_context_processor.py` - 19 TODOs
- [ ] `bin/maintenance/phase3_backfill_check.py:196`
- [ ] `predictions/coordinator/player_loader.py:1226`
- [ ] `predictions/coordinator/shared/alerts/alert_manager.py:461`
- [ ] `ml_models/nba/train_xgboost_v1.py:472`
- [ ] `ml/experiment_runner.py:344`
- [ ] `services/admin_dashboard/main.py:1402,1406`

**Notes:**


---

### Task #10: Add Tests for Tools Module
**Status:** Pending
**Priority:** P2 - MEDIUM
**Estimated Effort:** 4 hours

**Files Needing Tests:**
- [ ] `tools/fixtures/capture.py`
- [ ] `tools/health/bdl_ping.py`
- [ ] `tools/health/bdl_data_analysis.py`
- [ ] `tools/monitoring/check_prop_freshness.py`
- [ ] `tools/monitoring/check_pipeline_health.py`
- [ ] `tools/monitoring/check_prediction_coverage.py`
- [ ] `tools/player_registry/*`
- [ ] `tools/name_resolution_review.py`

**Test Location:** `tests/tools/`

**Notes:**


---

### Task #11: Improve Error Handling for External APIs
**Status:** Pending
**Priority:** P0 - HIGH
**Estimated Effort:** 3 hours

**Files to Fix:**
- [ ] `predictions/coordinator/shared/utils/processor_alerting.py` (Line 219)
- [ ] `tools/health/bdl_data_analysis.py` (Lines 49, 59-60)
- [ ] `bin/alerts/daily_summary/main.py` (Line 385)
- [ ] `shared/utils/processor_alerting.py` (Line 404)
- [ ] `shared/utils/notification_system.py` (Lines 541, 630)
- [ ] `orchestration/cloud_functions/phase4_to_phase5/main.py` (Line 993)

**Solution:** Replace bare `except:` with specific exceptions, add proper logging

**Notes:**


---

### Task #12: Convert Raw Processors to BigQuery Pool
**Status:** Pending
**Priority:** P3 - MEDIUM
**Estimated Effort:** 3 hours

**Scope:** 37 raw processors

**Notes:**


---

### Task #13: Add Tests for ML Training Scripts
**Status:** Pending
**Priority:** P2 - MEDIUM
**Estimated Effort:** 8 hours

**Scope:** 33 files, 4 existing tests

**Priority Files:**
- [ ] Train scripts: `train_*.py`
- [ ] Backfill scripts: `backfill_*.py`
- [ ] Analysis: `calculate_betting_accuracy.py`, `compare_champion_challenger.py`

**Test Location:** `tests/ml/`

**Notes:**


---

### Task #14: Refactor Functions Over 250 Lines
**Status:** Pending
**Priority:** P3 - MEDIUM
**Estimated Effort:** 8 hours

**Functions to Refactor:**
- [ ] `main_processor_service.py: process_pubsub()` (692 lines)
- [ ] `verify_database_completeness.py: main()` (496 lines)
- [ ] `analytics_base.py: run()` (476 lines)
- [ ] `main_processor_service.py: extract_opts_from_path()` (427 lines)
- [ ] `self_heal/main.py: self_heal_check()` (356 lines)
- [ ] `nba_grading_alerts/main.py: build_alert_message()` (336 lines)
- [ ] `mlb_team_mapper.py: _load_teams_data()` (333 lines)
- [ ] `precompute_base.py: run()` (332 lines)
- [ ] `train_challenger_v10.py: main()` (329 lines)
- [ ] `roster_registry_processor.py: aggregate_roster_assignments()` (320 lines)

**Notes:**


---

### Task #15: Deploy New Cloud Functions
**Status:** Pending
**Priority:** P1 - HIGH
**Estimated Effort:** 30 minutes

**Functions to Deploy:**
- [ ] `pipeline-dashboard`
- [ ] `auto-backfill-orchestrator`

**Commands:**
```bash
# Deploy pipeline dashboard
gcloud functions deploy pipeline-dashboard \
  --gen2 --runtime=python311 --region=us-west2 \
  --source=orchestration/cloud_functions/pipeline_dashboard \
  --entry-point=pipeline_dashboard --trigger-http \
  --allow-unauthenticated --timeout=60s --memory=256MB

# Deploy auto-backfill orchestrator
gcloud functions deploy auto-backfill-orchestrator \
  --gen2 --runtime=python311 --region=us-west2 \
  --source=orchestration/cloud_functions/auto_backfill_orchestrator \
  --entry-point=auto_backfill_orchestrator --trigger-http \
  --timeout=120s --memory=512MB
```

**Notes:**


---

## Completed Tasks

(None yet)

---

## Blockers & Issues

(None yet)

---

## Session Notes

### Session 1 - 2026-01-24
- Created task list from automated codebase analysis
- Identified 15 tasks across security, testing, and code quality
- Set up project tracking in `docs/08-projects/current/code-quality-2026-01/`
