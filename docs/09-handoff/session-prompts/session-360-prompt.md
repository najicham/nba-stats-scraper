# Session 361 Prompt — Shadow Fleet Review + Next Experiments

Read the Session 360 handoff first:

```
docs/09-handoff/2026-02-27-SESSION-360-HANDOFF.md
```

## Context

Session 360 implemented and tested V17 opportunity risk features — dead end (all <1% importance). The infrastructure (contract, extractor, processor, worker) is deployed and reusable. V12 vegas=0.25 remains the best model at 75% HR edge 3+ (backtest).

## Steps

### 1. Daily Operations

Run `/daily-steering` and `/validate-daily`.

### 2. Shadow Fleet Performance Check

Check how Session 359's new models are performing with live data:

```sql
SELECT system_id,
       COUNT(*) as total_picks,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_w,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct)
         / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND predicted_points > line_value AND prediction_correct) as over_w,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND predicted_points > line_value) as over_n,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND predicted_points <= line_value AND prediction_correct) as under_w,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND predicted_points <= line_value) as under_n
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-02-28'
GROUP BY system_id ORDER BY edge3_hr DESC;
```

**Key models to watch:**
- `catboost_v12_train1201_0215` — V12 vegas=0.25 (75% backtest)
- `catboost_v16_noveg_rec14_train1201_0215` — V16 noveg + 14-day recency (69% backtest, best UNDER)
- `catboost_v16_noveg_train1201_0215` — V16 noveg baseline
- LightGBM models (`lgbm_*`) — different framework, genuine feature diversity

### 3. Front-Load Detection Check

Are any models showing front-loaded performance (good early, bad late)?

```sql
SELECT model_id,
       game_date,
       rolling_hr_7d,
       rolling_hr_14d,
       ROUND(rolling_hr_7d - rolling_hr_14d, 1) as trend_7d_vs_14d,
       rolling_n_7d,
       state
FROM nba_predictions.model_performance_daily
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND rolling_n_7d >= 10
ORDER BY model_id, game_date DESC;
```

If `trend_7d_vs_14d` is consistently negative (7d HR < 14d HR), the model is degrading. Consider building automated front-load detection into `decay-detection` CF if the pattern is common.

### 4. Next Experiment (Pick One)

Based on what the fleet data shows, choose the most promising next step:

**Option A: Ensemble top 2 models**
If V12 vegas=0.25 and V16 noveg rec14 both show good live HR, try simple averaging:
```bash
# This would need new code — average predictions from 2 models per player
```

**Option B: Per-direction OVER/UNDER models**
UNDER has been the persistent weakness (47-61% across all experiments). Train a model specifically on UNDER outcomes:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "under_specialist" \
  --feature-set v12_noveg \
  --category-weight "vegas=0.25" \
  --train-start 2025-12-01 --train-end 2026-02-15 \
  --force
# Then evaluate UNDER-only performance
```

**Option C: Longer window + vegas=0.25**
The 92-day window was bad for noveg, but dampened vegas might handle it:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "v12_vw25_long" \
  --feature-set v12 \
  --category-weight "vegas=0.25" \
  --train-start 2025-11-01 --train-end 2026-02-15 \
  --force
```

## Key References

- `prediction_accuracy` schema: use `predicted_points` and `line_value`
- `signal_best_bets_picks` is self-contained (has `prediction_correct` and `actual_points`)
- Dead ends list in CLAUDE.md — check before trying anything new
- V17 code is deployed but features are dead — don't retrain V17
