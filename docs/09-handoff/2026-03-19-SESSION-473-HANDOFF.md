# Session 473 Handoff — Pick Drought Root Cause Found & Fleet Restored

**Date:** 2026-03-19
**Previous:** Session 472 (CF eval window fix, catboost_v12_noveg_train0113_0310 manual retrain)

## TL;DR

The session 472 manual retrain did NOT fix the edge collapse. `catboost_v12_noveg_train0113_0310` also has avg_abs_diff ~1.1 — same problem. The real cause: models trained through March (TIGHT market, Vegas MAE 4.1-4.9) learn to track the Vegas line. Restored the 4 Feb-trained models with 67-73% governance HR that were generating picks as recently as March 4-10. Fleet now at 6 models.

---

## What Was Done

### 1. Full Drought Diagnosis

Investigated the full chain from signal health to model edge to filter audit.

**Edge distribution (all active models):**
- Models trained through March 10: avg_abs_diff **1.1-1.3** (edge collapse)
- Models trained through Feb 8-27: avg_abs_diff **1.4-2.2** (healthier)

The `catboost_v12_noveg_train0113_0310` from session 472 had avg_abs_diff = 1.1 on all dates March 11-16. Same as the disabled models.

**Root cause of edge collapse:** Vegas MAE dropped from 5.3 (late Feb) to 4.1-4.9 (mid-March) — the TIGHT market regime. Models trained on this period learn Vegas is accurate and predict close to the line. Models trained through end-of-February learned from higher-variance data and deviate more.

**Double deadlock in BB pipeline:**
1. OVER floor 5.0 + models avg_abs_diff 1-2 → few edge_5+ candidates
2. Edge_5+ OVER candidates blocked by `sc3_over_block` (real_sc = 0): all HOT OVER signals (`projection_consensus_over` 80%, `usage_surge_over` 83%) are in SHADOW_SIGNALS → don't count toward real_sc
3. UNDER candidates: signals mostly COLD, failing `signal_density`/`under_low_rsc`
4. Result: 0 picks March 12-18

**Filter audit summary (rejected_json analysis):**
- March 12-18: 3-32 candidates/day, 0 passing
- UNDER filters dominating: bench_under, flat_trend_under, under_after_streak, under_low_rsc, b2b_under_block
- March 17-18: only 3-4 candidates (edge floor + signal collapse both active)

### 2. Re-enabled 4 Feb-Trained Models

The model fleet was reduced to 2 models (session 472). The March 4-10 productive fleet had 9-11 models. Re-enabled the 4 with best governance HR and Feb training windows (avoiding TIGHT market):

| Model | Gov HR | Gov N | Trained through |
|-------|--------|-------|-----------------|
| `lgbm_v12_noveg_train0103_0227` | **73.1%** | 26 | Feb 27 |
| `catboost_v12_noveg_train0108_0215` | **71.1%** | 38 | Feb 15 |
| `catboost_v16_noveg_train1201_0215` | **70.8%** | 24 | Feb 15 |
| `catboost_v12_noveg_train0104_0215` | **67.6%** | 37 | Feb 15 |

**Current enabled fleet (6 models):**
- `catboost_v12_noveg_train0113_0310` (session 472, 66.7%)
- `lgbm_v12_noveg_train0103_0227` (73.1%) ← re-enabled
- `catboost_v16_noveg_train1201_0215` (70.8%) ← re-enabled
- `catboost_v12_noveg_train0108_0215` (71.1%) ← re-enabled
- `catboost_v12_noveg_train0104_0215` (67.6%) ← re-enabled
- `lgbm_v12_noveg_vw015_train1215_0208` (bridge, 66.7%)

### 3. Fixed `retrain.sh` lgbm/xgb Framework Bug (P0.4)

`retrain.sh --all` was training lgbm and xgb families as CatBoost (default) because it never read `model_type` from the registry. Fixed by:
1. Adding `model_type` to `get_families()` BQ query
2. Adding `--framework lightgbm/xgboost` to RETRAIN_ARGS when `model_type != catboost`

Now `retrain.sh --all` will correctly use LightGBM for `lgbm_v12_noveg_mae` family and XGBoost for `xgb_v12_noveg_mae` family.

**Commit:** `65b6d8c4` — pushed to main.

### 4. Confirmed P0.3 Already Fixed

`filter_counts` was already `defaultdict(int)` at line 341 of aggregator.py — the P0.3 task was already done before this session.

---

## Current State

### Signal Health (March 18)

**COLD (bad):** downtrend_under (16.7%), star_favorite_under (21.4%), sharp_line_drop_under (25%), scoring_cold_streak_over (33.3%), edge_spread_optimal (41.7%), high_edge (41.7%), combo_he_ms (50%), combo_3way (50%)

**HOT (good but mostly SHADOW):** projection_consensus_over (80% — SHADOW), usage_surge_over (83% — SHADOW), self_creation_over (100% — SHADOW), q4_scorer_over (67% — active), b2b_boost_over (67% — active), consistent_scorer_over (75% — SHADOW)

**Active non-shadow OVER signals that generate real_sc:**
- `line_rising_over`: NORMAL 60% (N=10)
- `book_disagreement`: NORMAL 60% (N=5)
- `q4_scorer_over`: HOT 67% (N=3)
- `b2b_boost_over`: NORMAL 67% (N=6)
- `cold_3pt_over` (3pt_bounce): NORMAL 67% (N=3)

### League Macro

