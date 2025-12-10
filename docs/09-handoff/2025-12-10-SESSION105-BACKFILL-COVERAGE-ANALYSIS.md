# Session 105: Backfill Coverage Analysis and MLFS Fix

**Date:** 2025-12-10
**Status:** FIX IMPLEMENTED AND TESTED - Ready for December Re-backfill

---

## Executive Summary

Deep analysis of Nov-Dec 2021 backfill revealed a 35% coverage gap in December (64% vs 99% in November). Root cause identified and fixed: MLFS processor used forward-looking player data instead of actual played data for historical backfills. Fix tested on Dec 1 - coverage increased from 174 to 190 players (100%).

---

## Work Completed This Session

### 1. Confidence Scale Fix (from S104)
**Status:** COMPLETE
**Commit:** `6bccfdd`

- Changed `normalize_confidence()` to output 0-1 scale instead of 0-100
- Fixed 40 bad records in BigQuery via UPDATE

### 2. Root Cause Analysis
**Status:** COMPLETE

Identified why December coverage was 64% vs November's 99%:
- MLFS queried `upcoming_player_game_context` (expected players)
- Should query `player_game_summary` (actual players) for backfill
- Stars like Luka, Jokic, Herro were missing because they weren't in expected roster

### 3. MLFS Backfill Mode Fix
**Status:** COMPLETE
**Commit:** `e4e31c0`

Added `backfill_mode` parameter to `get_players_with_games()`:
- `feature_extractor.py`: New query path for backfill mode
- `ml_feature_store_processor.py`: Passes `backfill_mode` to all 3 call sites

### 4. Fix Verification (Dec 1 Test)
**Status:** COMPLETE

| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| MLFS players | 174 | 223 |
| Players who played | 190 | 190 |
| Missing players | 16 | **0** |

---

## Current Data State

### Prediction Quality (Nov-Dec 2021)
| System | MAE | Predictions | Notes |
|--------|-----|-------------|-------|
| ensemble_v1 | 4.45 | 7,013 | Best performer |
| xgboost_v1 | 4.47 | 7,013 | Very good |
| moving_average | 4.58 | 7,013 | Good |
| similarity_balanced_v1 | 4.79 | 6,088 | Good |
| zone_matchup_v1 | 5.58 | 7,013 | Acceptable |

### Data Integrity
| Check | Status |
|-------|--------|
| NULL game_id | 0 ✅ |
| Bad confidence (>1 or <0) | 0 ✅ |
| Negative predicted_points | 0 ✅ |
| Duplicates | 0 ✅ |

### Coverage Gap (To Be Fixed)
10 December dates have <70% coverage (will be fixed by re-running backfill):

| Date | Current Coverage | After Fix |
|------|------------------|-----------|
| Dec 30 | 33.3% | ~100% |
| Dec 19 | 42.6% | ~100% |
| Dec 22 | 43.6% | ~100% |
| Dec 29 | 45.2% | ~100% |
| Dec 14 | 50.6% | ~100% |
| Dec 31 | 53.4% | ~100% |
| Dec 20 | 54.3% | ~100% |
| Dec 27 | 56.2% | ~100% |
| Dec 28 | 58.6% | ~100% |
| Dec 16 | 58.7% | ~100% |

---

## Technical Details

### Root Cause: Wrong Data Source for Backfill

**Before (Bug):**
```
MLFS Processor
    └── get_players_with_games()
            └── queries: upcoming_player_game_context (174 expected players)
                         ↓
                    Missing 16 who actually played!
```

**After (Fixed):**
```
MLFS Processor (backfill_mode=True)
    └── get_players_with_games(backfill_mode=True)
            └── queries: player_game_summary (190 actual players)
                         ↓
                    All players who played get features!
```

### Code Changes

