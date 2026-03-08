# Session 436 Handoff — MLB V3 Model, FanGraphs Features, League Macro, 12-Book Odds

**Date**: 2026-03-08
**Focus**: MLB system optimization — V3 model deployment, experiment validation, new infrastructure
**Commits**: 2 pushed to main (8c211080, 48050114)
**Season starts**: Mar 24-25

---

## What Was Done

### 1. V3 Model Deployed (40 features, 72.7% HR)

Trained and deployed CatBoost V3 with 40 features (was 31 in V1):
- **31 base** (unchanged) + **5 workload/matchup** (f65-f69, Session 435) + **4 FanGraphs** (f70-f73, NEW)
- Wider hyperparams: 500 iterations, 0.015 LR (was 300/0.03)
- **All 5 governance gates passed**

| Metric | V1 (31f) | V3 (40f) |
|--------|----------|----------|
| HR (edge 1+) | 64.58% (N=48) | **72.73%** (N=44) |
| OVER HR | 60.31% | **63.01%** |
| UNDER HR | 55.96% | **56.92%** |
| Vegas bias | +0.14 K | **+0.09 K** |
| MAE | 1.839 | **1.817** |

**Top 5 features by importance:** f44_over_implied_prob (6.80), **f72_fip (4.45)**, f16_ballpark_k_factor (4.23), f68_k_per_pitch (4.15), f03_k_std_last_10 (4.10)

**Model path:** `gs://nba-props-platform-ml-models/mlb/catboost_mlb_v1_40f_train20250517_20250914_20260308_090647.cbm`
**Registry:** `catboost_mlb_v1_40f_train20250517_20250914` — enabled=TRUE, is_production=TRUE

**Known limitation:** f65_vs_opp_k_per_9 and f66_vs_opp_games are 100% NaN — `pitcher_game_summary` doesn't compute `vs_opponent_*` columns. These features are NaN-tolerant (CatBoost handles natively) but contribute nothing until the data pipeline adds them.

### 2. FanGraphs Features — Biggest Experiment Win (+5.9pp)

Session 435 showed FanGraphs as DEAD_END (-1.9pp) because player_lookup matching was 0%. Root cause: FanGraphs uses `carlosrodon` (no underscores, no accents), our system uses `carlos_rodón`.

**Fix:** `normalize_fangraphs_lookup()` in experiment_runner.py — strips accents, removes underscores/suffixes, normalizes both sides to common form. 5 edge cases handled by `FANGRAPHS_NAME_OVERRIDES` dict.

**After fix:** 100% match rate, **+5.9pp BB top1 HR = PROMOTE**. FIP alone became #2 feature.

Files updated: `quick_retrain_mlb.py`, `catboost_v1_predictor.py`, `pitcher_loader.py`, `experiment_runner.py`

### 3. Multi-Book Odds — Data Fix Works, Signal is NOISE

One-line fix: `odds_df['game_date'] = pd.to_datetime(odds_df['game_date'])` (pd.Timestamp vs datetime.date hash mismatch in zip join).

After fix: 5,419 DK + 5,119 FD matches. But **+0.7pp = NOISE**. DK-FD line spread doesn't add meaningful signal. Not worth adding to model.

### 4. DOW Filter — DEBUNKED

Session 435 found Mon/Thu/Sat = 86% HR (p=0.0002). Deep investigation in Session 436:

| Factor | Favorable (M/Th/Sa) | Unfavorable (Tu/W/F) | Gap |
|--------|---------------------|---------------------|-----|
| OVER HR | 48.8% | 48.8% | **0.0pp** |
| K/9 | 8.51 | 8.59 | negligible |
| Ace % | 36.8% | 37.2% | negligible |
| Vegas MAE | 1.68 | 1.67 | negligible |
| Slate size | 15.4 pitchers/day | 19.8 | significant |

**Verdict:** DOW was a walk-forward selection artifact. The 86% HR came from model picks, not base rates. Only structural difference is slate size — already captured by our MAX_PICKS_PER_DAY=2 limit.

DOW filter kept as **shadow-only tracking** (DOW_FILTER_ENABLED=false). Comments updated to prevent future activation.

### 5. MLB League Macro Tracker (NEW)

Created `ml/analysis/mlb_league_macro.py` — daily K environment + Vegas accuracy + model performance tracking.

**Metrics tracked:**
- K environment: avg K/game, K/9, innings, games (7d/14d/30d rolling)
- Vegas accuracy: MAE, bias, avg line level (7d/14d/30d rolling)
- Model performance: MAE, HR, prediction count, %OVER (7d/14d rolling)
- Best bets: HR 7d/14d rolling
- Market regime: TIGHT (<1.7 MAE), NORMAL (1.7-2.0), LOOSE (>2.0)

**BQ table:** `mlb_predictions.league_macro_daily` (auto-created, partitioned by game_date)
**Backfill:** 361/361 dates completed (2024-04-01 to 2025-09-28)

Usage:
```bash
PYTHONPATH=. .venv/bin/python ml/analysis/mlb_league_macro.py --date 2025-09-15
PYTHONPATH=. .venv/bin/python ml/analysis/mlb_league_macro.py --backfill --start 2024-04-01 --dry-run
```

