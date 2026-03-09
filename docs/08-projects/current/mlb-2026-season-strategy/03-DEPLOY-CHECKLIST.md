# MLB 2026 — Deploy Checklist

*Updated Session 444: 36 features (5 dead removed), 23-pitcher blacklist*

## Pre-Season (Mar 18-23)

### Step 1: Train Final Model (Mar 18-20)
```bash
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2026-03-20 \
    --window 120
```
- Verify model file created in `models/mlb/`
- Check training metrics (MAE should be ~1.4-1.6 based on replay)
- **Feature count should be 36** (5 dead features removed in Session 444)

### Step 2: Upload Model to GCS
```bash
gsutil cp models/mlb/catboost_mlb_v2_regressor_*.cbm \
    gs://nba-props-platform-ml-models/mlb/
```

### Step 3: Push Code to Main
```bash
git push origin main
# This auto-deploys NBA services. MLB worker is manual.
```
Wait for Cloud Build to complete:
```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

### Step 4: Deploy MLB Worker (Manual)
```bash
gcloud builds submit --config cloudbuild-mlb-worker.yaml
gcloud run services update-traffic mlb-prediction-worker \
    --region=us-west2 --to-latest
```
**Verify traffic routing:**
```bash
gcloud run services describe mlb-prediction-worker --region=us-west2 \
    --format="value(status.traffic)"
```

### Step 5: Set Environment Variables
```bash
gcloud run services update mlb-prediction-worker \
    --region=us-west2 \
    --update-env-vars="\
MLB_ACTIVE_SYSTEMS=catboost_v1,catboost_v2_regressor,\
MLB_CATBOOST_V2_MODEL_PATH=gs://nba-props-platform-ml-models/mlb/catboost_mlb_v2_regressor_YYYYMMDD.cbm,\
MLB_EDGE_FLOOR=0.75,\
MLB_MAX_EDGE=2.0,\
MLB_MAX_PICKS_PER_DAY=3,\
MLB_UNDER_ENABLED=false"
```

### Step 6: Resume MLB Schedulers (Mar 24)
```bash
./bin/mlb-season-resume.sh
# Unpauses 24 scheduler jobs
```

## Opening Day Verification (Mar 27+)

### Predictions Check
```sql
SELECT game_date, system_id, COUNT(*) as n,
       COUNTIF(recommendation = 'OVER') as n_over,
       AVG(edge) as avg_edge
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-03-27'
GROUP BY 1, 2 ORDER BY 1, 2;
```

### Best Bets Check
```sql
SELECT game_date, COUNT(*) as n_picks,
       AVG(edge) as avg_edge,
       algorithm_version
FROM mlb_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-27'
GROUP BY 1, 3 ORDER BY 1;
```

### Filter Audit Check
```sql
SELECT filter_name, filter_result, COUNT(*) as n
FROM mlb_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-27'
GROUP BY 1, 2 ORDER BY 1, 2;
```

### Verify Regressor Edges
Edges should be in real K units (0.3-2.0 range), not probability units (0.5-5.0).
```sql
SELECT system_id, MIN(edge) as min_edge, MAX(edge) as max_edge,
       AVG(edge) as avg_edge
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-03-27' AND system_id = 'catboost_v2_regressor'
GROUP BY 1;
```

### Verify Ultra Tags
Ultra picks should have `ultra_tier=true`, `staking_multiplier=2`, and criteria including
`half_line`, `is_home`, `projection_agrees`.

```sql
SELECT game_date, pitcher_lookup, edge, ultra_tier, ultra_criteria, staking_multiplier
FROM mlb_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-27' AND ultra_tier = TRUE
ORDER BY game_date;
```

## Week 1 Monitoring

- [ ] Predictions generating daily for both v1 and v2
- [ ] Best bets publishing 2-3 picks/day
- [ ] Filter audit shows whole_line_over and pitcher_blacklist firing
- [ ] Algorithm version = `mlb_v6_season_replay_validated`
- [ ] v1 vs v2 predictions side-by-side comparison
- [ ] No errors in Cloud Run logs

## 3-Week Checkpoint (Apr 14)

- [ ] Force retrain with in-season data
- [ ] Compare v1 classifier vs v2 regressor live HR
- [ ] Review blacklist — any pitchers with improved performance?
- [ ] UNDER enablement decision (if OVER HR >= 58%)

## May 1: UNDER Decision Point

If OVER system is performing at >= 58% HR:
```bash
gcloud run services update mlb-prediction-worker \
    --region=us-west2 \
    --update-env-vars="MLB_UNDER_ENABLED=true"
```
