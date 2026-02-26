# Session 348 Handoff — Decline Diagnosis, Fresh Retrain, Signal-Density Filter

**Date:** 2026-02-26
**Status:** ALL DEPLOYED. Four major changes shipped.

---

## What Changed

### 1. Signal-Density Negative Filter (Biggest Impact)

**Commit:** `3b8dae53` — `feat: add signal-density negative filter to best bets aggregator`

**File:** `ml/signals/aggregator.py`

Session 348 analysis revealed picks with only the base 3 signals (model_health + high_edge + edge_spread_optimal) hit **57.1%** (24/42), while picks with 4+ signals hit **76.2%** (48/63). The base signals fire on nearly every edge 5+ pick — they're necessary but not sufficient.

**Filter logic:** Block any pick where ALL qualifying signal tags are a subset of `{model_health, high_edge, edge_spread_optimal}`. Picks need at least one additional signal (rest_advantage_2d, combo_he_ms, combo_3way, book_disagreement, etc.) to pass.

**Backtest impact:**
- Before: 105 picks, 72-33, 68.6% HR
- After: 63 picks, 48-15, **76.2% HR** (+8pp)
- Volume reduction: ~40% (from ~5/day to ~3/day)

**Signal value ranking (Session 348 analysis):**

| Signal | HR | N | Status |
|--------|------|------|---------|
| book_disagreement | 100% | 8 | PREMIUM |
| combo_he_ms / combo_3way | 88.2% | 17 | PREMIUM |
| rest_advantage_2d | 74.0% | 50 | STRONG |
| prop_line_drop_over | 66.7% | 15 | OK |
| blowout_recovery | 57.1% | 14 | HARMFUL (WATCH status) |

**Position in filter chain:** After combo matching, before composite score. Algorithm version bumped to `v348_signal_density_filter`.

**Tests:** 7 new unit tests. All 37 aggregator tests pass.

**NOTE:** Tonight's 5 best bets (exported before deploy) are ALL base-only — they would have been blocked under the new filter. This is expected: they're all Stars UNDER from a stale model. Tomorrow will be the first day with the filter active.

### 2. Fresh v12_noveg_q55_tw Model Retrained & Registered as Shadow

**Model:** `catboost_v12_noveg_q55_tw_train0105_0215`
**GCS:** `gs://nba-props-platform-models/catboost/v12/monthly/catboost_v12_50f_noveg_q55_trend_wt_train20260105-20260215_20260226_110254.cbm`

Retrained the best-performing recipe (Q55 quantile + trend weights) with fresh data (Jan 5 - Feb 15):

| Metric | Value |
|--------|-------|
| HR edge 3+ | **68.0%** (17/25) |
| HR edge 5+ | **77.8%** (7/9) |
| OVER | **87.5%** (7/8) |
| UNDER | **58.8%** (10/17) |
| Vegas bias | **+0.11** (near-perfect calibration) |
| Role Players OVER | 85.7% (6/7) |

Gates failed on MAE (structural for quantile loss) and sample size (N=25, structural for 11-day eval). Registered as shadow with user approval. Will start generating predictions Feb 27.

**Also trained v9_low_vegas** (Jan 5 - Feb 15): 56.8% HR edge 3+, UNDER at 51.5% (below breakeven). Stars UNDER at 42.9%. Saved locally but NOT deployed.

### 3. pubsub_v1 Import Error Fixed

**Commit:** `424ca507` — `feat: Session 348 — decline diagnosis, fresh retrain, pubsub fix`

**Files:**
- `orchestration/cloud_functions/post_grading_export/requirements.txt` — added `google-cloud-pubsub>=2.20.0`
- `shared/utils/__init__.py` — made `PubSubClient` import lazy (try/except)

**Root cause:** `shared/utils/__init__.py` eagerly imported `PubSubClient` at module level, which requires `google-cloud-pubsub`. Any code doing `from shared.utils.X import Y` would trigger this, but post-grading-export didn't list pubsub as a dependency. Steps 6-8 (tonight/all-players.json, best-bets/all.json, record.json re-exports) would crash.

**Fix:** Two layers — add the dependency AND make the import lazy so other CFs without pubsub won't break.

### 4. Full February Decline Diagnosis

**Document:** `docs/08-projects/current/model-system-evaluation-session-343/SESSION-348-PLAN.md`

Diagnosed why best bets HR dropped from 73.1% (January) to 60.5% (February):

| Root Cause | Detail |
|-----------|--------|
| **OVER collapsed** | 80.0% → 58.3% (-22pp) |
| **Starters OVER collapsed** | 90.0% → 33.3% (-57pp) |
| **Full-vegas architecture failing** | 54.5% HR vs noveg 100% (N=6) |
| **Edge quality weakened** | Avg edge 7.2 → 5.4 |
| **All models past shelf life** | V12: 26 days stale, V9: 21 days |

