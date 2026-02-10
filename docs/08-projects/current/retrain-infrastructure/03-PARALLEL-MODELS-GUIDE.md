# Parallel V9 Models Guide

Session 177 (2026-02-09): Running multiple CatBoost V9 models in production.

## How It Works

Multiple V9 models run simultaneously, each with its own `system_id`. The production champion (`catboost_v9`) handles user-facing picks and alerts. Challenger models run in **shadow mode** — they generate predictions, get graded, and produce signals, but don't affect user-facing output.

**Key infrastructure (no changes needed):**
- `worker.py` iterates `_monthly_models` list, stores predictions per model
- `signal_calculator.py` groups by `system_id` — each model gets its own signal
- `prediction_accuracy_processor.py` grades all predictions per `system_id`
- `subset_picks_notifier.py` is hard-coded to `catboost_v9` — challengers don't affect picks
- Slack alerts only fire for `PRIMARY_ALERT_MODEL = 'catboost_v9'`

## Adding a New Challenger

### Step 1: Train and Evaluate

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "MY_EXPERIMENT" \
    --train-start 2025-11-02 \
    --train-end 2026-02-15 \
    --eval-start 2026-02-01 \
    --eval-end 2026-02-08 \
    --use-production-lines
```

When all gates pass, the script prints a ready-to-paste `MONTHLY_MODELS` config snippet.

### Step 2: Upload Model to GCS

```bash
gsutil cp models/catboost_v9_33f_train*.cbm \
    gs://nba-props-platform-models/catboost/v9/monthly/
```

### Step 3: Add Config to catboost_monthly.py

Paste the config snippet from Step 1 into the `MONTHLY_MODELS` dict in
`predictions/worker/prediction_systems/catboost_monthly.py`:

```python
MONTHLY_MODELS = {
    "catboost_v9_train1102_0215": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260215_20260216_123456.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-02-15",
        "backtest_mae": 4.5,
        "backtest_hit_rate_all": 60.0,
        "backtest_hit_rate_edge_3plus": 70.0,
        "backtest_n_edge_3plus": 100,
        "enabled": True,
        "description": "MY_EXPERIMENT — extended training data",
    },
}
```

**Naming convention:** `catboost_v9_train{MMDD}_{MMDD}` — training dates visible in every BQ query.

### Step 4: Deploy

Push to main triggers auto-deploy:

```bash
git add predictions/worker/prediction_systems/catboost_monthly.py
git commit -m "feat: Add challenger model catboost_v9_train1102_0215"
git push origin main
```

### Step 5: Monitor

```bash
# After games are graded (next day)
python bin/compare-model-performance.py catboost_v9_train1102_0215

# Or via model-registry wrapper
./bin/model-registry.sh compare catboost_v9_train1102_0215

# BQ query for raw data
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as n, ROUND(AVG(predicted_points), 1) as avg_pred
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3
  AND system_id LIKE 'catboost_v9_train%'
GROUP BY 1"
```

## Promoting a Challenger to Champion

If a challenger outperforms the champion over 2+ days:

1. **Update the env var** to point to the challenger's GCS model path:
   ```bash
   gcloud run services update prediction-worker --region=us-west2 \
       --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/monthly/the_model.cbm"
   ```

2. **Update GCS manifest** and sync to BQ:
   ```bash
   ./bin/model-registry.sh sync
   ```

3. **Update CLAUDE.md** model section with new production model info.

4. **Disable the old challenger** entry (set `enabled: False`) since it's now the champion via `CATBOOST_V9_MODEL_PATH`.

## Retiring a Challenger

Set `enabled: False` in `MONTHLY_MODELS` and deploy:

```python
"catboost_v9_train1102_0215": {
    ...
    "enabled": False,  # Retired: underperformed champion by 5pp
},
```

## Resource Impact

- **Memory:** Each model is ~0.1-1 MB, negligible
- **Prediction table:** ~75 extra rows per model per game day (419K+ existing)
- **Latency:** Each model adds ~50ms per player prediction
- **GCS downloads:** Once at worker startup, cached in /tmp

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No predictions for challenger | Check `enabled: True` and model file exists in GCS |
| GCS download fails | Verify path: `gsutil ls gs://nba-props-platform-models/catboost/v9/monthly/` |
| Model loads wrong features | All V9 models use same 33 features — check CatBoostV8 base class |
| compare script shows no data | Games need to be graded first (next day after games complete) |
