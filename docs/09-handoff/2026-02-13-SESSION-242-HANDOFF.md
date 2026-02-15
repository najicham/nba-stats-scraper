# Session 242 Handoff — All-Star Break Infrastructure Fix + Training Data Discovery

**Date:** 2026-02-13
**Status:** Infrastructure fixes COMPLETE, training data fix READY FOR REVIEW

---

## What Was Done

### Block 1: IAM Permissions (COMPLETE)
Fixed `roles/run.invoker` on 8 services that were missing it:
- `phase3-to-grading`, `phase3-to-phase4-orchestrator`, `validation-runner`
- `validate-freshness`, `grading-gap-detector`, `live-export`
- `nba-phase1-scrapers`, `nba-grading-service`

**Root cause:** `gcloud functions deploy` with Eventarc wipes IAM on the underlying Cloud Run service.

### Block 2: Scheduler Jobs (COMPLETE)
- Fixed 3 scraper workflow jobs (`nba-props-morning`, `midday`, `pregame`): updated URI from old format (`nba-phase1-scrapers-756957797294.us-west2.run.app`) to current (`nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app`), updated OIDC audience to match, increased `attemptDeadline` from 540s to 900s
- Fixed `live-export-late-night`: updated from Gen1 Cloud Functions URL to Gen2 Cloud Run URL
- 7 prediction jobs returning NOT_FOUND: expected during All-Star break (no games scheduled), will self-resolve Feb 19
- 3 PERMISSION_DENIED jobs: resolved by Block 1 IAM fixes
- 3 phase6 jobs (CODE_-1): newly created, haven't fired yet, will work on next run

### Block 3: Deploy 4 Stale Services (COMPLETE)
- `nba-grading-service` — deployed via hot-deploy (Cloud Run service)
- `reconcile` — deployed as Cloud Function. **Required adding missing deps** (`google-cloud-firestore`, `google-cloud-pubsub`, `google-cloud-storage`) because `shared/clients/__init__.py` eagerly imports all pool modules
- `validate-freshness` — deployed as Cloud Function, same dep fix
- `validation-runner` — deployed as Cloud Function, worked first try
- IAM re-applied to all 3 Cloud Functions post-deploy

### Block 4: V9 Retrain (ATTEMPTED — LED TO DISCOVERY)
Ran retrain with `--train-start 2025-11-02 --train-end 2026-02-05 --eval-start 2026-02-06 --eval-end 2026-02-12`. Results:
- MAE: 4.76 (better than 5.14 baseline)
- Hit rate: 49.5% (below 54.5% baseline)
- Edge 3+ picks: **only 2** out of 325 predictions
- Governance gates: FAILED (3 of 6)

Classic retrain paradox — fresh data makes model hug Vegas lines, producing near-zero edges.

### Block 5: Unknown Model Investigation (COMPLETE)
`catboost_v9_2026_02` identified as a Feb 1 monthly retrain experiment (`V9_2026_02_MONTHLY`). Registered as "untested" in model registry. Performance: 22.9% HR, 5.91 MAE. Legitimate shadow experiment, no action needed.

### Block 6: Prevention Infrastructure (COMPLETE)
- **`bin/infrastructure/fix_all_iam.sh`** — Created. Auto-discovers all Pub/Sub push and Cloud Scheduler HTTP targets, checks IAM, fixes missing bindings. JSON parsing for reliable output. Supports `--dry-run`. Verified: 45 services, 44 OK, 1 non-existent (mlb-grading-service)
- **Coordinator 200 on no-games** — `predictions/coordinator/coordinator.py` returns `200 {"status": "no_games_scheduled"}` instead of 404 when no games exist
- **Scheduler canary** — `bin/monitoring/pipeline_canary_queries.py` new `check_scheduler_health()` using Cloud Scheduler API, alerts if >3 jobs failing
- **Cloud Function deps fixed** — `pipeline_reconciliation/requirements.txt` and `prediction_monitoring/requirements.txt` now include firestore, pubsub, storage

### Commit
`1dd0a69c` — pushed to main, auto-deploy triggered for coordinator

---

## CRITICAL DISCOVERY: Training Data Filter Bug

### The Problem

The **entire 2024-25 NBA season is excluded from V9 model training** due to an overly aggressive zero-tolerance filter.

| Season | Total Records | Passes Current Filter | Actually V9-Clean | Records Wasted |
|--------|-------------|----------------------|-------------------|----------------|
| 2022-23 | 25,565 | 11,650 (46%) | ~19,064 (75%) | ~7,414 |
| 2023-24 | 25,948 | 13,672 (53%) | ~19,106 (74%) | ~5,434 |
| **2024-25** | **25,846** | **0 (0%)** | **~19,311 (75%)** | **~19,311** |
| 2025-26 | 25,823 | 15,232 (59%) | 15,232 (59%) | 0 |

**~42,000 usable training records are being thrown away**, including the entire previous season.

### Root Cause

The feature store (`ml_feature_store_v2`) has 54 feature columns. V9 uses features 0-32 (33 features). V12+ added features 33-53.

The zero-tolerance filter in `shared/ml/training_data_loader.py` line 47:
```python
"zero_tolerance": "COALESCE({alias}.required_default_count, {alias}.default_feature_count, 0) = 0"
```

