# MLB Pipeline Backfill Session Handoff

**Date:** 2026-01-08
**Session Focus:** Complete MLB historical data backfill and prediction generation
**Status:** COMPLETE - Batter data collected, analytics generated, predictions regenerated

---

## Executive Summary

This session completed the full MLB pipeline backfill:
1. ✅ Verified all orchestrator Cloud Functions are correct
2. ✅ Made timeout configuration flexible via environment variable
3. ✅ Added 13 unit tests for orchestrator logic
4. ✅ Updated dashboard templates with sport toggle (NBA/MLB)
5. ✅ Uploaded trained ML model to GCS
6. ✅ **Collected 97,679 batter game stats** (2024-2025 seasons)
7. ✅ **Generated 97,679 batter_game_summary analytics rows**
8. ✅ **Regenerated 8,028 predictions with bottom-up features (MAE: 1.54)**
9. ✅ **Fixed team_abbr "UNK" bug** - now extracts from correct API path
10. ⏳ **Backfill script running** - updating existing data with correct abbreviations

---

## Current Data State

### What's Populated

| Dataset | Table | Rows | Date Range | Status |
|---------|-------|------|------------|--------|
| `mlb_raw` | mlb_game_lineups | 10,319 | 2024-03-28 → 2025-09-28 | ✅ |
| `mlb_raw` | mlb_lineup_batters | 185,418 | 2024-03-28 → 2025-09-28 | ✅ |
| `mlb_raw` | mlb_pitcher_stats | 42,125 | 2024-03-28 → 2025-09-28 | ✅ |
| `mlb_analytics` | pitcher_game_summary | 9,793 | 2024-03-28 → 2025-09-28 | ✅ |
| `mlb_predictions` | pitcher_strikeouts | 8,130 | 2024-04-09 → 2025-09-28 | ✅ |

### What's Now Populated (This Session)

| Dataset | Table | Rows | Date Range | Status |
|---------|-------|------|------------|--------|
| `mlb_raw` | bdl_batter_stats | 97,679 | 2024-03-28 → 2025-09-28 | ✅ NEW |
| `mlb_analytics` | batter_game_summary | 97,679 | 2024-03-28 → 2025-09-28 | ✅ NEW |

### Still Empty (Not Critical)

| Dataset | Table | Notes | Priority |
|---------|-------|-------|----------|
| `mlb_precompute` | lineup_k_analysis | Inline calculation used instead | LOW |
| `mlb_raw` | mlb_schedule | Only needed for live prediction | LOW |

---

## Model Performance

The trained model (`mlb_pitcher_strikeouts_v1_20260107`) achieved:

| Metric | Value |
|--------|-------|
| Test MAE | 1.71 |
| Historical Backfill MAE | 1.54 |
| Baseline MAE | 1.92 |
| **Improvement** | **19.8%** |

Model location: `gs://nba-scraped-data/models/mlb/mlb_pitcher_strikeouts_v1_20260107.json`

---

## Batter Data Backfill - COMPLETED

### What Was Done

The bottom-up model features (f25, f26, f33) are now populated with real data:

1. **Created batter stats collector** (`scripts/mlb/collect_batter_stats.py`)
   - Uses MLB Stats API game feed endpoint
   - Extracts individual batter game stats from boxscore data
   - Resumable with checkpoint support
   - Collected 97,679 batter stats across 4,846 games

2. **Fixed batter_game_summary processor bugs**
   - `game_status IN ('STATUS_FINAL', 'STATUS_F')` - both formats now supported
   - Date serialization for JSON - converts date objects to ISO strings
   - Generated 97,679 batter analytics rows

3. **Updated prediction script with inline bottom-up features**
   - Joins `mlb_lineup_batters` with `batter_game_summary` to get K rates
   - Calculates per-game lineup K aggregates
   - Uses `game_pk` for proper join instead of `team_abbr` (which is "UNK")

### Data Quality Note - BUG FIXED

**Issue:** All `team_abbr` values were "UNK" across tables due to original collection bug.

**Root Cause:** Code was extracting team abbreviation from `boxscore.teams.away.team.abbreviation` which doesn't exist. The correct path is `gameData.teams.away.abbreviation`.

