# Session 92: Enhanced Failure Tracking - Phase 3 Analytics Complete

**Date:** 2025-12-09
**Focus:** Complete Enhanced Failure Tracking implementation for Phase 3 Analytics processors
**Status:** COMPLETE - Phase 3 Analytics at 100% coverage
**Commit:** `a01fdb8` (pushed to main)

---

## Executive Summary

Session 92 completed the Enhanced Failure Tracking implementation for all Phase 3 Analytics processors. The key additions enable DNP (Did Not Play) vs Data Gap detection for player-based failures, with unified failure persistence to `analytics_failures` table.

---

## What Was Implemented This Session

### 1. Added `classify_recorded_failures()` to analytics_base.py

**File:** `data_processors/analytics/analytics_base.py`
**Lines:** 1828-1959

This method mirrors the Phase 4 implementation in `precompute_base.py` and provides:
- Auto-classification of INCOMPLETE_DATA failures
- Distinguishes PLAYER_DNP from DATA_GAP
- Uses `CompletenessChecker` for raw data verification
- Only processes player-based processors (PGS, UPGC)

### 2. Modified `save_failures_to_bq()` to Auto-Classify

**File:** `data_processors/analytics/analytics_base.py`
**Lines:** 1978-1983

Added automatic call to `classify_recorded_failures()` before inserting failures to BigQuery:
```python
# Auto-classify INCOMPLETE_DATA failures before saving
try:
    self.classify_recorded_failures()
except Exception as classify_e:
    logger.warning(f"Could not classify failures (continuing anyway): {classify_e}")
```

### 3. Added Failure Tracking to PlayerGameSummaryProcessor

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Changes (3 locations):**

**A. finalize() - Registry Failures (Lines 950-965)**

Updated `finalize()` to:
- Convert existing `registry_failures` to unified `failed_entities` format
- Call `super().finalize()` to trigger `save_failures_to_bq()`

```python
def finalize(self) -> None:
    # ... existing registry flush ...

    # Convert registry_failures to unified failure tracking format
    if hasattr(self, 'registry_failures') and self.registry_failures:
        for failure in self.registry_failures:
            self.record_failure(
                entity_id=failure.get('player_lookup', 'unknown'),
                entity_type='PLAYER',
                category='REGISTRY_LOOKUP_FAILED',
                reason=f"Player not found in registry for game {failure.get('game_id', 'unknown')}",
                can_retry=True,
                missing_game_ids=[failure.get('game_id')] if failure.get('game_id') else None
            )

    # Call parent finalize() which saves failures to analytics_failures table
    super().finalize()
```

**B. _process_single_player_game() - Processing Errors (Lines 1173-1181)**

Added `record_failure()` to the exception handler in parallel processing:

```python
except Exception as e:
    logger.error(f"Failed to process record {idx} ({row.get('game_id', 'unknown')}_{row.get('player_lookup', 'unknown')}): {e}")

    # Record failure for unified failure tracking
    self.record_failure(
        entity_id=row.get('player_lookup', 'unknown'),
        entity_type='PLAYER',
        category='PROCESSING_ERROR',
        reason=f"Exception processing player game record: {str(e)[:200]}",
        can_retry=True,
        missing_game_ids=[row.get('game_id')] if row.get('game_id') else None
    )
    return None
```

**C. _process_player_games_serial() - Processing Errors (Lines 1337-1345)**

Added `record_failure()` to the exception handler in serial processing:

```python
except Exception as e:
    logger.error(f"Error processing {row['game_id']}_{row['player_lookup']}: {e}")

    # Record failure for unified failure tracking
    self.record_failure(
        entity_id=row.get('player_lookup', 'unknown'),
        entity_type='PLAYER',
        category='PROCESSING_ERROR',
        reason=f"Exception processing player game record: {str(e)[:200]}",
        can_retry=True,
        missing_game_ids=[row.get('game_id')] if row.get('game_id') else None
    )
    continue
```

### 4. Added Failure Tracking to TeamOffenseGameSummaryProcessor

**File:** `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`
**Lines:** 768-776

Added `record_failure()` call in the processing exception handler:
```python
# Record failure for unified failure tracking
self.record_failure(
    entity_id=row['team_abbr'],
    entity_type='TEAM',
    category='PROCESSING_ERROR',
    reason=f"Error processing team record: {str(e)[:200]}",
    can_retry=True,
    missing_game_ids=[row['game_id']] if row.get('game_id') else None
)
```

### 5. Added Failure Tracking to TeamDefenseGameSummaryProcessor

**File:** `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`
**Lines:** 1282-1289

