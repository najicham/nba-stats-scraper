# Session 358 Prompt — V16 Shadow Monitoring + Fleet Health

Read the Session 357 handoff first:

```
docs/09-handoff/2026-02-27-SESSION-357-HANDOFF.md
```

## Mission

Check on the V16 model's first predictions and the overall shadow fleet health. Session 357 trained and enabled `catboost_v16_noveg_train1201_0215` (70.83% backtest HR edge 3+, OVER 88.9%) — it should have generated its first predictions by now.

## Steps

### 1. Verify V16 Model Predictions

Check if the V16 model generated predictions:

```sql
SELECT system_id, game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v16_noveg_train1201_0215'
  AND game_date >= '2026-02-28'
GROUP BY system_id, game_date
ORDER BY game_date;
```

If **no predictions**, debug:
1. Check worker logs: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND textPayload:v16" --limit=20 --format="table(timestamp, textPayload)" --project=nba-props-platform`
2. Verify model is in the manifest: `gsutil cat gs://nba-props-platform-models/manifest.json | python3 -c "import json,sys; [print(m['model_id'],m.get('feature_set')) for m in json.load(sys.stdin).get('models',[])]"`
3. Check model discovery: the worker uses `discover_models()` from BQ registry — verify `enabled=TRUE` and `status='active'`

### 2. Check Anchor-Line Model (Q5)

Same issue — `catboost_v12_noveg_q5_train0115_0222` was enabled but had no predictions as of Session 357.

```sql
SELECT system_id, game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v12_noveg_q5_train0115_0222'
  AND game_date >= '2026-02-27'
GROUP BY system_id, game_date
ORDER BY game_date;
```

### 3. Check V16 Graded Performance (if predictions exist)

```sql
SELECT system_id, game_date,
       COUNT(*) as picks,
       COUNTIF(prediction_correct) as wins,
       COUNT(*) - COUNTIF(prediction_correct) as losses,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
       COUNTIF(ABS(predicted_value - prop_line) >= 3) as edge_3plus,
       COUNTIF(ABS(predicted_value - prop_line) >= 3 AND prediction_correct) as edge_3plus_wins
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v16_noveg_train1201_0215'
  AND game_date >= '2026-02-28'
GROUP BY system_id, game_date ORDER BY game_date;
```

### 4. Daily Operations

Run `/daily-steering` and `/validate-daily`.

### 5. Shadow Fleet Review

If V16 has 2+ days of graded data, compare it against the rest of the fleet:

```sql
SELECT system_id,
       COUNT(*) as picks,
       COUNTIF(prediction_correct) as wins,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
       COUNTIF(ABS(predicted_value - prop_line) >= 3 AND prediction_correct) as edge3_wins,
       COUNTIF(ABS(predicted_value - prop_line) >= 3) as edge3_total,
       ROUND(100.0 * COUNTIF(ABS(predicted_value - prop_line) >= 3 AND prediction_correct) / NULLIF(COUNTIF(ABS(predicted_value - prop_line) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY system_id
ORDER BY edge3_hr DESC;
```

## Context

- V16 model: `catboost_v16_noveg_train1201_0215`, feature_set=`v16_noveg`, 52 features
- Backtest: 70.83% HR edge 3+ (OVER 88.9%, UNDER 60.0%), Dec 1 - Feb 15 training
- 13 shadow models enabled + 1 production (catboost_v12)
- All models BLOCKED at raw level, but best bets filters extracting 62.5% HR (30d)
- Zero deployment drift as of Session 357
- Pipeline healthy: Phase 3 processing normally, 11 models producing 65-66 predictions each
