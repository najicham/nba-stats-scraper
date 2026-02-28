# Model Diversity Analysis — Session 350

**Date:** 2026-02-26
**Goal:** Assess current model diversity, identify profitable expansion opportunities, and design experiments.

---

## Current State: Zero Architectural Diversity

All 10 enabled models are CatBoost using 50-54 features from the same pipeline. Variation is limited to:
- **Loss function:** MAE vs quantile (Q43, Q45, Q55, Q57)
- **Feature subset:** vegas vs no-vegas
- **Training window:** different date ranges

### Who Actually Sources Best Bets (Jan 1 - Feb 25)

| Model | Picks | HR |
|-------|-------|-----|
| catboost_v9 | 70 | **64.1%** |
| catboost_v12_train1102_1225 | 23 | **78.3%** |
| catboost_v12 | 6 | 33.3% |
| Others (tiny samples) | 18 | ~80% |

**V9 sources 60% of all best bets picks.** The "10 models" gives an illusion of diversity.

### Feb Model Family Performance (edge 3+)

| Family | Direction | Picks | HR |
|--------|-----------|-------|-----|
| v9_low_vegas | UNDER | 43 | **58.1%** |
| v12_production | UNDER | 109 | 52.3% |
| v12_production | OVER | 19 | 52.6% |
| v9_production | UNDER | 123 | 37.4% |
| v9_production | OVER | 84 | 46.4% |

Only v9_low_vegas UNDER is performing well (58.1%).

---

## Signal-Density Filter: Confirmed Optimal

| Non-Base Signals | Picks | HR | Avg Edge |
|-----------------|-------|-----|----------|
| 0 (base-only) | 42 | 57.1% | 6.1 |
| 1 | 25 | **76.0%** | 6.8 |
| 2 | 20 | 70.0% | 9.0 |
| 3+ | 18 | **83.3%** | 7.0 |

The 0→1 jump (+18.9pp) is the largest gap. Current threshold (block base-only) is optimally placed.

### Top Non-Base Signals in Best Bets

| Signal | Appearances | HR |
|--------|-------------|-----|
| book_disagreement | 8 | **100.0%** |
| combo_he_ms | 17 | 88.2% |
| combo_3way | 17 | 88.2% |
| rest_advantage_2d | 50 | 74.0% |
| prop_line_drop_over | 15 | 66.7% |

### Retroactive Filter Performance (Feb 15-24)

| Filter Result | Picks | W-L | HR |
|---------------|-------|-----|-----|
| BLOCKED (base-only) | 8 | 5-3 | 62.5% |
| KEPT (signal-rich) | 4 | 3-1 | 75.0% |

---

## Edge Floor Relaxation: NOT Recommended

Raw model-level HR by edge band (Jan 15 - Feb 25):

| Edge Band | Picks | HR |
|-----------|-------|-----|
| 3-4 | 1,777 | 52.1% |
| 4-4.5 | 554 | 51.8% |
| 4.5-5 | 407 | 51.6% |
| 5+ | 1,372 | 49.1% |

**Higher edge does NOT predict better accuracy at the raw level.** The value comes from signal-density filtering, not edge alone.

Volume impact: Edge 4+ signal-rich = 1.8 picks/day = same as edge 5+ signal-rich. No volume gain from relaxation.

---

## Model Agreement: Anti-Correlated

| Models Agreeing (edge 3+, same direction) | Picks | HR |
|-------------------------------------------|-------|-----|
| 1 | 154 | 53.2% |
| 2 | 44 | **38.6%** |
| 3 | 26 | 57.7% |
| 4 | 11 | 63.6% |
| 5+ | 6 | 33.3% |

2-model agreement (38.6%) is WORSE than 1-model (53.2%). Confirms CLAUDE.md note that V9+V12 agreement is anti-correlated. Suggests current models solve the same problem similarly — they fail together.

---

## Infrastructure Readiness

| Framework | Loader | Training | Prediction System | Status |
|-----------|--------|----------|-------------------|--------|
| CatBoost | Yes | Yes (`quick_retrain.py`) | Yes (v9, v12) | Production |
| XGBoost | Yes | No | Stub (mock models) | Dormant |
| LightGBM | Yes | No | No | Dormant |
| Sklearn | Yes | No | No | Legacy |

Feature contract supports V8-V15 (33-65 features). Training pipeline is CatBoost-only.

---

## Diversity Opportunities Ranked

### Tier 1: High Potential

**1. Binary Over/Under Classification (CatBoost Logloss)**
- Predict P(over) directly instead of raw points
- Same CatBoost framework, same features, same pipeline
- Fundamentally different optimization target
- Generates independent "edge" (probability vs point spread)
- Catches "likely over but by small margin" cases that regression misses
- **Effort: ~1 session** (modify `quick_retrain.py` target, add prediction system variant)

**2. Player-Cluster Models (Stars/Starters/Bench)**
- Train separate models per player archetype
- Addresses Starters OVER collapse (90%→33%) diagnosed Session 348
- Different feature importance per cluster
- **Effort: ~1-2 sessions** (cluster logic, 3 training runs, prediction routing)

**3. LightGBM with Same Features**
- Different tree-building algorithm (leaf-wise vs CatBoost's level-wise)
- Generates different edge distributions
- Infrastructure partially exists (loader ready)
- **Effort: ~1 session** (training script, prediction system, register)

### Tier 2: Medium Potential

**4. Short-Window "Hot Hand" Model (7-14 day)**
- Ultra-recent training data, retrained weekly
- High variance but captures momentum/slumps
- Complementary to 30-42 day window models
- **Effort: ~0.5 session** (modify training window, frequent retrain schedule)

**5. V13/V14 Feature Set Deployment**
- Already defined in feature_contract.py (V13: +FG%, 3PT%; V14: +engineered signals)
- Never deployed to production
- Different features → different edges
- **Effort: ~0.5 session** (feature store population, training)

### Tier 3: Not Recommended

- XGBoost (too similar to CatBoost, marginal)
- Neural networks (insufficient data volume for NBA)
- More CatBoost quantile variants (saturated)
- Ensemble stacking (proven dead end)

---

## Dead Ends (Don't Revisit)

Two-stage pipeline, Edge Classifier (AUC < 0.50), Huber loss (47.4%), recency weighting (33.3%), lines-only training (20%), min-PPG filter (33.3%), 96-day window, Q43+Vegas (20% edge 5+), RSM 0.5 + v9_low_vegas, 87-day window, min-data-in-leaf 25/50, Q60 quantile (50% OVER), health gate on raw HR, blowout_recovery signal, ensemble stacking with Ridge meta-learner.
