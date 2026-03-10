# Session 460 Handoff — NBA Leakage Fix, True Model Accuracy, BB Strategy Overhaul

**Date:** 2026-03-09
**Focus:** Data leakage discovery + fix, clean walk-forward, BB pipeline strategy

## Critical Discovery: Data Leakage

### What Happened
- Features 0-4 (scoring averages, 62% of model importance) **included today's actual game score**
- `player_daily_cache_processor.py` used `game_date <=` instead of `game_date <`
- Code was fixed Feb 4 2026 but **data was never regenerated** for historical dates
- 72% of feature_0 values matched the leaked computation (confirmed at scale)
- Previous walk-forward showed 85% HR — **entirely due to leakage**

### What Was Fixed (9 files)
- `player_daily_cache_processor.py`: 3 fixes (main query, 2 hash queries, is_dnp NULL handling)
- `team_defense_zone_analysis_processor.py`: 4 `<=` → `<` fixes
- `player_shot_zone_analysis_processor.py`: 3 `<=` → `<` fixes
- `feature_extractor.py`: 2 lines reviewed and annotated as correct (LAG for days_rest, pre-game odds)
- `.pre-commit-hooks/check_date_comparisons.py`: warning → BLOCKING

### Data Regeneration (COMPLETED)
1. **Cache regen:** 788 dates, 100,274 records via SQL MERGE (`scripts/regenerate_player_daily_cache.py --all-historical`)
2. **Feature store regen:** 789 dates, 779 success, 44 edge-case failures (`scripts/regenerate_feature_store_parallel.py`)

## True Walk-Forward Results (Clean Data)

### Raw Model (edge 3+, 2 seasons: 2023-24 + 2024-25)

| Config | HR | N | P&L | OVER HR | UNDER HR |
|--------|-----|------|-----|---------|----------|
| **w56_r7** | **53.4%** | 2,193 | +46.8 | 49.6% | 54.3% |
| w42_r7 | 52.8% | 2,399 | +21.8 | 48.5% | 53.9% |
| w56_r14 | 52.4% | 2,555 | +1.4 | 48.9% | 53.3% |
| w90_r14 | 51.9% | 2,378 | -26.5 | 47.1% | 53.1% |

**Raw model is ~53%.** UNDER slightly better. OVER barely above coin flip.

### BB Pipeline (2025-26 production, graded picks)

| Tier | Rule | HR | N | Picks/Day |
|------|------|-----|-----|-----------|
| Platinum | Edge 5+ + combo_3way/he_ms | **83.3%** | 18 | 1.3 |
| Gold | Edge 7+ | **78.8%** | 33 | 1.6 |
| Silver | Edge 5+ + rest_advantage_2d | **74.0%** | 50 | 2.4 |
| Edge 5+ all | All edge 5+ | **65.6%** | 122 | 2.9 |
| All BB | Everything | **60.3%** | 156 | 3.6 |
| **Edge 3-5** | Low-edge | **40.0%** | 34 | — |

### Signals Working on BB Picks

| Signal | HR | N | Status |
|--------|-----|-----|--------|
| book_disagreement | 75.0% | 12 | STRONG |
| rest_advantage_2d | 74.0% | 50 | **SLEEPER** |
| combo_3way / combo_he_ms | 73.9% | 23 | VALIDATED |
| edge_spread_optimal | 66.1% | 121 | base |
| predicted_pace_over | 41.7% | 24 | **DEAD** |
| low_line_over | 12.5% | 8 | **DEAD** |
| projection_consensus_over | 0.0% | 7 | **DEAD** |

### Filters Analysis

| Filter | CF HR | N | Action Needed |
|--------|-------|---|---------------|
| over_edge_floor | 71.4% | 14 | **Blocking winners — review** |
| under_star_away | 80.0% | 5 | **Blocking winners — review** |
| med_usage_under | 26.7% | 15 | Correct |
| high_spread_over | 25.0% | 8 | Correct |

## What Needs to Happen Next

