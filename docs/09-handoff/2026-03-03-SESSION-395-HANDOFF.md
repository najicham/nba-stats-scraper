# Session 395 Handoff — Fleet Rationalization + Calendar Regime Deep Dive

**Date:** 2026-03-03
**Status:** Research complete, deployed fleet changes, docs written

## What Was Done

### 1. Deployed Session 394 Changes (commit 181bce6e)
- SC=3 OVER block filter in aggregator.py
- New tools: `bin/simulate_best_bets.py`, `bin/bootstrap_hr.py`
- Training window sweep templates in `grid_search_weights.py`
- Model evaluation documentation

### 2. Fleet Rationalization — 12 → 6 Models
Disabled 7 redundant CatBoost clones (all r>0.97 correlated per Session 394 finding).

**Remaining fleet:**
| Model | Type | Training | Backtest HR |
|-------|------|----------|-------------|
| `catboost_v12_noveg_train0103_0227` | CatBoost V12 noveg | Jan 3-Feb 27 | 64.7% |
| `catboost_v12_noveg_train0108_0215` | CatBoost V12 noveg | Jan 8-Feb 15 | 71.1% |
| `catboost_v12_train0104_0222` | CatBoost V12 (vegas) | Jan 4-Feb 22 | 68.8% |
| `catboost_v16_noveg_train1201_0215` | CatBoost V16 noveg | Dec 1-Feb 15 | 70.8% |
| `catboost_v16_noveg_train0105_0221` | CatBoost V16 noveg (NEW shadow) | Jan 5-Feb 21 | 61.1% |
| `lgbm_v12_noveg_train0103_0227` | LightGBM | Jan 3-Feb 27 | 73.1% |

**Disabled:** v12_noveg_train0110_0220, v12_noveg_train1222_0214, v12_noveg_train1228_0222, v12_noveg_60d_vw025_train1222_0219, v12_train0104_0215, v12_train1228_0222, v16_noveg_rec14_train1201_0215

Worker cache refreshed twice (once for fleet prune, once for new V16 shadow).

### 3. Retrain Results — All 4 Configs Failed UNDER Gate

| Config | Edge 3+ HR | OVER | UNDER | Eval Window |
|--------|-----------|------|-------|-------------|
| V16 noveg | 61.1% | 81.8% | 52.0% | Feb 22-Mar 2 |
| V16 noveg rec14 | 54.1% | 58.3% | 52.0% | Feb 22-Mar 2 |
| V12 vw025 | 60.0% | 87.5% | 51.9% | Feb 22-Mar 2 |
| **V16 vw025** | **52.8%** | **66.7%** | **45.8%** | Feb 22-Mar 2 |

V16 noveg (no recency) is the best V16 config. Recency hurts V16. Adding vegas to V16 makes it worse (-8.3pp). V16 noveg registered as shadow via `--force-register` (UNDER miss is 0.4pp marginal).

### 4. UNDER Edge Cap — Skipped (No Impact)
Zero UNDER 10+ picks exist in best bets. The filter stack already prevents overconfident UNDER from reaching production. Cap would have no effect.

### 5. Calendar Regime Deep Dive (MAJOR FINDING)

Full findings in `docs/08-projects/current/calendar-regime-analysis/00-FINDINGS.md`.

**Key discovery:** Jan 30 → Feb 25 is a ~27-day toxic window around trade deadline (Feb 6) and All-Star break (Feb 13-18). The model under-predicts by ~1 point while actual scoring is unchanged, creating false UNDER signals.

**Tier x direction impact (normal → toxic HR):**
- Star OVER: 61.8% → 33.3% (-28.5pp) — worst affected
- Role UNDER: 59.0% → 41.8% (-17.2pp, N=777) — highest volume loser
- Bench OVER: 69.7% → 58.8% (-10.9pp) — **still profitable**
- Starter UNDER: 61.7% → 54.4% (-7.3pp) — **still profitable**

**Cross-season validated:** 2024-25 shows same pattern at smaller magnitude (2-4pp dips).

**Best bets picks during toxic window still profitable** at 65.9% (+6.72 units) — filter stack compensates but doesn't fully fix.

**Other patterns found:** Monday OVER best day (70.2%), B2B predictions better than rested (+4-7pp), light slate UNDER strongest (67.7%), edge compression during toxic (std halves).

## What's Next

### Immediate (High Priority)
1. **Implement calendar-aware filters** — Block Star OVER during toxic window. Consider raising UNDER edge floor during toxic.
2. **Build `bin/regime_analyzer.py`** — Daily regime detection + tier x direction reporting.

### Medium Priority
3. **Re-evaluate B2B signal** — Overall B2B is 63.5% HR (was disabled at 39.5% based on Feb-only data). Separate toxic window effect.
4. **Day-of-week analysis** — Monday OVER 70.2% vs Wednesday 53.3%. Needs cross-season validation.
5. **Slate size signal** — Light slate UNDER 67.7% vs mega 54.6%.

### Deferred
6. **Calendar feature for training** — Can't learn from ~2 events per season. Need multi-season data.
7. **Fleet diversity** — Need fundamentally different architectures (not more CatBoost retrains) for real diversity.

## Deployment Status
- Commit 181bce6e pushed and auto-deploying
- Worker refreshed at MODEL_CACHE_REFRESH=20260303_1816
- 7 models deactivated via `deactivate_model.py`
- V16 noveg shadow registered and enabled
- V16 vw025 registered but NOT enabled (worst performer)
