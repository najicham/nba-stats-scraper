# Session 366 Handoff — Post-Filter Eval, Filter Health, Grid Search, Smarter Selection

**Date**: 2026-02-28
**Status**: All 10 phases COMPLETE. Deploy + backfill + experiments remaining.

## What Was Done

### New Tools (4 scripts)
1. **`bin/post_filter_eval.py`** — Compare raw model HR vs post-filter HR for any model
2. **`bin/monitoring/filter_health_audit.py`** — Audit all negative filters against live data
3. **`bin/model_family_dashboard.py`** — Per-model raw HR, BB HR, direction splits, weight
4. **`ml/experiments/grid_search_weights.py`** — Systematic experiment grid search with templates

### Production Code Changes
5. **`bin/backfill_dry_run.py`** — Added `--model-id` for single-model eval + direction affinity blocks
6. **`ml/analysis/model_performance.py`** — Added 15 columns: directional HR (over/under 7d/14d) + best-bets stats
7. **`ml/signals/supplemental_data.py`** — Post-filter HR fallback chain for model selection weight
8. **`ml/experiments/quick_retrain.py`** — Added `--machine-output` JSON flag

### Skill Updates
9. **daily-steering** — Now shows directional splits + best-bets HR per model
10. **validate-daily** — New Phase 0.585 filter health spot-check

### Schema Change (APPLIED)
```sql
-- Already executed against production
ALTER TABLE model_performance_daily ADD COLUMN IF NOT EXISTS
  rolling_hr_over_7d FLOAT64, rolling_hr_under_7d FLOAT64,
  rolling_n_over_7d INT64, rolling_n_under_7d INT64,
  rolling_hr_over_14d FLOAT64, rolling_hr_under_14d FLOAT64,
  rolling_n_over_14d INT64, rolling_n_under_14d INT64,
  best_bets_hr_14d FLOAT64, best_bets_hr_21d FLOAT64,
  best_bets_n_14d INT64, best_bets_n_21d INT64,
  best_bets_over_hr_21d FLOAT64, best_bets_under_hr_21d FLOAT64,
  best_bets_filter_pass_rate FLOAT64
```

## Morning Verification Results (Phase A)
- AWAY block: **Working** (0 AWAY picks from v9/v12_noveg post-deploy)
- V9 share: Reduced (0% on Feb 28)
- **3 of 4 new shadow models MISSING** (tierwt, v13, v15). Only 60d active with 0 edge 3+ picks.

---

## Remaining Tasks (Priority Order)

### 1. DEPLOY + BACKFILL (must do before experiments)
```bash
# Push to main (auto-deploys changed services)
git add bin/backfill_dry_run.py bin/post_filter_eval.py bin/monitoring/filter_health_audit.py \
        bin/model_family_dashboard.py ml/analysis/model_performance.py ml/signals/supplemental_data.py \
        ml/experiments/grid_search_weights.py ml/experiments/quick_retrain.py \
        .claude/skills/daily-steering/SKILL.md .claude/skills/validate-daily/SKILL.md
git commit -m "feat: post-filter eval tools, grid search, directional HR, smarter model selection"
git push origin main

# Backfill model_performance_daily with new columns (15-20 min)
PYTHONPATH=. python ml/analysis/model_performance.py --backfill --start 2026-02-01

# Verify backfill
bq query --use_legacy_sql=false "
SELECT model_id, rolling_hr_over_7d, rolling_hr_under_7d, best_bets_hr_21d
FROM nba_predictions.model_performance_daily
WHERE game_date = '2026-02-27' LIMIT 5"
```

### 2. Investigate Missing Shadow Models
3 of 4 Session 365 shadow models not generating predictions:
```bash
# Check if registered
bq query --use_legacy_sql=false "
SELECT model_id, enabled, status, gcs_path
FROM nba_predictions.model_registry
WHERE model_id LIKE '%tierwt%' OR model_id LIKE '%v13%' OR model_id LIKE '%v15%'"

# Check if GCS artifacts exist
gsutil ls gs://nba-props-platform-models/catboost/ | grep -E 'tierwt|v13_|v15_'
```
Likely fix: Register and/or enable in model_registry, then deploy worker.

### 3. Run Filter Health Audit
```bash
PYTHONPATH=. python bin/monitoring/filter_health_audit.py --start 2026-01-01 --end 2026-02-27
```
Expected: All filters HR < 55%. If `star_under` drifted above 55%, consider injury-aware refinement.

### 4. Run Post-Filter Eval on Key Models
```bash
# Best current model
PYTHONPATH=. python bin/post_filter_eval.py \
    --model-id catboost_v12_train1201_0215 \
    --start 2026-02-15 --end 2026-02-27

# V16 noveg
PYTHONPATH=. python bin/post_filter_eval.py \
    --model-id catboost_v16_noveg_train1201_0215 \
    --start 2026-02-15 --end 2026-02-27

# Model family dashboard (quick overview)
PYTHONPATH=. python bin/model_family_dashboard.py --days 21
```

### 5. Run Experiment Grid Search

**Priority 1: Tier weight sweep** (~3h, 12 combos)
```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --template tier_weight_sweep \
    --train-start 2025-12-01 --train-end 2026-02-15 \
    --eval-start 2026-02-16 --eval-end 2026-02-27 \
    --csv results/tier_weight_sweep.csv
```

**Priority 2: Feature set shootout** (~1h, 4 combos)
```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --template feature_set_shootout \
    --train-start 2025-12-01 --train-end 2026-02-15 \
    --csv results/feature_set_shootout.csv
```

**Priority 3: Recency × tier interaction** (~2h, 8 combos)
```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --template recency_tier \
    --train-start 2025-12-01 --train-end 2026-02-15 \
    --csv results/recency_tier.csv
```

**Priority 4: Custom — vegas weight fine-tuning** (~1h)
```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --base-args "--feature-set v12_noveg --no-vegas" \
    --grid "category-weight=vegas=0.20,vegas=0.25,vegas=0.30,vegas=0.35" \
    --train-start 2025-12-01 --train-end 2026-02-15 \
    --csv results/vegas_weight_fine.csv
```

### 6. Deploy Best Grid Search Winner
After grid search completes:
1. Identify best combo (highest HR edge 3+, gates PASS)
2. Train with `--force-register --enable` using winning params
3. Shadow 2+ days before promoting
4. Run post_filter_eval.py on new model to verify filter improvement

### 7. End-of-Session Checklist
```bash
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
./bin/check-deployment-drift.sh --verbose
```

## Key Risks
- **E2 change (supplemental_data.py)**: Model selection now depends on `model_performance_daily` being backfilled. Until backfill runs, all models fall through to 50% default weight (0.91) — same as new model behavior, so safe.
- **Missing shadow models**: 3 Session 365 models aren't generating predictions. Need investigation before grid search results can be compared to them.
- **Schema columns nullable**: All 15 new columns are nullable, so existing rows won't break. But old rows have NULLs — only new backfilled/computed rows will have data.
