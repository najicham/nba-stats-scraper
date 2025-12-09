# Session 91: Enhanced Failure Tracking - Complete Analysis and Gap Identification

**Date:** 2025-12-09
**Focus:** Comprehensive analysis of failure tracking implementation across all processor phases
**Status:** ANALYSIS COMPLETE - Implementation recommendations provided

---

## Executive Summary

Session 91 completed the Phase 3 (Analytics) implementation of Enhanced Failure Tracking and conducted a comprehensive analysis of all processors to identify gaps. The analysis reveals:

- **Phase 4 (Precompute):** 100% coverage - All 5 processors use failure tracking with auto-classification
- **Phase 3 (Analytics):** 25% coverage - Only 1 of 4 processors uses failure tracking, missing DNP classification
- **Phase 2 (Raw):** 0% coverage - Expected, raw processors don't do entity-level analysis

---

## What Was Implemented This Session

### 1. Phase 3 Analytics Base Class (analytics_base.py)

**File:** `data_processors/analytics/analytics_base.py`

**Added Components:**

| Lines | Component | Description |
|-------|-----------|-------------|
| 130-136 | `failed_entities` list | Track failures during processing |
| 130-136 | `completeness_checker` | For DNP classification (initialized to None) |
| 1767-1821 | `record_failure()` | Record entity failures with enhanced fields |
| 1823-1900 | `save_failures_to_bq()` | Persist to `analytics_failures` table |
| 598-609 | `finalize()` update | Auto-save failures on completion |

**Usage Example:**
```python
# In any analytics processor:
self.record_failure(
    entity_id='zachlavine',
    entity_type='PLAYER',
    category='INCOMPLETE_DATA',
    reason='Missing 2 games in lookback window',
    can_retry=True,
    failure_type='PLAYER_DNP',      # Enhanced field
    is_correctable=False,           # Enhanced field
    expected_count=5,               # Enhanced field
    actual_count=3,                 # Enhanced field
    missing_game_ids=['0022100123'] # Enhanced field
)
# Failures auto-saved in finalize() hook
```

### 2. Updated Project Documentation

**File:** `docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md`

- Changed status to: "COMPLETE - Infrastructure for Phase 3 & Phase 4"
- Added implementation status table
- Documented all 8 methods in completeness_checker.py
- Listed remaining optional enhancements

---

## Complete Implementation Status

### BigQuery Tables

| Table | Schema | Data Population |
|-------|--------|-----------------|
| `nba_processing.precompute_failures` | 16 columns - COMPLETE | Phase 4 processors populate automatically |
| `nba_processing.analytics_failures` | 16 columns - COMPLETE | Infrastructure ready, most processors don't use |
| `nba_processing.prediction_failures` | Schema exists | Not yet used |

### Phase 4 Precompute Processors (100% Coverage)

| Processor | Uses Failure Tracking | Auto-Classification |
|-----------|----------------------|---------------------|
| PlayerDailyCacheProcessor | ✅ Yes | ✅ Yes (player-based) |
| PlayerCompositeFactorsProcessor | ✅ Yes | ✅ Yes (player-based) |
| PlayerShotZoneAnalysisProcessor | ✅ Yes | ✅ Yes (player-based) |
| MLFeatureStoreProcessor | ✅ Yes | ✅ Yes (player-based) |
| TeamDefenseZoneAnalysisProcessor | ✅ Yes | ⚠️ Skipped (team-based, DNP N/A) |

### Phase 3 Analytics Processors (25% Coverage)

| Processor | Uses Failure Tracking | Status |
|-----------|----------------------|--------|
| UpcomingPlayerGameContextProcessor | ✅ Yes | Records failures, NO classification |
| PlayerGameSummaryProcessor | ❌ No | **GAP - Largest processor, no tracking** |
| TeamOffenseGameSummaryProcessor | ❌ No | **GAP - Critical upstream data** |
| TeamDefenseGameSummaryProcessor | ❌ No | **GAP - Critical upstream data** |

---

## Identified Gaps (Prioritized)

### Gap 1: Analytics Missing DNP Classification (HIGH PRIORITY)

**Issue:** `analytics_base.py` has `record_failure()` and `save_failures_to_bq()` but lacks `classify_recorded_failures()` method that exists in Phase 4.

**Impact:**
- UPGC records failures but enhanced fields (failure_type, is_correctable) are never populated
- Can't distinguish DNP from data gaps in Phase 3

