# Session 332 Handoff — V12 Interim Promotion + Full Model Retrain

**Date:** 2026-02-23
**Focus:** V9 champion decay response — interim V12 promotion, all-family retrain
**Status:** COMPLETE — all tasks from Session 332 finished in Session 333

## What Happened

V9 champion hit BLOCKED state (47.1% edge 3+ HR, 14d: 45.6%). Below 52.4% breakeven for 2+ weeks. V12 base is HEALTHY at 58-60% 7d HR.

### Actions Taken

1. **Promoted `catboost_v12` as interim champion** (commit `40a5ed87`)
   - Changed `CHAMPION_MODEL_ID` in `shared/config/model_selection.py` from `catboost_v9` → `catboost_v12`
   - Pushed to main → auto-deploy across all services
   - Affects: best bets model health, pre-game signal, monitoring dashboards
   - Does NOT affect prediction generation pipeline (shadow models still generate independently)

2. **Deployed `nba-grading-service`** — was 1 commit behind (completeness checker fix)

3. **Fixed 3 scheduler job timeouts:**
   - `predictions-12pm`: 180s → 540s
   - `predictions-final-retry`: 180s → 540s
   - `self-heal-predictions`: 600s → 900s

4. **Updated CLAUDE.md** — new champion model info

5. **Full retrain completed** — all 9 families trained (see results below)

6. **4 top models uploaded to GCS** (`gs://nba-props-platform-models/catboost/v12/monthly/`)

## V12 Promotion Analysis

| Model | Edge 3+ HR | N | Edge 6+ HR | N | 7d State |
|-------|-----------|---|-----------|---|----------|
| `v12_train1102_1225` | **68.1%** | 138 | **100%** | 19 | DEGRADING |
| `v12_train1102_0125` | **73.9%** | 46 | **100%** | 6 | INSUF. DATA |
| `catboost_v12` (promoted) | 57.1% | 98 | 50.0% | 8 | **HEALTHY** |
| `catboost_v9` (demoted) | 51.6% | 545 | — | — | **BLOCKED** |

V12 base chosen for interim because it's the only V12 variant that is both HEALTHY and has sufficient sample size.

## Retrain Results — COMPLETE

Training window: Jan 4 → Feb 15 (42 days). Eval: Feb 16–22. All 9 families trained, saved locally, registered in `ml_experiments`.

| Family | MAE | Edge 3+ HR | N | Gates Passed | Notable |
|--------|-----|-----------|---|-------------|---------|
| v12_vegas_q43 | **4.70** | **66.7%** | 21 | 4/6 | Best MAE + HR |
| v12_noveg_q43 | 4.96 | **65.7%** | 35 | 4/6 | Most edge picks, vegas bias -1.98 (marginal) |
| v12_noveg_mae | 4.78 | **61.5%** | 26 | 5/6 | Only failed sample size |
| v9_mae | 4.86 | 60.0% | 20 | 4/6 | Solid V9 refresh |
| v9_low_vegas | 4.86 | 60.0% | 20 | 4/6 | Same as v9_mae |
| v12_mae (×2) | 4.74 | 55.6% | 18 | 3/6 | UNDER direction weak |
| v12_q43 | 4.74 | 55.6% | 18 | 3/6 | Same as v12_mae |

**All models improved MAE vs baseline.** All failed governance sample-size gate (7-day eval = 18-35 picks, need 50). Real validation happens after 2-3 days of production shadow data.

### Local Model Files

All saved in `models/` directory:
```
models/catboost_v9_54f_train20260104-20260215_20260223_082346.cbm     # v12_mae (54f)
models/catboost_v9_54f_train20260104-20260215_20260223_082428.cbm     # v12_mae dup
models/catboost_v9_50f_noveg_train20260104-20260215_20260223_082511.cbm  # v12_noveg_mae
models/catboost_v9_50f_noveg_train20260104-20260215_20260223_082549.cbm  # v12_noveg_q43
models/catboost_v9_54f_train20260104-20260215_20260223_082628.cbm     # v12_vegas_q43
models/catboost_v9_54f_q0.43_train20260104-20260215_20260223_082706.cbm  # v12_q43
models/catboost_v9_33f_train20260104-20260215_20260223_082719.cbm     # v9_mae
models/catboost_v9_33f_train20260104-20260215_20260223_082730.cbm     # v9_low_vegas
models/catboost_v9_33f_train20260104-20260215_20260223_082743.cbm     # v9_mae dup
```

### GCS Upload Status

