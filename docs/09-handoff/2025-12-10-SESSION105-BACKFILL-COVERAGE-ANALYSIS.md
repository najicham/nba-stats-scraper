# Session 105: Backfill Coverage Analysis and Root Cause Identification

**Date:** 2025-12-10
**Status:** ROOT CAUSES IDENTIFIED, FIX IN PROGRESS

---

## Executive Summary

Deep analysis of Nov-Dec 2021 backfill revealed significant coverage gap between November (98.9%) and December (64.2%). Root cause identified: MLFS processor uses forward-looking player data (`upcoming_player_game_context`) instead of actual played data (`player_game_summary`) for historical dates.

---

## Coverage Analysis Results

### Overall Coverage

| Month | Dates | Players Played | Players Predicted | Coverage |
|-------|-------|----------------|-------------------|----------|
| November | 24 | 458 | 453 | **98.9%** |
| December | 30 | 553 | 355 | **64.2%** |

### Daily Coverage Pattern

**November (post-bootstrap):** 100% coverage on all dates
```
Nov 6-30: Every player who played got predictions
```

**December:** Coverage drops to 33-80% depending on date
```
Worst dates:
- Dec 30: 33.3% (29/87 players)
- Dec 19: 42.6% (80/188 players)
- Dec 22: 43.6% (61/140 players)
- Dec 29: 45.2% (85/188 players)
```

---

## Root Causes Identified

### Root Cause #1: MLFS Uses Wrong Data Source for Backfill (PRIMARY ISSUE)

**Location:** `data_processors/precompute/ml_feature_store/feature_extractor.py:54-81`

