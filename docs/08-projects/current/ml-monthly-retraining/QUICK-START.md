# Monthly Model Quick Start Guide

**5-minute guide to adding a new monthly model**

## TL;DR

```bash
# 1. Train model
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_2026_03_MONTHLY" \
    --train-start 2025-11-02 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-07 \
    --line-source draftkings \
    --hypothesis "March monthly model"

# 2. Rename model file (use results from training output)
mv models/catboost_retrain_V9_2026_03_MONTHLY_*.cbm models/catboost_v9_2026_03.cbm

# 3. Edit predictions/worker/prediction_systems/catboost_monthly.py
# Add new entry to MONTHLY_MODELS dict (see template below)

# 4. Verify
python verify_monthly_models.py

# 5. Deploy
git add models/catboost_v9_2026_03.cbm predictions/worker/prediction_systems/catboost_monthly.py
git commit -m "feat: Add March 2026 monthly model (MAE X.XX, HR XX.X%)"
./bin/deploy-service.sh prediction-worker
```

## Configuration Template

Copy this into `MONTHLY_MODELS` dict in `catboost_monthly.py`:

```python
"catboost_v9_2026_XX": {  # Replace XX with month number
    "model_path": "models/catboost_v9_2026_XX.cbm",
    "train_start": "2025-11-02",  # Season start
    "train_end": "2026-XX-XX",    # Last day of previous month
    "eval_start": "2026-XX-01",   # First day of new month
    "eval_end": "2026-XX-07",     # 7 days later
    "mae": X.XX,                  # From training results
    "hit_rate_overall": XX.X,     # From training results
    "enabled": True,
    "description": "MONTH 2026 monthly model - XX day training window",
},
```

## Monthly Training Schedule

| Month | Train End | Eval Period | Training Days | Deploy By |
|-------|-----------|-------------|---------------|-----------|
| Feb 2026 | 2026-01-24 | Jan 25-31 | 84 | Feb 1 |
| Mar 2026 | 2026-02-28 | Mar 1-7 | 118 | Mar 1 |
| Apr 2026 | 2026-03-31 | Apr 1-7 | 149 | Apr 1 |

**Pattern**: Train on all data from season start to end of previous month, evaluate on first week of new month.

## Expected Results

After deploying, verify with:

```sql
-- Should see new system_id with predictions
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id LIKE 'catboost_v9_2026_%'
GROUP BY system_id
```

Expected:
```
system_id              predictions
catboost_v9_2026_02    450
catboost_v9_2026_03    450  <-- New model
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Model file not found | Check path in config matches `ls models/` |
| No predictions | Check `enabled: True` and worker deployed |
| Verification fails | Run with PYTHONPATH=. and check error message |

## Full Documentation

See `MONTHLY-MODEL-ARCHITECTURE.md` for:
- Architecture details
- Comparison queries
- Disabling models
- Advanced troubleshooting
