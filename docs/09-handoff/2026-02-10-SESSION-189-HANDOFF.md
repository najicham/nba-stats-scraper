# Session 189 Handoff — Breakout Dead Ends, Subset Planning, QUANT Fixes

**Date:** 2026-02-10
**Previous:** Session 188 (Verification, model assessment, scrapers deploy)
**Focus:** Breakout regression experiments, multi-model subset architecture, QUANT shadow cleanup

## What Was Done

### 1. Breakout Classifier — Confirmed Dead Ends, Kept Disabled

Ran 8 experiments across two approaches to improve breakout detection:

**Approach 1: Quantile Regression on Binary Target (Session 187)**

| Model | AUC | Max Score | Result |
|-------|-----|-----------|--------|
| Baseline (Classifier) | 0.5658 | ~0.60 | Best of 4, but weak |
| Q43 (alpha=0.43) | 0.5062 | 0.050 | Collapsed — all predictions near 0 |
| Q50 (alpha=0.50) | 0.5062 | 0.050 | Collapsed — identical to Q43 |
| Q57 (alpha=0.57) | 0.5097 | 0.050 | Collapsed — all predictions near 0 |

**Why it failed:** 83.4% of targets are 0 — the quantile learner predicts near-zero for everything. No gradient signal for the minority class on binary targets.

**Approach 2: Regression Reframe — Predict Points, Derive Breakout (Session 189)**

| Model | AUC | MAE | Bias | Flagged | Precision | Recall |
|-------|-----|-----|------|---------|-----------|--------|
| RMSE baseline | 0.5555 | 5.13 | -0.34 | 4/716 | 50.0% | 1.4% |
| Q43 (alpha=0.43) | **0.5813** | 5.23 | -1.79 | 2/716 | 0.0% | 0.0% |
| Q50 (alpha=0.50) | 0.5487 | 5.25 | -0.94 | 4/716 | 0.0% | 0.0% |
| Q57 (alpha=0.57) | 0.5391 | 5.22 | +0.16 | 6/716 | 33.3% | 1.4% |

**Why it failed:** Predicted point ranges are compressed (5-20 vs actual 0-43), so almost no predictions cross the 1.5x breakout threshold. The model learned to predict near the mean and can't identify breakout events.

**Conclusion:** The breakout problem needs better features (star_teammate_out, opponent injuries), not better loss functions. 87+ experiments across Sessions 134-189 confirm this. V3 roadmap is in `ml/features/breakout_features.py` BREAKOUT_FEATURE_ORDER_V3.

**Action:** Reverted Session 188's uncommitted breakout classifier re-enable. Keeping disabled until V3 features are implemented.

### 2. Fixed QUANT System ID Warning in data_loaders.py

**Problem:** Cloud Run logs showed `Unknown system_id catboost_v9_q43_train1102_0131 with value 92.0, assuming already percentage` on every prediction. The `normalize_confidence()` function didn't recognize QUANT system_ids.

**Fix:** Added `system_id.startswith('catboost_v9')` to the 0-100 scale check. This covers the champion + all monthly/quantile shadows without needing to register each one individually.

**Impact:** Cosmetic (confidence values were handled correctly), but cleans up ~40 warning messages per prediction run.

### 3. Multi-Model Subset Architecture Research

Explored the entire subset system to plan QUANT model integration.

**Current state:** 8 active subsets, all hardcoded to `system_id = 'catboost_v9'` in 20+ code locations across 14 files.

**Key hardcoded files:**
- `data_processors/publishing/subset_materializer.py` (4 instances)
- `data_processors/publishing/all_subsets_picks_exporter.py` (5 instances)
- `predictions/coordinator/coordinator.py` (8+ instances)
- `shared/notifications/subset_picks_notifier.py` (3 instances)

**Schema supports multi-model** — `dynamic_subset_definitions.system_id` column exists but code ignores it.

**Proposed QUANT subsets (post-promotion):**
- `q43_under_high_edge` — 7+ edge, UNDER only (~73% expected HR)
- `q43_under_top5` — 5+ edge, UNDER, GREEN/YELLOW signal, top 5
- `q43_all` — 3+ edge, any direction (full evaluation)
- `q45_under_high_edge` — 7+ edge, UNDER only (~68% expected HR)
- `q45_all` — 3+ edge, any direction

### 4. Updated Project Documentation

- `06-MODEL-MONITORING-STRATEGY.md` — Added multi-model subset strategy, breakout dead ends, Session 189 lessons
- `00-SUBSET-REFERENCE.md` — Added "Future: Quantile Model Subsets" section with implementation plan
- `SESSION-188-HANDOFF.md` — Fixed phantom commit reference, corrected breakout status