### 6. Odds API Expanded (2 → 12 Books)

All 6 MLB odds scrapers expanded from `draftkings,fanduel` to all 12 US books (matching NBA):
`draftkings,fanduel,betmgm,williamhill_us,betrivers,bovada,espnbet,hardrockbet,betonlineag,fliff,betparx,ballybet`

- Zero API cost increase (Odds API charges per request, not per bookmaker)
- Books that don't carry MLB pitcher K lines simply return no data
- Files: `mlb_pitcher_props.py`, `mlb_pitcher_props_his.py`, `mlb_batter_props.py`, `mlb_batter_props_his.py`, `mlb_game_lines.py`, `mlb_game_lines_his.py`

### 7. NBA Model Registry Dedup Fix

`ml/experiments/quick_retrain.py`: Changed INSERT → MERGE to prevent duplicate model_registry entries when same model_id is registered multiple times.

### 8. blowout_risk_under Filter Demoted

`ml/signals/aggregator.py`: Demoted `blowout_risk_under` back to observation mode.

---

## Files Changed

| File | Change |
|------|--------|
| `ml/training/mlb/quick_retrain_mlb.py` | FanGraphs LEFT JOIN + f70-f73 features |
| `predictions/mlb/prediction_systems/catboost_v1_predictor.py` | 40 features, V3 model path, FanGraphs NaN-tolerant |
| `predictions/mlb/pitcher_loader.py` | FanGraphs LEFT JOIN in batch query |
| `predictions/mlb/config.py` | V3 model path default |
| `ml/training/mlb/experiment_runner.py` | FanGraphs matching fix, 40-feature baseline, multi-book odds fix |
| `ml/signals/mlb/best_bets_exporter.py` | Shadow DOW filter with tracking |
| `ml/analysis/mlb_league_macro.py` | NEW: daily macro tracker |
| `scrapers/mlb/oddsapi/mlb_*.py` (6 files) | 2 → 12 sportsbooks |
| `ml/experiments/quick_retrain.py` | INSERT → MERGE dedup fix |
| `ml/signals/aggregator.py` | blowout_risk_under demoted |

---

## Model Registry State

| Model ID | Features | HR (e1+) | Enabled | Production |
|----------|----------|----------|---------|------------|
| `catboost_mlb_v1_40f_train20250517_20250914` | 40 | **72.73%** | TRUE | **TRUE** |
| `catboost_mlb_v1_36f_train20250517_20250914` | 36 | 64.58% | TRUE | FALSE |
| `catboost_mlb_v1_31f_train20250517_20250914` | 31 | 70.51% | TRUE | FALSE |

---

## Experiment Grid (Updated)

| Experiment | BB Top1 HR | Delta vs Baseline | Verdict |
|------------|-----------|-------------------|---------|
| **FanGraphs Advanced** | **65.2%** | **+5.9pp** | **PROMOTE** (deployed) |
| Deep Workload | 64.1% | +4.8pp | PROMOTE (deployed) |
| CatBoost Wider | 63.2% | +3.9pp | PROMOTE (deployed) |
| Pitcher Matchup | 62.6% | +3.3pp | PROMOTE (deployed, NaN) |
| Multi-Book Odds | 60.0% | +0.7pp | NOISE |
| Kitchen Sink | 60.3% | +1.0pp | NOISE |
| Lineup K Rate | 59.4% | +0.1pp | NOISE |
| K Trajectory | 56.8% | -2.5pp | DEAD_END |
| LightGBM | 57.4% | -1.9pp | DEAD_END |
| CatBoost Deeper | 59.3% | +0.0pp | NOISE |

---

## NOT Pushed / Still TODO

- [ ] **Push to main** — commit is local, not yet pushed
- [ ] **Deploy to Cloud Run** — no auto-deploy for MLB. Must manually deploy before Mar 24
- [ ] **Populate vs_opponent_* in pitcher_game_summary** — enables f65/f66 matchup features (currently 100% NaN)
- [ ] **Integrate macro tracker into daily-steering** — add MLB section to `/daily-steering` skill
- [ ] **Run combined walk-forward** — V3 (40f) through full 2024+2025 walk-forward to get realistic BB top1 HR
- [ ] **First in-season retrain** — ~Apr 10 (14-day cadence)
- [ ] **Resume 24 MLB schedulers** — `./bin/mlb-season-resume.sh` on Mar 24-25
- [ ] **E2E smoke test** — after first game day

---

## Quick Reference

```bash
# Push changes
git push origin main

# Deploy MLB worker (must do before Mar 24)
./bin/deploy-service.sh nba-scrapers

# Check macro trends
PYTHONPATH=. .venv/bin/python ml/analysis/mlb_league_macro.py --date 2025-09-28

# Retrain V3 (for in-season updates)
PYTHONPATH=. .venv/bin/python ml/training/mlb/quick_retrain_mlb.py \
    --model-type catboost --training-window 120 --upload --register

# Resume schedulers for season start
./bin/mlb-season-resume.sh
```