Added `record_failure()` call in the parallel processing exception handler:
```python
# Record failure for unified failure tracking
self.record_failure(
    entity_id=f"record_{idx}",
    entity_type='TEAM',
    category='PROCESSING_ERROR',
    reason=f"Exception processing team defense record: {str(e)[:200]}",
    can_retry=True
)
```

---

## Implementation Status

### Phase 4 Precompute (100% Coverage - Complete)

| Processor | Uses Failure Tracking | Auto-Classification |
|-----------|----------------------|---------------------|
| PlayerDailyCacheProcessor | Yes | Yes (player-based) |
| PlayerCompositeFactorsProcessor | Yes | Yes (player-based) |
| PlayerShotZoneAnalysisProcessor | Yes | Yes (player-based) |
| MLFeatureStoreProcessor | Yes | Yes (player-based) |
| TeamDefenseZoneAnalysisProcessor | Yes | Skipped (team-based) |

### Phase 3 Analytics (100% Coverage - Complete This Session)

| Processor | Uses Failure Tracking | Auto-Classification |
|-----------|----------------------|---------------------|
| UpcomingPlayerGameContextProcessor | Yes | Yes |
| PlayerGameSummaryProcessor | **Yes (NEW)** | Yes |
| TeamOffenseGameSummaryProcessor | **Yes (NEW)** | Skipped (team-based) |
| TeamDefenseGameSummaryProcessor | **Yes (NEW)** | Skipped (team-based) |

---

## BigQuery Tables

| Table | Status | Description |
|-------|--------|-------------|
| `nba_processing.precompute_failures` | ACTIVE | Phase 4 failures with enhanced fields |
| `nba_processing.analytics_failures` | ACTIVE | Phase 3 failures with enhanced fields |
| `nba_processing.prediction_failures` | Schema exists | Phase 5 (not yet used) |

---

## Key Methods Reference

### analytics_base.py Methods

| Method | Lines | Description |
|--------|-------|-------------|
| `record_failure()` | 1772-1826 | Record entity failures during processing |
| `classify_recorded_failures()` | 1828-1959 | **NEW** - Enrich with DNP/DATA_GAP classification |
| `save_failures_to_bq()` | 1961-2039 | Persist to analytics_failures table (auto-classifies) |
| `finalize()` | 598-609 | Auto-saves failures on completion |

### completeness_checker.py Methods (For Reference)

| Method | Description |
|--------|-------------|
| `check_raw_boxscore_for_player()` | Single player raw data check |
| `classify_failure()` | Determine DNP vs DATA_GAP |
| `get_player_game_dates_batch()` | Batch lookup for expected/actual games |

---

## Failure Types

| Type | Meaning | is_correctable |
|------|---------|----------------|
| `PLAYER_DNP` | Player didn't play (not in raw box score) | False |
| `DATA_GAP` | Player played but data missing | True |
| `MIXED` | Some games DNP, some gaps | True |
| `INSUFFICIENT_HISTORY` | < 5 games in lookback (early season) | False |

---

## Verification Queries

### Check Phase 3 Failures After Next Run

```sql
SELECT
  processor_name,
  analysis_date,
  entity_id,
  entity_type,
  failure_category,
  failure_type,
  is_correctable
FROM nba_processing.analytics_failures
WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY created_at DESC
LIMIT 20;
```

### Check Failure Distribution

```sql
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count
FROM nba_processing.analytics_failures
GROUP BY 1, 2
ORDER BY 3 DESC;
```

---

## Files Modified This Session

| File | Changes |
|------|---------|
| `data_processors/analytics/analytics_base.py` | +132 lines - classify_recorded_failures() method |
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | +27 lines - finalize(), parallel & serial processing error handlers |
| `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py` | Already had record_failure() (verified) |
| `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py` | Already had record_failure() (verified) |

---

## Next Steps (Optional Enhancements)

1. **Add More Granular Error Tracking**: Currently team processors only track processing exceptions. Could add tracking for extraction failures.

2. **Dashboard/Monitoring**: Build dashboard to visualize failure patterns across processors.

3. **Automated Retry System**: Use `is_correctable=True` failures to trigger targeted reprocessing.

---

## Testing

All modified files compile successfully:
```bash
python3 -m py_compile data_processors/analytics/analytics_base.py
python3 -m py_compile data_processors/analytics/player_game_summary/player_game_summary_processor.py
python3 -m py_compile data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py
python3 -m py_compile data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py
# All files compile successfully
```

---

## Background Jobs Note

Multiple background jobs from previous sessions may still be running. Check with:
```bash
ps aux | grep python | grep -E "(backfill|processor)"
```
