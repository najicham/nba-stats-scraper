# Session 154: Odds Data Backfill & Phase 3 Fixes

**Date:** 2025-12-20
**Duration:** ~45 minutes
**Status:** Complete - pipeline flowing through Phase 3

## Summary

Continued from Session 153 to complete pipeline restoration:
1. Backfilled odds game lines data (Dec 1-19) from GCS to BigQuery
2. Fixed Phase 3 `UpcomingPlayerGameContextProcessor` - missing package + validation bug

## Work Completed

### 1. Odds Data Backfill (Dec 1-19)

**Problem:** Due to Session 153's routing fix (`odds-api/game-lines` was missing from registry), historical GCS files had never been processed to BigQuery.

**Solution:** Created backfill script that simulates Pub/Sub messages to Phase 2:

```bash
# Script location
scripts/backfill_odds_game_lines.py

# Usage
python scripts/backfill_odds_game_lines.py --start-date 2025-12-01 --end-date 2025-12-19

# Dry run (list files without processing)
python scripts/backfill_odds_game_lines.py --start-date 2025-12-01 --end-date 2025-12-19 --dry-run
```

**Results:**
- 359 files processed (first run: 281 success, 78 errors due to token expiration)
- 75 files processed (second run: 100% success)
- Total: 2,936 rows loaded for Dec 1-20

**Data by date:**
```
Dec 1:  216 | Dec 7:  256 | Dec 13:  64 | Dec 19: 120
Dec 2:  144 | Dec 8:   72 | Dec 14: 272 | Dec 20:  88
Dec 3:  216 | Dec 9:   64 | Dec 15: 120
Dec 4:  120 | Dec 10:  48 | Dec 16:  24
Dec 5:  288 | Dec 11:  96 | Dec 17:  48
Dec 6:  224 | Dec 12: 168 | Dec 18: 288
```

### 2. Phase 3 Fixes

**Issue 1: Missing `db-dtypes` package**
- Error: `Please install the 'db-dtypes' package to use this function`
- Cause: BigQuery's `.to_dataframe()` requires `db-dtypes` for pandas integration
- Fix: Added `db-dtypes>=1.2.0` to `data_processors/analytics/requirements.txt`

**Issue 2: Validation mismatch in UpcomingPlayerGameContextProcessor**
- Error: "No data extracted" even when 401 players found
- Cause: Base class `validate_extracted_data()` checks `self.raw_data`, but this processor uses `self.players_to_process`
- Fix: Added `validate_extracted_data()` override to check `self.players_to_process`

**Files Changed:**
```
data_processors/analytics/requirements.txt
data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
scripts/backfill_odds_game_lines.py (new)
```

## Deployments

| Service | Revision | Status |
|---------|----------|--------|
| nba-phase3-analytics-processors | 00017-4hc | Deployed with both fixes |

## Current Pipeline State

```sql
| Table                        | Latest Data | Status |
|------------------------------|-------------|--------|
| odds_api_game_lines          | 2025-12-20  | ✅ Backfilled (was 0 rows) |
| upcoming_player_game_context | 2025-12-20  | ✅ Fixed (was 2025-12-19) |
| player_prop_predictions      | 2025-12-13  | ⚠️ Still needs Phase 4-6 run |
```

## Commands Used

```bash
# Backfill odds data
PYTHONPATH=. .venv/bin/python scripts/backfill_odds_game_lines.py \
  --start-date 2025-12-01 --end-date 2025-12-19

# Deploy Phase 3
./bin/analytics/deploy/deploy_analytics_processors.sh

# Trigger Phase 3 processor
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2025-12-20", "end_date": "2025-12-20", "processors": ["UpcomingPlayerGameContextProcessor"]}'

# Verify data
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) FROM nba_analytics.upcoming_player_game_context WHERE game_date >= "2025-12-19" GROUP BY 1'
```

## Remaining Work

### Priority 1: Complete Pipeline Flow
- [ ] Trigger Phase 4 (precompute) for Dec 20
- [ ] Verify Phase 5 (predictions) generates
- [ ] Verify Phase 6 (grading) works

### Priority 2: Grading Backfill (from Session 151)
Still pending - wait until pipeline is fully flowing.

## Lessons Learned & System Improvements

### 1. Package Dependency Management
**Problem:** `db-dtypes` was in some requirements files but not analytics.
**Improvement:** Create a shared base requirements file that all services inherit from, containing common BigQuery/pandas dependencies.

### 2. Long-Running Scripts & Auth Token Expiration
**Problem:** Backfill script failed mid-run due to token expiration (~1 hour).
**Improvement Options:**
- Refresh token periodically during long runs
- Use service account instead of user identity token
- Batch processing with shorter token lifetimes

### 3. Validation Mismatch Pattern
**Problem:** Child class used different data structure than base class expected.
**Improvement:**
- Document data contract in base class (what `validate_extracted_data` expects)
- Add abstract property `_validation_data` that child classes must implement
- Consider using a more explicit pattern like `has_data()` method

### 4. Missing Backfill Tooling
**Problem:** No standard way to reprocess GCS files through Phase 2.
**Improvement:**
- Add `/reprocess` endpoint to Phase 2 that takes GCS path directly
- Create generic backfill script that works for any processor type
- Add backfill commands to the orchestration system

### 5. Better Error Messages
**Problem:** "No data extracted" didn't indicate what was actually checked.
**Improvement:** Error messages should include:
- What data structure was checked
- What value it had (empty, None, etc.)
- What the processor expected

## Git Commits

```
2b6a75d fix: Phase 3 analytics - add db-dtypes and fix validation
```

## Quick Verification

```bash
# Check odds data
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM nba_raw.odds_api_game_lines WHERE game_date >= "2025-12-01"'

# Check Phase 3 output
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) FROM nba_analytics.upcoming_player_game_context WHERE game_date >= "2025-12-19" GROUP BY 1'

# Check Phase 3 logs
gcloud run services logs read nba-phase3-analytics-processors --region us-west2 --limit 20
```
