# Session 356 Prompt — Deploy V16 Features to Feature Store

Read the Session 355 handoff first:

```
docs/09-handoff/2026-02-27-SESSION-355-HANDOFF.md
```

## Mission

Deploy the V16 features to the feature store so the V16 model (75% HR edge 3+, OVER 88.9%, UNDER 63.6%) can run in production. This was the best-performing experiment in Session 355.

## What Are V16 Features

Two new features that encode a player's recent history vs their prop line:

1. **`over_rate_last_10`** (feature index 55): Fraction of last 10 games where `actual_points > prop_line`. Range 0.0-1.0. Direct OVER/UNDER tendency signal.

2. **`margin_vs_line_avg_last_5`** (feature index 56): Average of `(actual_points - prop_line)` over last 5 games. Can be negative (player consistently missing line) or positive (beating line). How much the player has been beating/missing lines recently.

### Why They Work

The current model anchors to season averages (46% importance in top 3 features) but books price in recent streaks. V16 features directly encode "is this player beating or missing their line recently?" — the exact signal needed for directional accuracy. In backtest: 75% HR edge 3+ with both OVER (88.9%) and UNDER (63.6%) above breakeven.

### Data Sources

Both features are computed from:
- `actual_points` from `nba_analytics.player_game_summary`
- `prop_line` from `nba_predictions.prediction_accuracy` (graded prop lines) OR `nba_predictions.player_prop_predictions` (current lines)

The computation is a **per-player rolling window** over recent games, looking back from each game_date (no leakage — only prior games).

## Implementation Plan

### Step 1: Add Features to Feature Contract

In `shared/ml/feature_contract.py`:
- Add `"over_rate_last_10"` and `"margin_vs_line_avg_last_5"` to `FEATURE_STORE_NAMES` (indices 55-56)
- Update `FEATURE_STORE_FEATURE_COUNT` from 55 to 57
- Update `CURRENT_FEATURE_STORE_VERSION` to `"v2_57features"`
- Add to V12_CONTRACT and any other relevant contracts

### Step 2: Add Schema Columns to BigQuery

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS feature_55_value FLOAT64,
ADD COLUMN IF NOT EXISTS feature_55_quality STRING,
ADD COLUMN IF NOT EXISTS feature_55_source STRING,
ADD COLUMN IF NOT EXISTS feature_56_value FLOAT64,
ADD COLUMN IF NOT EXISTS feature_56_quality STRING,
ADD COLUMN IF NOT EXISTS feature_56_source STRING;
```

### Step 3: Add Computation to Feature Calculator

In `data_processors/precompute/ml_feature_store/feature_calculator.py`:

The features need a rolling window query per player. Pseudocode:

```sql
-- For each player on each game_date, look at their last N games
-- where they had a prop line, and compute the features
WITH player_line_history AS (
  SELECT
    pgs.player_lookup,
    pgs.game_date,
    pgs.points AS actual_points,
    pa.line_value AS prop_line,
    ROW_NUMBER() OVER (
      PARTITION BY pgs.player_lookup
      ORDER BY pgs.game_date DESC
    ) AS games_ago
  FROM nba_analytics.player_game_summary pgs
  INNER JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pgs.player_lookup
    AND pa.game_date = pgs.game_date
  WHERE pa.line_value > 0
    AND pgs.game_date < @target_date  -- Only prior games (no leakage)
)
SELECT
  player_lookup,
  -- over_rate_last_10: fraction of last 10 where actual > line
  COUNTIF(actual_points > prop_line AND games_ago <= 10)
    / NULLIF(COUNTIF(games_ago <= 10), 0) AS over_rate_last_10,
  -- margin_vs_line_avg_last_5: mean(actual - line) over last 5
  AVG(CASE WHEN games_ago <= 5 THEN actual_points - prop_line END) AS margin_vs_line_avg_last_5
FROM player_line_history
WHERE games_ago <= 10
GROUP BY player_lookup
```

### Step 4: Update Worker Feature Extraction

In `predictions/worker/prediction_systems/catboost_monthly.py`:
- The V12 feature vector is built from `V12_NOVEG_FEATURES` list and `features` dict
- Add `over_rate_last_10` and `margin_vs_line_avg_last_5` to the feature names list
- The data loader already reads all `feature_N_value` columns, so no loader changes needed

### Step 5: Re-enable V16 Model

```bash
bq query --project_id=nba-props-platform --use_legacy_sql=false \
  "UPDATE nba_predictions.model_registry SET enabled=TRUE
   WHERE model_id='catboost_v12_noveg_train0115_0222'
   AND gcs_path LIKE '%_v16_%'"
```

### Step 6: Retrain with Feature Store V16

Once V16 features are in the feature store (backfilled), retrain:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V16_PRODUCTION" --feature-set v12 --no-vegas \
    --v16-features \
    --train-start 2025-12-01 --train-end 2026-02-27 \
    --eval-start 2026-02-23 --eval-end 2026-02-27 \
    --force --enable
```

## Key Files

| File | What to change |
|------|---------------|
| `shared/ml/feature_contract.py` | Add feature 55-56 definitions |
| `data_processors/precompute/ml_feature_store/feature_calculator.py` | Add V16 computation |
| `schemas/ml_feature_store_v2.json` | Add feature_55/56 schema fields |
| `predictions/worker/prediction_systems/catboost_monthly.py` | Add V16 to feature vector |
| `predictions/worker/prediction_systems/catboost_v12.py` | Add V16 to V12_NOVEG_FEATURES |

## BigQuery Column Approach — CONFIRMED OK

Adding columns 55-56 to the wide `ml_feature_store_v2` table is the right approach:
- BigQuery columnar storage only scans referenced columns (no perf impact on existing queries)
- Adding columns is a metadata-only operation (instant, no rewrite)
- Wide denormalized tables are BigQuery's recommended pattern
- NULL columns (for older data without V16) cost nothing in storage

## Context from Session 355

- The `--v16-features` flag in `quick_retrain.py` already computes these features from training data in Python
- The trained V16 model (`catboost_v12_52f_noveg_v16_train20260115-20260222_20260227_122302.cbm`) is in GCS
- The model has 52 features (50 base V12_NOVEG + 2 V16)
- V16 feature coverage in training: over_rate_last_10=528/4178, margin_vs_line_avg_last_5=1680/4178 (CatBoost handles NaN natively)
- Anchor-line model is also enabled as shadow (`catboost_v12_noveg_q5_train0115_0222`) — monitor it

## Don't Revisit (Dead Ends from Session 355)

- Anchor-line + 60-day window (collapsed to constant)
- Anchor-line + diff-features (collapsed)
- Anchor-line + category weights (collapsed)
- Diff-features only (doesn't fix UNDER bias)
