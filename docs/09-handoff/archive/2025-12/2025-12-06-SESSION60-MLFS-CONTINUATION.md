# Session 60: MLFS Backfill Continuation

**Date:** 2025-12-06
**Previous Sessions:** 58 (Optimization), 59 (MLFS Testing)
**Status:** Ready to continue

---

## Executive Summary

Session 59 tested MLFS backfill with performance optimizations. Key findings:
- MLFS runs at ~66-85s per date (acceptable)
- Dependency check sometimes regresses to 72s (needs investigation)
- Threshold change for early season is uncommitted
- Schema has one remaining REQUIRED field that should be NULLABLE

---

## Current Data Coverage (Oct-Nov 2021)

| Processor | Dates | First Date | Last Date | Status |
|-----------|-------|------------|-----------|--------|
| PGS       | 42    | 2021-10-19 | 2021-11-30 | Complete |
| TDZA      | 29    | 2021-11-02 | 2021-11-30 | Missing Oct 19 - Nov 1 |
| PSZA      | 26    | 2021-11-05 | 2021-11-30 | Missing Oct 19 - Nov 4 |
| PDC       | 25    | 2021-11-05 | 2021-11-30 | Missing Oct 19 - Nov 4 |
| PCF       | 19    | 2021-11-07 | 2021-11-30 | Missing Oct 19 - Nov 6 |
| MLFS      | 19    | 2021-11-07 | 2021-11-30 | Missing Oct 19 - Nov 6 |

**Gap Analysis:** MLFS is blocked by PCF which is blocked by early-season PDC threshold issue.

---

## Failure Tracking Tables

| Table | Records | Notes |
|-------|---------|-------|
| precompute_failures | 7,713 | Accumulated from all backfill attempts |
| registry_failures | 0 | Working correctly (all players resolving) |

---

## Uncommitted Changes

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Change:** Lower dependency thresholds from 100 to 20 in backfill mode:
```python
player_threshold = 20 if self.is_backfill_mode else 100
```

This allows early-season dates to pass dependency checks when fewer players have enough game history.

---

## Schema Issue

**Table:** `nba_processing.precompute_processor_runs`

**Problem:** `run_id` field is still REQUIRED but code sends NULLABLE values.

**Fix:**
```bash
bq query --use_legacy_sql=false "
ALTER TABLE nba_processing.precompute_processor_runs
ALTER COLUMN run_id DROP NOT NULL"
```

**Already Fixed:** `processor_name` and `run_date` (made NULLABLE in Session 59)

---

## Performance Analysis (Session 59 Results)

### MLFS Timing Breakdown

| Date | Players | Dep Check | Extract | Calculate | Write | Total |
|------|---------|-----------|---------|-----------|-------|-------|
| Nov 7 | 270 | 3.4s | 21.9s | 32.5s | 7.1s | **66.2s** |
| Nov 8 | 284 | **72.1s** | 19.6s | 32.2s | 7.4s | **132.6s** |
| Nov 10 | 450 | 5.0s | 19.0s | 44.4s | 15.8s | **85.3s** |

### Performance Concerns

1. **Dependency check regression**: Nov 8 took 72.1s vs 3.4s for Nov 7
   - Both dates have same dependencies available
   - May be a race condition or caching issue
   - Needs investigation

2. **Acceptable baseline**: 66-85s per date is reasonable
   - Full 4-year backfill (~850 dates) would take ~20 hours
   - Could parallelize to reduce to ~7 hours

---

## Two Paths Forward

### Option A: Continue Incremental (Fast)

Just commit the threshold fix and continue MLFS for available dates:

```bash
# 1. Fix schema
bq query --use_legacy_sql=false "
ALTER TABLE nba_processing.precompute_processor_runs
ALTER COLUMN run_id DROP NOT NULL"

# 2. Commit threshold change
git add data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
git commit -m "fix: Lower MLFS dependency thresholds for early season backfill"

# 3. Run MLFS for remaining Nov dates (Nov 5-6 if deps exist)
source .venv/bin/activate && PYTHONPATH=/home/naji/code/nba-stats-scraper \
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-06 --skip-preflight
```