**Fix Required:**
```python
# Add to analytics_base.py (copy/adapt from precompute_base.py lines 1560-1689)
def classify_recorded_failures(self, analysis_date=None) -> int:
    """Enrich INCOMPLETE_DATA failures with DNP vs DATA_GAP classification."""
    # Implementation similar to precompute_base.py
```

### Gap 2: Player Game Summary Not Tracking Failures (HIGH PRIORITY)

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Issue:**
- Largest Phase 3 processor by data volume
- Has complex multi-source fallback logic
- No `record_failure()` calls despite error handling
- Registry failures tracked separately (`self.registry_failures`)

**Impact:**
- No visibility into why player data is missing
- Can't analyze failure patterns for PGS

**Affected Code Paths:**
- Line ~800+: Multi-source fallback (BDL → NBA.com → fallback)
- Line ~1200+: Registry lookup failures
- Line ~1300+: Data validation failures

### Gap 3: Team Processors Not Recording Failures (MEDIUM PRIORITY)

**Files:**
- `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`
- `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`

**Issue:**
- Critical upstream data for Phase 4 processors (PCF uses team data)
- No failure tracking implemented

**Impact:**
- When team data is missing, downstream processors fail without context
- Harder to debug pipeline issues

### Gap 4: finalize() Override Without Parent Call (LOW PRIORITY)

**Potential Issue:** Some processors override `finalize()` but may not call `super().finalize()`

**Affected Processors:**
- `player_game_summary_processor.py`
- `team_defense_game_summary_processor.py`
- `team_offense_game_summary_processor.py`

**Fix:** Ensure all overrides include:
```python
def finalize(self) -> None:
    super().finalize()  # This calls save_failures_to_bq()
    # ... custom cleanup ...
```

---

## Core Infrastructure (completeness_checker.py)

**File:** `shared/utils/completeness_checker.py`

### Methods Added for DNP Detection (Lines 924-1540)

```python
# 1. Single player raw box score check
check_raw_boxscore_for_player(player_lookup, game_date) -> bool
# Returns True if player appears in bdl_player_boxscores for that date

# 2. Batch raw box score check (efficient)
check_raw_boxscore_batch(player_lookups, game_dates) -> Dict[str, List[date]]
# Returns {player_lookup: [dates_they_played]}

# 3. Single player failure classification
classify_failure(player_lookup, analysis_date, expected_games, actual_games, check_raw_data=True) -> dict
# Returns {failure_type, is_correctable, expected_count, actual_count, missing_dates, dnp_dates, data_gap_dates}

# 4. Batch failure classification
classify_failures_batch(player_failures, check_raw_data=True) -> Dict[str, dict]
# Efficient: 2 BQ queries for N players

# 5. Get expected vs actual game dates for player
get_player_game_dates(player_lookup, analysis_date, lookback_days=14) -> dict
# Returns {player_lookup, team_abbr, actual_games, expected_games, ...}

# 6. Batch get game dates (efficient)
get_player_game_dates_batch(player_lookups, analysis_date, lookback_days=14) -> Dict[str, dict]
# Uses 2 queries: one for actuals (bdl_player_boxscores), one for expected (nbac_schedule)
```

### Failure Types

| Type | Meaning | is_correctable |
|------|---------|----------------|
| `PLAYER_DNP` | Player didn't play (not in raw box score) | False |
| `DATA_GAP` | Player played but data missing | True |
| `MIXED` | Some games DNP, some gaps | True |
| `INSUFFICIENT_HISTORY` | < 5 games in lookback (early season) | False |
| `COMPLETE` | No missing games | False |
| `UNKNOWN` | Could not determine | None |

### Name Normalization

The implementation auto-normalizes player names using `shared/utils/player_name_normalizer.py`:
- Input: `lebron_james` or `LeBron James` or `lebronjames`
- Normalized: `lebronjames` (BDL format)

---

## precompute_base.py Integration

**File:** `data_processors/precompute/precompute_base.py`

### Key Methods

| Lines | Method | Description |
|-------|--------|-------------|
| 1560-1689 | `classify_recorded_failures()` | Auto-classifies INCOMPLETE_DATA failures |
| 1691-1790 | `save_failures_to_bq()` | Saves to `precompute_failures` with enhanced fields |

### Auto-Classification Flow