### 5. QUANT Shadow Status Check

| Model | Feb 10 Predictions | Actionable | Avg Bias | Graded |
|-------|-------------------|------------|----------|--------|
| champion | 20 | 4 | +0.42 | Yes |
| _0108 | 20 | 0 | -0.02 | Yes |
| _0131_tuned | 20 | 0 | +0.09 | Yes |
| **QUANT_43** | **2** | **0** | **-1.20** | No |
| **QUANT_45** | **2** | **0** | **-1.35** | No |

Low QUANT volume (2 vs 20) is confirmed as a timing issue — deployed after main prediction run. Expected UNDER bias visible in the 2 predictions. Full volume expected on next daily run.

Phase 2→3 trigger: Still `_triggered: False` for Feb 10 (only 2/5 processors done — games haven't completed yet).

## Quick Start for Next Session

```bash
# 1. CRITICAL: Check QUANT prediction volume (should be ~20+ by Feb 11)
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as total,
       COUNTIF(is_actionable) as actionable
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE 'catboost_v9_%'
  AND game_date >= '2026-02-10'
GROUP BY 1, 2 ORDER BY 2 DESC, 1"

# 2. Check Phase 2→3 trigger fired for Feb 10
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase2_completion').document('2026-02-10').get()
if doc.exists:
    data = doc.to_dict()
    print(f'_triggered: {data.get(\"_triggered\", False)}')
    processors = [k for k in data.keys() if not k.startswith('_')]
    print(f'Processors ({len(processors)}): {sorted(processors)}')
"

# 3. Model landscape (once grading available)
PYTHONPATH=. python bin/compare-model-performance.py --all --days 7

# 4. If QUANT has 3+ days of data: segment breakdown
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --segments --days 7

# 5. Daily validation
/validate-daily
```

## Pending Follow-Ups

### P0 — Immediate
1. **Verify QUANT full prediction volume** — Should be 15-20+ predictions per model per game day by Feb 11
2. **Verify Phase 2→3 trigger fires** — Feb 10 is first real test
3. **Monitor champion decay** — 43.8% HR edge 3+ (Feb 8 week), losing money

### P1 — This Week (~Feb 14-15)
4. **Model promotion decision** — Once QUANT_43 has 3-5 days of production data
5. **Narrow quantile alpha** — Try alpha 0.41, 0.42, 0.44 around the 0.43 sweet spot
6. **QUANT_43 + recency weighting** — `--recency-weight 30` experiment

### P2 — Multi-Model Subsets (After Promotion)
7. **Parameterize system_id** — Remove hardcoded 'catboost_v9' from 20+ files
8. **Insert QUANT subset definitions** — In BigQuery `dynamic_subset_definitions`
9. **Backfill QUANT materialized picks** — For all dates with QUANT predictions
10. **Update public names mapping** — `shared/config/subset_public_names.py`

### P3 — Breakout V3 (Lower Priority)
11. **Implement V3 contextual features** — `star_teammate_out`, `fg_pct_last_game`, opponent injuries
12. **Retrain model with V3 features** — Use `breakout_experiment_runner.py --mode shared`
13. **Re-enable classifier** — Only after V3 model achieves AUC > 0.65 with high-confidence predictions

## Key Findings

### Quantile Regression: Domain-Specific Conclusions

| Target Type | Works? | Why |
|-------------|--------|-----|
| Continuous (points scored) | Yes — V9 props | Bias in loss function creates edge vs Vegas |
| Binary (is_breakout) | **No** | 83% zeros, no gradient signal for minority class |
| Continuous then derive binary | **No** | Predicted range compression defeats thresholds |

**Rule:** Quantile regression only works when the target is naturally continuous AND the threshold for "success" is relative to an external reference (Vegas line). It fails when the target is binary or when success requires absolute prediction magnitude.

### Subset System: Ready for Multi-Model

The BQ schema already supports `system_id` per subset definition. The blocker is Python code with 20+ hardcoded `'catboost_v9'` strings. Implementation is mechanical (parameterize, not redesign).

### 87+ Total Experiments (Sessions 134-189)

Updated dead ends list:
- Grow policy changes (Depthwise, Lossguide) — zero edge picks
- NO_VEG + quantile — double low-bias, too aggressive
- CHAOS + quantile — randomization dilutes precision
- Residual mode — collapses with CatBoost
- Two-stage pipeline — identical to NO_VEG
- **Quantile on binary classification — collapses** (Session 189)
- **Regression reframe for breakout — range compression** (Session 189)
