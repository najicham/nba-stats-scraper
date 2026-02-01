# ML Challenger Experiments Plan

**Created:** 2026-02-01 (Session 61)
**Status:** PLANNING
**Goal:** Find a model that beats V8 for DraftKings betting

---

## Background

### Current Champion: CatBoost V8
- **Training Data:** BettingPros Consensus, Nov 2021 - Jun 2024 (~77K samples)
- **Features:** 33 features (v2_33features)
- **MAE:** 3.404 (test set)
- **Status:** Production since mid-2024

### Problem Discovered
V8 performance degraded significantly in Jan 2026:

| Period | Hit Rate | MAE |
|--------|----------|-----|
| Jan 2025 | 70-76% | 3.8-4.3 |
| Jan 2026 | 48-67% | 4.4-5.9 |

**Key Question:** Why did Jan 2026 degrade when Jan 2025 was stable?

---

## Naming Convention

```
exp_YYYYMMDD_hypothesis[_vN]
```

Examples:
- `exp_20260201_dk_only` - First attempt
- `exp_20260201_dk_only_v2` - Iteration with tweaks

Only promote to `catboost_vN` after proven in production shadow evaluation.

---

## Experiments

### Experiment 1: DraftKings Only (Odds API)
**ID:** `exp_20260201_dk_only`

**Hypothesis:** Training on DraftKings lines will improve calibration for DraftKings bets, since V8 was trained on Consensus which has different line distributions.

**Training Data:**
- Source: `nba_raw.odds_api_player_points_props`
- Bookmaker: DraftKings
- Date Range: 2023-05-03 to 2026-01-31
- Expected Samples: ~100K

**Baseline Comparison:** V8 (Consensus-trained)

**Success Criteria:**
- Hit rate improvement ≥2% on Jan 2026 holdout
- MAE improvement ≥0.2

**Status:** NOT STARTED

**Results:** _TBD_

---

### Experiment 2: DraftKings Only (BettingPros)
**ID:** `exp_20260201_dk_bettingpros`

**Hypothesis:** BettingPros DraftKings has 3x more data than Odds API DraftKings. More data might outweigh recency.

**Training Data:**
- Source: `nba_raw.bettingpros_player_points_props`
- Bookmaker: DraftKings
- Date Range: 2022-05-11 to 2026-01-31
- Expected Samples: ~330K

**Baseline Comparison:** V8, exp_20260201_dk_only

**Success Criteria:**
- Better than exp_20260201_dk_only
- Hit rate improvement ≥2% on Jan 2026 holdout

**Status:** NOT STARTED

**Results:** _TBD_

---

### Experiment 3: Recency Weighting (90 days)
**ID:** `exp_20260201_recency_90d`

**Hypothesis:** Aggressive recency weighting (90-day half-life) will help model adapt to current season patterns, addressing the Jan 2026 degradation.

**Training Data:**
- Source: BettingPros Consensus (same as V8)
- Date Range: 2021-11-01 to 2026-01-31
- Weighting: Exponential decay, 90-day half-life
- Expected Samples: ~475K (weighted)

**Baseline Comparison:** V8 (no recency)

**Success Criteria:**
- Hit rate improvement on Jan 2026
- Not worse on Jan 2025 (no overfitting to recent)

**Status:** NOT STARTED

**Results:** _TBD_

---

### Experiment 4: Recency Weighting (180 days)
**ID:** `exp_20260201_recency_180d`

**Hypothesis:** Moderate recency weighting (180-day half-life) balances recent patterns with historical stability.

**Training Data:**
- Source: BettingPros Consensus
- Date Range: 2021-11-01 to 2026-01-31
- Weighting: Exponential decay, 180-day half-life
- Expected Samples: ~475K (weighted)

**Baseline Comparison:** V8, exp_20260201_recency_90d

**Success Criteria:**
- Better balance than 90d (less volatility)
- Still improves Jan 2026

**Status:** NOT STARTED

**Results:** _TBD_

---

### Experiment 5: Current Season Only
**ID:** `exp_20260201_current_szn`

**Hypothesis:** Training only on 2025-26 season data captures current player roles, team dynamics, and league trends without historical noise.

**Training Data:**
- Source: Odds API DraftKings
- Date Range: 2025-10-22 to 2026-01-31
- Expected Samples: ~40K

**Baseline Comparison:** V8

**Risks:**
- Small dataset may underfit
- No historical patterns for rare situations

**Success Criteria:**
- Competitive with V8 despite less data
- Better on Jan 2026

**Status:** NOT STARTED

**Results:** _TBD_

---

### Experiment 6: Multi-Book with Indicator
**ID:** `exp_20260201_multi_book`

**Hypothesis:** Adding bookmaker as a categorical feature allows model to learn book-specific biases while using all available data.

**Training Data:**
- Source: All BettingPros + Odds API
- Bookmakers: DraftKings, FanDuel, Consensus
- Additional Feature: `bookmaker_id` (categorical)
- Date Range: 2021-11-01 to 2026-01-31
- Expected Samples: ~500K+

**Baseline Comparison:** V8, single-book experiments

**Risks:**
- More complex
- Needs careful encoding

**Success Criteria:**
- Best overall performance
- Can predict accurately for each book

**Status:** NOT STARTED

**Results:** _TBD_

---

## Investigation: Jan 2026 Degradation

Before running experiments, we need to understand WHY Jan 2026 degraded.

### Possible Causes to Investigate:

1. **Data Quality Issues**
   - Missing features in feature store?
   - Shot zone data completeness?
   - Phase 4 dependency gaps?

2. **Line Distribution Shift**
   - Did Vegas lines change distribution in Jan 2026?
   - Different bookmaker mix being used?

