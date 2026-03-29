# Session 503 Handoff — 2026-03-30 (Monday Morning)

**Context:** Session 502 completed a 27-issue system-wide audit and fix. Most changes are
deployed. This session starts with Monday morning tasks (retrain verification + Session G deploy)
and then monitors the results.

---

## IMMEDIATE ACTION: Monday Morning Sequence

### Step 1 — Check if weekly retrain fired (5 AM ET)
```bash
# Did weekly-retrain CF fire?
gcloud functions logs read weekly-retrain --region=us-west2 --limit=50 | head -30

# Check model registry for new models
./bin/model-registry.sh list
```

### Step 2 — Run BQ schema migration (do this FIRST, before Step 3)
```sql
-- Run in BQ console (https://console.cloud.google.com/bigquery)
ALTER TABLE `nba-props-platform.nba_predictions.filter_overrides`
  ADD COLUMN IF NOT EXISTS demote_start_date DATE,
  ADD COLUMN IF NOT EXISTS re_eval_date DATE;
```
Verify: `SELECT demote_start_date, re_eval_date FROM nba_predictions.filter_overrides LIMIT 1`

### Step 3 — Deploy Session G (decay_detection auto-retrain alert)
The file is already modified locally but NOT committed. Deploy after retrain completes:
```bash
git status  # Should show: M orchestration/cloud_functions/decay_detection/main.py
git add orchestration/cloud_functions/decay_detection/main.py
git commit -m "feat: add BLOCKED model stale retrain alert to decay_detection

trigger_retrain_if_stale() alerts #deployment-alerts when a model has been
BLOCKED for 7+ days. RETRAIN_ON_BLOCKED=false by default (alert-only mode).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push origin main
```

### Step 4 — After retrain + deploy, sync registry
```bash
./bin/model-registry.sh sync
./bin/refresh-model-cache.sh --verify
```

### Step 5 — Run morning checks
```bash
/daily-steering       # Full morning report
/validate-daily       # Pipeline validation
./bin/check-deployment-drift.sh --verbose
```

---

## Current System State (as of 2026-03-29 EOD)

### NBA Fleet (DEGRADED — retrain critical)
| Model | State | 7d HR |
|-------|-------|-------|
| `lgbm_v12_noveg_train0121_0318` | WATCH | 56.5% |
| `lgbm_v12_noveg_train0103_0227` | DEGRADING | 53.0% |
| `catboost_v12_noveg_train0121_0318` | BLOCKED | 45.5% |
| `catboost_v12_noveg_train0118_0315` | BLOCKED | 46.2% |

**Expected Monday:** weekly-retrain fires at 5 AM ET with TIGHT cap (train window Jan 9–Mar 7).
After new models train and pass governance gates, fleet should recover.

### MLB Pipeline (just went live 2026-03-28)
- **Phase 4 crash FIXED** today (Session 502-A) — `bdl_pitchers` → `bdl_active_pitchers`
- Monitor: `gcloud run services logs read mlb-phase4-precompute-processors --limit=20`
- Verify predictions are generating for today's games

### Auto-Deploys Triggered by Session 502 (verify these completed)
```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=10
```
Services that were rebuilt:
- `mlb-phase4-precompute-processors` (MLB crash fix)
- `nba-phase3-analytics-processors` (libgomp1)
- `nba-phase4-precompute-processors` (libgomp1 + tzdata)
- `nba-grading-service` grading/nba (libgomp1)
- `prediction-coordinator` (libgomp1)
- `nba-scrapers` (libgomp1)
- `services/admin_dashboard` (prediction_grades migration)
- `services/nba_grading_alerts` (prediction_grades migration)
- `filter-counterfactual-evaluator` CF (expiry logic)
- `daily-health-check` CF (grading freshness check)

---

## What Was Changed in Session 502 (quick reference)