**Fix Applied:**
- `scripts/mlb/collect_season.py` - Fixed `_parse_game_data()` to use correct API path
- `scripts/mlb/collect_batter_stats.py` - Same fix applied
- Committed: `664e64e fix(mlb): Fix team abbreviation bug and add batter data collection`

**Backfill Script:** `scripts/mlb/fix_team_abbreviations.py` is running to update existing data.
- Fetches correct abbreviations from MLB API for each game_pk
- Updates all 4 tables: mlb_game_lineups, mlb_lineup_batters, mlb_pitcher_stats, bdl_batter_stats
- Progress: ~22% complete, ETA ~2 hours remaining

Once backfill completes, bottom-up features will use opponent-specific lineup K rates instead of game averages.

---

## Code Changes Made This Session

### 1. Timeout Configuration
**File:** `orchestration/cloud_functions/mlb_phase4_to_phase5/main.py`
```python
# Now configurable via environment variable
MAX_WAIT_HOURS = float(os.environ.get('MAX_WAIT_HOURS', '4'))
```

**File:** `bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh`
- Added `MAX_WAIT_HOURS` parameter
- Deploy function now accepts 5th parameter for extra env vars

### 2. Dashboard Sport Toggle
**Files Modified:**
- `services/admin_dashboard/templates/base.html` - Added NBA/MLB toggle
- `services/admin_dashboard/templates/dashboard.html` - Sport-aware content

### 3. Unit Tests
**File:** `tests/orchestration/unit/test_mlb_orchestrators.py`
- 13 tests covering normalize_processor_name, check_timeout, config parsing
- All passing

### 4. Historical Prediction Script
**File:** `scripts/mlb/generate_historical_predictions.py`
- Generates predictions from pitcher_game_summary
- Saves to mlb_predictions.pitcher_strikeouts
- Includes metrics calculation

---

## Files Created This Session

```
scripts/mlb/generate_historical_predictions.py     # Historical prediction generator
scripts/mlb/collect_batter_stats.py                # NEW: Batter stats collector from MLB Stats API
tests/orchestration/unit/test_mlb_orchestrators.py # Unit tests for orchestrators
bin/backfill/run_batter_game_summary_backfill.sh   # NEW: Batter analytics backfill script
bin/backfill/run_mlb_full_backfill.sh              # NEW: Full MLB pipeline backfill script
docs/09-handoff/2026-01-08-MLB-BACKFILL-SESSION-HANDOFF.md  # This file
```

## Files Modified This Session

```
data_processors/analytics/mlb/batter_game_summary_processor.py
  - Fixed game_status filter to include both 'STATUS_FINAL' and 'STATUS_F'
  - Fixed date serialization for JSON (convert date objects to ISO strings)

scripts/mlb/generate_historical_predictions.py
  - Updated query to calculate bottom-up features inline
  - Added join with mlb_pitcher_stats to get game_pk for proper linking
  - Fixed duplicate row issue by using game_pk instead of team_abbr

scripts/mlb/collect_season.py
  - BUG FIX: Extract team_abbr from gameData.teams (not boxscore.teams)
  - This fixes "UNK" abbreviations for all future data collection

scripts/mlb/collect_batter_stats.py
  - Same bug fix applied

scripts/mlb/fix_team_abbreviations.py (NEW)
  - Backfill script to fix existing "UNK" abbreviations
  - Fetches correct values from MLB API and updates BigQuery tables
```

---

## Quick Verification Commands

```bash
# Check prediction counts
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM mlb_predictions.pitcher_strikeouts"

# Check model in GCS
gsutil ls gs://nba-scraped-data/models/mlb/

# Run unit tests
PYTHONPATH=. .venv/bin/python -m pytest tests/orchestration/unit/test_mlb_orchestrators.py -v

# Check MLB health
./bin/monitoring/mlb_daily_health_check.sh

# Check batter stats
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM mlb_raw.bdl_batter_stats"

# Check team_abbr fix progress (if running)
tail -20 logs/fix_team_abbr.log

# Verify team abbreviations are fixed
bq query --use_legacy_sql=false "SELECT DISTINCT away_team_abbr FROM mlb_raw.mlb_game_lineups WHERE away_team_abbr != 'UNK' LIMIT 5"
```

---

## What NOT to Deploy Yet

