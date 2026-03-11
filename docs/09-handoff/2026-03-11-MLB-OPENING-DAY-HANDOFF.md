# MLB 2026 Opening Day Handoff — Complete System Guide

**Date:** 2026-03-11
**Opening Day:** 2026-03-27 (16 days away)
**Purpose:** Everything a new chat needs to retrain, deploy, and launch the MLB prediction system for the 2026 season.

## What This System Does

We predict MLB pitcher strikeouts (OVER/UNDER) using a CatBoost regressor, filtered through a signal-based best bets pipeline. Currently **OVER-only**.

**4-season replay:** 63.4% HR, 1538-916, +470.7u, 12.8% ROI. All 4 seasons profitable.

## Current State (as of Session 468)

| Item | Status |
|------|--------|
| Code | All Phase 1 changes committed to `main` — NOT yet pushed/deployed |
| Model | Trained through Sep 2025. **Must retrain before opening day.** |
| BQ tables | All training + output tables verified healthy |
| Schedulers | 24 MLB schedulers PAUSED. Resume Mar 24. |
| 2026 schedule | Empty — populates after schedulers resume |
| Worker | NOT deployed with latest code — needs manual build |

## What Needs To Happen (Ordered)

### Step 1: Retrain Model (Mar 18-20)

```bash
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2026-03-20 \
    --window 120
```

**Verify:**
- Feature count = 36 (NOT 40 — 5 dead features removed)
- MAE ~1.4-1.6
- OVER HR >= 55% at edge >= 0.75
- Governance gates all PASS

**Optional — train LightGBM/XGBoost for fleet diversity:**
```bash
PYTHONPATH=. python scripts/mlb/training/train_lightgbm_v1.py \
    --training-end 2026-03-20 --window 120
PYTHONPATH=. python scripts/mlb/training/train_xgboost_v1.py \
    --training-end 2026-03-20 --window 120
```

### Step 2: Upload Model to GCS

```bash
gsutil cp models/mlb/catboost_mlb_v2_regressor_*.cbm \
    gs://nba-props-platform-ml-models/mlb/
gsutil cp models/mlb/*_metadata.json \
    gs://nba-props-platform-ml-models/mlb/
```

### Step 3: Push Code + Deploy Worker

```bash
# Push triggers NBA auto-deploy but NOT MLB worker
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5

# MLB worker is manual
gcloud builds submit --config cloudbuild-mlb-worker.yaml

# CRITICAL: route traffic to new revision (may not auto-route)
gcloud run services update-traffic mlb-prediction-worker \
    --region=us-west2 --to-latest

# Verify
gcloud run services describe mlb-prediction-worker --region=us-west2 \
    --format="value(status.traffic)"
```

### Step 4: Set Environment Variables

**ALWAYS use `--update-env-vars`, NEVER `--set-env-vars` (wipes all vars).**

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

Replace `YYYYMMDD` with the actual model date.

### Step 5: Resume Schedulers (Mar 24)

```bash
./bin/mlb-season-resume.sh
# Unpauses 24 scheduler jobs
# Schedule scraper fires first → populates 2026 calendar
# Umpire/weather/props scrapers start daily cadence
```

### Step 6: Opening Day Verification (Mar 27)

```sql
-- Are predictions generating?
SELECT game_date, system_id, COUNT(*) as n,
       COUNTIF(recommendation = 'OVER') as n_over,
       AVG(edge) as avg_edge
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-03-27'
GROUP BY 1, 2 ORDER BY 1, 2;
-- Expected: ~15-20 predictions/day, mostly OVER, avg edge 0.5-1.0 K

-- Are best bets publishing?
SELECT game_date, COUNT(*) as n_picks, AVG(edge) as avg_edge
FROM mlb_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-27'
GROUP BY 1 ORDER BY 1;
-- Expected: 3-5 picks/day, avg edge 1.0-1.5 K

-- Are filters working?
SELECT filter_name, filter_result, COUNT(*) as n
FROM mlb_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-27'
GROUP BY 1, 2 ORDER BY 1, 2;
-- Expected: pitcher_blacklist and whole_line_over blocking some picks
```

---

## System Architecture

```
Scrapers (18) → GCS JSON → BQ Raw Tables → Analytics (pitcher_game_summary)
                                                    ↓
BettingPros Props → Feature Assembly (36 features) → CatBoost Regressor → Predictions
                                                    ↓
                              Supplemental Data (umpire, weather, game context, catcher framing)
                                                    ↓
                              Signal Evaluation (20 active + 30 shadow) → Negative Filters (6)
                                                    ↓
                              Best Bets Pipeline (edge floor → rescue → RSC gate → rank → cap)
                                                    ↓
                              signal_best_bets_picks (BQ) + /best-bets endpoint (JSON)
```

## Model Details

**Type:** CatBoost V2 Regressor — predicts raw strikeout count.
**Features:** 36 (was 40 — 5 dead features removed Session 444: f17, f18, f24, f67, f69)
**Hyperparams:** depth=4, lr=0.015, iters=500, l2_leaf_reg=10, subsample=0.8, RMSE loss
**Training:** 120-day rolling window, 14-day retrain interval
**Governance gates:** MAE < 2.0, OVER HR >= 55% at edge >= 0.75, N >= 30, OVER rate 30-95%