**File: `data_processors/precompute/ml_feature_store/feature_extractor.py`**
```python
def get_players_with_games(self, game_date: date, backfill_mode: bool = False):
    if backfill_mode:
        # Query player_game_summary (actual players)
        query = """SELECT ... FROM player_game_summary WHERE game_date = ..."""
    else:
        # Query upcoming_player_game_context (expected players)
        query = """SELECT ... FROM upcoming_player_game_context WHERE game_date = ..."""
```

**File: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`**
- Line 329: `get_players_with_games(analysis_date, backfill_mode=self.is_backfill_mode)`
- Line 467: `get_players_with_games(analysis_date, backfill_mode=self.is_backfill_mode)`
- Line 614: `get_players_with_games(analysis_date, backfill_mode=self.is_backfill_mode)`

---

## Next Steps: Re-run December Backfill

### Step 1: Re-run MLFS for December
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-12-02 --end-date 2021-12-31
```
**Expected time:** ~10-15 minutes
**Expected result:** All December dates will have MLFS features for ALL players who played

### Step 2: Re-run Predictions for December
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-12-01 --end-date 2021-12-31 --skip-preflight
```
**Expected time:** ~10-15 minutes
**Expected result:** December prediction coverage increases from 64% to ~100%

### Step 3: Validate Results
```bash
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date 2021-12-01 --end-date 2021-12-31 --details
```

### Validation Query
```sql
-- After re-backfill, this should show ~100% coverage for all dates
SELECT
  game_date,
  COUNT(DISTINCT pgs.player_lookup) as played,
  COUNT(DISTINCT pred.player_lookup) as predicted,
  ROUND(COUNT(DISTINCT pred.player_lookup) * 100.0 / COUNT(DISTINCT pgs.player_lookup), 1) as coverage_pct
FROM nba_analytics.player_game_summary pgs
LEFT JOIN nba_predictions.player_prop_predictions pred
  ON pgs.game_date = pred.game_date AND pgs.player_lookup = pred.player_lookup
WHERE pgs.game_date >= '2021-12-01' AND pgs.game_date <= '2021-12-31'
GROUP BY game_date
ORDER BY coverage_pct
LIMIT 10;
```

---

## Session Progress

### Session 104 → 105 Completed Items

| Item | S104 Status | S105 Status |
|------|-------------|-------------|
| P1: Confidence scale fix | PENDING | ✅ COMPLETE |
| Coverage analysis | - | ✅ COMPLETE |
| Root cause identification | - | ✅ COMPLETE |
| MLFS backfill mode fix | - | ✅ COMPLETE |
| Fix verification (Dec 1) | - | ✅ COMPLETE |
| December re-backfill | - | PENDING |

### Commits This Session
1. `6bccfdd` - fix: Normalize confidence scores to 0-1 scale instead of 0-100
2. `e4e31c0` - feat: Add backfill mode to MLFS for 100% player coverage

---

## Files Modified

| File | Change |
|------|--------|
| `predictions/worker/data_loaders.py` | Fixed `normalize_confidence()` to output 0-1 |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Added `backfill_mode` parameter |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Passes `backfill_mode` to feature extractor |

---

## Future Improvements (Optional)

### 1. Extend Backfill to Jan-Apr 2022
The 2021-22 season continues through April 2022. After December is complete:
```bash
# Phase 4
./bin/backfill/run_phase4_backfill.sh --start-date 2022-01-01 --end-date 2022-04-30

# Phase 5
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2022-01-01 --end-date 2022-04-30 --skip-preflight
```

### 2. Add Backfill Mode to Daily Worker
Currently only the backfill script has `backfill_mode`. Consider if daily worker needs similar handling for edge cases.

---

## Key Learnings

1. **Forward-looking vs Backward-looking Data:** For historical backfills, always use actual outcome data (`player_game_summary`) not expected/projected data (`upcoming_player_game_context`).

2. **COVID Protocol Impact:** December 2021 (Omicron wave) caused many unexpected roster changes, making the forward-looking data especially unreliable for that period.

3. **Test on Representative Dates:** Testing on Dec 1 (which had the coverage issue) immediately validated the fix.
