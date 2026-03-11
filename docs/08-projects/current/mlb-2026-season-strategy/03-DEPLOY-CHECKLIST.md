# MLB 2026 — Deploy Checklist

*Updated Session 468: Phase 1 code deployed, BQ verified, multi-model fleet ready, umpire tiebreaker added*

## Pre-Season Phase 1 — COMPLETED (Session 468, Mar 11)

- [x] **Dockerfile fix**: Added `COPY ml/` — `/best-bets` endpoint would 500 without it
- [x] **Multi-model fleet**: LightGBM V1 + XGBoost V1 predictors + training scripts created
- [x] **Worker registration**: New models opt-in via `MLB_ACTIVE_SYSTEMS`
- [x] **Umpire tiebreaker**: Ranking uses umpire signal to break ties (no RSC inflation)
- [x] **Replay config sync**: `MAX_PICKS_PER_DAY` 3→5 to match production
- [x] **Training SQL cleanup**: Removed 5 dead features, fixed contract string 40→36
- [x] **Blacklist review script**: `bin/mlb/review_blacklist.py` for periodic refresh
- [x] **BQ verification**: All 4 training tables healthy, all 3 output tables exist

### BQ Verification Results (Mar 11)

| Table | Status | Rows | Latest |
|-------|--------|------|--------|
| `pitcher_game_summary` | OK | 5,081 (2025) | 2025-09-28 |
| `bp_pitcher_props` | OK | 7,355 (2025) | 2025-09-28 |
| `pitcher_rolling_statcast` | OK | 17,616 (2025) | 2025-10-01 |
| `fangraphs_pitcher_season_stats` | OK | 3,408 | 2025 season |
| `mlb_umpire_assignments` | OK | 2,474 | 2025-10-02 |
| `mlb_schedule` (2026) | EMPTY | 0 | Fills after scraper resume |
| `umpire_stats` | EMPTY | 0 | Fills during season |
| `mlb_weather` | EMPTY | 0 | Fills after scraper resume |
| `catcher_framing` | EMPTY | 0 | Fills after scraper resume |
| Output: `signal_best_bets_picks` | OK (schema) | — | Ready |
| Output: `best_bets_filter_audit` | OK (schema) | — | Ready |
| Output: `pitcher_strikeouts` | OK (schema) | — | Ready |

## Pre-Season Phase 2 (Mar 18-24)

### Step 1: Train Final Model (Mar 18-20)
```bash
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2026-03-20 \
    --window 120
```
- Verify model file created in `models/mlb/`
- Check training metrics (MAE should be ~1.4-1.6 based on replay)
- **Feature count: 36** (5 dead features removed Session 444)
- **Hyperparams:** depth=4, lr=0.015, iters=500, l2=10 (L2=10+D4 validated S460)

**Optional — train LightGBM/XGBoost for fleet diversity:**
```bash
PYTHONPATH=. python scripts/mlb/training/train_lightgbm_v1.py \
    --training-end 2026-03-20 --window 120
PYTHONPATH=. python scripts/mlb/training/train_xgboost_v1.py \
    --training-end 2026-03-20 --window 120
```

### Step 2: Upload Model(s) to GCS
```bash
gsutil cp models/mlb/catboost_mlb_v2_regressor_*.cbm \
    gs://nba-props-platform-ml-models/mlb/
# If training LightGBM/XGBoost:
gsutil cp models/mlb/lightgbm_mlb_v1_regressor_*.txt \
    gs://nba-props-platform-ml-models/mlb/
gsutil cp models/mlb/xgboost_mlb_v1_regressor_*.json \
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
MLB_ACTIVE_SYSTEMS=catboost_v2_regressor,\
MLB_CATBOOST_V2_MODEL_PATH=gs://nba-props-platform-ml-models/mlb/catboost_mlb_v2_regressor_YYYYMMDD.cbm,\
MLB_EDGE_FLOOR=0.75,\
MLB_AWAY_EDGE_FLOOR=1.25,\
MLB_BLOCK_AWAY_RESCUE=true,\
MLB_MAX_EDGE=2.0,\
MLB_MAX_PROB_OVER=0.85,\
MLB_MAX_PICKS_PER_DAY=5,\
MLB_UNDER_ENABLED=false"
```

**If also deploying LightGBM/XGBoost:**
```bash
gcloud run services update mlb-prediction-worker \
    --region=us-west2 \
    --update-env-vars="\
MLB_ACTIVE_SYSTEMS=catboost_v2_regressor,lightgbm_v1_regressor,xgboost_v1_regressor,\
MLB_LIGHTGBM_V1_MODEL_PATH=gs://nba-props-platform-ml-models/mlb/lightgbm_mlb_v1_regressor_36f_YYYYMMDD.txt,\
MLB_XGBOOST_V1_MODEL_PATH=gs://nba-props-platform-ml-models/mlb/xgboost_mlb_v1_regressor_36f_YYYYMMDD.json"
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
`is_home`, `projection_agrees`.

```sql
SELECT game_date, pitcher_lookup, edge, ultra_tier, ultra_criteria, staking_multiplier
FROM mlb_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-27' AND ultra_tier = TRUE
ORDER BY game_date;
```

## Week 1 Monitoring

- [ ] Predictions generating daily
- [ ] Best bets publishing 3-5 picks/day
- [ ] Filter audit shows whole_line_over and pitcher_blacklist firing
- [ ] Umpire data flowing (umpire_k_friendly signal fires as tiebreaker)
- [ ] Weather data flowing (temperature in supplemental)
- [ ] Game context flowing (moneyline, game total)
- [ ] Catcher framing scraper run weekly (check BQ row count)
- [ ] Shadow combo signals firing (day_game_high_csw, etc.)
- [ ] No errors in Cloud Run logs
- [ ] Algorithm version = `mlb_v8_s456_v3final_away_5picks`

## 3-Week Checkpoint (Apr 14)

- [ ] Force retrain with in-season data
- [ ] If multi-model deployed: compare CatBoost vs LightGBM vs XGBoost live HR
- [ ] Review blacklist: `PYTHONPATH=. python bin/mlb/review_blacklist.py --since 2026-03-27`
- [ ] UNDER enablement decision (if OVER HR >= 58%)

## May 1: UNDER Decision Point

If OVER system is performing at >= 58% HR:
```bash
gcloud run services update mlb-prediction-worker \
    --region=us-west2 \
    --update-env-vars="MLB_UNDER_ENABLED=true"
```
