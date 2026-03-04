# Session 393 Findings — What Actually Predicts Winning Picks

**Data window:** 2025-12-01 through 2026-03-02
**Total graded best bets picks:** 118 (79 wins, 39 losses = 66.9% HR)

## Factor Analysis

### 1. Edge — The Strongest Predictor

| Edge Band | Picks | Wins | HR | Avg Signal Count |
|-----------|:-----:|:----:|:--:|:----------------:|
| 7+ | 32 | 26 | **81.3%** | 4.5 |
| 5-7 | 82 | 52 | **63.4%** | 4.1 |
| 3-5 | 4 | 1 | 25.0% | 2.8 |

Edge 7+ is the "golden zone" — 81.3% HR with decent volume (32 picks). Edge 5-7 is profitable at 63.4%. Edge 3-5 barely exists in best bets (only 4 picks, likely from early pipeline before the OVER edge 5.0 floor).

**Verdict:** Edge is the primary quality signal. The system's "rank by edge" approach is fundamentally correct.

### 2. Signal Count — The Second Strongest Predictor

| Signal Count | Picks | Wins | HR |
|:------------:|:-----:|:----:|:--:|
| 3 | 49 | 27 | **55.1%** |
| 4 | 25 | 19 | **76.0%** |
| 5 | 23 | 16 | **69.6%** |
| 6 | 11 | 10 | **90.9%** |
| 7 | 6 | 5 | **83.3%** |
| 8 | 2 | 1 | 50.0% |

**SC=3 is the weak spot** — 41.5% of picks but only 55.1% HR (barely above breakeven at -110 odds). SC=4+ picks are 76.1% HR collectively. There's a 21pp quality gap between SC=3 and SC=4+.

SC=8 at 50% is a small sample anomaly (N=2).

**Verdict:** Signal count ≥ 4 is a meaningful quality threshold. SC=3 picks are marginal and drag down overall performance.

### 3. Direction — OVER Outperforms

| Outcome | N | Avg Edge | Avg Signals | % OVER |
|---------|:-:|:--------:|:-----------:|:------:|
| WIN | 79 | 7.0 | 4.4 | 63.3% |
| LOSS | 39 | 6.4 | 3.8 | 56.4% |

Winners skew OVER (63.3% vs 56.4% for losers). This aligns with the known pattern: OVER predictions at high edge tend to be more reliable than UNDER.

### 4. Confidence Score — Completely Useless

| Confidence Band | Picks | HR |
|:-:|:-:|:-:|
| 0.8+ | 117 | 66.7% |
| <0.5 | 1 | 100.0% |

All CatBoost models output confidence = 9.999. This field carries zero information. It's a vestigial artifact from early model architectures that never implemented meaningful confidence calibration.

**Verdict:** Confidence score should be either repurposed or removed from selection logic entirely.

### 5. Which Signals Matter Most

Signal tags on best bets picks (Feb 2026+):

| Signal | Times Tagged | HR When Tagged |
|--------|:-----------:|:--------------:|
| model_health | 56 | 58.0% |
| high_edge | 52 | 60.9% |
| edge_spread_optimal | 52 | 60.9% |
| combo_he_ms | 7 | **83.3%** |
| combo_3way | 7 | **83.3%** |
| book_disagreement | 7 | 57.1% |
| blowout_recovery | 6 | 20.0% (disabled) |
| rest_advantage_2d | 14 | 57.1% |
| prop_line_drop_over | 16 | 53.3% (disabled) |

**Combo signals (combo_he_ms, combo_3way) are the highest quality** at 83.3% HR. These fire on OVER picks with high edge + momentum signals.

Many newer signals (fast_pace_over, self_creation_over, sharp_line_move_over, home_under, etc.) have very few or zero best bets picks because:
- They were added in Feb/Mar
- Feb/Mar has very few best bets picks overall (fleet degradation)
- Most picks in the data are from Jan when v9/v12_train1225 dominated

## Per-Model Best Bets Performance

### Models That Actually Source Best Bets Picks (Dec 1+)

| Model | BB Picks | BB HR | Avg Edge | Direction Split |
|-------|:--------:|:-----:|:--------:|:-:|
| catboost_v12_train1102_0125 | 4 | 100% | 10.3 | 4 OVER / 0 UNDER |
| catboost_v9_low_vegas_train0106_0205 | 3 | 100% | 5.5 | 1 OVER / 2 UNDER |
| catboost_v12_train1102_1225 | 23 | **78.3%** | 7.0 | 12 OVER / 11 UNDER |
| catboost_v9 | 64 | 64.1% | 7.0 | 43 OVER / 21 UNDER |
| catboost_v12_noveg_q43_train0104_0215 | 4 | 50.0% | 6.1 | 0 OVER / 4 UNDER |
| catboost_v12 (legacy) | 6 | 33.3% | 5.9 | 2 OVER / 4 UNDER |

**Two models produced 87 of 104 graded picks (83.7%):** catboost_v9 (64) and catboost_v12_train1102_1225 (23). Everything else is noise-level sample size.

### Models That NEVER Source Best Bets (Despite Being Enabled)

Over 10 enabled models have produced ZERO best bets picks. They never win per-player selection because their edges are lower.

### The "Latent Quality" Problem

Models with good overall HR that can't break into best bets:

| Model | Overall HR (edge 3+, Feb+) | Avg Edge | BB Picks |
|-------|:-:|:-:|:-:|
| v12_noveg_60d_vw025_train1222_0219 | **75.0%** (6/8) | 4.2 | 0 |
| v16_noveg_train1201_0215 | **66.7%** (8/12) | 3.7 | 0 |
| v16_noveg_rec14_train1201_0215 | **66.7%** (10/15) | 4.0 | 0 |
| v12_noveg_train0110_0220 | 61.5% (8/13) | 4.4 | 2 (just started) |

**These models are well-calibrated** — they predict closer to the actual line, which means lower edge. The system's "highest edge wins" selection punishes accuracy. A model predicting 22.3 points vs a 20 line (edge 2.3) when the player scores 23 is MORE ACCURATE than a model predicting 27 (edge 7) — but the second model wins selection.

### Monthly Trend

| Month | Top Model | BB Picks | BB HR |
|-------|-----------|:--------:|:-----:|
| Jan | catboost_v9 | 40 | 67.5% |
| Jan | catboost_v12_train1102_1225 | 23 | 78.3% |
| Feb | catboost_v9 | 24 | 58.3% |
| Feb | catboost_v9_low_vegas | 3 | 100% |
| Mar | catboost_v12_noveg_train0110_0220 | 2 | 100% |

Jan was dominant (63 picks, 71.4% HR). Feb declined significantly (33 picks, 60.6%). Mar is just starting.

## Overall HR vs Best Bets HR

The filter stack adds 10-50 percentage points on top of a model's raw HR:

| Model | Overall HR (edge 3+) | Best Bets HR | Lift |
|-------|:---:|:---:|:---:|
| catboost_v12_train1102_0125 | 70.0% | 100% | +30pp |
| catboost_v12_train1102_1225 | 66.5% | 78.3% | +12pp |
| catboost_v9 | ~55% | 64.1% | +9pp |
| catboost_v9_low_vegas | 57.8% | 100% | +42pp |

**The filter stack IS the value-add.** Even mediocre models become profitable after filtering. The question is whether we're applying filters uniformly when models have different strengths and weaknesses.
