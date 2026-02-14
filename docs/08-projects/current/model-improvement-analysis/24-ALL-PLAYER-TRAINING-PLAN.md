# 24: All-Player Predictions — Backfill, Re-prediction, and Training

**Session:** 241
**Date:** 2026-02-13
**Status:** Implementation complete

## Context

The prediction pipeline now includes ALL production-ready players (player_loader fix already made in Session 240). Previously, only players with prop lines (~40%) got V9 predictions due to a UPCG query filter bug.

**Key discovery: Vegas features DO affect V9 predictions.** `vegas_points_line` is feature #25 in V9's 33-feature vector. When a line arrives, the prediction changes. V12 is vegas-free — no impact.

## What Was Implemented

### 1. V9 NO_PROP_LINE Backfill Script (`bin/backfill-v9-no-line-predictions.py`)

Generates historical V9 predictions for players who were quality-ready but had no prop lines. Uses stored features from `ml_feature_store_v2` and produces NO_PROP_LINE predictions for MAE evaluation.

- Loads V9 model from GCS
- Queries quality-ready players missing V9 predictions
- Builds 33-feature vector (vegas features = NaN for no-line players)
- Safety: hard-coded training end dates prevent data leakage
- Supports champion and all shadow models

### 2. V9 Re-prediction on Enrichment

When the enrichment trigger adds prop lines to predictions, V9 predictions need regeneration because `vegas_points_line` changed from NaN to a real value.

**Flow:**
1. Enrichment processor enriches predictions with lines (existing)
2. Enrichment processor identifies V9 players that just got lines
3. Enrichment trigger calls coordinator `/line-update` endpoint
4. Coordinator supersedes old predictions and generates new ones with real vegas features

**Files changed:**
- `predictions/coordinator/coordinator.py` — new `/line-update` endpoint
- `predictions/coordinator/quality_gate.py` — `LINE_UPDATE` mode (bypasses "already_has_prediction")
- `orchestration/cloud_functions/enrichment_trigger/main.py` — triggers V9 re-prediction
- `data_processors/enrichment/.../prediction_line_enrichment_processor.py` — returns enriched player list, adds `get_v9_players_needing_reprediction()`

### 3. Training Line Coverage Flag (`--include-no-line`)

Added `--include-no-line` flag to `ml/experiments/quick_retrain.py`. Reports line coverage breakdown in training data.

**Key finding:** Training data already includes ALL quality-ready players (the training query JOINs on `player_game_summary`, not on lines). The flag adds diagnostics showing what % of training data has prop lines.

### 4. Quality Gate Findings (No Code Changes Needed)

- ~20% of players per day fail quality gates (expected for low-history players)
- These are genuinely low-data players with player_history defaults
- Coverage improves naturally as players accumulate games
- Working as designed — quality gate protects prediction accuracy

## Evaluation Criteria

### Backfill
```sql
-- Check V9 coverage after backfill
SELECT game_date,
  COUNTIF(line_source = 'NO_PROP_LINE') as no_line,
  COUNTIF(line_source != 'NO_PROP_LINE') as has_line,
  COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date >= '2026-01-09'
GROUP BY 1 ORDER BY 1
```

### Re-prediction
After deployment, verify enrichment trigger produces LINE_UPDATE predictions:
```sql
SELECT prediction_run_mode, COUNT(*) as n
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
GROUP BY 1
```

### Training with `--include-no-line`
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "ALL_PLAYER_TEST" \
    --include-no-line \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force
```

Compare MAE on all players vs line-only players. Training data is identical (already includes all players), but line coverage stats are now visible.