**Additional research findings:**
- Medium slates (6-8 games) hit 74.4%, small slates 50%
- Friday is worst day (46.2% HR, N=13) — needs monitoring
- All profitable picks come from HOME players
- `blowout_recovery` signal is harmful (57.1% HR, N=14) — should be investigated

---

## Deployment Status

All services current after auto-deploy:
- `phase6-export`: `4abbeb69` (signal-density filter)
- `live-export`: `4abbeb69`
- `post-grading-export`: `4abbeb69` (pubsub fix)
- All other services: current from prior deploys

**New shadow model registered:** `catboost_v12_noveg_q55_tw_train0105_0215` — enabled in model_registry, will generate predictions starting Feb 27.

---

## Current Model Registry (11 enabled)

| Model ID | Family | Status | Training End | Notes |
|----------|--------|--------|-------------|-------|
| catboost_v9 | v9_mae | production | Feb 5 | Champion (21d stale) |
| catboost_v12 | v12_mae | production | Jan 31 | Co-champion (26d stale) |
| catboost_v12_mae_train0104_0215 | v12_mae | active | Feb 15 | |
| catboost_v12_noveg_mae_train0104_0215 | v12_noveg_mae | active | Feb 15 | |
| catboost_v12_noveg_q43_train0104_0215 | v12_noveg_q43 | active | Feb 15 | |
| catboost_v9_low_vegas_train0106_0205 | v9_low_vegas | active | Feb 5 | |
| catboost_v12_noveg_q55_train1225_0209 | v12_noveg_q55 | shadow | Feb 9 | |
| catboost_v12_noveg_q55_tw_train1225_0209 | v12_noveg_q55_tw | shadow | Feb 9 | Session 343 |
| catboost_v12_noveg_q57_train1225_0209 | v12_noveg_q57 | shadow | Feb 9 | Session 344 |
| catboost_v9_low_vegas_train1225_0209 | v9_low_vegas | shadow | Feb 9 | Session 343 |
| **catboost_v12_noveg_q55_tw_train0105_0215** | **v12_noveg_q55_tw** | **shadow** | **Feb 15** | **Session 348 — freshest model** |

---

## Known Issues

### blowout_recovery Signal Is Harmful
57.1% HR on 14 picks (vs 70.3% without). Currently in WATCH status. Doesn't appear as sole non-base signal, so it doesn't bypass the signal-density filter. But should be evaluated for demotion.

### Tonight's 5 Picks Would Be Blocked by New Filter
All 5 Feb 26 picks (Kawhi, Embiid, Luka, Ant, Green) have only base signals. These were exported BEFORE the filter deployed. Tomorrow will be the first filtered day. Results will tell us if the filter is correctly identifying the weak picks.

### Two v12_noveg_q55_tw Shadow Models Active
Both `train1225_0209` (older, Dec 25 - Feb 9) and `train0105_0215` (newer, Jan 5 - Feb 15) are enabled. Both will generate predictions. The older one could be disabled after the newer one has a few days of data.

---

## Next Session Priorities

### Priority 0: Grade Feb 26 Best Bets
- 5 picks (all base-only, all UNDER, all Stars/Starters)
- These would have been blocked by the new filter — their results are a natural experiment

### Priority 1: Verify Shadow Model Coverage (Feb 27)
- Expect ~117 predictions per shadow model (was 6 on Feb 26 due to deploy timing)
- The NEW `train0105_0215` model should also show ~117
- If still low, investigate feature preparation failures

### Priority 2: First Day With Signal-Density Filter (Feb 27)
- Check how many picks survive the new filter
- If zero picks on some days, consider lowering edge floor to 4.5 for signal-rich picks

### Priority 3: Grade Shadow Models (Mar 1-3)
- 5 shadow models now: 4 from Sessions 343-344 + 1 from Session 348
- Need 3-5 days of predictions before meaningful evaluation
- This is THE decision point for promoting q55_tw to production

### Priority 4: Evaluate blowout_recovery Demotion
- 57.1% HR (14 picks) vs 70.3% without
- Consider moving to DISABLED or removing from signal system
- Need to check if it provides value in specific sub-segments

### Priority 5: Evaluate Disabling Older q55_tw Shadow
- `train1225_0209` is now redundant with `train0105_0215`
- Disable older version after new one has 2-3 days of predictions

---

## Key Files

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Signal-density filter + algorithm version bump |
| `tests/unit/signals/test_aggregator.py` | 7 new tests for signal-density filter |
| `orchestration/cloud_functions/post_grading_export/requirements.txt` | Added google-cloud-pubsub |
| `shared/utils/__init__.py` | Lazy PubSubClient import |
| `CLAUDE.md` | Updated model section, dead ends, negative filters list |
| `docs/08-projects/current/model-system-evaluation-session-343/SESSION-348-PLAN.md` | Full decline diagnosis + recovery plan |
| `docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md` | Updated Week 2 checklist |
