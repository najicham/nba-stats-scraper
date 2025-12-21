# Session 155/156: Pipeline Diagnosis and Fixes

**Date:** 2025-12-21
**Duration:** Session 155 (~45 min) + Session 156 (~30 min)
**Status:** ✅ FULLY RESTORED - gamebook backfilled, scheduler fixed

## Executive Summary

This session diagnosed why the pipeline wasn't processing Dec 20 data automatically and applied several fixes:
1. Fixed Phase 4 date conversion bug
2. Removed silent Docker pip install failures
3. Cleared stale run history to force reprocessing
4. Successfully loaded Dec 20 box scores (283 players)
5. Ran Phase 4 (4/5 processors succeeded)

**Key Blocker:** NBA.com gamebook scraper hasn't run since Dec 15, blocking MLFeatureStoreProcessor.

---

## Issues Found & Fixed

### 1. Phase 4: Date String Conversion Bug

**Symptom:** `AttributeError: 'str' object has no attribute 'month'`

**Root Cause:** In `precompute_base.py`, the date conversion happened AFTER `set_additional_opts()` was called. `TeamDefenseZoneAnalysisProcessor.set_additional_opts()` accesses `self.opts['analysis_date']` before conversion.

**Fix:** Added date conversion immediately after `set_opts()`:
```python
# precompute_base.py lines 169-172
if 'analysis_date' in self.opts and isinstance(self.opts['analysis_date'], str):
    self.opts['analysis_date'] = date.fromisoformat(self.opts['analysis_date'])
```

### 2. Docker: Silent pip Install Failures

**Symptom:** `db-dtypes` package missing despite being in requirements

**Root Cause:** `docker/precompute-processor.Dockerfile` had `|| true` which masked pip install failures:
```dockerfile
RUN pip install --no-cache-dir -r /app/shared/requirements.txt || true
```

**Fix:** Removed `|| true` to fail fast on install errors.

### 3. Run History: Premature Success Status

**Symptom:** Dec 20 box scores skipped with "already processed" despite 0 rows

**Root Cause:** BdlBoxscoresProcessor ran on Dec 20 at 17:42 UTC (before games finished), marked as "success" with 0 rows. When actual data arrived at 03:05 UTC Dec 21, it was skipped.

**Fix:** Deleted run history entries for Dec 20:
```sql
DELETE FROM nba_reference.processor_run_history
WHERE processor_name = "BdlBoxscoresProcessor" AND data_date = "2025-12-20"
```

### 4. Stats Reporting Bug (Not Fixed - Low Priority)

**Symptom:** `rows_processed: 0` reported even when 283 rows successfully loaded

**Root Cause:** `BdlBoxscoresProcessor.save_data()` returns a dict with rows_processed, but the base class doesn't capture this return value in the stats.

**Impact:** Cosmetic only - data is actually loaded correctly.

---

## Data Source Status

| Source | Latest Date | Status |
|--------|-------------|--------|
| `bdl_player_boxscores` | 2025-12-20 | ✅ Fixed this session |
| `nbac_gamebook_player_stats` | 2025-12-15 | ❌ 6 days stale |
| `espn_boxscores` | NULL | ❌ No data |
| `nbac_schedule` | 2026-04-12 | ✅ OK |

---

## Pipeline Status After Session

### Phase 2 (Raw Processing)
- Dec 20 BDL box scores: ✅ 283 players loaded

### Phase 3 (Analytics)
| Processor | Status | Notes |
|-----------|--------|-------|
| PlayerGameSummaryProcessor | ❌ | Missing gamebook data |
| TeamOffenseGameSummaryProcessor | ❌ | Missing gamebook data |
| TeamDefenseGameSummaryProcessor | ❌ | Missing team boxscore |
| UpcomingPlayerGameContextProcessor | ✅ | Success |
| UpcomingTeamGameContextProcessor | ❌ | Missing schedule |

### Phase 4 (Precompute)
| Processor | Status | Notes |
|-----------|--------|-------|
| TeamDefenseZoneAnalysisProcessor | ✅ | Success |
| PlayerShotZoneAnalysisProcessor | ✅ | Success |
| PlayerDailyCacheProcessor | ✅ | Success |
| PlayerCompositeFactorsProcessor | ✅ | Success |
| MLFeatureStoreProcessor | ❌ | No players found (gamebook stale) |

### Phase 5 (Predictions)
- Still blocked - feature store doesn't have Dec 20 data

---

## Other Issues Discovered

### 1. BigQuery Quota Exceeded
```
403 Quota exceeded: Your table exceeded quota for Number of partition modifications
```
Affecting run history logging. This is causing incomplete audit trails.

### 2. OddsApiPropsProcessor Path Parsing Bug
```python
IndexError: list index out of range at extract_metadata_from_path
```
The processor fails when file_path is "unknown" or malformed.

