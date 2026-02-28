# Session 367 Handoff — Filter Relaxation + Grid Search Experiments

**Date**: 2026-02-28
**Status**: COMPLETE — filter changes deployed, grid search experiments finished.

## What Was Done

### Phase 1: Filter Relaxation (DEPLOYED)

**Problem**: Two negative filters blocking profitable picks above breakeven (52.4%):
- `star_under`: 55.3% HR on 519 blocked picks
- `under_edge_7plus_non_v12`: 56.2% HR on 635 blocked picks

**BQ Validation Results**:

1. **star_under by period**: Jan was 65-68% HR (all models), Feb declined to 48-53%. Broad-based collapse, not model-specific.
2. **star_under with injury context**: `star_teammates_out >= 1` = 58.3% HR vs 55.6% without (+2.7pp). Both above breakeven.
3. **under_edge_7plus by model**: V9 = 34.1% HR (N=41, catastrophic). No V16/V13/V15/LightGBM data yet. "Other" models = 57.9%.

**Changes Made**:

1. **`ml/signals/aggregator.py`** — star_under filter now injury-aware:
   - Allows star UNDER when `star_teammates_out >= 1` (feature_37_value from feature store)
   - Blocks star UNDER only when no star teammate is out
   - Rationale: Usage boost from injured teammates shifts scoring distribution

2. **`ml/signals/aggregator.py`** — under_edge_7plus narrowed to V9 only:
   - Was: blocks ALL non-V12 models at UNDER edge 7+
   - Now: blocks only V9 family (excluding v9_low_vegas) at UNDER edge 7+
   - V16/V13/V15/LightGBM now pass through

3. **`ml/signals/supplemental_data.py`** — piped `feature_37_value` (star_teammates_out):
   - Added to `book_stats` CTE, SELECT output, and prediction dict

4. **Algorithm version**: `v367_star_under_injury_aware_under7plus_v9_only`

**Backfill Validation (Feb 15-27)**:
- 66.7% HR (12W-6L) on 18 graded picks
- Est P&L: +$540
- `star_under` still filtered 15 picks (star UNDER without injured teammates)
- `under_edge_7plus` had 0 rejections (V9 edge 7+ UNDER picks rare in multi-model selection)
- All 20 picks were OVER — UNDER pass rate still low but structurally improved

### Phase 2: Grid Search Experiments (COMPLETE)

**Fix**: `grid_search_weights.py` was missing `--force` flag, causing all experiments to silently abort at duplicate training dates check. Fixed with `--force` + diagnostic logging.

**Feature Set Shootout** (4 combos, all with vegas=0.25):

| Feature Set | HR 3+ | N | HR 5+ | OVER | UNDER | MAE |
|------------|-------|---|-------|------|-------|-----|
| **v12_noveg** | **73.1%** | 26 | 83.3% | 100% | 61.1% | 5.15 |
| v13 | 66.7% | 21 | 85.7% | 100% | 50.0% | 5.16 |
| v15 | 61.9% | 21 | 100% | 75.0% | 53.8% | 5.21 |
| v16_noveg | 60.0% | 25 | 66.7% | 81.8% | 42.9% | 5.24 |

**v12_noveg dominates** — best HR, best UNDER, best MAE. Adding features (V13 shooting, V15 profile, V16 deviation) does NOT improve performance. V12_noveg's simplicity is its strength.

**Vegas Fine-Tune** (v12 WITH vegas, 5 weight levels):

| Weight | HR 3+ | N | OVER | UNDER | MAE |
|--------|-------|---|------|-------|-----|
| **0.15** | **76.2%** | 21 | 100% | 61.5% | 5.15 |
| **0.25** | **76.2%** | 21 | 100% | 61.5% | 5.20 |
| 0.35 | 72.2% | 18 | 100% | 54.5% | 5.20 |
| 0.30 | 66.7% | 18 | 100% | 40.0% | 5.25 |
| 0.20 | 64.7% | 17 | 87.5% | 44.4% | 5.20 |

vegas=0.15 and 0.25 are TIED at 76.2% HR. 0.15 has slightly better MAE. Weight 0.30+ degrades UNDER. Non-monotonic: 0.20 is worse than 0.25, suggesting noise at these sample sizes.

**Tier Weight Sweep** (12 combos, v12_noveg + vegas=0.25):

| Rank | Weights | HR 3+ | N | OVER | UNDER |
|------|---------|-------|---|------|-------|
| 1 | star=2.0,s=1.2,r=0.8,b=0.3 | **75.0%** | 20 | 100% | 61.5% |
| 2 | star=2.0,s=1.5,r=1.0,b=0.8 | **73.9%** | 23 | 88.9% | **64.3%** |
| 3 | star=3.0,s=1.0,r=0.8,b=0.5 | **73.1%** | 26 | 83.3% | **64.3%** |
| 12 | star=2.5,s=1.3,r=0.8,b=0.3 | 63.0% | 27 | 88.9% | 50.0% |

**All combos fail governance gates** (N < 50 edge 3+, short eval window). Top combo (star=2.0,s=1.2,r=0.8,b=0.3) at 75% but N=20. The #3 combo has largest sample (N=26) with best UNDER (64.3%).

**Key takeaway**: Tier weighting adds 2-3pp HR but needs more evaluation data. The baseline v12_noveg is already at 73.1%.

### Deployment Status

- prediction-coordinator: manually deployed (ml/signals/ not in auto-trigger watch paths)
- Cloud Builds: phase6-export, live-export, post-grading-export triggered from push
- prediction-worker: not affected (no changes)

