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

### Investigation Status: ROOT CAUSE FOUND

## Root Cause: Missing Vegas Line Features

**Discovery Date:** 2026-02-01 (Session 61)

The model degradation in Jan 2026 is caused by **missing vegas_line features in the feature store**.

### Evidence

| Month | Feature Store with vegas_line | Phase 3 with current_points_line |
|-------|------------------------------|----------------------------------|
| Jan 2025 | **99.4%** | N/A |
| Oct 2025 | N/A (bootstrap) | 16.8% |
| Nov 2025 | 57.9% | 25.4% |
| Dec 2025 | 32.5% | 44.1% |
| Jan 2026 | **43.4%** | 44.7% |

### Impact

When vegas_line = 0 (missing), the model:
1. Loses a critical input feature
2. Cannot calculate meaningful edge
3. Predictions degrade significantly

### High-Edge Hit Rate Collapsed

| Edge Bucket | Jan 2025 | Jan 2026 | Drop |
|-------------|----------|----------|------|
| 0-2 (low) | 60.3% | 52.2% | -8% |
| 2-5 (medium) | 72.3% | 55.3% | -17% |
| 5+ (high) | **86.1%** | **60.5%** | **-26%** |

### Why Is Coverage Low?

The Phase 3 `current_points_line` field is populated from betting data cascade. Possible causes:
1. Odds API scraper coverage gaps
2. Player matching issues (player_lookup not matching)
3. Timing issues (lines scraped before they're available)

### Next Steps

1. **Fix the pipeline** - Ensure vegas_line is populated for all predictions
2. **Backfill feature store** - Reprocess Nov 2025 - Jan 2026 with correct lines
3. **Then train experiments** - No point training on broken data

---

## Execution Order

1. **Investigate Jan 2026 degradation** (understand root cause)
2. **Run exp_20260201_dk_only** (simplest change from V8)
3. **Run exp_20260201_recency_90d** (if bookmaker isn't the issue)
4. **Compare and iterate**
5. **Best performer → challenger evaluation**
6. **If beats V8 → promote to v9**

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

| Experiment | Status | Hit Rate (Jan 26) | MAE | vs V8 |
|------------|--------|-------------------|-----|-------|
| V8 (baseline) | PRODUCTION | 48-67% | 4.4-5.9 | - |
| exp_20260201_dk_only | NOT STARTED | - | - | - |
| exp_20260201_dk_bettingpros | NOT STARTED | - | - | - |
| exp_20260201_recency_90d | NOT STARTED | - | - | - |
| exp_20260201_recency_180d | NOT STARTED | - | - | - |
| exp_20260201_current_szn | NOT STARTED | - | - | - |
| exp_20260201_multi_book | NOT STARTED | - | - | - |

---

*Last Updated: 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
