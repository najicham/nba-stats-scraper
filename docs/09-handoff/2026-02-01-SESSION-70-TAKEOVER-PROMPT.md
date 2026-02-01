# Session 70 Takeover Prompt

Copy this prompt to start the next session:

---

## Context

Session 69 established the monthly model retraining infrastructure. Key accomplishments:

1. **Cloud Scheduler Active** - Monthly retrain runs 1st of each month at 6 AM ET
2. **Multi-Model Deployed** - `catboost_v9` and `catboost_v9_2026_02` running in parallel
3. **pct_over Signal Validated** - Under-heavy days (<25%) have 54% HR vs 82% for balanced days (p=0.0065)

## Read First

```
docs/09-handoff/2026-02-01-SESSION-69-HANDOFF.md
docs/08-projects/current/ml-monthly-retraining/README.md
docs/08-projects/current/pre-game-signals-strategy/README.md
```

## Immediate Tasks

### 1. Verify Multi-Model Predictions

Check that both models are making predictions for today:

```sql
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id LIKE 'catboost%'
GROUP BY 1
```

Expected: Both `catboost_v9` and `catboost_v9_2026_02` should have predictions.

If `catboost_v9_2026_02` is missing, the prediction worker may need to be triggered or there's an issue with the monthly model loading.

### 2. Check Today's pct_over Signal

```sql
SELECT
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  CASE 
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 
    THEN '⚠️ UNDER_HEAVY - Expect ~54% HR'
    ELSE '✅ BALANCED - Expect ~82% HR'
  END as signal
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
```

### 3. Uncommitted Files

There are uncommitted files from other sessions. Review and commit if appropriate:
- `orchestration/cloud_functions/*/shared/*` - Symlink fixes from Session 70
- `docs/09-handoff/2026-02-01-SESSION-68-GRADING-GAP-FIXES-HANDOFF.md`
- `docs/09-handoff/2026-02-01-ORCHESTRATION-ISSUES-INVESTIGATION.md`

## Optional Tasks

### Add pct_over to /top-picks Skill

The pct_over signal is validated. Consider adding it to the `/top-picks` skill to warn users on under-heavy days.

### Compare Model Performance

After a few days, compare v9 vs v9_2026_02:

```sql
SELECT 
  system_id,
  COUNT(*) as predictions,
  COUNTIF(ABS(predicted_points - line_value) >= 5) as high_edge,
  ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_points - line_value) >= 5) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL AND ABS(predicted_points - line_value) >= 5), 0), 1) as high_edge_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-02-01'
  AND system_id LIKE 'catboost%'
GROUP BY 1
```

### Run Recency Weighting Experiments

The `--half-life` argument is now available. Test if recency weighting helps:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_RECENCY_60" \
    --train-start 2025-11-02 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --half-life 60 \
    --hypothesis "60-day half-life recency weighting"
```

## Key Files

| File | Purpose |
|------|---------|
| `ml/experiments/quick_retrain.py` | Monthly retraining script |
| `predictions/worker/prediction_systems/catboost_monthly.py` | Multi-model configuration |
| `docs/08-projects/current/ml-monthly-retraining/QUICK-START.md` | How to add new monthly models |

## Monthly Process (For Reference)

```bash
# 1. Train new model
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_2026_03_MONTHLY" \
    --train-start 2025-11-02 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-07

# 2. Rename model file
mv models/catboost_retrain_*.cbm models/catboost_v9_2026_03.cbm

# 3. Add to MONTHLY_MODELS in catboost_monthly.py

# 4. Deploy
./bin/deploy-service.sh prediction-worker
```

---

*Session 69 Complete - Feb 1, 2026*