```
1. Processor runs, records failures with category='INCOMPLETE_DATA'
2. save_failures_to_bq() called (manually or in cleanup)
3. classify_recorded_failures() called automatically first
4. For each INCOMPLETE_DATA failure:
   - Get expected/actual game dates via get_player_game_dates_batch()
   - Call classify_failure() to determine DNP vs DATA_GAP
   - Update failure record with enhanced fields
5. Insert to BigQuery
```

---

## Test Results

### DNP Detection Test (Zach LaVine COVID Period)

```python
# Test: Dec 31, 2021 - Zach LaVine was out Dec 19-20 due to COVID
get_player_game_dates('zachlavine', date(2021, 12, 31), 14)

Result:
  Team: CHI
  Actual games (5): Dec 22, 26, 27, 29, 31
  Expected games (6): Dec 19, 20, 26, 27, 29, 31
  Missing: Dec 19, 20

classify_failure() result:
  failure_type: PLAYER_DNP
  is_correctable: False
  dnp_dates: [2021-12-19, 2021-12-20]
  data_gap_dates: []
```

### Analytics Base Class Test

```python
# Test record_failure() and save_failures_to_bq()
processor.record_failure(
    entity_id='zachlavine',
    entity_type='PLAYER',
    category='INCOMPLETE_DATA',
    reason='Missing games',
    failure_type='PLAYER_DNP',
    is_correctable=False
)

Result:
  Recorded 2 failures:
    - zachlavine: INCOMPLETE_DATA (PLAYER_DNP)
    - jokic: PROCESSING_ERROR (N/A)
  Phase 3 failure tracking implementation WORKS!
```

---

## Files Modified This Session

| File | Changes |
|------|---------|
| `data_processors/analytics/analytics_base.py` | +145 lines - failure tracking |
| `data_processors/precompute/precompute_base.py` | +138 lines - auto-classification |
| `shared/utils/completeness_checker.py` | +616 lines - 8 new methods |
| `docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md` | Updated status |

---

## Recommendations for Next Session

### Priority 1: Add classify_recorded_failures() to analytics_base.py

**Effort:** 1-2 hours

Copy and adapt from `precompute_base.py:1560-1689`:
1. Add method to `analytics_base.py`
2. Call it in `save_failures_to_bq()` before inserting
3. Update `finalize()` to use it

### Priority 2: Add Failure Tracking to Player Game Summary

**Effort:** 2-3 hours

1. Identify all error handling paths in `player_game_summary_processor.py`
2. Add `record_failure()` calls at each path
3. Ensure `finalize()` calls parent
4. Test with backfill

### Priority 3: Add Failure Tracking to Team Processors

**Effort:** 1-2 hours each

Same pattern as Priority 2 for:
- `team_offense_game_summary_processor.py`
- `team_defense_game_summary_processor.py`

---

## Verification Queries

### Check precompute_failures Enhanced Fields

```sql
SELECT
  processor_name,
  analysis_date,
  entity_id,
  failure_category,
  failure_type,
  is_correctable,
  expected_game_count,
  actual_game_count,
  missing_game_dates
FROM nba_processing.precompute_failures
WHERE failure_type IS NOT NULL
ORDER BY created_at DESC
LIMIT 20;
```

### Check analytics_failures (Should Be Empty Until Implementation)

```sql
SELECT COUNT(*) as total_failures
FROM nba_processing.analytics_failures;
```

### Failure Type Distribution (After More Data)

```sql
SELECT
  processor_name,
  failure_type,
  COUNT(*) as count,
  COUNTIF(is_correctable) as correctable
FROM nba_processing.precompute_failures
WHERE failure_type IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
```

---

## Background Jobs Status

Multiple backfill jobs are running. Check status with:

```bash
# Check running background jobs
ps aux | grep python | grep -E "(backfill|processor)"

# Check specific logs
tail -20 /tmp/pdc_oct2021.log
tail -20 /tmp/pcf_oct2021.log
tail -20 /tmp/psza_oct2021.log
```

---

## Summary

**Completed:**
- Phase 4 Enhanced Failure Tracking - 100% infrastructure, auto-classification working
- Phase 3 Enhanced Failure Tracking - Infrastructure added, needs processor integration
- Comprehensive gap analysis - All gaps documented with priorities

**Next Steps:**
1. Add `classify_recorded_failures()` to `analytics_base.py`
2. Add failure tracking to `player_game_summary_processor.py`
3. Add failure tracking to team processors
4. Verify enhanced fields populate in BigQuery after next backfill run
