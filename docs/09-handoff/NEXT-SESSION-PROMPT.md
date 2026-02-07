# Session 143 Prompt - ML Feature Store Performance Investigation

Copy-paste this into the next Claude Code session.

---

Read the Session 142 handoff at `docs/09-handoff/2026-02-06-SESSION-142-HANDOFF.md`.

## The Problem

The ML Feature Store processor (`data_processors/precompute/ml_feature_store/`) takes **17.7 minutes per game date**. This processor runs daily in production orchestration as Phase 4. We measured a single date (2026-02-05, backfill mode) at 1,167 seconds:

```
batch_extract_all_data: 1061.6s (96% of total time)
player_processing:       21.1s
write/MERGE:              8.2s
```

The extraction phase runs 11 BigQuery queries in parallel via `ThreadPoolExecutor(max_workers=11)` in `feature_extractor.py`, but we don't know which queries are slow because there's no per-query timing.

## Tasks

### 1. Check Production Timing First

Before changing anything, see if production (non-backfill) is equally slow:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase4-precompute-processors" AND textPayload:"PERFORMANCE TIMING"' --project=nba-props-platform --limit=10 --format=json
```

If production is fast (< 2 min), this is backfill-only. If production is also slow, it's urgent.

### 2. Add Per-Query Timing

In `data_processors/precompute/ml_feature_store/feature_extractor.py`, the method `batch_extract_all_data()` (~line 211) submits 11 tasks to a ThreadPoolExecutor. Each task calls a `batch_extract_*` method. Add timing around each one so we can see which queries are slow.

### 3. Identify and Fix Bottleneck Queries

Two suspects:
- **`batch_extract_last_10_games` (~lines 602-687)**: Has a CTE that counts ALL historical games per player with NO date lower bound. Fix: add `AND game_date >= DATE_SUB(target_date, INTERVAL 365 DAY)`
- **`batch_extract_opponent_history` (~lines 891-943)**: Uses `INTERVAL 3 YEAR` lookback for 500+ players. Fix: reduce to 1 year

Also: no query timeouts exist anywhere. Add `query_job.result(timeout=120)` to prevent indefinite hangs.

### 4. Run Backfill for 3,594 Remaining Records

After fixing performance, backfill records missing `feature_N_source` columns:

```bash
# 2025-26 season (342 records, ~32 dates)
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-12-01 --end-date 2026-02-06

# 2021 season (3,231 records, ~60 dates)
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-02 --end-date 2021-12-31
```

### 5. Verify and Deploy

- Run tests: `PYTHONPATH=. python -m pytest tests/unit/prediction_tests/coordinator/test_quality_gate.py tests/test_quality_system.py -v`
- Deploy Phase 4 if feature_extractor changed: `./bin/deploy-service.sh nba-phase4-precompute-processors`
- Check drift: `./bin/check-deployment-drift.sh --verbose`

## Key Files

| File | What to Look At |
|------|----------------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | 11 `batch_extract_*` methods, ThreadPoolExecutor at ~line 211 |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | `process_game_date()` flow, timing breakdown |
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | Backfill orchestration |

## Context from Session 142

- Added `default_feature_indices ARRAY<INT64>` to both `ml_feature_store_v2` and `player_prop_predictions`
- SQL backfill populated 127,616 of 131,363 records (97.2%) in 20 seconds
- 3,594 records still have NULL `feature_N_source` columns (need full processor rerun)
- Both Phase 4 and prediction-worker deployed with new code
- All 60 tests pass
