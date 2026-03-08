# Session 435b Handoff — MLB Model V2: Experiments + Production Strategy

**Date:** 2026-03-08
**Focus:** MLB model optimization — systematic experiments, feature discovery, production strategy

---

## What Was Done

### 1. NaN-Native CatBoost Training
- COALESCE fix in `pitcher_loader.py` + `pitcher_strikeouts_predictor.py`
- Stopped dropping 30% of training data — CatBoost handles NaN natively
- +43% more training samples (2,161 vs 1,509)
- Model deployed: `catboost_mlb_v1_31f_train20250517_20250914_20260308_014509.cbm`

### 2. Cross-Season Walk-Forward (2024 + 2025)
| Strategy | 2024 HR | 2025 HR |
|---|---|---|
| OVER raw e>=1.0 | 62.0% | 56.1% |
| **Top-1/day e>=1.5 prob<=75%** | **63.8%** | **66.9%** |
| Top-2/day e>=1.5 prob<=75% | 63.2% | 64.2% |

### 3. Production Strategy Deployed
- OVER-only, overconfidence cap (MAX_EDGE=2.5), daily limit (MAX_PICKS_PER_DAY=2)
- Season phases: Phase 1 (45d, e>=2.0), Phase 2 (e>=1.0), June tightening (e>=1.5)
- 3 new signals: projection_agrees_over, k_trending_over, recent_k_above_line

### 4. Experiment Grid (10 experiments, 3 seeds)
Built `ml/training/mlb/experiment_runner.py`.
- **PROMOTE:** Deep Workload (+4.8pp), CatBoost Wider (+3.9pp), Pitcher Matchup (+3.3pp)
- **PROMISING:** Multi-Book Odds (+2.1pp) — blocked by type mismatch bug
- **DEAD_END:** K Trajectory, FanGraphs (0% match), LightGBM

### 5. V2 Feature Code Ready (NOT retrained/deployed yet)
5 new features added to training + predictor + loader. Wider hyperparams (500 iter, 0.015 LR).
5-seed combo: 62.4% BB top1, +19.2% ROI.

### 6. Vegas MAE: 2024=1.830, 2025=1.807 (-1.2%) — slightly tighter

---

## Immediate TODO (Next Session)

### 1. Retrain V2 Model (CODE READY)
```bash
PYTHONPATH=. python ml/training/mlb/quick_retrain_mlb.py \
    --model-type catboost --training-window 120 \
    --train-end 2025-09-14 --eval-days 14
# Review results, then: --upload --register
# Update worker: gcloud run services update mlb-prediction-worker \
#   --region=us-west2 --project=nba-props-platform \
#   --update-env-vars="MLB_CATBOOST_V1_MODEL_PATH=gs://..."
```

### 2. Fix Multi-Book Odds Bug
In `experiment_runner.py` line ~661: add `odds_df['game_date'] = pd.to_datetime(odds_df['game_date'])`
Root cause: `pd.Timestamp != datetime.date` hash mismatch. BQ join works (84.8%), Python fails.
Re-run: could add +2.1pp if data matches.

### 3. Fix FanGraphs Player Lookup
`fangraphs_pitcher_season_stats.player_lookup` doesn't match `pitcher_game_summary.player_lookup`.
Agent was investigating via `shared/utils/player_name_normalizer.py`. Format difference unknown.

### 4. Push for 70% HR
Agent was analyzing temporal patterns, line levels, streak effects in walk-forward data.
Run: `PYTHONPATH=. python ml/training/mlb/experiment_runner.py --all --seeds 42,123,456,789,999`
Key angle: combine model V2 + signal stack + smart filtering.

### 5. Season Launch (Mar 24-25)
Run `./bin/mlb-season-resume.sh` to enable all 24 scheduler jobs.
E2E smoke test after first game day.

---

## Commits This Session
```
c6cda5cc feat: MLB V2 features — workload + matchup + wider CatBoost
c594087a feat: MLB experiment runner + systematic feature/model grid results
aa484bc8 feat: MLB overconfidence cap + daily pick limit
52c1b55c feat: MLB OVER-only strategy + season phases + 3 new signals
379f3c91 feat: MLB NaN-native CatBoost training + COALESCE fix
```