## Key Findings

### Star UNDER Is Above Breakeven
The star_under filter was overly aggressive. Originally justified at 51.3% HR, the revalidation shows 55.3% overall. Injury-aware version allows the highest-confidence subset (58.3%) while keeping the marginal ones blocked.

### V9 UNDER 7+ Is Structural
V9's catastrophic UNDER performance (34.1%) is model-specific, not a general UNDER problem. Blocking ALL non-V12 models was preventing V16/V13/V15/LightGBM from contributing UNDER picks at high edge. These newer models should not inherit V9's structural weakness.

### V12_NOVEG Is The Best Feature Set
Tested V12/V13/V15/V16 — adding features consistently hurts. V12_noveg's 50-feature set with vegas=0.25 weight is optimal. Future experimentation should focus on training windows and tier weighting, not new features.

### Vegas Weight Sweet Spot: 0.15-0.25
v12 + vegas=0.15 achieved 76.2% HR — potentially better than v12_noveg's 73.1%. But N=21 vs N=26. The vegas fine-tune shows diminishing returns (or noise) rather than a clear winner between 0.15 and 0.25.

### Grid Search Infrastructure Now Works
The `--force` fix + diagnostic logging ensures experiments produce results. Future sessions can immediately run grids without debugging. CSVs saved in `results/`.

### Phase 2B: Multi-Window Grid Search (COMPLETE)

**55 experiments across 4 eval windows** (train Dec 1-31 except Window D):

| Window | Train | Eval | Purpose |
|--------|-------|------|---------|
| A | Dec 1-31 | Jan 1 - Feb 27 | Full eval, max N |
| B | Dec 1-31 | Jan 1-31 | Pre-decay baseline |
| C | Dec 1-31 | Feb 1-27 | Decay period |
| D | Dec 1 - Jan 31 | Feb 1-27 | More training data |

**Feature Set Decay Analysis:**

| Feature Set | Jan HR (N) | Feb HR (N) | Decay |
|------------|------------|------------|-------|
| **v12_noveg** | 70.9% (141) | **66.3%** (101) | **-4.6pp** |
| v13 | 73.2% (123) | N/A | — |
| v15 | 75.9% (116) | 63.0% (100) | -12.9pp |
| v16_noveg | 67.4% (132) | 61.4% (88) | -6.0pp |

**Vegas Weight Decay Analysis (v12 WITH vegas):**

| Weight | Jan HR (N) | Feb HR (N) | Full HR (N) | Gates |
|--------|------------|------------|-------------|-------|
| **0.15** | 75.7% (111) | **63.6%** (77) | **73.0% (189)** | **PASS** |
| 0.20 | 75.8% (120) | 58.7% (92) | N/A | — |
| **0.25** | 74.3% (109) | 62.7% (67) | 68.1% (185) | PASS |
| 0.30 | 73.8% (122) | 62.2% (82) | 65.6% (218) | PASS |
| 0.35 | 71.4% (112) | 61.5% (83) | 68.0% (194) | PASS |

**Window D (more training data, Feb eval):**
- v12+vegas=0.25: **72.7% HR** (N=44) — up from 62.7% with 31-day training
- v15: 69.4% (N=49), v12_noveg: 65.4% (N=52)

**Tier Weight Decay Analysis:**

| Tier Weights | Jan (N) | Feb (N) | Full (N) | Decay |
|-------------|---------|---------|----------|-------|
| star=2.0,s=1.2,r=0.8,b=0.3 | 67.5% (160) | **63.8% (105)** | **67.9% (271)** | **-3.7pp** |
| star=3.0,s=1.0,r=0.8,b=0.5 | 70.5% (139) | 63.0% (108) | 67.2% (247) | -7.5pp |

## Key Findings

### Best Config: v12 + vegas=0.15
73.0% HR on full Jan-Feb eval (N=189), **passes all governance gates**. UNDER: 74.8%, OVER: 70.3%. This is the top candidate for shadow deployment.

### v12_noveg: Most Decay-Resistant
Only -4.6pp decay (70.9%→66.3%). The simplest feature set is the most robust to market shifts. This should remain the production baseline.

### V15 Is A Trap
Best in January (75.9%) but worst decay (-12.9pp). Overfits to training period patterns that don't persist.

### More Training Data Helps For February
62-day training (Dec-Jan) significantly boosts Feb performance: v12+vegas=0.25 goes from 62.7% to 72.7%. This argues for longer training windows over frequent retraining.

### Tier Weighting: Marginal
Best tier combo (67.9% on full eval) underperforms baseline v12_noveg (70.0%) on the same window. Tier weights constrain the model for limited gain.

## Next Session Priorities

1. **Register v12+vegas=0.15 model** — re-run quick_retrain.py with `--feature-set v12 --category-weight vegas=0.15` without `--skip-register` to upload to GCS
2. **Shadow deploy the winner** — add to model registry, deploy to prediction-worker
3. **Monitor filter changes** — check if UNDER picks start passing through
4. **Test 62-day training window** — Window D showed more data helps. Try Dec 1 - Jan 31 train with v12+vegas=0.15
5. **Direction-aware weighting** — analyze directional HR splits once data accumulates

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | star_under injury-aware, under_7plus V9-only, version bump |
| `ml/signals/supplemental_data.py` | Added star_teammates_out from feature store |
| `ml/experiments/grid_search_weights.py` | Added --force flag, diagnostic logging |

## Commit

```
229d6773 feat: relax star_under + under_edge_7plus filters, fix grid search --force
```
