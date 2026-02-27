# Session 357 Prompt — Train and Enable V16 Model

Read the Session 356 handoff first:

```
docs/09-handoff/2026-02-27-SESSION-356-HANDOFF.md
```

## Mission

Train a V16 model using the newly deployed feature store V16 features and enable it in shadow. Session 356 deployed `over_rate_last_10` (feature 55) and `margin_vs_line_avg_last_5` (feature 56) to the feature store and backfilled Dec 1 → Feb 27. The V16 experiment in Session 355 hit **75% HR edge 3+ (OVER 88.9%, UNDER 63.6%)** — best of all experiments.

## Steps

### 1. Train V16 Model

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V16_PRODUCTION" --feature-set v12 --no-vegas \
    --v16-features \
    --train-start 2025-12-01 --train-end 2026-02-27 \
    --eval-start 2026-02-23 --eval-end 2026-02-27 \
    --force --enable
```

The `--v16-features` flag auto-upgrades feature_set to `v16`, so the model registers as `feature_set='v16_noveg'` (52 features). The worker already supports this.

If governance gates fail, adjust training window or try quantile variants (Q55, Q57).

### 2. Verify Registration

After training, verify the model is correctly registered:

```sql
SELECT model_id, feature_set, feature_count, enabled, evaluation_hit_rate_edge_3plus
FROM nba_predictions.model_registry
WHERE feature_set = 'v16_noveg'
ORDER BY created_at DESC LIMIT 5;
```

Confirm `feature_set='v16_noveg'` and `feature_count=52`.

### 3. Monitor Existing Shadow Models

Check how the anchor-line model (Session 355) is performing:

```sql
SELECT system_id, game_date, COUNT(*) as picks,
       COUNTIF(is_correct) as correct,
       ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE '%q5_train0115%'
  AND game_date >= '2026-02-27'
GROUP BY system_id, game_date ORDER BY game_date;
```

### 4. Daily Health Check

Run `/daily-steering` and `/validate-daily` to check overall pipeline health.

## Context

- V16 features are in the feature store (v2_57features, 57 columns)
- Backfill: 12,587 records with over_rate_last_10, 13,172 with margin_vs_line_avg_last_5
- All services deployed with commit `bd7f451a` (zero drift)
- Worker supports `v16_noveg` feature set (52-feature vector)
- `quick_retrain.py` has V16 contract import and auto-upgrade logic
