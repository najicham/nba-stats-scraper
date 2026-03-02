# Session 382C Handoff — Spread Fix Retrains + Fleet Triage + Line Drop Signal

**Date:** 2026-03-02
**Commit:** `7a1530b2`
**Status:** Deployed, coordinator redeployed manually.

## Context

Fleet in crisis: 23/32 models BLOCKED, only 2 HEALTHY (both LightGBM 71.4%, 19 days stale). Best bets 7d: 46.2% (6-7). Biggest opportunity: Feature 41 (spread_magnitude) was ALL ZEROS the entire season — backfilled Session 375. No model had ever trained with real spread data. Governance gates reformed Session 381 (sample size 50 → 25).

## What Was Done

### 1. Spread Fix Model Retrains (Experiments 1-2)

Both trained on 56-day window (Jan 3 - Feb 27) with corrected spread_magnitude + implied_team_total.

**LightGBM (ALL GATES PASSED):**
- Model: `lgbm_v12_noveg_train0103_0227`
- HR edge 3+: **73.08% (N=26)**
- OVER: 60.0% (N=15), UNDER: 90.9% (N=11)
- MAE: 5.27 (vs 5.50 baseline)
- Vegas bias: +0.34
- Auto-registered, enabled in registry

**CatBoost V12_NOVEG + VW015 (force-registered):**
- Model: `catboost_v12_noveg_train0103_0227`
- HR edge 3+: **64.71% (N=17)** — all gates pass except sample size (17 < 25, only 2 eval days)
- OVER: 55.6%, UNDER: 75.0%
- MAE: 5.29
- Force-registered with `--force-register`, enabled in registry

**Spread feature importance:** `implied_team_total` = 0.94% (#28), `spread_magnitude` = 0.59% (#35). Non-zero but not transformative — the model was already getting scoring context from other features. The real value may emerge as these models accumulate live data.

### 2. Filter Health Audit (Experiment 3)

All 5 directly-evaluated filters in OK status. No drift or review alerts. Filter overlap analysis shows double-filtered picks at 19.6% HR — correctly identifying bad picks.

### 3. Line Drop UNDER Signal (Experiment 4)

**BQ validation:**
- DK line down 2+, UNDER: **72.4% HR (N=293)** — strong signal
  - Dec-Jan: 80.5% (N=185)
  - Feb: 58.3% (N=108) — above breakeven
- By line range: Mid 74.7%, High 74.8%, Low 55.6%
- Mirror of `sharp_line_move_over` (line UP 2+ → OVER, 67.8%)

**Built and deployed:** `sharp_line_drop_under` signal
- Files: `ml/signals/sharp_line_drop_under.py` (new), registry.py, signal_health.py, pick_angle_builder.py, combo_registry.py
- 22 signals total (was 21)
- Coordinator manually redeployed (signal changes not in auto-deploy trigger)

### 4. Fleet Triage — Zombie Prediction Cleanup

**Critical finding:** Disabling a model in registry does NOT deactivate its existing predictions. 12,977 active predictions from BLOCKED/legacy models were competing in best bets per-player selection.

**Worst offenders deactivated:**
| Model | HR | Active Preds | Risk |
|-------|-----|-------------|------|
| `v12_noveg_q43_train0104_0215` | 15.9% | 408 | Catastrophic UNDER |
| `v12_q43_train1225_0205` | 14.3% | 41 | Catastrophic |
| `v12_noveg_q57_train1225_0209` | 14.3% | 143 | Catastrophic |
| `v12_noveg_q55_tw_train1225_0209` | 11.1% | 143 | Catastrophic |
| `ensemble_v1` | Unknown | 597 | Avg edge 6.3 — winning selection |
| `xgb_v12_noveg_train1221_0208` | Poisoned | 10 | Avg edge 9.3 — Session 378c mismatch |
| `catboost_v9` | 36.8% | 450 | Worst champion |

**Total deactivated:** 12,977 predictions across 30 BLOCKED + legacy models.

**Important nuance (per user):** Overall model HR doesn't determine value — what matters is best bets pick quality. A model with poor overall HR can still source winning best bets picks at high edge. The models deactivated here were genuinely BLOCKED by the decay system with catastrophic HR (11-50%), and legacy models with no tracking. This was conservative triage of clearly dead models, not aggressive pruning.

## Deployment State

| Service | Status | Notes |
|---------|--------|-------|
| prediction-coordinator | Redeployed | Rev `prediction-coordinator-00325-7sv`, commit `7a1530b2` |
| model_registry | 2 models enabled | `lgbm_v12_noveg_train0103_0227`, `catboost_v12_noveg_train0103_0227` |
| player_prop_predictions | 12,977 deactivated | All BLOCKED + legacy model predictions |

## Active Fleet After Triage

**Enabled in registry (generating new predictions):**
- `lgbm_v12_noveg_train1102_0209` — HEALTHY, 71.4% HR (19d stale)
- `lgbm_v12_noveg_train0103_0227` — NEW, no data yet (spread-fix)
- `catboost_v12_noveg_train0103_0227` — NEW, no data yet (spread-fix, vw015)
- `catboost_v12_noveg_60d_vw025_train1222_0219` — INSUFFICIENT_DATA
- `catboost_v12_noveg_train0110_0220` — no performance data yet
- `catboost_v16_noveg_train1201_0215` — no performance data yet
- `catboost_v16_noveg_rec14_train1201_0215` — no performance data yet
- `catboost_v12_noveg_train0108_0215` — no performance data yet
- `catboost_v12_train0104_0215` — no performance data yet
- `catboost_v12_train0104_0222` — no performance data yet

**Disabled but still have active predictions (low risk):**
- Several disabled models with small volumes and decent/unknown HR. Left active since they're accumulating shadow data.

## Next Session Priorities

1. **Monitor new models:** Check if `lgbm_v12_noveg_train0103_0227` and `catboost_v12_noveg_train0103_0227` generated predictions on next pipeline run (~6 AM ET). Check edge distributions and directional balance.
2. **Monitor signal:** Check `sharp_line_drop_under` firing rate and if it's boosting signal count on UNDER picks.
3. **Best bets impact:** After 2-3 days, compare best bets HR before/after the fleet triage. The cleanup of 12,977 zombie predictions should improve selection quality.
4. **5-seed stability for CatBoost:** Was planned but skipped since model was force-registered. Run if needed for confidence.
5. **Consider enabling `lgbm_v12_noveg_train1201_0209`:** HEALTHY at 71.4% but disabled. Dec 1 training start = more focused window.
6. **Retrain cadence:** Both new models trained through Feb 27. Schedule next retrain around Mar 10-14 (7-day cadence).

## Dead Ends Confirmed This Session

- Spread features (F41/F42) are non-zero importance (0.59-0.94%) but not top-10. The model was already getting scoring context from other features. Value is marginal, not transformative.
- Filter stack is well-calibrated for February — no drift detected.