**Multi-model fleet (Session 468):** LightGBM V1 + XGBoost V1 predictors exist with identical 36-feature contract. Opt-in via `MLB_ACTIVE_SYSTEMS`. Previous testing showed ~2pp lower HR than CatBoost, but with updated hyperparams they may perform differently — evaluate independently, do NOT ensemble (ensembling is a proven dead end).

## Best Bets Pipeline

**File:** `ml/signals/mlb/best_bets_exporter.py`

Pipeline flow:
1. Direction filter → OVER only (UNDER disabled)
2. Overconfidence cap → edge > 2.0 K blocked
3. Probability cap → p_over > 0.85 blocked
4. **6 negative filters:** bullpen_game, il_return, pitch_count_cap, insufficient_data, pitcher_blacklist (28 pitchers), whole_line_over
5. Edge floor → Home 0.75 K (with rescue), Away 1.25 K (no rescue)
6. **20 active signals** evaluated → real_signal_count computed
7. RSC gate → OVER needs >= 2, UNDER needs >= 3
8. Rank by pure edge (OVER), with umpire tiebreaker (+0.01 for umpire_k_friendly)
9. Cap at top 5 per day
10. Ultra tier → home + proj_agrees + edge >= 0.5 + not rescued → 2u stake
11. Write to BQ + filter audit

**Algorithm version:** `mlb_v8_s456_v3final_away_5picks`

## Signal System

**20 active signals** (count toward RSC):
- `high_edge` (BASE), `opponent_k_prone` (RESCUE), `projection_agrees_over`, `regressor_projection_agrees`, `home_pitcher_over`, `recent_k_above_line`, `high_csw_over`, `elite_peripherals_over`, `pitch_efficiency_depth_over`, `day_game_shadow_over`, `pitcher_on_roll_over`, `xfip_elite_over`, `day_game_high_csw_combo`, `ballpark_k_boost`, `umpire_k_friendly` (TIEBREAKER ONLY), `velocity_drop_under`, `short_rest_under`, `high_variance_under`, `k_trending_over` (TRACKING), `long_rest_over` (TRACKING)

**30 shadow signals** tracking data for future promotion. Key candidates:
- `day_game_elite_peripherals_combo_over` — 72.0% HR (N=182, but 2023: 55.2%)
- `high_csw_low_era_high_k_combo_over` — 70.6% HR (N=170, but 2023: 50.0%)
- `catcher_framing_over/poor_under` — waiting for live data

**6 negative filters:** bullpen_game, il_return, pitch_count_cap, insufficient_data, pitcher_blacklist, whole_line_over

**Promotion criteria:** HR >= 60% + N >= 30 in live data.

## 28-Pitcher Blacklist

Pitchers with < 45% HR in walk-forward replay (defined in `ml/signals/mlb/signals.py` line 635):
tanner_bibee, logan_webb, mitchell_parker, casey_mize, logan_gilbert, jake_irvin, george_kirby, bailey_ober, blake_snell, paul_skenes, mitch_keller, jose_berrios, logan_allen, mackenzie_gore, zach_eflin, ryne_nelson, jameson_taillon, ryan_feltner, luis_severino, randy_vasquez, adrian_houser, stephen_kolek, dean_kremer, michael_mcgreevy, tyler_mahle, ranger_suárez, cade_horton, luis_castillo

**Review tool:** `PYTHONPATH=. python bin/mlb/review_blacklist.py --since 2026-03-27` (run after 4-6 weeks of data)

## BQ Tables — Verified Status

### Training Data (all healthy)
| Table | Rows (2025) | Latest |
|-------|-------------|--------|
| `mlb_analytics.pitcher_game_summary` | 5,081 | 2025-09-28 |
| `mlb_raw.bp_pitcher_props` | 7,355 | 2025-09-28 |
| `mlb_analytics.pitcher_rolling_statcast` | 17,616 | 2025-10-01 |
| `mlb_raw.fangraphs_pitcher_season_stats` | 3,408 | 2025 season |

### Output Tables (schemas verified)
- `mlb_predictions.pitcher_strikeouts`
- `mlb_predictions.signal_best_bets_picks`
- `mlb_predictions.best_bets_filter_audit`

### Supplemental (empty — expected, fill after season resume)
- `mlb_raw.mlb_umpire_assignments` — 2,474 rows (2025 backfill), no 2026 yet
- `mlb_raw.mlb_umpire_stats` — 0 rows (fills during season)
- `mlb_raw.mlb_weather` — 0 rows
- `mlb_raw.catcher_framing` — 0 rows
- `mlb_raw.mlb_schedule` (2026) — 0 rows (fills after scraper resume)

## Bootstrap Period

The system needs ~6-7 weeks to reach full performance:

| Period | BB HR | Picks/Day | Bottleneck |
|--------|-------|-----------|------------|
| Week 0-2 (Mar 27 - Apr 14) | ~56% | ~3 | Pitchers need 3+ starts for rolling features |
| Week 3-7 (Apr 15 - May 14) | ~58% | ~5 | Season stats (xFIP, CSW) still noisy |
| Week 8+ (May 15+) | ~68% | ~5 | Full signal coverage, stable features |

