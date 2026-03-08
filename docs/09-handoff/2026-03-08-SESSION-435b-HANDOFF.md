# Session 435b Handoff — MLB Experiments, Strategy, V2 Features

**Date**: 2026-03-08
**Focus**: MLB system optimization — experiments, walk-forward validation, production strategy
**Commits**: 5 pushed to main

---

## What Was Done

### 1. NaN-Native CatBoost Training
- **Problem**: 30% of training data dropped due to NULL statcast features (28.8% of pitchers lack statcast tracking data entirely)
- **Fix**: CatBoost handles NaN natively via separate splits — stopped dropping rows
- **Result**: 2,161 training samples (was 1,509 = +43%)
- **COALESCE fix** applied to pitcher_loader.py + pitcher_strikeouts_predictor.py (both batch and single-pitcher queries)
- Fixed velocity_last_3 → velocity_change bug (f53 was never mapping correctly in single-pitcher query)

### 2. Cross-Season Walk-Forward Validation
Ran CatBoost 120d NaN-native on both 2024 and 2025 seasons:

| Strategy | 2024 HR | 2025 HR | Combined |
|----------|---------|---------|----------|
| OVER raw e>=1.0 | 62.0% | 56.1% | ~57% |
| **Top-1/day e>=1.5 prob<=75%** | **63.8%** | **66.9%** | **~66%** |
| Top-2/day e>=1.5 prob<=75% | 63.2% | 64.2% | ~64% |
| UNDER any | 52.4% | 48.1% | unprofitable |

### 3. OVER-Only Strategy + Season Phases (Deployed)
- **Phase 1** (first 45 days): OVER-only, edge >= 2.0 (conservative April)
- **Phase 2** (day 45+): OVER + qualified UNDER, edge >= 1.0
- **June tightening** (Jun 15 - Jul 20): edge >= 1.5
- UNDER disabled by default (`MLB_UNDER_ENABLED=false`)
- UNDER gate: 3+ real signals (vs OVER's 2)

### 4. Overconfidence Cap + Daily Limit (Deployed)
- `MAX_EDGE=2.5` (= prob cap 75%) — blocks overconfident picks that hit 52% HR
- `MAX_PICKS_PER_DAY=2` — top-2 by edge after prob cap
- Both env-configurable

### 5. Three New Signals (Deployed)
- `projection_agrees_over` — BettingPros projection > line + 0.5K
- `k_trending_over` — K avg last 3 > last 10 + 1.0 (momentum)
- `recent_k_above_line` — K avg last 5 > current line
- Signal count now: 11 active + 6 shadow + 4 negative filters

### 6. Systematic Experiment Grid (10 Experiments)
Built `ml/training/mlb/experiment_runner.py` — multi-seed walk-forward with auto-verdict.

**PROMOTE (3):**
- Deep Workload: +4.8pp (season_starts, k_per_pitch, workload_ratio)
- CatBoost Wider: +3.9pp (500 iter, 0.015 LR)
- Pitcher Matchup: +3.3pp (vs_opp_k_per_9, vs_opp_games)

**PROMISING (1):** Multi-Book Odds: +2.1pp (needs data join fix)

**DEAD_END (4):** K Trajectory, FanGraphs Advanced, LightGBM, CatBoost Deeper

### 7. V2 Features Added to Production Code
- 5 new features: f65_vs_opp_k_per_9, f66_vs_opp_games, f67_season_starts, f68_k_per_pitch, f69_recent_workload_ratio
- Wider hyperparams: 500 iterations, 0.015 learning rate
- Updated: quick_retrain_mlb.py, pitcher_loader.py, catboost_v1_predictor.py

### 8. Day-of-Week Discovery
Walk-forward analysis found massive DOW effect:
- Mon+Thu+Sat: **86.0% HR** (N=57, p=0.0002)
- Tue+Wed+Fri: ~50% HR (essentially random)
- Needs 2026 live validation before deploying as hard filter

### 9. Vegas MAE Analysis
- 2024: 1.830, 2025: 1.807 (-1.2%) — Vegas slightly tighter
- Lines consistently underestimate K (bias +0.15 to +0.23) — structural OVER edge
- Mid-high lines (6.0-6.5) got LOOSER in 2025 — potential opportunity zone

---

## Data Fix Discoveries (Not Yet Implemented)

### oddsa Multi-Book Odds Join
- **Root cause**: pd.Timestamp vs datetime.date hash mismatch in Python
- **BQ join works fine** — 84.8% match rate. Player_lookup formats match.
- **One-line fix**: `odds_df['game_date'] = pd.to_datetime(odds_df['game_date'])`

### FanGraphs Player Lookup
- **Root cause**: FanGraphs uses `carlosrodon` (no underscores, no accents), BQ uses `carlos_rodón`
- **Fix**: normalize with REPLACE('_','') + accent stripping + suffix removal → 98.6% match
- 5 unfixable name variants need manual mapping table

---

## Immediate Next Steps (Session 436)

### Priority 1: Deploy V2 Model
```bash
# Retrain with V2 features (code already updated)
PYTHONPATH=. python ml/training/mlb/quick_retrain_mlb.py \
    --model-type catboost --training-window 120 --train-end 2025-09-14 --eval-days 14

# Upload + register + update worker env var
```

### Priority 2: Implement DOW Filter
Add day-of-week logic to best_bets_exporter.py:
- Configurable via env var `MLB_DOW_FILTER=Mon,Thu,Sat,Sun`
- Shadow mode first (track but don't filter) until N=30 in 2026

### Priority 3: Fix Multi-Book Odds Data Join
One-line fix in experiment_runner.py. Then re-run experiment to validate +2.1pp improvement.

### Priority 4: Fix FanGraphs Matching
Write player_lookup normalization function. Then re-run FanGraphs experiment (oSwing%, FIP = strong K predictors in theory).

---

## Files Changed

| File | Change |
|------|--------|
| `ml/training/mlb/quick_retrain_mlb.py` | NaN-native training + V2 features/hyperparams |
| `predictions/mlb/pitcher_loader.py` | COALESCE fix + V2 features (f65-f69) |
| `predictions/mlb/pitcher_strikeouts_predictor.py` | COALESCE fix (both queries) |
| `predictions/mlb/prediction_systems/catboost_v1_predictor.py` | NaN-tolerant statcast + V2 features |
| `predictions/mlb/config.py` | New model path |
| `ml/signals/mlb/signals.py` | 3 new OVER signals |
| `ml/signals/mlb/registry.py` | 11 active signals |
| `ml/signals/mlb/best_bets_exporter.py` | Phase system + prob cap + daily limit |
| `ml/training/mlb/experiment_runner.py` | NEW: systematic experiment grid |
| `scripts/mlb/training/walk_forward_simulation.py` | NaN-native + COALESCE + hybrid filter |

---

## Path to 70%+ HR

Current best: 66.9% (top-1/day, e>=1.5, prob<=75%)

Stacking improvements:
1. V2 features (workload+matchup+wider): +3.3pp → ~70%
2. DOW filter (Mon/Thu/Sat/Sun): +4-6pp on filtered days → ~73-76%
3. Multi-book odds (after fix): +2.1pp potential
4. Signal stacking (as signals accumulate): additional lift TBD

**Conservative target: 70%+ on DOW-filtered days with V2 model.**