**Problem:**
```python
def get_players_with_games(self, game_date: date) -> List[Dict[str, Any]]:
    query = f"""
    SELECT player_lookup, ...
    FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`  # <-- WRONG FOR BACKFILL
    WHERE game_date = '{game_date}'
    """
```

**Why This Matters:**
- `upcoming_player_game_context`: Forward-looking (who is EXPECTED to play)
- `player_game_summary`: Backward-looking (who ACTUALLY played)

**Impact on Dec 1, 2021:**
| Data Source | Players |
|-------------|---------|
| `upcoming_player_game_context` | 174 |
| `player_game_summary` | 190 |
| **Missing players** | **16** |

**Missing Star Players:**
- Luka Doncic (16 prior games)
- Nikola Jokic (15 prior games)
- Joel Embiid (11 prior games)
- Tyler Herro (18 prior games)
- Jaylen Brown (12 prior games)

These stars PLAYED on Dec 1 but weren't in `upcoming_player_game_context`, so they have NO MLFS features and NO predictions.

### Root Cause #2: COVID Protocols (December 2021)

**Context:** December 2021 was the Omicron wave peak in the NBA.

**Impact on Data:**
- 48+ game gaps >7 days in player schedules
- Maximum gap: 21 days (players in health protocols)
- PDC processor's `INCOMPLETE_DATA` check fails for irregular schedules

**Failure Breakdown:**
```sql
-- PDC failures in December (all INCOMPLETE_DATA)
Dec 1:  51 failures
Dec 8:  68 failures
Dec 15: 50 failures
Dec 23: 40 failures
```

**Note:** These players still got PCF and MLFS features, so this is NOT blocking predictions. The INCOMPLETE_DATA failure is informational.

### Root Cause #3: Prediction Script Correctly Filters Non-Players

**Behavior:** 33 players on Dec 1 have MLFS features but NO predictions.

**Reason:** These 33 players were EXPECTED to play (in `upcoming_player_game_context`) but did NOT actually play on Dec 1. The prediction backfill script correctly queries `player_game_summary` for who to predict.

**Verdict:** This is CORRECT behavior. No fix needed.

---

## Data Flow Diagram

```
For Real-Time (Daily) Predictions:
  upcoming_player_game_context → MLFS → Predictions
  (expected players)            (features)

For Backfill (Historical) Predictions:
  upcoming_player_game_context → MLFS → Predictions ← player_game_summary
  (expected players)            (features)            (actual players)
                                   ↓
                        MISMATCH: Features generated for expected players
                                  but predictions only for actual players
```

**The Fix:**
```
For Backfill (Historical) Predictions:
  player_game_summary → MLFS → Predictions ← player_game_summary
  (actual players)     (features)            (actual players)
                                ↓
                    MATCH: Features and predictions aligned
```

---

## Fix Required

### Option A: Add Backfill Mode to MLFS Feature Extractor (RECOMMENDED)

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

**Change:**
```python
def get_players_with_games(self, game_date: date, backfill_mode: bool = False) -> List[Dict[str, Any]]:
    if backfill_mode:
        # For historical dates, use actual played data
        query = f"""
        SELECT player_lookup, universal_player_id, game_id, game_date,
               opponent_team_abbr, home_game AS is_home, days_rest,
               FALSE AS has_prop_line, NULL AS current_points_line
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date = '{game_date}'
        ORDER BY player_lookup
        """
    else:
        # For real-time, use expected players
        query = f"""
        SELECT player_lookup, ...
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{game_date}'
        """
```

**Also Update:**
- `ml_feature_store_processor.py`: Pass `backfill_mode` flag
- Add CLI argument `--backfill-mode` to processor

### After Fix: Re-run Backfill

1. Re-run MLFS for December 2021:
```bash
PYTHONPATH=. .venv/bin/python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor \
  --start-date 2021-12-01 --end-date 2021-12-31 --backfill-mode
```

2. Re-run Phase 5 predictions for December:
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-12-01 --end-date 2021-12-31 --skip-preflight
```

---

## Validation Queries

### Check Current Coverage Gap
```sql
SELECT
  CASE WHEN game_date < '2021-12-01' THEN 'November' ELSE 'December' END as month,
  COUNT(DISTINCT p.player_lookup) as played,
  COUNT(DISTINCT pred.player_lookup) as predicted,
  ROUND(COUNT(DISTINCT pred.player_lookup) * 100.0 / COUNT(DISTINCT p.player_lookup), 1) as coverage_pct
FROM nba_analytics.player_game_summary p
LEFT JOIN nba_predictions.player_prop_predictions pred
  ON p.game_date = pred.game_date AND p.player_lookup = pred.player_lookup
WHERE p.game_date >= '2021-11-01' AND p.game_date <= '2021-12-31'
GROUP BY 1;
```

### Check Missing Star Players
```sql
WITH pgs AS (
  SELECT DISTINCT player_lookup
  FROM nba_analytics.player_game_summary
  WHERE game_date = '2021-12-01'
),
mlfs AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = '2021-12-01'
)
SELECT p.player_lookup,
  (SELECT COUNT(*) FROM nba_analytics.player_game_summary
   WHERE player_lookup = p.player_lookup AND game_date < '2021-12-01') as games_before
FROM pgs p
LEFT JOIN mlfs m ON p.player_lookup = m.player_lookup
WHERE m.player_lookup IS NULL
ORDER BY games_before DESC;
```

### Verify After Fix
```sql
-- Should return 0 after fix
SELECT COUNT(*) as missing_mlfs
FROM nba_analytics.player_game_summary p
LEFT JOIN nba_predictions.ml_feature_store_v2 m
  ON p.game_date = m.game_date AND p.player_lookup = m.player_lookup
WHERE p.game_date = '2021-12-01'
  AND m.player_lookup IS NULL;
```

---

## Session 104 → 105 Progress

| Item | S104 Status | S105 Status |
|------|-------------|-------------|
| P1: Confidence scale fix | PENDING | **COMPLETE** (commit `6bccfdd`) |
| P2: Extend backfill Jan-Apr | PENDING | PENDING |
| Coverage analysis | - | **COMPLETE** |
| Root cause identification | - | **COMPLETE** |
| MLFS backfill mode fix | - | **IN PROGRESS** |

---

## Files Modified This Session

1. `predictions/worker/data_loaders.py` - Fixed `normalize_confidence()` to output 0-1 scale

## Commits This Session

1. `6bccfdd` - fix: Normalize confidence scores to 0-1 scale instead of 0-100

---

## Next Steps

1. **Implement backfill mode in MLFS** (this session)
2. Re-run MLFS for December 2021
3. Re-run Phase 5 predictions for December
4. Validate coverage reaches ~100%
5. Consider extending to Jan-Apr 2022