### P0: BB Pipeline Experiments Across 4 Seasons

The model is a 53% coin flip. **All edge comes from the BB pipeline.** We need to test pipeline changes on historical data before deploying.

#### Experiment Plan

Build a **BB pipeline simulator** that takes walk-forward predictions and applies signal/filter logic retroactively. Test each change across all 4 available seasons.

**Experiment 1: Raise edge floor to 5.0**
- Current: edge 3.0 floor. Edge 3-5 picks are 40% HR (net-negative).
- Test: Apply edge 5.0 floor to walk-forward predictions for each season.
- Expected: HR jumps from 60% to 66%, volume drops from 3.6 to 2.9/day.

**Experiment 2: Kill dead signals**
- Remove from active: `projection_consensus_over` (0%), `scoring_momentum_over` (0%), `low_line_over` (12.5%), `hot_form_over` (25%), `volatile_scoring_over` (20%), `predicted_pace_over` (41.7%)
- These are allowing bad picks through rescue or inflating signal_count.

**Experiment 3: Fix bad filters**
- `over_edge_floor`: blocking 71% HR picks. Relax or remove.
- `under_star_away`: blocking 80% HR picks. Relax or remove.

**Experiment 4: New Ultra tier**
- Platinum: edge 7+ OR (edge 5+ AND combo_3way) → target 80%+
- Gold: edge 5+ AND (rest_advantage_2d OR book_disagreement) → target 74%+
- Test retroactively on all 4 seasons.

**Experiment 5: UNDER expansion**
- Starter UNDER (18-25 line) was 65.5% HR in prior analysis.
- `b2b_fatigue_under` at edge 5+.
- Can we double UNDER volume while maintaining 63%+ HR?

**Experiment 6: rest_advantage_2d formalization**
- 74% HR on 50 picks — largest high-HR signal.
- Test as rescue signal, combo booster, or standalone filter.

#### How to Run Experiments

```bash
# Walk-forward predictions already exist at:
ls results/nba_walkforward_clean/predictions_w56_r7.csv

# Need to build: bb_pipeline_simulator.py
# Input: walk-forward predictions CSV
# Apply: signal rules, filters, edge floors, team caps, volume caps
# Output: simulated BB picks with HR/P&L per configuration
# Must work across 4 seasons (2021-22 through 2024-25)

# Alternative: use the existing walk-forward to generate raw predictions,
# then apply BB pipeline logic in a separate script that can be iterated quickly.
```

The key insight is: we don't need to retrain models for each experiment. The raw predictions are fixed. We only need to change the **pick selection** logic (signals, filters, edge floors, caps) and measure the impact.

### P1: Deploy & Retrain
- Push code to main (auto-deploys leakage fixes + weekly-retrain CF)
- Create scheduler for weekly-retrain CF
- Retrain fleet (all models 10-60 days stale)

### P2: Model Diversity
- All 145 model pairs r >= 0.95 (zero diversity)
- Need structurally different models (different feature subsets, objectives)
- Per-model pipeline only adds value if models genuinely disagree

## Files Changed This Session

### New Files
- `orchestration/cloud_functions/weekly_retrain/main.py` (779 lines)
- `orchestration/cloud_functions/weekly_retrain/requirements.txt`
- `orchestration/cloud_functions/weekly_retrain/deploy.sh`
- `results/nba_walkforward_clean/` — clean walk-forward results

### Modified Files
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
- `data_processors/precompute/ml_feature_store/feature_extractor.py`
- `.pre-commit-hooks/check_date_comparisons.py`
- `scripts/regenerate_player_daily_cache.py`
- `CLAUDE.md`
- `docs/08-projects/current/model-management/MONTHLY-RETRAINING.md`

## Key Lesson

**Never trust a number that's too good to be true.** The 85% survived 5 audit checks because the leakage was subtle — a `<=` vs `<` in code that was already "fixed" but whose data was never regenerated. The definitive test: manually trace one player's rolling average game-by-game.