| Issue | Fix | File |
|-------|-----|------|
| MLB Phase 4 crash | Use `bdl_active_pitchers` VIEW | `pitcher_features_processor.py:515` |
| 6 Dockerfiles missing libgomp1 | Added apt-get install | analytics, precompute, grading/nba, grading/mlb, coordinator, scrapers |
| 11× `--set-env-vars` | → `--update-env-vars` | 9 deploy scripts |
| Hardcoded 756957797294 | Substitution variable | `cloudbuild-functions.yaml`, `weekly_retrain/deploy.sh` |
| No MLB canary | 3 new CanaryChecks | `pipeline_canary_queries.py` |
| Filter overrides never expire | 14-day re-eval + `check_reactivation()` | `filter_counterfactual_evaluator/main.py` |
| CF evaluator non-consecutive days | Streak CTE, 10-day window | `filter_counterfactual_evaluator/main.py` |
| BLOCKED models never alert | `trigger_retrain_if_stale()` | `decay_detection/main.py` (**UNSTAGED**) |
| `prediction_grades` deprecated refs | → `prediction_accuracy` | `bigquery_service.py`, `nba_grading_alerts/main.py` |
| No grading completion check | `check_grading_freshness()` | `daily_health_check/main.py` |
| Feature drift detector outdated | 34 → 60 features | `feature_drift_detector.py` |
| `ensemble_v1` hardcoded default | Dynamic champion lookup | `scoring_tier_processor.py` |
| No per-model grading check | `detect_per_model_grading_gaps()` | `grading_gap_detector.py` |
| OFFSET SQL deprecated pattern | `feature_N_value` column names | `2026-01-29` patch SQL |
| Pick angles missing context | Rescue + TIGHT market angles | `pick_angle_builder.py` |
| `book_disagreement` HR below breakeven | Added to CF evaluator auto-demote eligible | `filter_counterfactual_evaluator/main.py` |
| NumberFire SPOF undocumented | Warning note added | Scraper inventory docs |
| `win_flag` always False undocumented | Inline comment at both False locations | `player_game_summary_processor.py` |

---

## Open Items to Monitor

### 1. Monday Retrain Outcome
After retrain:
- New models should appear with training window Jan 9–Mar 7 (TIGHT cap applied)
- All 4 enabled families should retrain: `lgbm_v12_noveg`, `catboost_v12_noveg` + variants
- Governance gates: HR ≥ 60% at edge 3+, N ≥ 25, vegas bias ±1.5
- If models pass gates and are promoted, fleet health should improve

### 2. TIGHT Market Cap — Is It Still TIGHT?
```sql
SELECT game_date, vegas_mae_7d, market_regime
FROM nba_predictions.league_macro_daily
WHERE game_date >= CURRENT_DATE() - 7
ORDER BY game_date DESC
```
If `vegas_mae_7d < 4.5` = TIGHT: train window is capped at Mar 7.
If market loosened: train window can extend closer to today.

### 3. First MLB Predictions Validation
March 30 is an MLB game day. Verify predictions generate:
```sql
SELECT game_date, COUNT(*) as predictions
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = CURRENT_DATE()
GROUP BY 1
```
If 0: check if Phase 4 deployed successfully (`gcloud run services describe mlb-phase4-precompute-processors`)

### 4. Admin Dashboard Smoke Test
The `prediction_grades` → `prediction_accuracy` migration could have broken dashboard charts.
Open the admin dashboard and check:
- Accuracy metrics load without BQ errors
- 7-day grading stats show correctly

### 5. Filter Overrides Schema Migration
Verify BQ ALTER TABLE ran successfully:
```sql
SELECT column_name
FROM nba_predictions.INFORMATION_SCHEMA.COLUMNS
WHERE table_name = 'filter_overrides'
ORDER BY ordinal_position
```
Should show: `filter_name, override_type, reason, cf_hr_7d, n_7d, triggered_at, triggered_by, active, demote_start_date, re_eval_date`

### 6. `home_under` UNDER pick drought
Per recent context, most UNDER picks have real_sc=1. After Monday retrain, check if UNDER
pick volume improves (new models may generate more UNDER candidates):
```sql
SELECT game_date, COUNT(*) as under_picks
FROM nba_predictions.signal_best_bets_picks
WHERE recommendation = 'UNDER' AND game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC
```

---

## Commands Quick Reference

```bash
# Morning sequence
/daily-steering
/validate-daily
./bin/check-deployment-drift.sh --verbose

# Model registry
./bin/model-registry.sh list          # Show all models + states
./bin/model-registry.sh sync          # Sync GCS manifest → BQ
./bin/refresh-model-cache.sh --verify # Force worker to reload model list

# Reset a demoted filter (new tool from Session 502)
python bin/monitoring/reset_demoted_filter.py --filter-name FILTER_NAME --dry-run
python bin/monitoring/reset_demoted_filter.py --filter-name FILTER_NAME

# Check MLB predictions
gcloud run services logs read mlb-phase4-precompute-processors --region=us-west2 --limit=20
gcloud run services logs read mlb-predictions-worker --region=us-west2 --limit=20

# Manual retrain if needed
./bin/retrain.sh --all --enable --no-production-lines
```

---

## Key Dates
- **2026-03-30 5 AM ET:** weekly-retrain fires
- **2026-03-30 (Monday):** NBA game day — predictions should generate after retrain
- **2026-03-30:** MLB Opening Week continues — validate pitcher predictions