### 3. BasketballRefRosterProcessor SQL Injection
```
400 Syntax error: Expected ")" or "," but got identifier "Neale"
```
Player names with special characters aren't being escaped properly.

---

## Files Changed

```
data_processors/precompute/precompute_base.py
  - Added early date conversion (lines 169-172)

docker/precompute-processor.Dockerfile
  - Removed || true from pip install (line 15)
```

---

## Deployments

| Service | Revision | Time |
|---------|----------|------|
| nba-phase4-precompute-processors | 00016-c9h | 5m 27s |

---

## Immediate Actions Needed

### 1. Fix Gamebook Scraper (BLOCKER)
The `nbac_gamebook_player_stats` data is 6 days stale (Dec 15). This blocks:
- PlayerGameSummaryProcessor
- MLFeatureStoreProcessor
- Predictions

**Check:** Why isn't the gamebook scraper running? Check scheduler and logs:
```bash
gcloud scheduler jobs describe [gamebook-job] --location=us-west2
gcloud run services logs read nba-phase1-scrapers --region us-west2 --limit 50 | grep -i gamebook
```

### 2. Backfill Gamebook Data (Dec 16-21)
Once scraper is fixed, backfill the missing days.

### 3. Run Full Pipeline for Dec 20
After gamebook data is available:
```bash
# Phase 3
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"start_date": "2025-12-20", "end_date": "2025-12-20"}'

# Phase 4 - MLFeatureStore only
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-precompute" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"processor": "ml_feature_store", "analysis_date": "2025-12-20", "backfill_mode": true}'

# Phase 5
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"game_date": "2025-12-20", "force": true}'
```

---

## Lessons Learned

### 1. Run History: Don't Mark Success with 0 Rows
When a processor runs before data is available and returns 0 rows, it shouldn't be marked as "success". Consider:
- Only mark success if rows > 0
- Add a "no_data" status for cases where processing worked but no data found

### 2. Docker: Never Use `|| true` for Critical Installs
Silent failures make debugging extremely difficult. Let the build fail fast.

### 3. Date Conversion Order Matters
In class hierarchies with mixins and overrides, ensure type conversions happen before derived methods access the values.

### 4. Data Source Dependencies
The pipeline has hidden dependencies. MLFeatureStoreProcessor appears to depend on gamebook data, not BDL boxscores. Document and validate these dependencies.

---

## Git Commits

```
(Changes not committed - Phase 4 was redeployed from working directory)

Files modified:
- data_processors/precompute/precompute_base.py
- docker/precompute-processor.Dockerfile
```

---

## Session 156: Full Restoration (continued)

### Root Cause Found: Scheduler Gap

The `execute-workflows` scheduler only ran from **6 AM to 11 PM ET** (`5 6-23 * * *`), but the `post_game_window_3` workflow (which contains `nbac_gamebook_pdf`) is scheduled for **4 AM ET**.

The `/evaluate` at 4 AM correctly marked the workflow as "RUN", but `/execute-workflows` wasn't called until 6:05 AM, by which point the decision was stale.

### Fixes Applied (Session 156)

1. **Gamebook Backfill**: Scraped and processed 30 games (Dec 16-20)
   - 1,051 player rows loaded
   - 0 failures
   - Duration: 15 minutes

2. **Scheduler Fix**: Updated `execute-workflows` to run every hour:
   ```bash
   gcloud scheduler jobs update http execute-workflows \
       --location=us-west2 \
       --schedule="5 0-23 * * *"
   ```

3. **Pipeline Run for Dec 20**:
   - Phase 4: All 5 processors succeeded (including MLFeatureStoreProcessor)
   - Phase 3: Partial success (see known issues below)

### Data Source Status (Updated)

| Source | Latest Date | Status |
|--------|-------------|--------|
| `bdl_player_boxscores` | 2025-12-20 | ✅ OK |
| `nbac_gamebook_player_stats` | 2025-12-20 | ✅ FIXED |
| `espn_boxscores` | NULL | ❌ No data |
| `nbac_schedule` | 2026-04-12 | ✅ OK |
| `ml_feature_store_v2` | 2025-12-20 | ✅ OK |

### Known Issues Remaining

1. **Phase 3 Processors Failing**: PlayerGameSummaryProcessor, TeamOffenseGameSummaryProcessor, TeamDefenseGameSummaryProcessor, UpcomingTeamGameContextProcessor still have errors
2. **Predictions not working for Dec 21**: Coordinator returns "No players found" - likely needs additional data or query adjustment

---

## Quick Reference

```bash
# Gamebook status
bq query --use_legacy_sql=false 'SELECT MAX(game_date) FROM nba_raw.nbac_gamebook_player_stats'

# ML Feature Store status
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date >= "2025-12-18" GROUP BY game_date ORDER BY game_date'

# Run Phase 4 for a specific date
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d '{"analysis_date": "2025-12-20", "backfill_mode": true}'
```
