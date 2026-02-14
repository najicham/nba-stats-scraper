# 24: All-Player Predictions — Backfill, Re-prediction, and Training Results

**Session:** 241
**Date:** 2026-02-13
**Status:** Complete — backfilled, graded, experiment run, deployed

## Context

The prediction pipeline now includes ALL production-ready players (player_loader fix from Session 240). Previously, only players with prop lines (~40%) got V9 predictions due to a UPCG query filter bug.

**Key discovery: Vegas features DO affect V9 predictions.** `vegas_points_line` is feature #25 in V9's 33-feature vector. When a line arrives, the prediction changes. V12 is vegas-free — no impact.

---

## What Was Implemented

### 1. V9 NO_PROP_LINE Backfill Script (`bin/backfill-v9-no-line-predictions.py`)

Generates historical V9 predictions for players who were quality-ready but had no prop lines. Uses stored features from `ml_feature_store_v2` and produces NO_PROP_LINE predictions for MAE evaluation.

- Loads V9 model from GCS
- Queries quality-ready players missing V9 predictions
- Builds 33-feature vector (vegas features = NaN for no-line players)
- Safety: hard-coded training end dates prevent data leakage
- Supports champion and all shadow models

### 2. V9 Re-prediction on Enrichment (Deployed)

When the enrichment trigger adds prop lines to predictions, V9 predictions need regeneration because `vegas_points_line` changed from NaN to a real value.

**Flow:**
1. Enrichment processor enriches predictions with lines (existing)
2. Enrichment processor identifies V9 players that just got lines (`get_v9_players_needing_reprediction()`)
3. Enrichment trigger calls coordinator `/line-update` endpoint
4. Coordinator supersedes old predictions (`is_active=FALSE`) and generates new ones with real vegas features

**Files changed:**
- `predictions/coordinator/coordinator.py` — new `/line-update` endpoint
- `predictions/coordinator/quality_gate.py` — `LINE_UPDATE` mode (bypasses "already_has_prediction")
- `orchestration/cloud_functions/enrichment_trigger/main.py` — triggers V9 re-prediction after enrichment
- `data_processors/enrichment/.../prediction_line_enrichment_processor.py` — returns enriched player list

### 3. Training Line Coverage Flag (`--include-no-line`)

Added `--include-no-line` flag to `ml/experiments/quick_retrain.py`. Reports line coverage breakdown in training data.

**Key finding:** Training data already includes ALL quality-ready players (the training query JOINs on `player_game_summary`, not on lines). The flag reveals that 36.2% of training samples are players without prop lines — the model has always trained on these players.

### 4. Quality Gate Findings (No Code Changes Needed)

- ~20% of players per day fail quality gates (expected for low-history players)
- These are genuinely low-data players with player_history defaults
- Coverage improves naturally as players accumulate games
- Working as designed — quality gate protects prediction accuracy

---

## Backfill Results

**Executed:** 2026-02-13
**Scope:** Feb 1-12, 2026 (12 game dates)

```
V9 NO_PROP_LINE PREDICTION BACKFILL
  System ID:    catboost_v9
  Model:        catboost_v9_candidate.cbm (sha256: 5b3a187b1b6dfac6)
  Predictions:  904 (all NO_PROP_LINE)
  Avg predicted: 6.8 pts
  Median:        6.7 pts
  Range:         0.0 - 26.4 pts
```

**Coverage after backfill (V9 predictions per day):**

| Date | No Line | Has Line | Total |
|------|---------|----------|-------|
| 2026-02-01 | 109 | 143 | 252 |
| 2026-02-03 | 197 | 146 | 343 |
| 2026-02-07 | 116 | 493 | 609 |
| 2026-02-11 | 173 | 192 | 365 |

Prediction count roughly doubled on most dates.

---

## Grading Results

**15,370 predictions graded** across 12 dates (up from ~10K before backfill).

### MAE: With-Line vs No-Line

| Segment | N | MAE | Bias | Avg Actual | Avg Predicted |
|---------|---|-----|------|------------|---------------|
| has_line | 1,223 | **5.45** | -0.74 | 13.6 | 12.9 |
| no_line | 1,065 | **4.99** | -0.47 | 7.3 | 7.0 |
| **Overall** | **2,288** | **5.30** | **-0.65** | | |

**Key insight:** No-line predictions have *lower* MAE (4.99 vs 5.45). This is because no-line players are predominantly bench/role players with low, predictable scoring (avg 7.3 pts). The model predicts them well even without vegas features.

### MAE by Tier and Segment

| Segment | Tier | N | MAE | Bias |
|---------|------|---|-----|------|
| has_line | Stars (25+) | 127 | 10.20 | -9.97 |
| has_line | Starters (15-24) | 349 | 5.42 | -3.86 |
| has_line | Role (5-14) | 524 | 4.13 | +1.67 |
| has_line | Bench (0-4) | 223 | 6.09 | +6.08 |
| no_line | Stars (25+) | 12 | 18.51 | -18.51 |
| no_line | Starters (15-24) | 68 | 10.19 | -9.95 |
| no_line | Role (5-14) | 246 | 3.08 | -2.15 |
| no_line | Bench (0-4) | 739 | 4.79 | +4.73 |