3. **Player/Team Changes**
   - Major injuries affecting predictions?
   - Mid-season trades impacting team dynamics?

4. **Seasonal Patterns**
   - All-Star break timing effects?
   - Schedule compression?

5. **Feature Drift**
   - Are input features drifting from training distribution?
   - Which features have largest drift?

### Investigation Status: ROOT CAUSES FOUND (Session 62)

## Root Causes: THREE Interrelated Issues

**Discovery Date:** 2026-02-01 (Session 61 + 62)

The model degradation in Jan 2026 is caused by **THREE interrelated issues**:

### Issue 1: team_win_pct Constant Value Bug (MAJOR)

| Period | team_win_pct = 0.5 | Impact |
|--------|-------------------|--------|
| V8 Training (2022-23) | **100%** | Model only saw 0.5 |
| Jan 2025 (72.8% hit rate) | **100%** | Matched training |
| Jan 2026 (55.5% hit rate) | **22.3%** | Model sees 0.2-0.9 it never trained on |

**V8 was trained on broken data!** The feature calculator wasn't receiving `team_abbr` and defaulted to 0.5 for ALL records. When this was fixed (Nov 2025+), V8 started seeing feature values it was never trained on.

### Issue 2: Vegas Line Coverage Drop (MEDIUM)

| Month | Feature Store with vegas_line | Records/Day |
|-------|------------------------------|-------------|
| Jan 2025 | **99.4%** | 158 (props-only) |
| Jan 2026 | **43.4%** | 276 (all players) |

Backfill mode includes ALL players who played, but Vegas extraction only covers props players.

**Fix Applied (Session 62):** Modified `_batch_extract_vegas_lines()` for backfill mode.

### Issue 3: Vegas Imputation Mismatch (MEDIUM)

| Phase | Missing Vegas Handling |
|-------|----------------------|
| Training | Imputed with `season_avg` (~6-8 pts) |
| Inference | Uses `np.nan` |

Model learned that missing vegas_line means "low-scoring player", but inference shows `np.nan`.

### High-Edge Hit Rate Collapsed

| Edge Bucket | Jan 2025 | Jan 2026 | Drop |
|-------------|----------|----------|------|
| 1-3 (low) | 63.4% | 55.0% | -8.4 |
| 3-5 (medium) | 76.1% | 54.8% | -21.3 |
| 5+ (high) | **86.1%** | **60.5%** | **-25.6** |

### Implications for Experiments

1. **New training should use Nov 2025+ data** where team_win_pct is realistic
2. **Don't train on historical data without fixes** - it has broken features
3. **Jan 2026 feature store is actually BETTER quality** than training data
4. **Consider retraining V8 on recent data** as a baseline

**Full Analysis:** `docs/08-projects/current/ml-challenger-training-strategy/V8-TRAINING-DISTRIBUTION-MISMATCH.md`

### Next Steps

1. **Re-run feature store backfill** with vegas fix (code done, backfill pending)
2. **Verify team_win_pct** is realistic in chosen training data
3. **Train experiments on Nov 2025+ data** to avoid distribution mismatch

---

## Execution Order (Updated Session 62)

1. ~~**Investigate Jan 2026 degradation**~~ ✅ ROOT CAUSES FOUND
   - team_win_pct bug (MAJOR)
   - Vegas coverage drop (MEDIUM)
   - Vegas imputation mismatch (MEDIUM)
2. **Re-run feature store backfill** with vegas fix (code done)
3. **Verify training data quality** - ensure team_win_pct is realistic
4. **Run exp_20260201_dk_only** using Nov 2025+ data (avoid broken features)
5. **Run exp_20260201_current_szn** - current season only may work best
6. **Compare and iterate**
7. **Best performer → challenger evaluation**
8. **If beats V8 → promote to v9**

---

## Infrastructure

### Existing Tools
- `ml/experiments/train_walkforward.py` - Walk-forward validation
- `ml/experiment_registry.py` - Experiment tracking
- `.claude/skills/model-experiment/` - Experiment skill
- `ml/experiments/configs/` - Configuration templates

### Needed
- Review existing experiment framework
- Ensure registry is working
- Create standardized evaluation script

---

## Results Summary

| Experiment | Status | Hit Rate (Jan 26) | MAE | vs V8 | Notes |
|------------|--------|-------------------|-----|-------|-------|
| V8 (baseline) | PRODUCTION | 55.5% | 5.3 | - | Broken due to training distribution mismatch |
| exp_20260201_dk_only | NOT STARTED | - | - | - | Use Nov 2025+ data only |
| exp_20260201_dk_bettingpros | NOT STARTED | - | - | - | Use Nov 2025+ data only |
| exp_20260201_recency_90d | NOT STARTED | - | - | - | |
| exp_20260201_recency_180d | NOT STARTED | - | - | - | |
| exp_20260201_current_szn | PRIORITY | - | - | - | Best option - avoids all distribution issues |
| exp_20260201_multi_book | NOT STARTED | - | - | - | |

**Note:** All experiments should use Nov 2025+ data to ensure `team_win_pct` is realistic. Historical data (2021-Oct 2025) has broken features.

---

## Related Documents

- [V8 Training Distribution Mismatch](../ml-challenger-training-strategy/V8-TRAINING-DISTRIBUTION-MISMATCH.md) - Critical root cause
- [V8 Training Data Analysis](../ml-challenger-training-strategy/V8-TRAINING-DATA-ANALYSIS.md) - Bookmaker analysis
- [Vegas Line Root Cause](../feature-quality-monitoring/2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md)

---

*Last Updated: 2026-02-01 Session 62*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