4 models uploaded to `gs://nba-props-platform-models/catboost/v12/monthly/`:
- `catboost_v9_54f_q0.43_train20260104-20260215_20260223_082706.cbm` (v12_vegas_q43)
- `catboost_v9_50f_noveg_train20260104-20260215_20260223_082511.cbm` (v12_noveg_mae)
- `catboost_v9_50f_noveg_train20260104-20260215_20260223_082549.cbm` (v12_noveg_q43)
- `catboost_v9_54f_train20260104-20260215_20260223_082346.cbm` (v12_mae)

### DONE (Session 333) — Model Registration in `model_registry`

All 4 models registered in `nba_predictions.model_registry` with `enabled=TRUE, status='active'`:

| model_id | model_family | MAE | HR 3+ | N |
|----------|-------------|-----|-------|---|
| `catboost_v12_vegas_q43_train0104_0215` | v12_vegas_q43 | 4.70 | 66.7% | 21 |
| `catboost_v12_noveg_q43_train0104_0215` | v12_noveg_q43 | 4.96 | 65.7% | 35 |
| `catboost_v12_noveg_mae_train0104_0215` | v12_noveg_mae | 4.78 | 61.5% | 26 |
| `catboost_v12_mae_train0104_0215` | v12_mae | 4.74 | 55.6% | 18 |

Missing v12_mae model was also uploaded to GCS (was local-only).

## Known Issues

### FIXED (Session 333): Duplicate Model Families in Registry
Disabled 9 older/deprecated entries. Each family now has exactly 1 enabled model:
- v12_mae, v12_noveg_mae, v12_noveg_q43, v12_q43, v12_vegas_q43, v9_low_vegas, v9_mae (7 families, 7 rows)

### FIXED (Session 333): Hardcoded V9 References
- `player_blacklist.py` — was defaulting to `catboost_v9` for blacklist computation. Now uses `get_best_bets_model_id()` (V12)
- `signal_health.py` — had `SYSTEM_ID = 'catboost_v9'` hardcoded. Now uses champion dynamically
- `supplemental_data.py` — still has hardcoded `catboost_v12_noveg%` for cross-model CTE (low priority, annotation-only)

### FIXED (Session 333): Cross-Model Pattern Matching Bug
`catboost_v12_vegas_q43_*` models were misclassified as `v12_mae` instead of `v12_vegas_q43`. Added `alt_pattern` support to `MODEL_FAMILIES` in `cross_model_subsets.py`.

### FIXED (Session 333): `validation-runner` auto-deployed via push
Cloud Function — auto-deploys via `cloudbuild-functions.yaml` on push to main.

### Scheduler Jobs Still Failing
- `auto-retry-processor-trigger` — DEADLINE_EXCEEDED (Pub/Sub-based, different timeout mechanism)
- `predictions-last-call` — code 2 UNKNOWN (coordinator still processing when scheduler times out; work likely completes despite error)

### Firestore Completion Records Missing
No Phase 2/Phase 3 completion docs found for Feb 22 or Feb 23. Pipeline data IS flowing (analytics records exist), so this is a tracking gap, not a data gap. Investigate if Firestore writes are failing silently.

## Files Changed

### Session 332
- `shared/config/model_selection.py` — Champion model ID: V9 → V12
- `CLAUDE.md` — Updated ML Model section

### Session 333
- `shared/config/cross_model_subsets.py` — Added `alt_pattern` for v12_vegas_q43/q45 family classification
- `ml/signals/player_blacklist.py` — Dynamic champion model instead of hardcoded V9
- `ml/signals/signal_health.py` — Dynamic champion model instead of hardcoded V9
- `docs/09-handoff/2026-02-23-SESSION-332-HANDOFF.md` — Updated with completion status

## Next Session Priorities

1. ~~Register fresh models~~ DONE
2. ~~Fix duplicate model families~~ DONE
3. ~~Deploy validation-runner~~ DONE (auto-deploy on push)
4. ~~Monitor V12 interim champion~~ DONE (HEALTHY 59.6% HR 7d, best bets 68% HR 30d)
5. **Verify 4 new shadow models generating predictions** — check Feb 24 predictions after worker auto-deploys
6. **Investigate Firestore completion tracking** gap (Phase 2/3 docs missing)
7. **After 2-3 days of shadow data** — evaluate fresh models with 50+ edge 3+ graded picks for permanent promotion
8. **Top candidates for permanent champion:** v12_vegas_q43 (66.7% HR, best MAE 4.70) and v12_noveg_q43 (65.7% HR, most volume)
9. **Fix `supplemental_data.py` hardcoded `catboost_v12_noveg%`** — low priority, annotation-only impact
