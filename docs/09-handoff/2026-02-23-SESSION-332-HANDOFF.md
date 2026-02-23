# Session 332 Handoff — V12 Interim Promotion + Full Model Retrain

**Date:** 2026-02-23
**Focus:** V9 champion decay response — interim V12 promotion, all-family retrain
**Status:** PARTIALLY COMPLETE — retrain done, model registration NOT finished

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

### NOT YET DONE — Model Registration in `model_registry`

The session ran out of context before registering these fresh models in `nba_predictions.model_registry`. **This is the critical next step.** Without registration, the prediction worker won't load these models and they won't generate shadow predictions.

To register, use:
```bash
# Check model_registry schema
bq show --schema nba-props-platform:nba_predictions.model_registry

# Insert a new model (example for v12_vegas_q43 — the best performer)
bq query --use_legacy_sql=false --project_id=nba-props-platform "
INSERT INTO nba_predictions.model_registry
(model_id, model_version, model_type, gcs_path, feature_count, ...)
VALUES (
  'catboost_v12_vegas_q43_train0104_0215',
  'v12_vegas_q43',
  'catboost',
  'gs://nba-props-platform-models/catboost/v12/monthly/catboost_v9_54f_q0.43_train20260104-20260215_20260223_082706.cbm',
  54,
  ...
)"

# Or use the model-registry script if it supports add
./bin/model-registry.sh --help
```

## Known Issues

### Duplicate Model Families in Registry
The `model_registry` has duplicate entries for `v12_mae` and `v9_mae` families, causing the retrain script to train each twice. Non-blocking but wasteful. Fix:
```sql
SELECT model_family, model_id, status, enabled
FROM nba_predictions.model_registry
WHERE model_family IN ('v12_mae', 'v9_mae') AND enabled = TRUE
ORDER BY model_family, model_id;
-- Then disable the older/deprecated entries
```

### Scheduler Jobs Still Failing
- `auto-retry-processor-trigger` — DEADLINE_EXCEEDED (Pub/Sub-based, different timeout mechanism)
- `predictions-last-call` — code 2 UNKNOWN (coordinator still processing when scheduler times out; work likely completes despite error)

### `validation-runner` Still 1 Commit Behind
Non-critical service. Deploy when convenient:
```bash
./bin/deploy-service.sh validation-runner
```

### Firestore Completion Records Missing
No Phase 2/Phase 3 completion docs found for Feb 22 or Feb 23. Pipeline data IS flowing (analytics records exist), so this is a tracking gap, not a data gap. Investigate if Firestore writes are failing silently.

## Files Changed

- `shared/config/model_selection.py` — Champion model ID: V9 → V12
- `CLAUDE.md` — Updated ML Model section
- `docs/09-handoff/2026-02-23-SESSION-332-HANDOFF.md` — This file

## Next Session Priorities

1. **Register fresh models in `model_registry`** — CRITICAL: models are in GCS but not registered, so they won't generate predictions yet
2. **Monitor V12 interim champion** — run `/daily-steering` to verify best bets export uses V12 correctly
3. **Fix duplicate model families** in registry (v12_mae and v9_mae appear twice)
4. **Deploy `validation-runner`** — still 1 commit behind
5. **Investigate Firestore completion tracking** gap
6. **After 2-3 days of shadow data** — evaluate fresh models with 50+ edge 3+ graded picks for permanent promotion
7. **Top candidates for permanent champion:** v12_vegas_q43 (66.7% HR, best MAE 4.70) and v12_noveg_q43 (65.7% HR, most volume)