**Interpretation:**
- **No-line role players** (5-14 pts) have the **best MAE of any segment**: 3.08
- **No-line stars/starters** have terrible MAE (18.5 / 10.2) — these are rare cases (12 + 68) where a star had no prop line. Without vegas as an anchor, the model severely underpredicts them.
- **Bench players** show positive bias (+4.7-6.1) regardless of line status — model overpredicts bench players who score near zero.

### Hit Rate (With-Line Predictions Only)

| Metric | Value |
|--------|-------|
| Hit Rate (all) | 48.0% (344/717) |
| Hit Rate (edge 3+) | 40.6% (76/187) |

Note: This is the **champion V9 model** (35+ days stale, decaying as documented in Session 220). These numbers reflect model staleness, not the backfill quality.

---

## Training Experiment: `--include-no-line` Diagnostics

**Command:**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "ALL_PLAYER_LINE_DIAG" --include-no-line \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register
```

### Training Data Line Coverage

| Metric | Value |
|--------|-------|
| Total training samples | 9,629 |
| With prop lines | 6,146 (63.8%) |
| Without lines | 3,483 (36.2%) |

**The model has always trained on all players.** The `--include-no-line` flag simply reveals this. Training data doesn't filter by line availability — it uses `player_game_summary` for actual_points, not a lines table.

### Model Performance

| Metric | Result | vs V9 Baseline |
|--------|--------|----------------|
| MAE (with lines) | **4.90** | 5.14 baseline (-0.24) |
| MAE (all players) | **4.52** | N/A (new metric) |
| Hit Rate (all) | **56.7%** | 54.5% (+2.2%) |
| Hit Rate (edge 3+) | **69.2%** | 63.7% (+5.5%) |
| Vegas Bias | -0.12 | within +/-1.5 |

### Walk-Forward Evaluation

| Week | N | MAE | HR All | HR 3+ | Bias |
|------|---|-----|--------|-------|------|
| Jan 26 - Feb 1 | 111 | 4.37 | 58.8% | 100.0% | -0.04 |
| Feb 2 - Feb 8 | 367 | 5.13 | 59.2% | 62.5% | -0.15 |
| Feb 9 - Feb 15 | 172 | 4.75 | 50.0% | 66.7% | -0.09 |

### Feature Importance (Top 5)

1. `vegas_points_line` — 29.4%
2. `vegas_opening_line` — 11.1%
3. `points_avg_last_5` — 9.2%
4. `points_avg_season` — 7.5%
5. `points_avg_last_10` — 6.4%

### Governance Gates

| Gate | Result |
|------|--------|
| MAE improvement | PASS (4.90 vs 5.14) |
| Hit rate 3+ >= 60% | PASS (69.2%) |
| Sample size >= 50 | **FAIL** (n=13) |
| Vegas bias +/-1.5 | PASS (-0.12) |
| No critical tier bias | PASS |
| Directional balance | PASS (OVER 75%, UNDER 67%) |

**Not deployable** due to insufficient edge 3+ sample size (13 graded, need 50). This is expected for a 12-day eval window. The model itself looks healthy.

---

## Deployment Status

All 3 Cloud Build triggers completed successfully:
- `prediction-coordinator` — deployed with `/line-update` endpoint
- `enrichment-trigger` — deployed with V9 re-prediction logic
- Cloud Functions auto-deploy via `cloudbuild-functions.yaml`

**Verify re-prediction works** on the next game day by checking:
```sql
SELECT prediction_run_mode, COUNT(*) as n
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
GROUP BY 1
```
Expected: `LINE_UPDATE` mode predictions should appear after 18:40 UTC.

---

## Conclusions

1. **Backfill worked** — 904 NO_PROP_LINE predictions generated and graded. V9 now has full-population coverage.
2. **No-line MAE is actually better** (4.99 vs 5.45) because bench/role players are predictable. The overall MAE including all players is 5.30.
3. **Training already includes all players** — 36.2% of training data is players without lines. No code change needed to training data loader.
4. **Re-prediction infrastructure deployed** — enrichment trigger now calls `/line-update` to regenerate V9 predictions when lines arrive.
5. **Model decay confirmed** — champion V9 at 48% all-HR and 40.6% edge 3+ HR (well below 52.4% breakeven). Fresh retrain shows 56.7% / 69.2% respectively. Monthly retrain is overdue.
6. **No-line stars are problematic** — without vegas as anchor, model predicts stars at ~7 pts. Only 12 cases, but MAE is 18.5. This is a known limitation of V9's vegas dependency.
