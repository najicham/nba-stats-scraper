# Session 294 Handoff — Prop Line Delta Signal, Anti-Pattern Pre-Filters, Feature f54

**Date:** 2026-02-18
**Previous:** Session 293 — Feature store validation, Feb collapse diagnosis, streak signal discovery

## Summary

1. Implemented `prop_line_drop_over` signal — line dropped 3+ from previous game + OVER = 72.2% HR (N=370)
2. Added 3 UNDER anti-pattern pre-filters to aggregator — blocks 101 picks at 17.8% HR, +$6,664 P&L
3. Added `prop_line_delta` (f54) to feature store — 55 features now
4. Backtested 6 new streak/momentum ideas — found neg +/- streak UNDER catastrophe (13.1% HR)
5. Ran combination backtests — FG cold + line drop + OVER = 84.6% HR (N=13)

## Current State

| Component | Status |
|-----------|--------|
| Production model | `catboost_v9_33f_train20251102-20260205` — 14 days old, DEGRADING in Feb |
| Feature store | **55 features** (f54 added, BQ column created, not yet backfilled) |
| Signal count | **19 active** (18 + prop_line_drop_over) |
| Pre-filters | **8 total** (5 existing + 3 new UNDER anti-patterns) |
| Games | Resume Feb 19 — All-Star break ends |
| Code | Committed (`441cf4cc`, `2264798d`), **not yet pushed** |

## Start Here

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-18-SESSION-294-HANDOFF.md

# 2. Push to deploy (if not already pushed)
git push origin main

# 3. Check post-All-Star model performance (games resume Feb 19)
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT system_id,
  COUNTIF(ABS(predicted_margin) >= 3) as edge3,
  ROUND(100.0 * COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct) / NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as hr_edge3
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-02-19'
GROUP BY 1 HAVING COUNTIF(ABS(predicted_margin) >= 3) >= 3
ORDER BY hr_edge3 DESC"

# 4. Backfill f54 for training window (prerequisite for retrain with new feature)
# See "Backfill f54" section below

# 5. Retrain when eval data available (Feb 21+)
./bin/retrain.sh --promote --eval-days 3
```

---

## What Was Implemented

### 1. New Signal: `prop_line_drop_over`

**File:** `ml/signals/prop_line_drop_over.py`

Triggers when OVER recommendation + player's prop line dropped 3+ points from their previous game. The market drops lines reactively after bad games, creating OVER value when players revert to mean.

| Metric | Value |
|--------|-------|
| Tag | `prop_line_drop_over` |
| Direction | OVER only |
| HR (edge 3+) | **72.2%** (N=370) |
| Confidence | 0.90 (scales +0.05 per point above 3) |
| Data source | `prop_line_stats` in supplemental data |

Registered in `ml/signals/registry.py`. Now 19 active signals.

### 2. Three UNDER Anti-Pattern Pre-Filters

All added to `ml/signals/aggregator.py`. Algorithm version bumped to `v294_prop_line_delta`.

| Filter | Blocks | HR (edge 3+) | N | Mechanism |
|--------|--------|-------------|---|-----------|
| UNDER + line jumped 3+ | UNDER when market raised line sharply | 47.4% | 627 | Market overreacted to big game |
| UNDER + line dropped 3+ | UNDER when market already priced decline | 41.0% | 188 | Double-declining, already priced in |
| UNDER + neg +/- streak 3+ | UNDER when player in losing lineups | 13.1% | 84 | Bounce-back candidates, not decliners |

**Combined impact (P&L simulation):** Blocks 101 picks at 17.8% HR. Converts edge-3+ pool from -$5,718 to +$946 (+$6,664 improvement).

**Important correction:** Session 293 originally proposed blocking OVER + line jumped 3+ (citing 28.6% HR). Our large-N backtest found OVER + jumped = 56.8-64.9% HR (profitable). The correct filter blocks UNDER + jumped, which is 47.4% HR (below breakeven). Fixed in commit `2264798d`.

### 3. Feature f54: `prop_line_delta`

**Added to:**
- `shared/ml/feature_contract.py` — index 54, version `v2_55features`
- `data_processors/precompute/ml_feature_store/feature_extractor.py` — batch extraction from `odds_api_player_points_props`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` — wired into feature vector
- `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` — schema + ALTER TABLE
- BQ column `feature_54_value` created via ALTER TABLE

