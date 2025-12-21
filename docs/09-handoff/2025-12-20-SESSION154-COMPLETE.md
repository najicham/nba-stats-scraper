# Session 154: Complete Pipeline Restoration

**Date:** 2025-12-20
**Duration:** ~2 hours
**Status:** Pipeline flowing through Phase 4; Phase 5 blocked on game data

## Executive Summary

This session continued from Session 153 to complete pipeline restoration. We:
1. Backfilled 2,936 odds data records (Dec 1-19)
2. Fixed 8 bugs across Phases 3, 4, and 5
3. Deployed 4 services with fixes
4. Documented architectural limitations for pre-game predictions

The pipeline is now operational through Phase 4. Phase 5 predictions require post-game data and will run automatically once Dec 20 games complete.

---

## Table of Contents

1. [Work Completed](#work-completed)
2. [Bugs Fixed](#bugs-fixed)
3. [Files Changed](#files-changed)
4. [Deployments](#deployments)
5. [Current Pipeline State](#current-pipeline-state)
6. [Commands Reference](#commands-reference)
7. [Architectural Findings](#architectural-findings)
8. [Lessons Learned](#lessons-learned)
9. [Remaining Work](#remaining-work)
10. [Git Commits](#git-commits)

---

## Work Completed

### 1. Odds Data Backfill (Dec 1-19)

**Problem:** Session 153 fixed the Phase 2 routing for `odds-api/game-lines`, but historical GCS files (Dec 1-19) had never been processed.

**Solution:** Created backfill script that simulates Pub/Sub messages to Phase 2.

**Script:** `scripts/backfill_odds_game_lines.py`

```bash
# Usage
python scripts/backfill_odds_game_lines.py --start-date 2025-12-01 --end-date 2025-12-19

# Dry run (list files without processing)
python scripts/backfill_odds_game_lines.py --start-date 2025-12-01 --end-date 2025-12-19 --dry-run
```

**Results:**
| Metric | Value |
|--------|-------|
| Total files | 434 |
| First run | 281 success, 78 errors (token expired) |
| Second run | 75 success, 0 errors |
| Total rows loaded | 2,936 |
| Date range | Dec 1-20, 2025 |

**Row counts by date:**
```
Dec 1:  216 | Dec 7:  256 | Dec 13:  64 | Dec 19: 120
Dec 2:  144 | Dec 8:   72 | Dec 14: 272 | Dec 20:  88
Dec 3:  216 | Dec 9:   64 | Dec 15: 120
Dec 4:  120 | Dec 10:  48 | Dec 16:  24
Dec 5:  288 | Dec 11:  96 | Dec 17:  48
Dec 6:  224 | Dec 12: 168 | Dec 18: 288
```

### 2. Phase 3 Analytics Fixes

Triggered `UpcomingPlayerGameContextProcessor` for Dec 19-20:
- Dec 19: 107 players processed
- Dec 20: 159 players processed

### 3. Phase 4 Precompute Execution

Triggered all processors for Dec 20:
| Processor | Status | Notes |
|-----------|--------|-------|
| PlayerDailyCacheProcessor | ✅ Success | Dec 20 |
| PlayerShotZoneAnalysisProcessor | ✅ Success | Dec 20 |
| PlayerCompositeFactorsProcessor | ✅ Success | Dec 20 |
| TeamDefenseZoneAnalysisProcessor | ⚠️ Expected | No play-by-play (games not played) |
| MLFeatureStoreProcessor | ⚠️ Expected | Depends on game data |

### 4. Phase 5 Predictions Attempt

Attempted to trigger predictions for Dec 20:
- 66 prediction requests published successfully
- All failed due to missing `ml_feature_store_v2` data
- **Root cause:** Feature store requires post-game data

---

## Bugs Fixed

### Phase 3 Bugs (2)

#### Bug 1: Missing `db-dtypes` Package
- **Error:** `Please install the 'db-dtypes' package to use this function`
- **Cause:** BigQuery's `.to_dataframe()` requires `db-dtypes` for pandas integration
- **Fix:** Added `db-dtypes>=1.2.0` to `data_processors/analytics/requirements.txt`
- **File:** `data_processors/analytics/requirements.txt`

#### Bug 2: Validation Mismatch in UpcomingPlayerGameContextProcessor
- **Error:** "No data extracted" even when 401 players found
- **Cause:** Base class `validate_extracted_data()` checks `self.raw_data`, but this processor uses `self.players_to_process`
- **Fix:** Added `validate_extracted_data()` override to check `self.players_to_process`
- **File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

### Phase 4 Bugs (4)

#### Bug 3: `backfill_mode` Not Passed to Processors
- **Error:** Dependency checks blocking manual runs
- **Cause:** `/process-date` endpoint didn't support bypassing dependency checks
- **Fix:** Added `backfill_mode` parameter to request body and opts
- **File:** `data_processors/precompute/main_precompute_service.py`

#### Bug 4: `analysis_date` String Not Converted
- **Error:** `'str' object has no attribute 'month'`
- **Cause:** Processors expected `date` object but received string from JSON
- **Fix:** Added `date.fromisoformat()` conversion in `precompute_base.run()`
- **File:** `data_processors/precompute/precompute_base.py`

#### Bug 5: `RunHistoryMixin._run_start_time` Not Initialized
- **Error:** `'TeamDefenseZoneAnalysisProcessor' object has no attribute '_run_start_time'`
- **Cause:** Mixin attribute accessed before initialization
- **Fix:** Added `_init_run_history()` call in `PrecomputeProcessorBase.__init__`
- **File:** `data_processors/precompute/precompute_base.py`

#### Bug 6: Missing `db-dtypes` in Shared Requirements
- **Error:** Same as Bug 1, but in Phase 4
- **Cause:** `shared/requirements.txt` missing the package
- **Fix:** Added `db-dtypes>=1.2.0` to `shared/requirements.txt`
- **File:** `shared/requirements.txt`

### Phase 5 Bugs (2)

#### Bug 7: Wrong Pub/Sub Topic Names
- **Error:** `404 Resource not found (resource=prediction-request)`
- **Cause:** Default topic was `prediction-request` but actual is `prediction-request-prod`
- **Fix:** Changed defaults to include `-prod` suffix
- **File:** `predictions/coordinator/coordinator.py`

#### Bug 8: SQL Column Doesn't Exist
- **Error:** `400 Unrecognized name: games_played_last_30`
- **Cause:** Query referenced non-existent column
- **Fix:** Changed to `l10_games_used as games_played`
- **File:** `predictions/coordinator/player_loader.py`

---

## Files Changed

```
data_processors/analytics/requirements.txt
  - Added db-dtypes>=1.2.0

data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
  - Added validate_extracted_data() override

data_processors/precompute/main_precompute_service.py
  - Added backfill_mode parameter support

data_processors/precompute/precompute_base.py
  - Added date string to object conversion
  - Added _init_run_history() call

shared/requirements.txt
  - Added db-dtypes>=1.2.0

predictions/coordinator/coordinator.py
  - Fixed Pub/Sub topic defaults

predictions/coordinator/player_loader.py
  - Fixed SQL column reference

scripts/backfill_odds_game_lines.py (NEW)
  - Backfill script for odds data
```

---

## Deployments

| Service | Revisions | Time |
|---------|-----------|------|
| nba-phase3-analytics-processors | 00016-cfm, 00017-4hc | 5m 35s, 5m 31s |
| nba-phase4-precompute-processors | 00013-pdp, 00014-2zg, 00015-vsc | 4m 24s, 4m 20s, 4m 21s |
| prediction-coordinator | 00002-56q, 00003-kxw | 4m 3s, 3m 58s |

**Total deployment time:** ~32 minutes

---

## Current Pipeline State

### Data Freshness

```sql
| Table                          | Latest Date | Status |
|--------------------------------|-------------|--------|
| nba_raw.odds_api_game_lines    | 2025-12-20  | ✅ Backfilled |
| nba_analytics.upcoming_player_game_context | 2025-12-20 | ✅ |
| nba_precompute.player_daily_cache | 2025-12-20 | ✅ |
| nba_precompute.player_shot_zone_analysis | 2025-12-20 | ✅ |
| nba_precompute.player_composite_factors | 2025-12-20 | ✅ |
| nba_precompute.team_defense_zone_analysis | 2025-12-19 | ⚠️ Waiting for play-by-play |
| nba_predictions.ml_feature_store_v2 | 2025-12-19 | ⚠️ Waiting for game data |
| nba_predictions.player_prop_predictions | 2025-12-13 | ⚠️ Blocked on feature store |
```

### Service Health

All services healthy:
- nba-phase3-analytics-processors: ✅
- nba-phase4-precompute-processors: ✅
- prediction-coordinator: ✅
- prediction-worker: ✅

---

## Commands Reference

### Backfill Odds Data
```bash
PYTHONPATH=. .venv/bin/python scripts/backfill_odds_game_lines.py \
  --start-date 2025-12-01 --end-date 2025-12-19
```

### Deploy Services
```bash
# Phase 3
./bin/analytics/deploy/deploy_analytics_processors.sh

# Phase 4
./bin/precompute/deploy/deploy_precompute_processors.sh

# Phase 5 Coordinator
./bin/predictions/deploy/deploy_prediction_coordinator.sh
```

### Trigger Phase 3
```bash
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2025-12-20", "end_date": "2025-12-20", "processors": ["UpcomingPlayerGameContextProcessor"]}'
```

### Trigger Phase 4
```bash
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2025-12-20", "backfill_mode": true}'
```

### Trigger Phase 5
```bash
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-20", "force": true}'
```

### Check Prediction Batch Status
```bash
curl "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status?batch_id=BATCH_ID" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Verify Data
```bash
# Odds data
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) FROM nba_raw.odds_api_game_lines WHERE game_date >= "2025-12-01" GROUP BY 1 ORDER BY 1'

# Phase 3 output
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) FROM nba_analytics.upcoming_player_game_context WHERE game_date >= "2025-12-19" GROUP BY 1'

# Phase 4 output
bq query --use_legacy_sql=false 'SELECT "player_daily_cache" as tbl, MAX(cache_date) FROM nba_precompute.player_daily_cache UNION ALL SELECT "ml_feature_store_v2", MAX(game_date) FROM nba_predictions.ml_feature_store_v2'

# Feature store for predictions
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*), AVG(feature_quality_score) FROM nba_predictions.ml_feature_store_v2 WHERE game_date >= "2025-12-18" GROUP BY 1 ORDER BY 1'
```

### Check Logs
```bash
# Phase 3
gcloud run services logs read nba-phase3-analytics-processors --region us-west2 --limit 50

# Phase 4
gcloud run services logs read nba-phase4-precompute-processors --region us-west2 --limit 50

# Phase 5 Coordinator
gcloud run services logs read prediction-coordinator --region us-west2 --limit 50

# Phase 5 Worker
gcloud run services logs read prediction-worker --region us-west2 --limit 50
```

---

## Architectural Findings

### Pre-Game Prediction Limitation

**Finding:** Phase 5 predictions cannot run for future/current dates because they require `ml_feature_store_v2` data, which is only populated AFTER games are played.

**Data Flow:**
```
Games Play → Scrapers → Phase 1 (GCS) → Phase 2 (Raw BQ)
           → Phase 3 (player_game_summary, team_defense_zone)
           → Phase 4 (ml_feature_store_v2)
           → Phase 5 (predictions)
           → Phase 6 (grading)
```

**The Catch-22:**
- `ml_feature_store_v2` requires `player_game_summary` (post-game stats)
- `team_defense_zone_analysis` requires `play_by_play` (post-game data)
- Predictions need features from both of these

**Current Workaround:**
- `upcoming_player_game_context` has pre-game data (159 players for Dec 20)
- But predictions don't use this directly - they use `ml_feature_store_v2`

**Potential Future Enhancement:**
Create a "pre-game feature store" that generates features from `upcoming_player_game_context` for same-day predictions. This would allow predictions BEFORE games start.

### Pub/Sub Topic Naming

**Finding:** Several services have mismatched topic defaults vs actual infrastructure.

| Service | Default | Actual Topic |
|---------|---------|--------------|
| prediction-coordinator | prediction-request | prediction-request-prod |
| prediction-coordinator | prediction-ready | prediction-ready-prod |

**Recommendation:** Standardize on environment-specific suffixes and ensure all defaults match production infrastructure.

### BigQuery Quota Issues

**Observed:** Multiple "quota exceeded for partition modifications" errors during run history logging.

**Impact:** Run history records may be incomplete, affecting dependency checks.

**Recommendation:**
1. Batch run history inserts
2. Use streaming buffer with appropriate batching
3. Consider reducing partition granularity

---

## Lessons Learned

### 1. Package Dependency Management

**Problem:** `db-dtypes` was missing from multiple requirements files.

**Root Cause:** Package was added to some services but not the shared requirements that other services depend on.

**Improvement:**
- Create hierarchy: `shared/requirements.txt` → service-specific requirements
- Add integration test that validates all services have required packages
- Document package purposes in requirements files

### 2. Long-Running Scripts & Auth Token Expiration

**Problem:** Backfill script failed mid-run (78 errors) because identity token expired (~1 hour).

**Improvement Options:**
1. Refresh token periodically during long runs
2. Use service account key instead of user identity token
3. Batch processing with breaks for token refresh
4. Add retry logic with fresh token on 401 errors

### 3. Validation Contract Mismatch

**Problem:** Child class used `self.players_to_process` but base class validation checked `self.raw_data`.

**Improvement:**
- Document data contract in base class
- Add abstract property/method that child classes must implement
- Use explicit interface like `has_data()` or `get_validation_data()`

### 4. Environment Configuration Defaults

**Problem:** Pub/Sub topic defaults didn't match actual production topics.

**Improvement:**
- Environment-specific configuration files
- Validate configuration on startup
- Log actual values being used (not just defaults)

### 5. Mixin Initialization Order

**Problem:** `RunHistoryMixin._run_start_time` not initialized before use.

**Root Cause:** `PrecomputeProcessorBase.__init__` didn't call mixin's init method.

**Improvement:**
- Always call `super().__init__()` in class hierarchies
- Document initialization requirements in mixins
- Add defensive initialization checks

### 6. Missing Backfill Tooling

**Problem:** No standard way to reprocess GCS files through Phase 2.

**Improvement:**
- Add `/reprocess` endpoint to Phase 2 that takes GCS path directly
- Create generic backfill framework
- Add backfill commands to orchestration system
- Track backfill progress in a dedicated table

---

## Remaining Work

### Immediate (After Games Complete)

1. **Verify automatic pipeline flow** - Once Dec 20 games complete, verify:
   - Phase 1 scrapers capture box scores
   - Phase 2 processes to BigQuery
   - Phase 3 generates analytics
   - Phase 4 generates features
   - Phase 5 predictions run
   - Phase 6 grading works

### Short-term

2. **Grading backfill** (from Session 151) - Still pending
   - Requires completed predictions to grade

3. **Fix BigQuery quota issues** - Run history inserts hitting rate limits
   - Implement batching or reduce frequency

### Medium-term

4. **Pre-game predictions** - Architectural enhancement
   - Create pre-game feature store from `upcoming_player_game_context`
   - Allow predictions before games start

5. **Standardize topic naming** - Configuration cleanup
   - Environment-specific defaults
   - Validation on startup

---

## Git Commits

```
b2d31f8 docs: Update Session 154 handoff with Phase 5 fixes
e154d07 fix: Phase 5 predictions - topic names and column reference
de364ce docs: Update Session 154 handoff with Phase 4 fixes
d45fc53 fix: Phase 4 precompute - backfill_mode, date conversion, mixin init
175bb20 docs: Add Session 154 handoff - odds backfill and Phase 3 fixes
2b6a75d fix: Phase 3 analytics - add db-dtypes and fix validation
```

---

## Quick Start for Next Session

```bash
# Check pipeline state
bq query --use_legacy_sql=false 'SELECT MAX(game_date) as latest FROM nba_predictions.player_prop_predictions'

# If predictions are still at Dec 13 after games complete, trigger manually:
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-20", "force": true}'

# Check prediction batch status
curl "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# View logs if issues
gcloud run services logs read prediction-worker --region us-west2 --limit 50 | grep -i error
```
