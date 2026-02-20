# Session 309 Handoff — Fix model_performance_daily Registry Name Mismatch

**Date:** 2026-02-19
**Focus:** Fix model_performance_daily computation broken since ASB retrain (Feb 18)

---

## What Was Done

### 1. Root Cause

`model_performance_daily` stopped computing after the All-Star Break retrain. The table had only 1 model (`catboost_v9`) with data through Jan 31. Root cause: `get_active_models_from_registry()` returned full deployment names from the model registry (e.g., `catboost_v9_33f_train20260106-20260205_20260218_223530`) but `prediction_accuracy` stores short runtime system_ids (e.g., `catboost_v9`). The `WHERE system_id IN UNNEST(@model_ids)` clause found no matches.

### 2. Fix: Discovery-Based Model Lookup

Replaced `get_active_models_from_registry()` with `discover_active_models()` — a two-step approach:

**Step A — Discover runtime system_ids from grading data:**
```sql
SELECT DISTINCT system_id
FROM prediction_accuracy
WHERE game_date BETWEEN DATE_SUB(@ref_date, INTERVAL 30 DAY) AND @ref_date
  AND {MODEL_FAMILIES SQL filter}
  AND prediction_correct IS NOT NULL
```
Returns actual runtime IDs: `catboost_v9`, `catboost_v12`, `catboost_v9_q43_train1102_0131`, etc.

**Step B — Map training dates via family classification:**
- Query all model_registry entries with training_end_date
- Classify each into a family using `classify_system_id()` (with new v9_mae fallback)
- Build family → most_recent_training_end_date mapping
- Map each runtime system_id → family → training date

### 3. V9 MAE Fallback in classify_system_id()

Registry champion name `catboost_v9_33f_train*` didn't match any family pattern (v9_mae requires exact match `catboost_v9`). Added fallback: if a system_id starts with `catboost_v9` but didn't match any specific V9 variant (q43, q45, low_vegas), classify as v9_mae.

### 4. Date-Aware Backfill

Made discovery date-aware so backfill finds which models had grading data at each historical date (not just today). The backfill correctly showed:
- Jan 20-31: 1 model (catboost_v9)
- Feb 1-7: 2 models (V9 + V12 shadow)
- Feb 8-12: 4 models (V9, V12, V9 Q43, V9 Q45)
- Feb 18: 4 models (post-ASB, all fresh)

### 5. Backfill Executed

Backfilled Jan 20 → Feb 18: **46 rows across 24 dates**. Deleted 47 stale rows from the old single-model computation.

---

## Files Modified

| File | Change |
|------|--------|
| `shared/config/cross_model_subsets.py` | Added v9_mae fallback in `classify_system_id()` for registry names like `catboost_v9_33f_train*` |
| `ml/analysis/model_performance.py` | Replaced `get_active_models_from_registry()` with `discover_active_models()` + `_map_training_dates_from_registry()`. Made backfill per-date discovery. Updated fallback models. |

---

## Verification

```
$ PYTHONPATH=. python ml/analysis/model_performance.py --date 2026-02-18
Discovered 4 runtime models: catboost_v12, catboost_v9, catboost_v9_q43_train1102_0131, catboost_v9_q45_train1102_0131
  catboost_v9_q45_train1102_0131: 85.7% HR 7d (N=7), state=HEALTHY
  catboost_v12: None% HR 7d (N=0), state=INSUFFICIENT_DATA
  catboost_v9: 60.0% HR 7d (N=5), state=HEALTHY
  catboost_v9_q43_train1102_0131: 75.0% HR 7d (N=8), state=HEALTHY
```

---

## What This Unblocks

- **Decay state machine** — HEALTHY/WATCH/DEGRADING/BLOCKED tracking resumes for all 4 models
- **Slack alerts** — `decay-detection` CF (11 AM ET daily) will receive current model state data
- **Future Phase B** — Trust-weighted scoring needs per-model performance history

---

## Known Issue Resolved

Session 308 item #1 ("model_performance_daily registry mismatch") is now **FIXED**.

---

## Next Session Priorities

1. **Build signal graduation tracking table** — BQ table tracking each signal's N, HR, lift at each edge bucket
2. **Build `/weekly-report-card` skill** — Performance cube from `01-REVISED-STRATEGY.md`
3. **Verify Phase A in production** — Check for non-V9 picks after tonight's games