## Known Dead Ends (DO NOT Retry)

- Adding features to model (V12_noveg > V13 > V15 > V16)
- Dynamic pitcher blacklist (only 3 suppressed)
- Away edge floor changes (all within noise)
- Raising RSC gate to 3 (RSC=2 is best bucket at 75.9%)
- Composite scoring for ranking (fails cross-season)
- Ensembling models (averaging dilutes CatBoost signal)
- Cross-model agreement filtering (-3.1pp when unanimous)

**Full list:** `docs/08-projects/current/mlb-2026-season-strategy/05-DEAD-ENDS.md`

## Post-Opening Day Tasks

### 3-Week Checkpoint (Apr 14)
- Force retrain with in-season data
- Review blacklist: `PYTHONPATH=. python bin/mlb/review_blacklist.py --since 2026-03-27`
- If multi-model: compare live HR across CatBoost/LightGBM/XGBoost

### May 1: UNDER Decision Point
If OVER HR >= 58%: `--update-env-vars="MLB_UNDER_ENABLED=true"`
UNDER has 3 active signals + RSC gate of 3 — currently skeletal. Biggest untapped opportunity.

### May 15: Shadow Signal Promotion
Review 30 shadow signals accumulating live data. Promote those with HR >= 60% at N >= 30.

### Ongoing: Monthly Retrain
Every 14 days, 120-day window. Same governance gates.

## Key Files

| File | Purpose |
|------|---------|
| `scripts/mlb/training/train_regressor_v2.py` | CatBoost training |
| `scripts/mlb/training/train_lightgbm_v1.py` | LightGBM training |
| `scripts/mlb/training/train_xgboost_v1.py` | XGBoost training |
| `scripts/mlb/training/season_replay.py` | Walk-forward replay simulator |
| `ml/signals/mlb/signals.py` | All 58 signal classes (~2000 lines) |
| `ml/signals/mlb/registry.py` | Signal registration |
| `ml/signals/mlb/best_bets_exporter.py` | BB pipeline (filters → signals → rank → publish) |
| `predictions/mlb/worker.py` | Cloud Run worker (Flask, 6 endpoints) |
| `predictions/mlb/pitcher_loader.py` | Feature + betting line loading from BQ |
| `predictions/mlb/supplemental_loader.py` | Umpire, weather, game context, catcher framing |
| `predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py` | CatBoost predictor |
| `predictions/mlb/prediction_systems/lightgbm_v1_regressor_predictor.py` | LightGBM predictor |
| `predictions/mlb/prediction_systems/xgboost_v1_regressor_predictor.py` | XGBoost predictor |
| `predictions/mlb/Dockerfile` | Worker container (includes `COPY ml/` fix) |
| `predictions/mlb/requirements.txt` | Python deps (catboost, lightgbm, xgboost) |
| `cloudbuild-mlb-worker.yaml` | Cloud Build config for manual deploys |
| `bin/mlb-season-resume.sh` | Resume 24 scheduler jobs |
| `bin/mlb/review_blacklist.py` | Blacklist add/remove recommendations |
| `docs/08-projects/current/mlb-2026-season-strategy/03-DEPLOY-CHECKLIST.md` | Step-by-step deploy |
| `docs/08-projects/current/mlb-2026-season-strategy/06-SEASON-PLAN-2026.md` | Full season timeline |
| `docs/08-projects/current/mlb-2026-season-strategy/05-DEAD-ENDS.md` | What not to try |
| `docs/09-handoff/2026-03-10-SESSION-466-MLB-SEASON-REVIEW.md` | Full system deep dive |

## GCP Resources

| Resource | Value |
|----------|-------|
| Project | nba-props-platform |
| Region | us-west2 |
| MLB Worker | `mlb-prediction-worker` (Cloud Run) |
| Model Bucket | `gs://nba-props-platform-ml-models/mlb/` |
| BQ Dataset (predictions) | `mlb_predictions` |
| BQ Dataset (analytics) | `mlb_analytics` |
| BQ Dataset (raw) | `mlb_raw` |

## Warnings

1. **MLB worker is NOT auto-deployed.** Push to main deploys NBA services only. MLB needs manual `gcloud builds submit --config cloudbuild-mlb-worker.yaml`.
2. **Cloud Run traffic may not auto-route.** Always `update-traffic --to-latest` after deploy.
3. **NEVER `--set-env-vars`** — wipes all existing vars. Always `--update-env-vars`.
4. **Feature count is 36, not 40.** Docs/comments saying 40 are stale.
5. **numpy not installed locally.** Training scripts run in Cloud Run or need a venv. BQ SQL was validated via `--dry_run`.
6. **Spring Training data likely won't help training.** Starters rarely pitch 3+ IP. Training window will effectively end at Sep 2025.
7. **Supplemental data (umpire, weather, etc.) will be empty on opening day.** The pipeline handles this gracefully — predictions still generate, just without supplemental signals firing.