This counts defaults across **ALL 54 features**, not just the 33 that V9 uses. For 2024-25:
- `required_default_count = 1` for 87% of records — but the defaulted features are indices 37, 38, 41, 42, 47, 50 (all V12+ features that V9 doesn't use)
- The remaining records have `required_default_count IS NULL`, falling back to `default_feature_count` which is ≥ 4 (also includes V12+ defaults)
- **Result: 0 records pass the filter**, despite all V9 features (0-32) having real data

### Evidence

```sql
-- 2024-25 records with required_default_count = 1: defaults are at V12+ indices only
SELECT default_feature_indices, COUNT(*)
FROM ml_feature_store_v2
WHERE game_date BETWEEN '2024-10-01' AND '2025-06-30' AND required_default_count = 1
GROUP BY 1 ORDER BY 2 DESC LIMIT 2;

-- Result:
-- [37, 38, 41, 42, 47, 50]  →  15,257 records  (all V12+ features)
-- [25, 26, 27, 37, 38, 41, 42, 47, 50, 53]  →  3,979 records  (vegas + V12+)
```

None of these defaults are in V9 features 0-32 (excluding allowed vegas 25-27).

### Proposed Fix

Change the zero-tolerance filter to be feature-version-aware. Instead of checking aggregate counts, check `default_feature_indices` directly:

```sql
-- Current (broken for V9 on 2024-25 data):
AND COALESCE(required_default_count, default_feature_count, 0) = 0

-- Proposed fix for V9 (features 0-32, vegas 25-27 allowed):
AND NOT EXISTS (
  SELECT 1 FROM UNNEST(default_feature_indices) idx
  WHERE idx <= 32 AND idx NOT IN (25, 26, 27)
)
```

This is a one-line change in `shared/ml/training_data_loader.py`. The `get_quality_where_clause()` function should accept a `feature_version` parameter that determines which feature indices to enforce zero-tolerance on.

**No backfill needed.** The data is already in the feature store with correct values. Only the filter logic needs updating.

### Impact

- Training data for V9 increases from ~10,400 to potentially ~50,000+ samples (adding 2024-25 + more 2022-24 records)
- The retrain that produced only 2 edge 3+ picks was trained on current-season-only data. Including prior seasons should produce a more diverse model
- V12+ training would use a different feature range (0-53) and would correctly enforce zero-tolerance on all those features

### Verification Query

Run this to confirm the fix would work:
```sql
SELECT
  CASE
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
    WHEN game_date BETWEEN '2025-10-01' AND '2026-06-30' THEN '2025-26'
  END as season,
  COUNT(*) as total,
  COUNTIF(NOT EXISTS (
    SELECT 1 FROM UNNEST(default_feature_indices) idx
    WHERE idx <= 32 AND idx NOT IN (25, 26, 27)
  )) as v9_clean
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2024-10-01'
GROUP BY 1 ORDER BY 1;
```

---

## What Needs To Happen Next

### Priority 1: Fix Training Data Filter
1. Update `shared/ml/training_data_loader.py` `get_quality_where_clause()` to accept a `max_feature_index` parameter (default 32 for V9)
2. Change the zero-tolerance clause to check `default_feature_indices` instead of aggregate counts
3. Re-run V9 retrain with the full dataset (2022-23 through 2025-26)
4. Evaluate whether more training data improves edge generation

### Priority 2: Verify Feb 19 Resumption
When games resume after All-Star break:
- Confirm prediction scheduler jobs return 200 (coordinator fix)
- Confirm scraper workflow jobs complete (URL + timeout fixes)
- Confirm grading/orchestrator IAM is working
- Run `./bin/infrastructure/fix_all_iam.sh --dry-run` to verify no drift

### Priority 3: Add Cloud Build Triggers for 3 Cloud Functions
`reconcile`, `validate-freshness`, and `validation-runner` have no auto-deploy triggers (unlike the other 16 Cloud Functions). They require manual `gcloud functions deploy`. Creating triggers would prevent future drift.

---

## Files Changed This Session

| File | Action | What |
|------|--------|------|
| `bin/infrastructure/fix_all_iam.sh` | CREATED | Automated IAM discovery and repair |
| `predictions/coordinator/coordinator.py` | EDITED | Return 200 on no-games instead of 404 |
| `bin/monitoring/pipeline_canary_queries.py` | EDITED | Scheduler health canary check |
| `orchestration/cloud_functions/pipeline_reconciliation/requirements.txt` | EDITED | Added firestore, pubsub, storage deps |
| `orchestration/cloud_functions/prediction_monitoring/requirements.txt` | EDITED | Added firestore, pubsub, storage deps |

---

## Key Commands

```bash
# Verify IAM health
./bin/infrastructure/fix_all_iam.sh --dry-run

# Check scheduler job status
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform --format="table(name,status.code)" | grep -v "^$"

# Run the verification query for training data fix
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
    WHEN game_date BETWEEN '2025-10-01' AND '2026-06-30' THEN '2025-26'
  END as season,
  COUNT(*) as total,
  COUNTIF(NOT EXISTS (
    SELECT 1 FROM UNNEST(default_feature_indices) idx
    WHERE idx <= 32 AND idx NOT IN (25, 26, 27)
  )) as v9_clean
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= '2022-10-01'
GROUP BY 1 ORDER BY 1"

# Retrain after fix (use explicit eval dates to avoid All-Star break)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN_FULL" \
    --train-start 2024-10-01 \
    --train-end 2026-02-05 \
    --eval-start 2026-02-06 --eval-end 2026-02-12 \
    --walkforward --force
```
