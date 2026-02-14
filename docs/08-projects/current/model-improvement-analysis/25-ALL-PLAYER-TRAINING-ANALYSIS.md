# 25: All-Player Training Analysis — Line Coverage & Performance Impact

**Session:** 241
**Date:** 2026-02-13
**Status:** Analysis complete, no model changes made

## Purpose

Investigate the impact of including players WITHOUT prop lines in V9 training data. The `--include-no-line` flag was added to `quick_retrain.py` to surface line coverage diagnostics.

**Key question:** Does the V9 model already train on no-line players, and if so, what does performance look like on the full population?

## Discovery: Training Already Includes All Players

The `load_train_data()` function in `quick_retrain.py` calls `load_clean_training_data()` which JOINs `ml_feature_store_v2` with `player_game_summary`. It does NOT filter by whether a player has prop lines. **Training has always included all quality-ready players.**

The `--include-no-line` flag simply surfaces the breakdown:

```
Line coverage in training data (--include-no-line):
  Total players:    9,629
  With prop lines:  6,146 (63.8%)
  Without lines:    3,483 (36.2%)
  NOTE: Training already includes ALL quality-ready players (lines not required).
```

**36.2% of training data comes from players without prop lines.** The model has always been learning from these players — we just never measured it before.

## Experiment Setup

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "ALL_PLAYER_LINE_DIAG" \
    --include-no-line \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register
```

- **Training:** 9,629 samples (Nov 2, 2025 - Jan 31, 2026)
- **Evaluation:** 650 samples with lines, 1,621 total (Feb 1-12, 2026)
- **Model:** V9 (33 features, CatBoost, default hyperparameters)
- **No deployment.** `--skip-register` used. Production model untouched.

## Results

### MAE (Point Prediction Accuracy)

| Population | MAE | N | Notes |
|-----------|-----|---|-------|
| With lines only | 4.90 | 650 | Standard eval — players with prop lines |
| **All players** | **4.52** | **1,621** | Includes 971 without lines |
| V9 Baseline | 5.14 | — | Production champion reference |

**Full-population MAE is 0.38 lower than with-lines MAE.** This makes sense — no-line players are typically bench players with lower, more predictable scoring (avg predicted: 6.8 pts). The model predicts bench players well because their scoring patterns are consistent.

### Hit Rate (Betting Accuracy)

| Metric | Result | V9 Baseline | Delta |
|--------|--------|-------------|-------|
| HR All | 56.74% | 54.53% | +2.21% |
| HR Edge 3+ | 69.23% | 63.72% | +5.51% |
| HR Edge 5+ | 100.00% | 75.33% | +24.67% |

**Caveat:** Edge 3+ n=13, Edge 5+ n=1. Sample sizes are too low for statistical significance. The governance gate correctly flagged this: `[FAIL] Hit rate (3+) sample >= 50: n=13`.

### Walk-Forward Evaluation (Per-Week)

| Week | N | MAE | HR All | HR 3+ | HR 5+ | Bias |
|------|---|-----|--------|-------|-------|------|
| Jan 26 - Feb 1 | 111 | 4.37 | 58.8% | 100.0% | N/A | -0.04 |
| Feb 2 - Feb 8 | 367 | 5.13 | 59.2% | 62.5% | 100.0% | -0.15 |
| Feb 9 - Feb 15 | 172 | 4.75 | 50.0% | 66.7% | N/A | -0.09 |

Week 3 (Feb 9-15) shows HR All dropping to 50% — consistent with the known champion model decay pattern (35+ days stale).

### Feature Importance (Top 10)

| Rank | Feature | Importance |
|------|---------|-----------|
| 1 | vegas_points_line | 29.38% |
| 2 | vegas_opening_line | 11.05% |
| 3 | points_avg_last_5 | 9.21% |
| 4 | points_avg_season | 7.49% |
| 5 | points_avg_last_10 | 6.35% |
| 6 | minutes_avg_last_10 | 3.28% |
| 7 | avg_points_vs_opponent | 3.03% |
| 8 | vegas_line_move | 2.58% |
| 9 | points_std_last_10 | 2.46% |
| 10 | pct_three | 2.16% |

Vegas features still dominate (42.01% combined). The model learns from no-line players' non-vegas features and applies that knowledge when vegas data is available for line players.

### Tier Bias

| Tier | Bias | N |
|------|------|---|
| Stars (25+) | -0.40 | 49 |
| Starters (15-24) | -0.01 | 165 |
| Role (5-14) | -0.36 | 406 |
| Bench (<5) | -1.86 | 30 |

Slight under-prediction across all tiers. Bench bias is -1.86 (on a ~5 point average, that's proportionally significant but absolute value is small).

### Governance Gates

| Gate | Result | Value |
|------|--------|-------|
| MAE improvement | PASS | 4.90 vs 5.14 |
| HR 3+ >= 60% | PASS | 69.23% |
| HR 3+ sample >= 50 | **FAIL** | n=13 |
| Vegas bias +/- 1.5 | PASS | -0.12 |
| No critical tier bias | PASS | All < +/- 5 |
| Directional balance | PASS | OVER 75%, UNDER 66.7% |

## What We Did in Session 241

### 1. V9 NO_PROP_LINE Backfill (Completed)
- Created `bin/backfill-v9-no-line-predictions.py`
- Backfilled **904 predictions** across 12 dates (Feb 1-12)
- All are `line_source='NO_PROP_LINE'`, `recommendation='NO_LINE'`
- Coverage now: ~150-340 total V9 predictions per game day (was ~100-170)

### 2. V9 Re-prediction on Enrichment (Deployed)
- When enrichment adds prop lines to predictions, V9 now re-predicts
- `vegas_points_line` (feature #25) changes from NaN to real value
- New `/line-update` coordinator endpoint handles supersede + regenerate
- `LINE_UPDATE` quality gate mode bypasses "Predict Once, Never Replace"
- Will activate automatically on next game day (enrichment runs 18:40 UTC)

### 3. `--include-no-line` Training Diagnostics (Completed)
- Added to `quick_retrain.py` and documented in SKILL.md
- Reports line coverage stats: 63.8% with lines, 36.2% without
- Confirmed training already includes all players — no behavior change

### 4. Grading Backfill (Pending)
- First attempt failed due to Firestore lock timeout (transient)
- Needs manual retry:
  ```bash
  PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
      --start-date 2026-02-01 --end-date 2026-02-12
  ```

## Key Takeaways

1. **Training already includes no-line players (36.2%).** The `--include-no-line` flag is diagnostic only — it doesn't change training behavior.

2. **Full-population MAE (4.52) < with-lines MAE (4.90).** Bench players are easier to predict. The model generalizes well to the full player pool.

3. **Hit rate sample sizes too small (n=13 edge 3+) for this eval window.** Need longer eval or more game days to draw conclusions.

4. **Vegas features remain dominant (42% importance).** The re-prediction on enrichment (Task 1) is justified — when vegas data arrives, predictions should change materially.

5. **No model was changed or deployed.** This was a diagnostic experiment with `--skip-register`. The production champion (`catboost_v9_33features_20260201_011018.cbm`) is untouched.

## Next Steps

- [ ] Retry grading backfill (Firestore lock timeout was transient)
- [ ] Verify enrichment re-prediction works on next game day
- [ ] Monitor `/line-update` endpoint in coordinator logs
- [ ] Consider longer eval window for hit rate analysis (need 50+ edge 3+ picks)
