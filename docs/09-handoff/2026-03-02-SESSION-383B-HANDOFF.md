# Session 383B Handoff — Retrain + Fleet Cleanup + Signal Review

**Date:** 2026-03-02
**Status:** Retrain passed all gates, fleet cleaned, worker redeployed. New model accumulating data.

## What Was Done

### 1. Retrain: `catboost_v12_noveg_train1222_0214` — ALL GATES PASSED

Trained with the validated 56-day window + vw015 config from Sessions 368-370.

| Parameter | Value |
|-----------|-------|
| Feature set | v12_noveg (50 features) |
| Training window | Dec 22 - Feb 14 (55 days) |
| Eval window | Feb 15 - Mar 1 (15 days) |
| Vegas weight | 0.15x |
| GCS path | `gs://nba-props-platform-models/catboost/v12/monthly/catboost_v12_50f_noveg_train20251222-20260214_20260301_222239.cbm` |

**Governance gates:**

| Gate | Result |
|------|--------|
| HR edge 3+ | **70.0% (N=30)** |
| Sample size | 30 >= 25 |
| Vegas bias | -0.14 |
| Tier bias | All clean |
| OVER | **90.0% (N=10)** |
| UNDER | **60.0% (N=20)** |
| MAE | 5.15 vs 5.50 baseline |

**Best segments:** Role OVER 100% (N=7), Starters 80% (N=10), Edge 5-7 87.5% (N=8).

**Feature importance:** `points_avg_season` (17.7%), `points_avg_last_10` (13.4%), `line_vs_season_avg` (9.8%), `points_avg_last_5` (7.3%), `deviation_from_avg_last3` (6.4%).

**Status:** Enabled in registry, will predict on next pipeline run (Mar 2).

**Other retrains attempted (not deployed):**
- `v12_noveg_vw015_train0104_0228` (Jan 4 - Feb 28): 66.67% HR e3+ but N=9 (1-day eval). Saved locally.
- `v12_noveg_vw015_train1230_0222` (Dec 30 - Feb 22): 66.67% HR e3+ N=12. Balanced OVER/UNDER. Failed sample size only.

### 2. Fleet Cleanup

**Zombie predictions deactivated:** 1,275 active predictions from 11 disabled models. These were competing in per-player best bets selection despite their source models being disabled.

**Affected models:** `catboost_v12_noveg_q5_train0115_0222` (205 preds), `catboost_v12_vw015_train1201_1231` (199), `catboost_v12_train0104_0208` (134), `catboost_v12_train1221_0208` (134), `catboost_v12_noveg_train1124_0119` (134), and 6 others.

**Root cause:** Worker Cloud Run revision was started before registry changes, caching stale model list. Disabled models continued generating predictions until revision restart.

**Final enabled fleet (11 models):**
- 6x CatBoost V12_noveg (incl. new retrain + spread-fix)
- 2x CatBoost V12 (with vegas)
- 2x CatBoost V16_noveg
- 1x LightGBM V12_noveg (spread-fix) + 1x older LightGBM

### 3. Worker + Coordinator Redeployed

Both `prediction-worker` (rev 00310-4j5) and `prediction-coordinator` (rev 00326-5r5) forced to new Cloud Run revisions via env var update. This refreshes the model registry cache — new models will predict, disabled models will stop.

### 4. Signal Review

- **3pt_bounce:** Recovered from COLD (40% 7d) to NORMAL (53.8% 7d). Season HR 58.8%. Keep monitoring.
- **prop_line_drop_over ghost:** Confirmed resolved. Last tracked Feb 28. `ACTIVE_SIGNALS` filter in `signal_health.py` correctly excludes it as of Mar 1.
- **sharp_line_drop_under:** 2 fires on Mar 1 (too early to assess).
- **sharp_line_move_over:** 1 fire, 100% (too early).

### 5. Spread-Fix Models Status

Both Session 382C models (`lgbm_v12_noveg_train0103_0227`, `catboost_v12_noveg_train0103_0227`) are enabled in registry but had no predictions — they were registered after the Mar 1 pipeline run. Will generate first predictions on Mar 2.

## Key Learning: Worker Model Cache Staleness

The prediction worker queries `model_registry WHERE enabled=TRUE` at **Cloud Run instance startup**, not per-request. With `minScale=1`, the instance persists indefinitely. Registry changes (enable/disable) don't take effect until a new revision is deployed.

**Fix applied:** Forced new revisions via `--update-env-vars`.

**Prevention:** After any model registry change, force a worker restart:
```bash
gcloud run services update prediction-worker \
  --region=us-west2 --project=nba-props-platform \
  --update-env-vars="MODEL_CACHE_REFRESH=$(date +%Y%m%d_%H%M)"
```

### 6. Fix: Model Family Classification Gaps

**Problem:** 7 of 11 enabled models were misclassified:
- `catboost_v12_noveg_*` MAE models fell through to `v12_mae` catch-all → wrong `v12_vegas` affinity group
- `catboost_v16_noveg_*` models returned `None` → bypassed all model-specific filters (AWAY block, direction affinity)

**Impact:** These models were:
- Not AWAY-blocked despite being noveg (should be blocked — v12_noveg AWAY HR 43.8%)
- Not subject to v12_noveg direction affinity analysis
- V16 models completely invisible to the filter system

**Fix (2 files):**
- `shared/config/cross_model_subsets.py`: Added `v12_noveg_mae`, `v16_noveg_mae`, `v16_noveg_rec14_mae` families before `v12_mae` catch-all
- `ml/signals/model_direction_affinity.py`: Added new families to `v12_noveg` affinity group, added V16 to direct system_id mapping

**Verification:** All 11 enabled models now classify correctly. No regressions on existing classifications.

**Deploy required:** prediction-coordinator (reads aggregator.py), signal_best_bets_exporter (Phase 6)

## Recommended Next Steps

1. **Monitor new retrained model** (Mar 2-3): Check if `catboost_v12_noveg_train1222_0214` generates predictions and tracks well.
2. **Best bets quality check** (Mar 4+): Compare performance after fleet cleanup + new model.
3. **Consider promoting** if retrained model shows 65%+ HR edge 3+ over first 50+ graded picks.
4. **Fleet thinning**: If `lgbm_v12_noveg_train1102_0209` (54.5% e3+ N=22, stale Nov training) continues underperforming, disable it.
5. **3pt_bounce**: If it drops below 50% 7d again, consider disabling.

## Best Bets Model Contribution (Feb 15+)

Key insight from this session: **raw model HR doesn't predict best bets contribution**.

| Model | Raw HR e3+ | Best Bets HR | Best Bets N |
|-------|-----------|-------------|-------------|
| catboost_v9_low_vegas | 56.7% | 100% | 3 |
| catboost_v12_noveg_train0110_0220 | 58.3% | 100% | 2 |
| catboost_v12 (production) | — | 25% | 4 |
| catboost_v12_noveg_q43 | 18.5% | 50% | 4 |
