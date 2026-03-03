# Session 389 Prompt — Post-Fix Monitoring & Signal Impact

## Context

Session 388 fixed a cascading auto-deploy failure (4 bugs) that blocked all March 2 predictions. Pipeline restored, 608 predictions generated. Both revived signals (line_rising_over, fast_pace_over) confirmed firing.

## Priority 1: Verify Signal Best Bets Populated

Session 388 couldn't populate `signal_best_bets_picks` due to BQ streaming buffer conflict on `current_subset_picks`. Check if the Phase 6 scheduler resolved this:

```sql
SELECT game_date, recommendation, COUNT(*) as picks,
  ROUND(AVG(signal_count), 1) as avg_sc,
  ROUND(AVG(edge), 1) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-02'
GROUP BY 1, 2
ORDER BY 1, 2;
```

If still empty for March 2, manually trigger:
```bash
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["signal-best-bets"], "target_date": "2026-03-02"}'
```

## Priority 2: Verify March 3 Pipeline Runs Clean

March 3 has 10 games. This is the first full-slate day with the Session 387+388 fixes. Verify:

```sql
-- Feature store populated with gold quality
SELECT game_date, quality_tier, COUNT(*) as players, feature_version
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-03-03'
GROUP BY 1, 2, 4;

-- Predictions generated
SELECT game_date, COUNT(DISTINCT system_id) as models, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-03-03'
GROUP BY 1;

-- Revived signals firing
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags,
UNNEST(signal_tags) AS signal_tag
WHERE game_date = '2026-03-03'
  AND signal_tag IN ('line_rising_over', 'fast_pace_over')
GROUP BY 1;
```

**Expected:** feature_version = v2_54features, gold quality players, predictions from 16 models, both signals firing.

## Priority 3: Signal Impact on OVER Performance

The revived signals specifically target OVER predictions. Track whether OVER HR improves:

```sql
-- OVER vs UNDER HR in best bets (last 14 days)
SELECT sb.recommendation,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks sb
JOIN nba_predictions.prediction_accuracy pa
  ON pa.player_lookup = sb.player_lookup
  AND pa.game_date = sb.game_date
  AND pa.system_id = sb.system_id
WHERE sb.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1;
```

Before fixes: OVER 50.0% (6/12), UNDER 66.7% (8/12). Target: OVER > 55%.

## Priority 4: Monitor Shadow Models

```sql
SELECT model_id, rolling_hr_7d, rolling_n_7d, rolling_hr_14d, rolling_n_14d, state
FROM nba_predictions.model_performance_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
  AND model_id LIKE '%train1228_0222%'
ORDER BY model_id;
```

Don't act until N>=25.

## Priority 5: Signal Canary Validation

Check if the canary ran after grading:
```bash
gcloud logging read 'resource.type="cloud_function" AND textPayload=~"canary"' \
  --limit=10 --freshness=48h --project=nba-props-platform \
  --format="table(timestamp, textPayload)"
```

Expected: `line_rising_over` and `fast_pace_over` should move from NEVER_FIRED to HEALTHY.

## Items NOT to Do

- **Don't retrain** — wait for signal fix impact data
- **Don't add new signals** — verify existing fixes first
- **Don't change FEATURE_COUNT** — current truncation fix is working
- **Don't promote a champion** — no model at N>=25 yet

## Quick Reference: What Changed in Session 388

| File | Change |
|------|--------|
| `ml_feature_store_processor.py` | Truncate features to FEATURE_COUNT for write + quality scoring; FEATURE_VERSION back to v2_54features |
| `predictions/worker/requirements-lock.txt` | Added PyYAML==6.0.2 |
| `predictions/worker/requirements.txt` | Added pyyaml>=6.0 |
| `bin/deploy-service.sh` | Added --cpu-throttling flag |
| `bin/hot-deploy.sh` | Added --cpu-throttling flag |
