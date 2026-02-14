# Session 237 Handoff - Feature Store Array-to-Columns Migration (Phase 1)

**Date:** 2026-02-13
**Session Type:** Infrastructure / Schema Migration
**Status:** Phase 1 Complete (Dual-Write + Backfill)
**Next Session Focus:** Phase 2 - Migrate Readers to Individual Columns

---

## What Was Done

### Problem

The `ml_feature_store_v2` table stores feature values in `ARRAY<FLOAT64>`. This has two problems:
1. **BigQuery arrays cannot contain NULL** — unavailable features get hardcoded default constants (5.0, 112.0, etc.) that are indistinguishable from real data
2. **Multiple models share the same quality gate** — V9 and V12 need different features but `default_feature_count` / `is_quality_ready` don't differentiate

### Solution: Individual `feature_N_value` Columns

Added 54 nullable `FLOAT64` columns (`feature_0_value` through `feature_53_value`) that store:
- **Real data** → actual value (matches array)
- **Default/missing data** → `NULL` (instead of fake constant)

This enables:
- Proper NULL semantics (no more fake 5.0 / 112.0 constants)
- Per-model quality gating (V12 can ignore features it doesn't use)
- Simpler SQL queries (`WHERE feature_39_value IS NOT NULL` vs array gymnastics)

### Changes Made

**1. Processor dual-write** (`ml_feature_store_processor.py:1707-1717`)
```python
for i, val in enumerate(features):
    source = feature_sources.get(i, 'unknown')
    if source == 'default':
        record[f'feature_{i}_value'] = None
    else:
        record[f'feature_{i}_value'] = val
```
- Existing array write UNCHANGED (backward compatible)
- New individual columns written alongside

**2. DDL schema** (`schemas/bigquery/predictions/04_ml_feature_store_v2.sql`)
- Added 54 `feature_N_value FLOAT64` columns to CREATE TABLE (Section 4b)
- Added ALTER TABLE statement for existing tables

**3. BigQuery backfill** (51,300 rows across 3 quarterly batches + 3 date-specific fixes)
- Logic: `IF(feature_N_source != 'default', features[OFFSET(N)], NULL)`
- Used `SAFE_OFFSET` for features 37-53 (not all rows have 54-element arrays)
- 363 rows without source columns (pre-Session-134) correctly skipped

### Backfill Results

| Category | Rows | % |
|----------|------|---|
| Populated (real data) | 47,084 | 91.1% |
| NULL (source = 'default') | 4,216 | 8.2% |
| NULL (no source columns) | 363 | 0.7% |
| **Missed** | **0** | **0%** |
| **Total** | **51,663** | **100%** |

### Verification

- Dead features (47, 50) always NULL
- Features 41, 42 NULL when default, populated when real spread/total data exists
- Real feature values match array values exactly (tested on 2026-02-12)
- Zero missed rows confirmed

---

## What Was NOT Changed

- **No readers modified** — `data_loaders.py`, `quick_retrain.py`, validation SQL all still read from the `features` array
- **No quality gating changes** — `default_feature_count` / `is_quality_ready` still computed from array + source columns
- **Array still written** — backward compatible, existing code unaffected

---

## Phase 2: Migrate Readers (Next Session)

### Recommended Approach

**Step 1: Update `data_loaders.py`** (training data loader)
- Currently reads `features` array and unpacks to numpy
- Change to read individual `feature_N_value` columns
- NULL values become `np.nan` (CatBoost handles natively)
- This eliminates the "fake defaults pollute training data" problem

**Step 2: Update `quick_retrain.py`** (if it has its own data loading)
- Same pattern as data_loaders.py

**Step 3: Update validation SQL queries**
- Replace `features[OFFSET(N)]` with `feature_N_value`
- Replace `COUNTIF(default_feature_count > 0)` with `COUNTIF(feature_N_value IS NULL)` per-model

**Step 4: Per-model quality gating**
- V9 model: gate on features 0-36 (original 37 features)
- V12 model: gate on features 0-53 minus dead features (47, 50) and optional vegas (25-27)
- Add `v9_quality_ready` and `v12_quality_ready` computed columns or processor logic

**Step 5: Stop writing arrays** (final cleanup)
- Remove `features` and `feature_names` from processor record
- Remove array columns from DDL (or deprecate)

### Key Files to Modify

| File | Change | Priority |
|------|--------|----------|
| `predictions/worker/data_loaders.py` | Read individual columns | HIGH |
| `ml/experiments/quick_retrain.py` | Read individual columns | HIGH |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Per-model gating | MEDIUM |
| `predictions/coordinator/quality_gate.py` | Per-model gating | MEDIUM |
| Various validation SQL | Use `feature_N_value` | LOW |

### Important Caveats

1. **CatBoost handles NaN natively** — no need to impute. Just pass NULL/NaN features and CatBoost uses its built-in missing value handling.
2. **Training data will change** — features that were previously fake constants (5.0, 112.0) will now be NaN. This WILL change model behavior. Retrain after migration.
3. **Backward compat period** — keep array writes until all readers migrated and validated. Then remove in a separate session.

---

## Files Modified This Session

1. **`data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`** (lines 1707-1717)
   - Added individual `feature_N_value` column dual-write loop
2. **`schemas/bigquery/predictions/04_ml_feature_store_v2.sql`**
   - Added 54 `feature_N_value` columns to CREATE TABLE (Section 4b)
   - Added ALTER TABLE statement for existing table

---

## Outstanding Issues (from Session 236)

These were NOT addressed this session:

1. **P0: UPCG days_rest broken** — Feb 11-12 have 0% days_rest coverage. Must fix before Feb 19 games.
2. **V12 Model 1 shadow deployment** — Ready to deploy, all Phase 1 gates pass (67% avg HR edge 3+)
3. **Q43 at 39/50 picks** — Need 11 more edge 3+ graded for promotion decision
4. **Champion decaying** — 50.2% HR edge 3+, below 52.4% breakeven

---

## Start Prompt for Next Session

```
Read the latest handoff: docs/09-handoff/2026-02-13-SESSION-237-HANDOFF.md

Session 237 completed Phase 1 of the feature store array-to-columns migration:
- 54 individual feature_N_value columns added and backfilled (51.3K rows)
- Processor dual-writes both array and individual columns
- NULL = default/missing, value = real data

Priority tasks:
1. P0: Fix UPCG days_rest processor (broken since Feb 11, blocks Feb 19 predictions)
2. Phase 2 of column migration: update data_loaders.py to read individual columns instead of array
3. Deploy V12 Model 1 to shadow mode
```

---

**Handoff Complete. Next session: Fix UPCG days_rest (P0) + Phase 2 reader migration.**