Vegas MAE trend: 5.0-5.3 in late Feb → 4.1-4.9 in mid-March (TIGHT market). model_mae_7d increased to 6.28 (models getting worse while market tightened). Market regime: NORMAL as of March 15.

---

## P0 — Immediate Actions (Next Session)

### 1. Check if Picks Flow on March 19

The 6-model fleet will run at 6 AM ET. Expect 3-7 picks/day if OVER signals fire naturally.

```sql
SELECT game_date, system_id, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-19'
GROUP BY 1, 2 ORDER BY 1 DESC
```

And verify edge distribution for Feb-trained models:
```sql
SELECT system_id,
  ROUND(AVG(ABS(predicted_points - current_points_line)),2) as avg_abs_diff,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as edge_5plus,
  COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE AND current_points_line IS NOT NULL
  AND system_id IN (
    'lgbm_v12_noveg_train0103_0227',
    'catboost_v12_noveg_train0108_0215',
    'catboost_v16_noveg_train1201_0215',
    'catboost_v12_noveg_train0104_0215'
  )
GROUP BY 1
```

Expected: avg_abs_diff 1.2-2.0 for these models (better than the 1.1 models).

### 2. If Still 0 Picks — Signal Deadlock Remains

If picks don't flow with 6 models, the OVER signal deadlock is still blocking. The HOT OVER signals (`projection_consensus_over` 80%, `usage_surge_over` 83%) are in SHADOW_SIGNALS and can't generate real_sc.

**Option A (lower risk):** Promote `usage_surge_over` from SHADOW_SIGNALS to active. It's at 83.3% HR (7d N=6), 69.2% HR (14d N=13). Graduation threshold is N>=30 at BB level with HR>=60%. Still short on N but the HR is strong.

**Option B (targeted):** Check what signals fired on the March 4-10 picks that passed — if OVER picks fired `line_rising_over` or `book_disagreement`, more models will help. If only UNDER picks passed, re-enabling models won't solve OVER deadlock.

```sql
-- What signals fired on the March 4-10 picks that passed filters?
SELECT game_date, pick_direction, signal_count, real_sc,
  signal_tags, system_id
FROM nba_predictions.signal_best_bets_picks
WHERE game_date BETWEEN '2026-03-04' AND '2026-03-10'
ORDER BY game_date DESC
```

### 3. Weekly Retrain (Monday March 23)

First CF run with the fixed out-of-sample eval window. Watch Slack `#deployment-alerts` for completion.

**CRITICAL: New models from this retrain will likely ALSO have edge collapse** if train_end = March 22 (TIGHT market). Might need to:
- Retrain with explicit train_end = Feb 28 to get Feb-trained models
- Or just continue with the 4 re-enabled Feb models as the core fleet

---

## P1 — Follow-up Tasks

### HOT OVER Signals in Shadow — Watch for Graduation

These signals need BB-level N >= 30 to graduate from SHADOW_SIGNALS:
- `usage_surge_over`: 83.3% 7d HR, N=6 at BB level (need 24 more)
- `consistent_scorer_over`: 75% HR, N=8
- `projection_consensus_over`: was 0% historically, now 80% 7d — unclear if genuine recovery

If `usage_surge_over` maintains HR >= 60% until N=30, remove from SHADOW_SIGNALS and add to OVER_SIGNAL_WEIGHTS.

### UNDER Signal Collapse — Ongoing Watch

All major UNDER signals COLD. No code action needed (they're already in BASE/SHADOW). But if UNDER HR doesn't recover by March 25, consider whether scoring environment shift (PPG 10.2→11.0) needs a signal audit.

### Season-End Tanking Risk

NBA regular season ends ~April 13. Add `tanking_risk` filter by April 1 for games where one team is tanking. This would block UNDER picks for star players on contenders playing tanking teams (stars get big minutes in comfortable wins).

---

## What NOT to Do

- **Don't retrain with train_end in March** — TIGHT market period causes edge collapse. Use Feb 28 or earlier as train_end if manually retraining.
- **Don't lower OVER floor (5.0)** to compensate for edge collapse — 5-season validated.
- **Don't promote `projection_consensus_over` from SHADOW** yet — historical BB HR was 0% (0-5). The recent 80% 7d is on 15 picks. Wait for N >= 30 at BB level.
- **Don't re-enable the March 16 batch** (`train0118_0315`) — confirmed edge collapse, avg_abs_diff 0.84-0.93.
- **Don't re-enable `catboost_v12_noveg_train0113_0310` as primary** — it has the same edge collapse (avg_abs_diff 1.1). It's still enabled but lower priority in the pool-and-rank.

---

## Key Files Changed This Session

| File | Change |
|------|--------|
| `bin/retrain.sh` | Fixed `get_families()` to include model_type; adds `--framework` flag for lgbm/xgb families |
| BQ `model_registry` | Re-enabled 4 models: lgbm_v12_noveg_train0103_0227, catboost_v12_noveg_train0108_0215, catboost_v16_noveg_train1201_0215, catboost_v12_noveg_train0104_0215 |

---

## Quick Start for Next Session

```bash
# 1. Check if March 19 picks are flowing
/todays-predictions

# 2. Check filter audit for candidate volume
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT game_date, total_candidates, passed_filters, algorithm_version
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-19'
ORDER BY 1 DESC"

# 3. If still 0 picks — check what signals fired on recent picks
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT game_date, player_lookup, pick_direction, real_sc, signal_tags
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-19'
ORDER BY 1 DESC"
```
