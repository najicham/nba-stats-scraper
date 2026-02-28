# Session 359 Prompt — Verify New Models + Fleet Health

Read the Session 358 handoff first:

```
docs/09-handoff/2026-02-27-SESSION-358-HANDOFF.md
```

## Mission

Verify that V16, Q5, and LightGBM models are now producing predictions after Session 358's fixes. If they are, check early performance. Run daily operations.

## Steps

### 1. Verify All 4 New Models Producing Predictions

```sql
SELECT system_id, game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-28'
  AND system_id IN (
    'catboost_v16_noveg_train1201_0215',
    'catboost_v12_noveg_q5_train0115_0222',
    'lgbm_v12_noveg_train1102_0209',
    'lgbm_v12_noveg_train1201_0209'
  )
GROUP BY system_id, game_date ORDER BY system_id, game_date;
```

**If LightGBM models still missing**, check worker logs for the defensive detection fix:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND (textPayload:lgbm OR textPayload:LightGBM)" --limit=30 --format="table(timestamp, textPayload)" --project=nba-props-platform
```

Look for: `Loading LightGBM monthly model from: ... (model_type='lightgbm', is_lightgbm=True)`

### 2. Check V16 + LightGBM Early Performance (if graded)

```sql
SELECT system_id, game_date,
       COUNT(*) as picks,
       COUNTIF(prediction_correct) as wins,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_w,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct)
         / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v16_noveg_train1201_0215', 'catboost_v12_noveg_q5_train0115_0222',
                    'lgbm_v12_noveg_train1102_0209', 'lgbm_v12_noveg_train1201_0209')
  AND game_date >= '2026-02-28'
GROUP BY system_id, game_date ORDER BY system_id, game_date;
```

Backtest references: V16 = 70.83% HR edge 3+, LightGBM = 67-73% HR edge 3+

### 3. Daily Operations

Run `/daily-steering` and `/validate-daily`.

### 4. If V16 Has 2+ Days Graded: Fleet Comparison

```sql
SELECT system_id,
       COUNT(*) as picks,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_w,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct)
         / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY system_id ORDER BY edge3_hr DESC;
```

## Context

- 13 shadow models + 1 production enabled
- Session 358 fixed LightGBM loading (defensive model_type detection)
- V16 and Q5 registered after Feb 27 batch — first predictions Feb 28
- Best bets: 66.7% HR 7d, 62.5% HR 14d (profitable despite all models BLOCKED)
- `prediction_accuracy` schema: use `predicted_points` and `line_value` (NOT `predicted_value`)
- `signal_best_bets_picks` is self-contained (has `prediction_correct` and `actual_points`)
