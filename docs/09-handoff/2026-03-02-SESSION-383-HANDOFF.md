# Session 383 Handoff — Manual Pick Grading Fix + Daily Steering

**Date:** 2026-03-02
**Commits:** `ed9a86ec`
**Status:** Fix deployed, steering report complete. Retrain recommended.

## What Was Done

### Fix: Manual pick grading in best-bets/all.json

**Problem:** Gui Santos (manual pick, `system_id = 'manual_override'`) appeared ungraded on the frontend despite having correct grading data in `signal_best_bets_picks` (actual_points=14, prediction_correct=true, WIN over 13.5).

**Root cause:** `BestBetsAllExporter._query_all_picks()` JOINs `signal_best_bets_picks` with `prediction_accuracy` on `system_id`. Manual picks have `system_id = 'manual_override'`, which has no matching row in `prediction_accuracy` (the grading service only grades real model predictions). The LEFT JOIN returned NULL grading.

**Fix:** Added `COALESCE` fallback in the query (lines 198-201):
```sql
COALESCE(pa.prediction_correct, b.prediction_correct) AS prediction_correct,
COALESCE(pa.actual_points, b.actual_points) AS actual_points,
COALESCE(pa.is_voided, FALSE) AS is_voided,
```

The `post_grading_export` already backfills `actual_points` and `prediction_correct` into `signal_best_bets_picks` via a fallback query — the data was there, just not being read by the `all.json` exporter.

**Verification:** Feb 28 record corrected from 2-3 (1 pending) to 3-3-0. Both `all.json` and `signal-best-bets/2026-02-28.json` re-exported.

**Impact:** All future manual picks will grade correctly on the frontend. No further action needed.

## Daily Steering Findings (2026-03-01)

### System State: DEGRADED

The system is in a losing stretch. Key metrics:

| Metric | Value | Assessment |
|--------|-------|------------|
| Best bets last 7d | **5-7 (41.7%)** | Actively losing |
| Best bets last 14d | 12-10 (54.5%) | Below breakeven |
| Best bets last 30d | 29-21 (58.0%) | Profitable but declining |
| catboost_v12 state | BLOCKED (50.6% 7d) | Primary model failing |
| catboost_v12 edge 5+ | **42.9% (N=21)** | LOSING at high edge |
| OVER HR 14d | 45.5% (N=11) | OVER collapse continuing |
| UNDER HR 14d | 63.6% (N=11) | UNDER still holding |

### Model Fleet Status

- **33 models tracked**, only 2 HEALTHY (LightGBM pair at 71.4% but N=7 each)
- catboost_v12 is BLOCKED and losing at edge 5+ — filter stack cannot save it
- v9_low_vegas is the only model PROFITABLE at edge 5+ (66.7%, N=18) but BLOCKED overall
- 25+ models are BLOCKED — fleet is mostly dead weight

### Market Regime

- Compression: 0.853 (GREEN — edge supply is fine)
- 3d rolling HR: 40.0% (RED — tiny N=5 but alarming)
- Direction divergence: 18pp (YELLOW — UNDER carrying, OVER dragging)
- Residual bias: -0.87 pts (OK — slight under-prediction)

### Signal Health

- 0 HOT, 13 NORMAL, 2 COLD
- b2b_fatigue_under: COLD (already disabled)
- 3pt_bounce: trending COLD (40% 7d, down from 58.8% season)
- Combo signals (combo_3way, combo_he_ms) haven't fired in 7d

## Recommended Next Steps (Priority Order)

### 1. Retrain (HIGH PRIORITY)

The validated config from Sessions 368-370:
- **56-day training window** with **vegas weight 0.15x**
- Cross-season validated at 66.7% HR, 73.9% on optimal window
- March data should help — Feb was the structural degradation period

```bash
# Suggested retrain command (adjust dates for 56-day window ending ~Feb 28):
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "v12_noveg_vw015_train0104_0228" \
  --feature-set v12_noveg \
  --no-vegas \
  --category-weight vegas=0.15 \
  --train-start 2026-01-04 \
  --train-end 2026-02-28
```

**Governance gates must pass before any deployment.** Train → gates → shadow 2+ days → promote.

### 2. Fleet Cleanup (MEDIUM)

25+ BLOCKED models are noise. Consider disabling models that have been BLOCKED 7+ consecutive days with N >= 20 (enough data to confirm they're bad). This simplifies monitoring and reduces multi-model aggregator confusion.

Candidates for immediate disable:
- catboost_v12_noveg_q43_train0104_0215 (15.9% HR, BLOCKED 5d)
- catboost_v12_q43_train1225_0205 (14.3% HR, BLOCKED 7d)
- catboost_v12_noveg_q57_train1225_0209 (14.3% HR, BLOCKED 1d)
- catboost_v12_noveg_q55_tw_train1225_0209 (11.1% HR, BLOCKED 1d)
- catboost_v12_vegas_q43_train0104_0215 (20.0% HR, BLOCKED 5d)
- All Q43 quantile models (confirmed dead end across multiple sessions)

### 3. OVER Filter Tightening (LOW)

OVER is at 45.5% HR in best bets over 14d. Could investigate whether additional OVER restrictions would help, but this is likely a symptom of model staleness rather than a filter gap. Retrain should address the root cause.

### 4. Signal Review

- `3pt_bounce` trending COLD — may need to disable or add conditions
- `prop_line_drop_over` still shows in signal_health_daily despite being DISABLED in code — check if signal_health computation needs updating

## Schedule Context

Full schedule all week: 4-10 games/day through Mar 9. No gaps, no breaks. Good volume for a retrained model to accumulate data quickly.
