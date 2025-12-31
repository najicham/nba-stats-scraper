# Session 93 Handoff: Reclassification Script and Future TODOs

**Date:** 2025-12-09
**Focus:** Created reclassification script for existing failures, identified correctable failures
**Status:** IN PROGRESS - Script ready, needs full run

---

## What Was Done This Session

### 1. Created Reclassification Script
**File:** `scripts/reclassify_existing_failures.py`

This script retroactively classifies existing `precompute_failures` records that have `failure_type=NULL` by:
1. Querying unclassified INCOMPLETE_DATA failures for player-based processors
2. Using `CompletenessChecker.classify_failure()` to determine if each is PLAYER_DNP, DATA_GAP, MIXED, or COMPLETE
3. Updating the records in BigQuery with classification data

**Usage:**
```bash
# Dry run (see what would be updated)
PYTHONPATH=. .venv/bin/python scripts/reclassify_existing_failures.py --dry-run

# Reclassify all unclassified failures (batches of 500)
PYTHONPATH=. .venv/bin/python scripts/reclassify_existing_failures.py

# Specific processor or date range
PYTHONPATH=. .venv/bin/python scripts/reclassify_existing_failures.py --processor PlayerDailyCacheProcessor --start-date 2021-12-01 --end-date 2021-12-31
```

### 2. Fixed Session 92 Code (Committed)
- Phase 3 Analytics enhanced failure tracking is complete
- Commit: `b0886d7` (pushed to main)

### 3. Dry Run Results
From 10 sample failures on 2021-12-01:
- **COMPLETE: 8** (false positives - data was actually complete)
- **PLAYER_DNP: 2** (expected - players didn't play)
- **DATA_GAP: 0** (correctable data gaps)

This confirms the pattern: most recorded failures are NOT correctable because they're either false positives or expected DNPs.

---

## Current Failure Statistics

```sql
-- Run this to see current state
SELECT
  processor_name,
  COUNT(*) as total,
  SUM(CASE WHEN failure_type IS NOT NULL THEN 1 ELSE 0 END) as classified,
  SUM(CASE WHEN failure_type = 'PLAYER_DNP' THEN 1 ELSE 0 END) as dnp,
  SUM(CASE WHEN failure_type = 'DATA_GAP' THEN 1 ELSE 0 END) as data_gap,
  SUM(CASE WHEN failure_type = 'COMPLETE' THEN 1 ELSE 0 END) as complete
FROM nba_processing.precompute_failures
WHERE failure_category = 'INCOMPLETE_DATA'
GROUP BY processor_name
ORDER BY total DESC
```

Current count of unclassified failures: ~27K+ (from previous backfills)

---

## TODO Items for Next Session

### HIGH Priority

1. **Run Full Reclassification**
   ```bash
   PYTHONPATH=. .venv/bin/python scripts/reclassify_existing_failures.py --batch-size 500
   ```
   Expected runtime: ~20-30 minutes for 27K failures

2. **Analyze Results**
   After reclassification, run:
   ```sql
   SELECT
     failure_type,
     COUNT(*) as count,
     SUM(CASE WHEN is_correctable THEN 1 ELSE 0 END) as correctable
   FROM nba_processing.precompute_failures
   WHERE failure_category = 'INCOMPLETE_DATA'
   GROUP BY failure_type
   ```

3. **Create Retry Script for DATA_GAP Failures**
   If DATA_GAP count > 0, create a script to:
   - Query DATA_GAP failures with is_correctable=True
   - Re-run the processor for those specific player/dates
   - Track resolution status

### MEDIUM Priority

4. **Add Monitoring Dashboard**
   Create a simple query/script to monitor:
   - New failures per day by type
   - Correctable failure rate trends
   - Resolution rate for DATA_GAP failures

5. **Phase 5 Prediction Failure Tracking**
   When prediction processors are built, add failure tracking:
   - Schema already exists: `nba_processing.prediction_failures`
   - Similar pattern to analytics_base.py

### LOW Priority

6. **Unit Tests for DNP Detection**
   - Mock BQ responses for `classify_failure()`
   - Test edge cases: mixed failures, season boundaries

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `scripts/reclassify_existing_failures.py` | Retroactive classification script |
| `data_processors/precompute/precompute_base.py:1560-1790` | Reference implementation |
| `data_processors/analytics/analytics_base.py:1767-1900` | Phase 3 implementation |
| `shared/utils/completeness_checker.py:924-1540` | DNP detection methods |

---

## Quick Test Commands

```bash
# Test DNP detection
PYTHONPATH=. .venv/bin/python -c "
from shared.utils.completeness_checker import CompletenessChecker
from google.cloud import bigquery
from datetime import date

bq_client = bigquery.Client(project='nba-props-platform')
checker = CompletenessChecker(bq_client, 'nba-props-platform')
result = checker.get_player_game_dates('zachlavine', date(2021, 12, 31), 14)
print(f'Team: {result[\"team_abbr\"]}')
print(f'Actual: {len(result[\"actual_games\"])} games')
print(f'Expected: {len(result[\"expected_games\"])} games')
"

# Test reclassify dry run
PYTHONPATH=. .venv/bin/python scripts/reclassify_existing_failures.py --dry-run --batch-size 20
```

---

## Coverage Summary

| Phase | Coverage | Status |
|-------|----------|--------|
| Phase 4 Precompute | 5/5 (100%) | Complete, auto-classification working |
| Phase 3 Analytics | 4/4 (100%) | Complete, commit b0886d7 |
| Phase 5 Prediction | 0/N | Schema ready, processors not built |

---

## Expected Reclassification Outcome

Based on dry run sample and earlier analysis:
- **~80% COMPLETE** (false positives - data actually present)
- **~15-20% PLAYER_DNP** (expected failures - players didn't play)
- **<5% DATA_GAP** (correctable - re-run backfill)

If DATA_GAP percentage is near 0%, no reprocessing needed. The existing backfill data is complete.

---

**Next Chat Start Point:** Run `scripts/reclassify_existing_failures.py` and analyze results.