**Properties:**
- Value: `current_game_line - previous_game_line` (negative = line dropped)
- Source: consensus (median) line from `odds_api_player_points_props`, latest snapshot per bookmaker
- Lookback: 14 days max for previous game
- Optional feature (won't block predictions if missing)
- Default: 0.0 (no change)

**NOT YET BACKFILLED.** Must backfill before retraining with this feature.

### 4. Supplemental Data Updates

**File:** `ml/signals/supplemental_data.py`

Added two data sources for the aggregator:

1. **Prop line delta** — CTE `prev_prop_lines` queries most recent previous line per player. Populates `supp['prop_line_stats']` and `pred['prop_line_delta']`.

2. **Plus/minus streak** — `neg_pm_1/2/3` LAG columns from `player_game_summary.plus_minus`. Computes consecutive negative +/- count and populates `pred['neg_pm_streak']`.

---

## Backtest Results (Session 294)

### Prop Line Delta (largest N signal found)

| Pattern | Direction | HR (edge 3+) | N | Avg Over Line |
|---------|-----------|-------------|---|---------------|
| **Line dropped 3+** | **OVER** | **72.2%** | **370** | **+6.9** |
| Line stable | OVER | 56.6% | 2,087 | +1.9 |
| Line jumped 3+ | OVER | 64.9% | 77 | +2.7 |
| Line stable | UNDER | 56.4% | 5,041 | -0.8 |
| Line jumped 3+ | UNDER | 47.4% | 627 | -0.6 |
| Line dropped 3+ | UNDER | 41.0% | 188 | +2.0 |

### Signal Combinations

| Combo | Direction | HR | N |
|-------|-----------|-----|---|
| FG cold + line drop | OVER | **84.6%** | 13 |
| Line drop only | OVER | **79.2-82.9%** | 41-53 |
| 3PT cold + line drop | OVER | **80.0%** | 5 |
| Triple confirm (FG+3PT+line) | OVER | **70.0%** | 10 |
| Line drop + neg PM | OVER | **78.8%** | 33 |
| neg_3+ streak | UNDER | **13-15%** | 72-84 |

### Streak/Momentum Backtests

| Pattern | Direction | HR | N | Actionable? |
|---------|-----------|-----|---|-------------|
| neg +/- 3+ games | UNDER | **13.1%** | 84 | **Yes — pre-filter implemented** |
| EFG cold 1 game | OVER | 81.4% | 43 | Monitor (small N) |
| 3PA volume drop | BOTH | 82.4% | 34 | Monitor (very small N) |
| High TO 2 games | OVER | 71.4% | 14 | Too small |
| Low self-creation | UNDER | 22.2% | 36 | Monitor (small N) |

---

## What's Next (Priority Order)

### 1. Push and Deploy (Immediate)

```bash
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

The new signal and pre-filters will be active for games resuming Feb 19.

### 2. Check Post-All-Star Performance (Feb 19+)

```bash
# Run after games are played and graded
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT system_id,
  COUNTIF(ABS(predicted_margin) >= 3) as edge3,
  ROUND(100.0 * COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct) / NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as hr_edge3
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-02-19'
GROUP BY 1 HAVING COUNTIF(ABS(predicted_margin) >= 3) >= 3
ORDER BY hr_edge3 DESC"
```

If V12 or Q45 continue outperforming V9 champion, consider promoting before retrain.

### 3. Backfill f54 for Training Window

The `prop_line_delta` feature needs backfilling across the training window (Nov 2 - present) before it can be used in model training. The batch extractor queries `odds_api_player_points_props` which has data going back to season start.

```bash
# Option A: Run Phase 4 reprocessing for each date
# This will populate feature_54_value for existing feature store rows
# Note: This will be slow (1 date at a time)

# Option B: Direct BQ backfill (faster)
bq query --use_legacy_sql=false --project_id=nba-props-platform "
WITH daily_consensus AS (
  SELECT player_lookup, game_date,
    APPROX_QUANTILES(points_line, 2)[OFFSET(1)] as consensus_line
  FROM (
    SELECT player_lookup, game_date, bookmaker, points_line,
      ROW_NUMBER() OVER (PARTITION BY player_lookup, game_date, bookmaker ORDER BY snapshot_timestamp DESC) as rn
    FROM nba_raw.odds_api_player_points_props
    WHERE game_date >= '2025-10-22' AND points_line IS NOT NULL AND points_line > 0
  )
  WHERE rn = 1
  GROUP BY player_lookup, game_date
),
with_delta AS (
  SELECT player_lookup, game_date,
    consensus_line - LAG(consensus_line) OVER (PARTITION BY player_lookup ORDER BY game_date) as line_delta
  FROM daily_consensus
)
UPDATE nba_predictions.ml_feature_store_v2 fs
SET feature_54_value = ROUND(d.line_delta, 1)
FROM with_delta d
WHERE fs.player_lookup = d.player_lookup
  AND fs.game_date = d.game_date
  AND d.line_delta IS NOT NULL
  AND fs.game_date >= '2025-11-02'"
```

### 4. Retrain with New Features (Feb 21+)

Once 2-3 days of eval data exists:

```bash
# Option A: Quick retrain (current features, fresh window)
./bin/retrain.sh --promote --eval-days 3

# Option B: Retrain with f54 (after backfill)
# Will require updating V9 contract to 34 features or training V12+f54
```

### 5. Add Shooting Bounce-Back Signal (Deferred)

Create `shooting_bounce_back` signal: FG% or 3PT% cold streak >= 2 going into game, direction OVER. Expected 58-65% HR. Session 293 validated the underlying patterns.

### 6. Add More Streak Features (Deferred)

Candidates for f55-f57:
- `fg_cold_streak_going_in` (int, 0-10) — 63.8% OVER HR at 3+ games
- `three_pt_cold_streak_going_in` (int, 0-10) — 64.6% OVER HR at 3+ games
- `neg_pm_streak` (int, 0-5) — blocks 13.1% HR UNDER picks

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/prop_line_drop_over.py` | **NEW** — prop line drop OVER signal |
| `ml/signals/registry.py` | Register new signal (19 total) |
| `ml/signals/aggregator.py` | 3 UNDER pre-filters, version bump to v294 |
| `ml/signals/supplemental_data.py` | Prop line delta CTE + neg PM streak LAGs |
| `shared/ml/feature_contract.py` | f54, version v2_55features, optional |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Batch extraction for f54 |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Wire f54 into feature vector |
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | Schema for feature_54_value |
| `docs/08-projects/current/streak-momentum-signals/00-BACKTEST-RESULTS.md` | Session 294 results |

## Commits

```
441cf4cc feat: prop line delta signal, 3 anti-pattern pre-filters, f54 feature
2264798d fix: correct line-jumped pre-filter to block UNDER not OVER
```

## Known Issues (Do NOT Investigate)

- f4 (411 bugs): upstream cache gap, blocked by quality gates
- f32 (524 bugs): bench player PPM gap, expected
- f5-f8 (18 bugs each): specific player-date composite factor gaps
- f54 not backfilled: feature store column exists but NULL for historical dates
- `features` array column: deprecated, dual-written, removal deferred
- V9 champion at 36.7% Feb HR: known, shadow models outperform, retrain pending

## Key Lesson

**Always validate anti-pattern directions with large-N backtests.** Session 293 proposed blocking OVER + line jumped 3+ (28.6% HR from a smaller subset). Our N=627 backtest showed OVER + jumped = 56.8-64.9% (profitable). The actual anti-pattern is UNDER + jumped = 47.4%. Cross-reference multiple backtest windows before committing a filter.
