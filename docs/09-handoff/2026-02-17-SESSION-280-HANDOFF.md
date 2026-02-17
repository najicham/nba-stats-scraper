# Session 280 Handoff — Full Season Replay with Multi-Model + Dimensional Analysis

**Date:** 2026-02-17
**Focus:** Build season replay simulator with 4 model families, 21 subsets, and full dimensional analysis
**Result:** Script BUILT + TESTED. Ready to run full season.

---

## What Was Done

### season_replay_full.py (NEW — 1,157 lines)

Built `ml/experiments/season_replay_full.py` — a multi-model season simulator that trains 4 model families every N days, applies subset definitions, runs dimensional analysis, and simulates signals.

**Extends** `season_walkforward.py` by importing its core functions (`prepare_features`, `compute_pnl`, `compute_hit_rate`, `_train_val_split`, constants) rather than duplicating them.

### 4 Model Families

| Key | Name | Contract | Loss |
|-----|------|----------|------|
| `v9` | V9 MAE | V9 (33 features) | RMSE |
| `v12_noveg` | V12 noveg MAE | V12_NOVEG (50 features) | RMSE |
| `v9_q43` | V9 Q43 | V9 (33 features) | Quantile:alpha=0.43 |
| `v9_q45` | V9 Q45 | V9 (33 features) | Quantile:alpha=0.45 |

### 21 Subsets Tracked

| Model | Subsets |
|-------|---------|
| V9 MAE | `top_pick`, `top_3`, `top_5`, `high_edge_over`, `high_edge_all`, `ultra_high_edge`, `all_picks` |
| V12 noveg | Same 7 with `nova_` prefix |
| V9 Q43 | `q43_under_top3`, `q43_under_all`, `q43_all_picks` |
| V9 Q45 | `q45_under_top3`, `q45_all_picks` |
| Cross-model | `xm_consensus_3plus`, `xm_consensus_5plus` |

### 7 Dimensional Analysis Tables

1. **Player Tier** — Star (25+), Starter (15-24.5), Bench (<15) by prop line
2. **Direction** — OVER vs UNDER
3. **Edge Bucket** — 3-4, 4-5, 5-7, 7+
4. **Confidence Tier** — Elite/Strong/Standard/Low
5. **Tier x Direction** — 6 combinations (Star OVER, Bench UNDER, etc.)
6. **Line Range** — Granular 5-pt buckets (5-9.5, 10-14.5, ..., 30+)
7. **Signal Simulation** — 16 signals using feature columns:
   - `bench_under`, `b2b_fatigue`, `b2b_under`, `rest_advantage`
   - `home_over`, `away_under`, `volatile_under`
   - `hot_streak_over`, `cold_snap_over`, `high_fatigue_under`
   - `star_high_edge`, `weak_def_over`, `strong_def_under`
   - `consistent_over`, `trending_up_over`, `trending_down_under`

### Dry Run Results (Dec 1 → Jan 15, 2 cycles)

Early patterns from the short window:

| Finding | Detail |
|---------|--------|
| **Bench UNDER dominates** | 69-76% HR across all models |
| **Low lines (5-14.5) crush** | 78-100% HR, high ROI |
| **25-29.5 is a dead zone** | 37-44% HR, lose money |
| **OVER has higher HR but fewer picks** | 72% V9 OVER vs 58% V9 UNDER |
| **Q43/Q45 generate more picks** | 188-214 edge 3+ picks vs 65-111 for MAE models |
| **Standard (3-5) edge bucket** | Best volume + profitability balance |
| **Cross-model consensus (3+)** | 60% HR on 70 picks (only 2 cycles) |

---

## Immediate Next Step — Run Full Season

The script is tested and ready. The next session should run:

```bash
# Full current season (will take 5-10 min, ~6 cycles x 4 models = 24 trainings)
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2025-11-04 --season-end 2026-02-17 \
    --cadence 14 --save-json ./replay_results.json
```

**What this does:**
- Loads all feature store + DK lines data in 2 BQ queries (bulk, fast)
- Expanding window: each cycle trains on ALL data from Nov 4 to train_end
- First eval starts ~Dec 2 (after 28-day bootstrap)
- Produces ~5-6 cycles of 14-day eval windows through Feb 17
- Trains 4 models per cycle, applies 21 subsets, 7 dimension tables, 16 signals
- Saves full results to JSON for further analysis

**What to look for in the output:**
1. **Subset Season Summary** — which subsets are most profitable over the full season?
2. **Model Summary** — does V9 beat V12? Do quantile models add value?
3. **Decay Analysis** — does 14-day retraining keep models fresh through week 2?
4. **Dimensional tables** — confirm Bench UNDER and low-line patterns hold over full season
5. **Signal simulation** — which feature-based signals actually work?

### Optional: Last Season

```bash
# Last season (longer, more cycles, may have sparse V12 features)
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2024-11-06 --season-end 2025-04-13 \
    --cadence 14 --save-json ./replay_results_last_season.json
```

### Optional: Single Model

```bash
# Just V9, 21-day cadence
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2025-11-04 --season-end 2026-02-17 \
    --cadence 21 --models v9
```

---

## What to Do With Results

After running, the key questions to answer:

1. **Which subsets to prioritize?** If `bench_under` and `q43_under_top3` lead, that shapes our best bets weighting
2. **Is cross-model consensus (3+) worth the complexity?** Compare its HR vs simpler subsets
3. **Should we adjust the 14-day cadence?** Decay analysis shows if models hold up or degrade
4. **Are any signals dead weight?** Signals below breakeven should be considered for removal
5. **Line range insights** — if 25-29.5 is consistently bad, add a smart filter to block it

---

## Files Created

| File | Lines | Description |
|------|-------|-------------|
| `ml/experiments/season_replay_full.py` | 1,157 | **NEW** — Full season replay simulator |
| `docs/09-handoff/2026-02-17-SESSION-280-HANDOFF.md` | this file | Handoff doc |

---

## Architecture Notes

- **Imports from `season_walkforward.py`** — does NOT duplicate `prepare_features`, `compute_pnl`, etc. If walkforward changes, replay inherits fixes.
- **2 BQ queries total** — bulk load, then everything is in-memory slicing. No per-cycle queries.
- **V12 feature availability check** — prints % populated at load time. If sparse (< 50%), V12 still trains but with NaN features (CatBoost handles natively). May underperform.
- **Cross-model consensus** requires 3+ models agreeing on direction with edge >= 3. With 4 models, `xm_consensus_5plus` can never fire. If V12 Q43/Q45 are added later (6 models), it becomes meaningful.
- **Signal simulation** uses feature_N_value columns from the eval dataframe — same features the model sees. This means signals are simulated with real pipeline data, not synthetic.
- **JSON export** includes all cycle details, subset results, and dimensional breakdowns for programmatic analysis.