**Pros:** Fast, builds on existing data
**Cons:** Won't have registry_failures tracking for existing data

### Option B: Clean Backfill (Comprehensive)

Delete all 2021-22 Phase 3 & 4 data and re-run with full tracking.

See: `docs/09-handoff/2025-12-06-SESSION59-CLEAN-BACKFILL-PLAN.md`

**Pros:** Full observability, validates entire lifecycle
**Cons:** Deletes 2+ hours of existing work, takes ~3 hours total

---

## Recommended Next Steps

1. **Fix schema** (30 seconds):
   ```bash
   bq query --use_legacy_sql=false "
   ALTER TABLE nba_processing.precompute_processor_runs
   ALTER COLUMN run_id DROP NOT NULL"
   ```

2. **Commit threshold change** (30 seconds):
   ```bash
   git add data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
   git commit -m "fix: Lower MLFS dependency thresholds for early season backfill"
   ```

3. **Investigate dep check regression** (optional, 15-30 min):
   - Run MLFS for Nov 7 and Nov 8 again
   - Compare timing logs
   - Check if it's consistent or random

4. **Choose path**:
   - **Option A**: Continue with existing data (30 min to finish MLFS)
   - **Option B**: Clean backfill (3 hours, full observability)

---

## Quick Validation Commands

```bash
# Check MLFS coverage
bq query --use_legacy_sql=false "
SELECT game_date FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2021-10-01' AND '2021-11-30'
GROUP BY game_date ORDER BY game_date"

# Check which dates have all MLFS dependencies
bq query --use_legacy_sql=false "
WITH deps AS (
  SELECT game_date as dt,
    (SELECT COUNT(DISTINCT cache_date) FROM nba_precompute.player_daily_cache WHERE cache_date = pgs.game_date) > 0 as has_pdc,
    (SELECT COUNT(DISTINCT game_date) FROM nba_precompute.player_composite_factors WHERE game_date = pgs.game_date) > 0 as has_pcf,
    (SELECT COUNT(DISTINCT analysis_date) FROM nba_precompute.player_shot_zone_analysis WHERE analysis_date = pgs.game_date) > 0 as has_psza,
    (SELECT COUNT(DISTINCT analysis_date) FROM nba_precompute.team_defense_zone_analysis WHERE analysis_date = pgs.game_date) > 0 as has_tdza
  FROM (SELECT DISTINCT game_date FROM nba_analytics.player_game_summary WHERE game_date BETWEEN '2021-10-19' AND '2021-11-30') pgs
)
SELECT dt, has_pdc, has_pcf, has_psza, has_tdza,
  CASE WHEN has_pdc AND has_pcf AND has_psza AND has_tdza THEN 'READY' ELSE 'MISSING_DEPS' END as mlfs_status
FROM deps ORDER BY dt"

# Check precompute_failures by processor
bq query --use_legacy_sql=false "
SELECT processor_name, failure_category, COUNT(*) as cnt
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN '2021-10-01' AND '2021-11-30'
GROUP BY processor_name, failure_category
ORDER BY processor_name, cnt DESC"
```

---

## Files Modified (Session 58-59)

| File | Status | Changes |
|------|--------|---------|
| `precompute_base.py` | Committed | 60s timeout, notification skip, failure tracking |
| `ml_feature_store_processor.py` | **UNCOMMITTED** | Threshold 100→20 for backfill mode |

---

## Related Documentation

- Clean Backfill Plan: `docs/09-handoff/2025-12-06-SESSION59-CLEAN-BACKFILL-PLAN.md`
- MLFS Backfill Plan: `docs/09-handoff/2025-12-06-SESSION59-MLFS-BACKFILL-PLAN.md`
- Session 58 Optimization: `docs/09-handoff/2025-12-06-SESSION58-BACKFILL-OPTIMIZATION.md`

---

**Document Created:** 2025-12-06
**Author:** Session 60 (Claude)
