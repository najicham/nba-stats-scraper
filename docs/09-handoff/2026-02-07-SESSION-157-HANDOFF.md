# Session 157 Handoff: Training Data Contamination Fix + Shared Loader

**Date:** 2026-02-07
**Focus:** Investigated and fixed training data contamination, created shared training data loader, archived legacy scripts, fixed quality scores

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

**The bug:** `feature_quality_score` was a weighted average across all 37 features. A record with 5 defaulted features could score 91.9 (passing >= 70 threshold) because good features carried the average. Training scripts used this score instead of `required_default_count = 0`.

**Three layers of fix implemented:**
1. **Shared training data loader** (`shared/ml/training_data_loader.py`) — enforces `required_default_count = 0` at SQL level
2. **Quality score cap** (`quality_scorer.py`) — records with 1+ required defaults now capped at 69, 5+ capped at 49
3. **Historical score fix** — SQL UPDATE fixed 7,088 records in BigQuery so `feature_quality_score >= 70` now excludes all contaminated records

### 4. Created Shared Training Data Loader

**New file: `shared/ml/training_data_loader.py`**

Single source of truth for ML training data quality filters:
- `get_quality_where_clause(alias)` — for WHERE conditions
- `get_quality_join_clause(alias)` — for LEFT JOIN ON conditions
- `load_clean_training_data(client, start, end)` — full DataFrame loader with validation

### 5. Migrated All Active Training Scripts + Archived 41 Legacy

6 active scripts migrated to shared loader. 41 legacy V6-V10 scripts moved to `ml/archive/`.

### 6. Fixed Quality Score Calculation

**quality_scorer.py** now caps scores when required (non-vegas) defaults exist:
- 1+ required defaults → max 69 (below bronze threshold)
- 5+ required defaults → max 49 (critical tier)
- Vegas-only defaults → no cap (optional features)

### 7. Fixed Historical Quality Scores in BigQuery

SQL UPDATE applied to 7,088 records (Nov 2025 - Feb 2026). After fix:
- Records with 1-4 defaults: all capped at 69 (0 pass >= 70 filter)
- Records with 5+ defaults: avg 58.2, max 69 (0 pass >= 70 filter)
- Clean records: unchanged, 14,406 pass >= 70

### 8. V9 Retrain Evaluation (Inconclusive)

Trained clean model — eval window too small (6 days, 467 samples). Decision: wait for backfill + 2-3 weeks of clean data, then retrain.

## Commits Made

1. `327770c9` — Session 156 changes (cache fallback, training quality gates, player filter)
2. `e49f00ac` — Shared training data loader + archive 41 legacy scripts
3. `a0f84491` — Session 157 handoff docs
4. `518edba4` — Quality score cap fix

## What Was NOT Done — Next Session Must Do

### Priority 1: Feature Store Backfill (CURRENT SEASON)

**Goal:** Re-run ML feature store processor for Nov 2025 - Feb 2026 (~98 game dates) with Session 156 improvements. This will:
- Produce fewer defaults (improved cache fallback fills 25+ fields)
- Filter out returning-from-injury players with no recent games
- Give the V9 retrain much better training data

**Backfill scripts available:**
```bash
# Option 1: Simple regenerate script (recommended)
PYTHONPATH=. python scripts/regenerate_ml_feature_store.py \
  --start-date 2025-11-02 --end-date 2026-02-07

# Option 2: Full backfill with checkpoints
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-11-02 --end-date 2026-02-07 --include-bootstrap
```

**IMPORTANT: Review backfill script before running.** Consider:
1. **Should PlayerDailyCacheProcessor also be re-run?** Session 156 expanded its player selection (UNION with roster players). The ML feature store depends on daily cache data. If cache is stale, feature store will still have gaps.
2. **Add logging for missing data.** When a feature can't find upstream data and falls back to default, log which player/date/feature was affected so we can identify data gaps to fix.
3. **Verify the script uses the deployed code.** The regenerate script imports `MLFeatureStoreProcessor` directly from the local codebase, which now has Session 156 changes. Make sure this is the current code.

### Priority 2: Tier Bias Investigation

Both V9 and clean retrain show regression-to-mean: stars underestimated by 9 pts, bench overestimated by 7 pts. Investigate and fix.

### DO NOT Retrain V9 Yet

V9 is performing adequately (54-56% hit rate, 65%+ at edge 3+). A clean retrain was tested in Session 157 but the 6-day eval window was too small for reliable comparison. **Wait until end of February for the regular monthly retrain.** By then the backfilled data + new clean data will give a much better training set.

## Feature Ideas to Explore Later

User suggested investigating these signals (not yet implemented):

1. **games_missed_in_last_10** — How many of the team's last 10 games did the player miss? Indicates injury/rest patterns. Could help identify "rust" after returning.

2. **days_on_current_team** — For recently traded players, track how long they've been on the new team. Players on new teams may have unpredictable usage patterns for the first 5-10 games.

**Where to add:** These would be new features in `feature_extractor.py` and added to a V11 contract. Not urgent but worth investigating for model improvement.

## Prevention Summary (3 Layers)

1. **Layer 1 — Shared loader** (`training_data_loader.py`): Enforces `required_default_count = 0` at SQL level
2. **Layer 2 — Quality score cap** (`quality_scorer.py`): 1+ defaults → max 69, fails >= 70 filter
3. **Layer 3 — Historical fix**: 7,088 BigQuery records updated, zero contaminated records pass filters

## Key Files

```
shared/ml/training_data_loader.py                              # NEW: Shared quality enforcement
data_processors/precompute/ml_feature_store/quality_scorer.py  # UPDATED: Score capping
ml/experiments/quick_retrain.py                                # UPDATED: Uses shared loader
ml/experiments/train_breakout_classifier.py                    # UPDATED: Uses shared loader
ml/experiments/breakout_experiment_runner.py                    # UPDATED: Uses shared loader
ml/experiments/backfill_breakout_shadow.py                     # UPDATED: Uses shared loader
ml/experiments/evaluate_model.py                               # UPDATED: Quality filters
ml/features/breakout_features.py                               # UPDATED: Uses shared loader
ml/archive/                                                    # 41 archived legacy scripts
scripts/regenerate_ml_feature_store.py                         # Backfill tool (review before using)
```
