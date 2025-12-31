# Session 90: Enhanced Failure Tracking Implementation Complete

**Date:** 2025-12-09
**Focus:** Implement DNP vs Data Gap Detection for Phase 4 Processors
**Status:** COMPLETE - Core Infrastructure Implemented

---

## Executive Summary

Successfully implemented the Enhanced Failure Tracking infrastructure that enables distinguishing between **Player DNP** (Did Not Play - expected, not correctable) and **DATA_GAP** (unexpected data gap - correctable) failures. The implementation auto-integrates with all Phase 4 precompute processors through the base class.

---

## What Was Implemented

### 1. completeness_checker.py - 6 New Methods (~350 lines)

**Location:** `shared/utils/completeness_checker.py` (lines 924-1540)

| Method | Purpose |
|--------|---------|
| `check_raw_boxscore_for_player()` | Check if player appears in raw BDL box score data |
| `check_raw_boxscore_batch()` | Batch version for efficiency |
| `classify_failure()` | Classify failure as PLAYER_DNP, DATA_GAP, MIXED, etc. |
| `classify_failures_batch()` | Batch classification for multiple players |
| `get_player_game_dates()` | Get expected (schedule) vs actual (box score) game dates |
| `get_player_game_dates_batch()` | Batch version using 2 queries instead of 2N |

### 2. precompute_base.py - Auto-Integration

**Location:** `data_processors/precompute/precompute_base.py`

| Change | Lines | Description |
|--------|-------|-------------|
| `classify_recorded_failures()` | 1560-1689 | New method that enriches INCOMPLETE_DATA failures |
| `save_failures_to_bq()` | 1713-1718 | Auto-calls classify before saving |

### 3. Key Design Decisions

- **Uses BDL raw data**: Queries `nba_raw.bdl_player_boxscores` for DNP detection
- **Auto-normalizes player names**: Uses existing `player_name_normalizer.py`
- **Player processors only**: Skips team-based processors (TDZA) - teams always play
- **Batch queries**: 2 BQ queries for N players, not 2N
- **Non-breaking**: Existing failures continue to work, enhanced fields are optional

---

## Test Results

```
=== Testing get_player_game_dates() ===
Player: zachlavine
Team: CHI
Actual games (5): Dec 22, 26, 27, 29, 31
Expected games (6): Dec 19, 20, 26, 27, 29, 31

=== Classification Result ===
failure_type: PLAYER_DNP
is_correctable: False
missing_dates: [Dec 19, Dec 20]
dnp_dates: [Dec 19, Dec 20]
data_gap_dates: []
```

This correctly identifies that Zach LaVine's missing games (Dec 19, 20) were due to DNP (COVID protocol), not data gaps.

---

## Files Modified

| File | Lines Changed | Description |
|------|---------------|-------------|
| `shared/utils/completeness_checker.py` | +350 | 6 new methods for failure classification |
| `data_processors/precompute/precompute_base.py` | +135 | classify_recorded_failures() + auto-integration |
| `docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md` | +50 | Updated project status |

---

## How It Works - Flow Diagram

```
Processor runs completeness checks
         ↓
Records failures to self.failed_entities
         ↓
Calls save_failures_to_bq()
         ↓
[NEW] Auto-calls classify_recorded_failures()
         ↓
   For each INCOMPLETE_DATA failure:
         ↓
   get_player_game_dates_batch()  → Gets expected vs actual games
         ↓
   classify_failure()             → Determines DNP vs DATA_GAP
         ↓
   Updates failure with:
     - failure_type: PLAYER_DNP | DATA_GAP | MIXED
     - is_correctable: bool
     - expected_count / actual_count
     - missing_dates (JSON)
     - raw_data_checked: True
         ↓
Inserts enriched records to BQ
```

---

## Failure Types

| Type | Meaning | is_correctable |
|------|---------|----------------|
| `PLAYER_DNP` | Player didn't play (injured, rest, COVID, etc.) | False |
| `DATA_GAP` | Player played but analytics data is missing | True |
| `MIXED` | Some games DNP, some gaps | True (partial) |
| `INSUFFICIENT_HISTORY` | Early season, not enough games yet | False |
| `COMPLETE` | No missing dates (shouldn't be a failure) | False |
| `UNKNOWN` | Could not determine | None |

---

## Validation Query

After running backfills, check enhanced failure data:

```sql
SELECT
  processor_name,
  failure_category,
  failure_type,
  COUNTIF(is_correctable = TRUE) as correctable,
  COUNTIF(is_correctable = FALSE) as not_correctable,
  COUNT(*) as total
FROM nba_processing.precompute_failures
WHERE analysis_date >= '2021-10-01'
  AND failure_type IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
```

---

## Remaining Work

| Task | Priority | Notes |
|------|----------|-------|
| Phase 3 analytics_base.py | Medium | Similar implementation for analytics processors |
| PSZA custom _save_failures | Low | Has own implementation, doesn't use base class |
| Resolution tracking UI | Low | Mark failures as RESOLVED |

---

## Files to Reference

```
# Core implementation
shared/utils/completeness_checker.py          # Lines 924-1540
data_processors/precompute/precompute_base.py # Lines 1560-1720

# Project documentation
docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md

# Schema
schemas/bigquery/processing/precompute_failures_table.sql
```

---

## Commands for Next Session

```bash
# 1. Verify implementation is working
PYTHONPATH=. .venv/bin/python -c "
from shared.utils.completeness_checker import CompletenessChecker
from google.cloud import bigquery
from datetime import date

bq = bigquery.Client(project='nba-props-platform')
checker = CompletenessChecker(bq, 'nba-props-platform')
result = checker.get_player_game_dates('lebron_james', date(2024, 12, 1), 14)
print(result)
"

# 2. Check if failures are being classified
bq query --use_legacy_sql=false "
SELECT failure_type, COUNT(*)
FROM nba_processing.precompute_failures
WHERE failure_type IS NOT NULL
GROUP BY 1"

# 3. Run a single processor to test
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2024-12-01 --end-date 2024-12-01 --skip-preflight
```

---

## Related Sessions

- **Session 86-87**: Initial enhanced failure tracking design
- **Session 88**: Schema applied to BigQuery
- **Session 89**: Schema consolidation, processor review
- **Session 90** (this): Core implementation complete

---

## Success Criteria - Achieved

1. ✅ `classify_failure()` correctly distinguishes DNP vs DATA_GAP
2. ✅ Auto-integrates with base class (no per-processor changes needed)
3. ✅ Uses existing name normalizer for player lookup format
4. ✅ Batch queries for efficiency (2 queries for N players)
5. ✅ Tested with real data (Zach LaVine COVID period Dec 2021)
