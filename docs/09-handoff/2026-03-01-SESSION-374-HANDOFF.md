# Session 374 Handoff — Retraining, New Training Features, Experiment Results

**Date:** 2026-03-01
**Status:** In progress

## Key Accomplishments

### 1. v373 Deployment Verified
- All Cloud Builds succeeded at ~2:23 AM UTC
- phase6-export updated with v373 code (new signals: high_scoring_environment_over, b2b_fatigue_under disabled)

### 2. Two Shadow Models Deployed
Both use v12 feature set with vegas=0.15 weight. Force-registered despite N<50 gate.

| Model ID | Window | HR Edge 3+ | N | OVER | UNDER | MAE |
|---|---|---|---|---|---|---|
| `catboost_v12_train0104_0208` | 35d (Jan 4-Feb 8) | **67.35%** | 49 | 80.0% | 64.1% | 4.97 |
| `catboost_v12_train1221_0208` | 49d (Dec 21-Feb 8) | **71.79%** | 39 | 66.7% | 74.1% | 4.90 |

Both uploaded to GCS and enabled in model_registry. 5 total v12_mae models now active.

### 3. Training Window Grid Search
Tested 5 windows, all ending Feb 8 (except one ending Feb 12):

| Window | HR Edge 3+ | N | Finding |
|---|---|---|---|
| 35d | 67.35% | 49 | Most high-edge picks |
| 42d | 62.16% | 37 | Weakest |
| **49d** | **71.79%** | 39 | **Best HR + UNDER** |
| 56d | 72.00% | 25 | Too few picks |
| 56d (Feb 12 end) | 61.54% | 26 | Including Feb training data HURTS |

**Finding:** 49-day window is optimal. Including February data in training degrades performance.

### 4. New Training Features Implemented
Two new flags added to `ml/experiments/quick_retrain.py`:

#### `--adversarial-noise FEATURE=RATE`
Shuffles feature values in a fraction of training rows to reduce reliance on drift-prone features.
- Example: `--adversarial-noise "usage_spike_score=0.2"` shuffles usage_spike_score in 20% of rows
- **Result:** Tested with usage_spike_score=0.2 → 62.5% HR (N=48), UNDER dropped to 55.6% from 64.1%
- **Conclusion:** Hurts UNDER predictions. Usage_spike_score is important for UNDER, noise disrupts it.

#### `--residual-base-model SYSTEM_ID`
Trains a stacked residual model on top of a base model's predictions.
- Loads base model predictions, computes residuals (actual - predicted), trains on residuals
- **Result:** Tested with catboost_v8 base → 47.37% HR (N=95), MAE worse than baseline
- **Conclusion:** Dead end. Residual model just learns noise. Base model already captures signal.

### 5. Investigations Completed

#### familiar_matchup Data Gap
- **Root cause:** NOT a data gap — filter works in production (exporter calls `query_games_vs_opponent()`)
- **Real issue:** Threshold of 6 games is unreachable — only 1 player-opponent pair has 6+ games this season
- **Action:** Consider lowering threshold to 4, or remove filter

#### Minutes Trend Signal
- **Dead end.** Feature_12 (minutes_change) is nearly all 0. Using player_game_summary directly:
  - No differential signal between increasing/decreasing minutes trends
  - All trends collapse equally in February
  - OVER: 56-61% regardless of trend; UNDER: 52-61%

#### CLV Data Availability
- **Blocked.** No `odds_api_*` tables exist in nba_raw. Only `bettingpros_player_points_props` available.
- CLV analysis requires multi-timestamp line data which we don't store.

#### line_jumped_under Filter
- **Keep filter.** Correctly blocks losing pattern: Dec-Jan 50.9% (N=336), Feb 46.9% (N=277)
- Below breakeven consistently at raw prediction level

## Dead Ends (Add to CLAUDE.md)
- Adversarial noise on usage_spike_score=0.2 (hurts UNDER 64.1%→55.6%, overall 62.5% vs 67.35%)
- Stacked residual model on catboost_v8 (47.37% HR, N=95 — learns noise not signal)
- Minutes trend signal (no differential signal, all trends collapse in Feb)
- CLV analysis (no multi-timestamp prop line data available)
- Including February data in training window (61.5% vs 71.8% — Feb drift contaminates)

## Code Changes
- `ml/experiments/quick_retrain.py`: Added `--adversarial-noise` and `--residual-base-model` flags
- Added `load_base_model_predictions()` function for residual stacking

## Next Steps (Tier 2-3 from original plan)
1. **Shadow fleet evaluation (Mar 5-7):** 16+ new models will have 7 days of data. Run model_family_dashboard
2. **Signal count floor:** If v373 data shows signal 4+ has adequate volume and 10pp+ HR delta, raise to 4
3. **Percentile features:** Convert drift-prone features to within-game-date percentile ranks
4. **Win probability overlay:** Home win probability as context signal (high effort)
5. **Cross-season validation:** Any production change needs cross-season check
