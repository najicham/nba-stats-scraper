# Session 157 Handoff: Training Data Contamination Fix + Shared Loader

**Date:** 2026-02-07
**Focus:** Investigated and fixed training data contamination, created shared training data loader, archived legacy scripts

## What Was Done

### 1. Committed and Deployed Session 156 Changes
- Pushed 11-file diff (417 additions) covering cache fallback completion, training quality gates, and player filtering
- Cloud Build triggered: `deploy-nba-phase4-precompute-processors` built successfully

### 2. Training Data Contamination Diagnostic
**Finding: 33.2% of V9 training data was contaminated**

```
Total records in training window (Nov 2025 - Feb 2026): 21,183
Clean (required_default_count = 0): 14,153 (66.8%)
Contaminated (required_default_count > 0): 7,030 (33.2%)
```

Monthly breakdown:
- November: 68.0% contaminated (early season, many missing processors)
- December: 21.9% contaminated
- January: 17.2% contaminated
- February: 21.2% contaminated

Most commonly defaulted non-vegas features:
- Feature 19 (pct_mid_range): 5,298 defaults
- Features 18, 20 (pct_paint, pct_three): 4,010 each
- Features 13, 14 (opponent defense): 3,140 each
- Features 22, 23 (team context): 2,100 each

### 3. Root Cause Analysis

**The bug:** `feature_quality_score` is a weighted average across all 37 features. A record with 5 defaulted features still scores 91.9 (passing the >= 70 threshold) because 32 good features "carry" the average up.

**Why it wasn't caught:** The system had two separate quality gates:
- `is_quality_ready` (uses `required_default_count = 0`) — used by **prediction pipeline** since Session 141
- `feature_quality_score >= 70` (weighted average) — used by **training scripts**

These were never reconciled. Training scripts used the weaker gate.

**Why contamination happened at the data level:**
1. PlayerDailyCacheProcessor only cached players with today's games
2. Cache miss fallback was incomplete (10 of 25+ fields)
3. Players returning from injury got records with 7+ defaults
4. Feature store created records for players with zero recent game history

### 4. V9 Retrain Evaluation

Trained clean model with zero-tolerance filters:
- Training data: 9,746 samples (down from ~14,000 with contamination)
- MAE: 5.20 vs 5.14 baseline (+0.06)
- Hit rate: 50.00% vs 54.53% baseline (-4.53%) on 6-day eval window
- Tier bias: Stars -9.11, Bench +7.20 (pre-existing issue, not from contamination)

**Decision: Don't deploy retrained model yet.** The 6-day eval window is too small for reliable comparison. Wait 2-3 weeks for clean data to accumulate, then retrain with 14+ day eval window.

### 5. Created Shared Training Data Loader

**New file: `shared/ml/training_data_loader.py`**

Single source of truth for ML training data quality filters. Three functions:
- `get_quality_where_clause(alias)` — for WHERE conditions
- `get_quality_join_clause(alias)` — for LEFT JOIN ON conditions
- `load_clean_training_data(client, start, end)` — full DataFrame loader with validation

Quality filters enforced at SQL level, cannot be bypassed:
```sql
COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
AND mf.feature_count >= 33
AND mf.feature_quality_score >= 70
AND mf.data_source NOT IN ('phase4_partial', 'early_season')
```

Validation prevents setting quality score below 50.

### 6. Migrated All Active Training Scripts

| Script | Migration |
|--------|-----------|
| `quick_retrain.py` | Uses `load_clean_training_data()` and `get_quality_where_clause()` |
| `train_breakout_classifier.py` | Uses `get_quality_where_clause()` via helper |
| `breakout_experiment_runner.py` | Uses `get_quality_where_clause()` via helper |
| `backfill_breakout_shadow.py` | Uses `get_quality_join_clause()` via helper |
| `breakout_features.py` | Uses `get_quality_join_clause()` via helper |
| `evaluate_model.py` | Added inline quality filters |

### 7. Archived 41 Legacy Scripts

Moved to `ml/archive/` and `ml/archive/experiments/`:
- 30 legacy training scripts (V6-V10 era, no quality filters)
- 11 legacy experiment scripts

Active directories now contain only 15 files total — all verified to have quality filters.

## What Was NOT Done

### 1. V9 Retrain and Deploy
The retrained model showed comparable MAE but worse hit rate on a tiny eval window. Need more clean data before making a decision. Recommend waiting until ~Feb 20 and retraining with 14+ day eval.

### 2. Feature Store Backfill
Historical feature store records were NOT re-processed with the improved fallback. The Session 156 improvements will produce better features going forward but existing records still have the old defaults. Consider backfilling Jan-Feb 2026 for better training data.

### 3. Tier Bias Investigation
Both the original V9 and clean retrain show regression-to-mean bias: underestimates stars (-9 pts), overestimates bench (+7 pts). This is a separate issue from contamination and needs investigation.

## Key Files

```
shared/ml/training_data_loader.py          # NEW: Shared quality enforcement
ml/experiments/quick_retrain.py             # UPDATED: Uses shared loader
ml/experiments/train_breakout_classifier.py # UPDATED: Uses shared loader
ml/experiments/breakout_experiment_runner.py # UPDATED: Uses shared loader
ml/experiments/backfill_breakout_shadow.py  # UPDATED: Uses shared loader
ml/experiments/evaluate_model.py            # UPDATED: Added quality filters
ml/features/breakout_features.py            # UPDATED: Uses shared loader
ml/archive/                                 # 41 archived legacy scripts
```

## Prevention Summary

The contamination bug can no longer recur because:

1. **Shared loader enforces filters at SQL level** — `training_data_loader.py`
2. **Validation rejects weak quality scores** — min 50, recommended 70
3. **Post-query validation** — `load_clean_training_data()` verifies zero tolerance in returned data
4. **Legacy scripts archived** — only quality-filtered scripts remain active
5. **100% coverage verified** — automated check confirms every active script with feature store queries has quality filters

## Next Session Priorities

1. **Wait for clean data** — Monitor feature store quality for 2-3 weeks
2. **V9 retrain** (~Feb 20) — Retrain with larger eval window (14+ days)
3. **Feature store backfill** — Re-run ML feature store for Jan-Feb 2026 dates
4. **Tier bias investigation** — Separate from contamination, affects both old and new models
