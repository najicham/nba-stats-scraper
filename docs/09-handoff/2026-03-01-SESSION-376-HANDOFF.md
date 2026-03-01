# Session 376 Handoff — Fleet Triage, Retrain, Experiment Suite

**Date:** 2026-03-01
**Status:** All work complete. Docs updated. Ready to commit.

## What Was Done

### P2: Retrain with Spread Fix (COMPLETE)
- Trained `catboost_v12_noveg_train0110_0220` — first model with real Feature 41/42 spread data
- **Results:** 65.62% edge 3+ HR (N=32), OVER 80.0%, UNDER 59.1%, vegas bias -0.41
- Uploaded to GCS, registered, enabled as shadow
- Config: V12_NOVEG + vw015, 42d window (Jan 10 - Feb 20)

### P3: Signal Verification (COMPLETE)
- New signals (fast_pace_over, volatile_scoring_over, low_line_over, line_rising_over) confirmed deployed
- Not yet firing because Feb 28 predictions generated before deployment (13:04-21:06 UTC vs deploy at ~06:01 UTC Mar 1)
- Will start firing with Mar 1 predictions

### P4: Fleet Triage (COMPLETE)
- Disabled 11 dead models from registry:
  - Q43/Q55/Q57 quantile variants (7.7%-20% HR)
  - Stale BLOCKED MAE models (33-42% HR)
  - Failed experiments (v13, v15, tier-weighted, LightGBM)
- Fleet: 24 → 13 enabled models
- Remaining fleet: 3 v12_noveg_mae, 3 v12_mae, 2 v9_low_vegas, 2 v16, 1 lgbm, 1 v9_mae, 1 v12_noveg_q5

### P5: Experiment Suite (5 experiments, ALL DEAD ENDS)

| Experiment | Result |
|-----------|--------|
| E1: Direction-specific models | Feature distributions identical OVER/UNDER. Circular prediction dependency. |
| E2: Dynamic edge by model age | Calendar date drives HR, not age. Model went 59%→83% aging through Jan. |
| E3: Post-ASB training | Only 637 samples (need 2,000+). Blocked. |
| E4: Window ensemble (35d/42d/63d) | All 64-66% HR — same feature set = no diversity to exploit. |
| E5: Line-level segmentation | Filter stack already handles. All segments profitable (61-73%). |

**Key insight:** Remaining alpha comes from the filter/signal stack, not model architecture changes. All CatBoost V12 configs produce the same quality within ~5pp. The February decline is structural (usage_spike_score distributional shift).

## Files Changed
```
CLAUDE.md                                                      — Dead ends updated (+5 new)
docs/08-projects/current/session-376-experiments/00-EXPERIMENT-PLAN.md — NEW: Full experiment plan + results
docs/09-handoff/2026-03-01-SESSION-376-HANDOFF.md              — NEW: This handoff
```

## What Still Needs Doing

### Monitor New Model
- `catboost_v12_noveg_train0110_0220` accumulating data as shadow
- Check after 3+ days of predictions: `bq query "SELECT * FROM nba_predictions.model_performance_daily WHERE model_id = 'catboost_v12_noveg_train0110_0220' ORDER BY game_date DESC LIMIT 5"`
- This is the first model with real spread data — watch if Feature 41 changes predictions

### Monitor New Signals (Mar 1+)
- Verify `fast_pace_over`, `volatile_scoring_over`, `low_line_over`, `line_rising_over` are firing
- Check: `SELECT signal_name, COUNT(*) FROM nba_predictions.pick_signal_tags, UNNEST(signal_tags) signal_name WHERE game_date >= '2026-03-01' GROUP BY 1 ORDER BY 2 DESC`
- Verify `prop_line_drop_over` is NOT firing

### Future Experiment Directions
Given that model architecture changes are exhausted within CatBoost V12, the next productive directions are:
1. **Alternative data sources** — new features from untried data (e.g., player tracking, advanced box score)
2. **Dynamic filter tuning** — auto-adjusting filter parameters based on recent performance
3. **Multi-sport diversification** — apply the system to other sports
4. **Live line arbitrage** — use intraday line movements for re-evaluation

## System State
- Season: 75-36 (67.6%), +32.25 units
- Best bets last 7d: 5-7 (41.7%) — below breakeven
- Best bets last 30d: 30-22 (57.7%) — above breakeven
- All models BLOCKED except new shadow + INSUFFICIENT_DATA
- 13 enabled models (trimmed from 24)
- Deployment: all clean except validation-runner (minor)