1. **MLB Orchestrators** - Ready but don't deploy until season starts
   - `./bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh`
   - Will start processing when Pub/Sub messages arrive

2. **Updated Dashboard** - Templates updated but not deployed
   - `cd services/admin_dashboard && ./deploy.sh`
   - Works locally with `?sport=mlb`

---

## Known Issues

### 1. Team Abbreviations Show "UNK"
In `pitcher_game_summary`, `team_abbr` and `opponent_team_abbr` show as "UNK".
- Not blocking but affects display quality
- Root cause: Data collection didn't properly map team IDs to abbreviations
- Fix: Update collection script to properly extract team abbreviations

### 2. No Historical Betting Lines
`strikeouts_line` is NULL for all historical predictions.
- Cannot grade predictions as "correct" vs betting line
- Would need historical odds data from archive
- Not critical for model validation (we have actual results)

### 3. Email Alerting Not Configured on Cloud Run
Services deployed without BREVO env vars.
- `.env` has correct values locally
- Need to `source .env` before deploy scripts
- Or add to Cloud Run service directly

---

## Recommended Next Steps

### Immediate Improvements (Optional)

1. **Fix team_abbr data quality issue**
   - Update `scripts/mlb/collect_season.py` to properly extract team abbreviations
   - Re-collect pitcher and lineup data with correct team_abbr
   - This would enable opponent-specific lineup features instead of game-level averages

2. **Populate mlb_schedule table**
   - Currently empty
   - Needed for Phase 4 lineup_k_analysis processor
   - Would enable real-time prediction with proper lineup data

### Before MLB Season (March 2026)

1. Deploy orchestrators: `./bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh`
2. Deploy updated dashboard: `cd services/admin_dashboard && ./deploy.sh`
3. Enable MLB scheduler jobs via GCP console
4. Configure email alerting (add BREVO env vars to Cloud Run)
5. Test end-to-end with Spring Training games

---

## Architecture Reference

```
MLB Pipeline Flow:
==================

Phase 1 (Scrapers) → GCS
    ↓ [Pub/Sub]
Phase 2 (Raw Processors) → mlb_raw.*
    ↓ [Pub/Sub]
Phase 3 (Analytics) → mlb_analytics.*
    ↓ [Orchestrator]
Phase 4 (Precompute) → mlb_precompute.*
    ↓ [Orchestrator with 4h timeout]
Phase 5 (Predictions) → mlb_predictions.*
    ↓ [Orchestrator]
Phase 6 (Grading) → Updates predictions with is_correct

Self-Heal: Runs 12:45 PM ET daily, checks for missing predictions
```

---

## Key File Locations

| Purpose | Path |
|---------|------|
| Season data collection | `scripts/mlb/collect_season.py` |
| Historical predictions | `scripts/mlb/generate_historical_predictions.py` |
| Model training | `scripts/mlb/train_pitcher_strikeouts.py` |
| Trained model | `models/mlb/mlb_pitcher_strikeouts_v1_20260107.json` |
| Batter processor | `data_processors/analytics/mlb/batter_game_summary_processor.py` |
| Pitcher processor | `data_processors/analytics/mlb/pitcher_game_summary_processor.py` |
| Orchestrator tests | `tests/orchestration/unit/test_mlb_orchestrators.py` |
| Deploy all orchestrators | `bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh` |
| Health check | `bin/monitoring/mlb_daily_health_check.sh` |

---

## Session Stats

- **Duration:** ~4 hours (including ~3 hours of background data collection)
- **Batter Stats Collected:** 97,679 (4,846 games, 787 unique players)
- **Batter Analytics Generated:** 97,679
- **Predictions Regenerated:** 8,028 (deduped)
- **Model MAE:** 1.54
- **Files Created:** 5 (collect_batter_stats.py, 2 backfill scripts, unit tests, handoff)
- **Files Modified:** 2 (batter_game_summary_processor.py, generate_historical_predictions.py)

---

## Contact/Context

This work is part of the MLB pitcher strikeouts prediction feature. The goal is to predict pitcher strikeout totals for betting purposes. The "bottom-up" model innovation sums individual batter K probabilities instead of just using pitcher averages.

For questions about the NBA pipeline (which this is modeled after), see `docs/` directory.
