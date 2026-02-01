# Historical Feature Cleanup: team_win_pct Fix

**Created:** 2026-02-01 (Session 68)
**Status:** SCRIPT READY - Awaiting Execution
**Priority:** Medium (enables cross-season training)

---

## Problem Summary

The `team_win_pct` feature (index 24) in `ml_feature_store_v2` is stuck at 0.5 for the entire 2024-25 season (~25K records). This prevents using historical data for ML training.

| Season | Records | Stuck at 0.5 | Impact |
|--------|---------|--------------|--------|
| 2024-25 | ~25,000 | 100% | Cannot train on last season |
| 2025-26 (Nov+) | ~15,000 | 0% | Fixed in production |

**Root Cause:** The feature calculator wasn't receiving `team_season_games` data, so it defaulted to 0.5.

---

## Solution

A fix script has been created that:
1. Computes correct `team_win_pct` from `bdl_player_boxscores` (has team scores)
2. Updates `ml_feature_store_v2.features[24]` with corrected values

**Script Location:** `backfill_jobs/feature_store/fix_team_win_pct.py`

---

## Important Notes

### Bootstrap Period Handling

The script correctly handles early-season games:
- Games with < 5 team games played → Default to 0.5
- This is intentional and matches production behavior

### Verified Working

Dry run on Nov 1-15, 2024 showed:
- 1,729 records with team_win_pct = 0.5
- 1,576 would be fixed to realistic values (0.1-1.0)
- 153 correctly remain at 0.5 (bootstrap period)

---

## Execution Instructions

### Step 1: Dry Run (Verify)

```bash
# Test on a small date range first
PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
    --start-date 2024-11-01 --end-date 2024-11-30 --dry-run
```

Expected output:
- Distribution of new values (should be 0.1-1.0)
- Count of records to be fixed
- Sample fixes showing player_lookup, date, old→new values

### Step 2: Execute Fix (Month by Month Recommended)

```bash
# November 2024
PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
    --start-date 2024-11-01 --end-date 2024-11-30

# December 2024
PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
    --start-date 2024-12-01 --end-date 2024-12-31

# January 2025
PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
    --start-date 2025-01-01 --end-date 2025-01-31

# February 2025
PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
    --start-date 2025-02-01 --end-date 2025-02-28

# March 2025
PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
    --start-date 2025-03-01 --end-date 2025-03-31

# April 2025
PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
    --start-date 2025-04-01 --end-date 2025-04-30

# May-June 2025 (playoffs)
PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
    --start-date 2025-05-01 --end-date 2025-06-22
```

### Step 3: Verify Fix

```sql
-- Check team_win_pct distribution after fix
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as records,
  COUNTIF(CAST(features[OFFSET(24)] AS FLOAT64) = 0.5) as at_0_5,
  ROUND(100.0 * COUNTIF(CAST(features[OFFSET(24)] AS FLOAT64) = 0.5) / COUNT(*), 1) as pct_at_0_5,
  ROUND(AVG(CAST(features[OFFSET(24)] AS FLOAT64)), 3) as avg_win_pct,
  ROUND(STDDEV(CAST(features[OFFSET(24)] AS FLOAT64)), 3) as stddev
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2024-10-22' AND game_date <= '2025-06-22'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1
```

**Expected after fix:**
- `pct_at_0_5` should be < 10% (only early season bootstrap games)
- `avg_win_pct` should be ~0.5 (league average)
- `stddev` should be ~0.15-0.20 (realistic spread)

---

## Technical Details

### Data Source for Correct Values

```sql
-- bdl_player_boxscores has team scores
SELECT DISTINCT
  game_id, game_date,
  home_team_abbr, away_team_abbr,
  home_team_score, away_team_score
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= '2024-10-22'
```

### Why Not Use win_flag from player_game_summary?

The `win_flag` column in `player_game_summary` is ALL FALSE (data quality issue). We use `bdl_player_boxscores` which has actual team scores.

### Update Mechanism

The script uses BigQuery MERGE to update `features[24]`:
1. Creates temp table with (player_lookup, game_date, new_features)
2. MERGE updates the entire features array
3. Cleans up temp table

---

## After Completion

### Enable Cross-Season Training

With fixed historical data, you can train on 2024-25 season:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "CROSS_SEASON_TEST" \
    --train-start 2024-11-15 --train-end 2025-04-15 \
    --eval-start 2025-11-01 --eval-end 2026-01-31
```

### Update Documentation

Mark this project as COMPLETED in README when done.

---

## Related Documents

- [V8 Training Distribution Mismatch](../ml-challenger-training-strategy/V8-TRAINING-DISTRIBUTION-MISMATCH.md) - Root cause analysis
- [Historical Feature Cleanup Plan](../ml-challenger-experiments/HISTORICAL-FEATURE-CLEANUP-PLAN.md) - Original plan
- [Experiment Variables](../ml-challenger-training-strategy/EXPERIMENT-VARIABLES.md) - Training window experiments

---

*Created: Session 68, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
