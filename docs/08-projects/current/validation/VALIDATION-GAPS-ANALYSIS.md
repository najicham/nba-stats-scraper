# Validation System - Gaps Analysis

**Date**: 2025-12-02
**Status**: Analysis Complete, High Priority Fixes Implemented

## Executive Summary

The validation system is well-designed and captures most critical issues. This document identifies potential gaps where issues could slip through undetected, prioritized by impact.

---

## Current Coverage (What We Validate Well)

| Category | Implementation | Files |
|----------|---------------|-------|
| Record counts | Per-table counts vs expected | `phase*_validator.py` |
| Player completeness | Active/rostered vs actual | `player_universe.py` |
| Quality tiers | Gold/silver/bronze distribution | `base.py:query_quality_distribution` |
| Fallback tracking | Primary vs fallback source | `chain_validator.py` |
| Run history | Errors, warnings, duration | `run_history.py` |
| Dependencies | Missing/stale detection | `run_history.py:43-44` |
| Bootstrap period | Days 0-13 flagged | `schedule_context.py:112` |
| Roster staleness | >7 days warning | `player_universe.py:374-378` |
| Prop coverage | With/without prop lines | `phase3_validator.py:189-205` |

---

## Identified Gaps

### HIGH PRIORITY - ✅ IMPLEMENTED (2025-12-02)

#### 1. ✅ Duplicate Detection - IMPLEMENTED

**File**: `shared/validation/validators/base.py`

**Added functions**:
- `query_duplicate_count()` - Counts records violating uniqueness
- `check_data_integrity()` - Comprehensive integrity check

**Usage**:
```python
from shared.validation.validators import check_data_integrity
result = check_data_integrity(client, dataset, table, date_column, game_date)
if result.duplicate_count > 0:
    print(f"Found {result.duplicate_count} duplicates!")
```

---

#### 2. ✅ Cross-Table Consistency Checks - IMPLEMENTED

**Files**:
- `shared/validation/validators/base.py` - `check_cross_table_consistency()`
- `bin/validate_pipeline.py` - `_check_cross_phase_consistency()`

**Behavior**: Automatically checks player consistency between Phase 3 (`player_game_summary`) and Phase 4 (`ml_feature_store_v2`) during validation. Warnings added if mismatches detected.

**Output**: Shows warnings like:
```
Cross-phase mismatch: 5 players in Phase 3 missing from Phase 4
```

---

#### 3. ✅ BQ Timeout Distinct from Missing - IMPLEMENTED

**File**: `shared/validation/validators/chain_validator.py`

**Change**: Timeout now returns `-1` sentinel value, which sets status to `'timeout'` (distinct from `'missing'`).

```python
# Before
except TimeoutError:
    return 0  # ← Treated same as "no data"

# After
except TimeoutError:
    return -1  # Sentinel value → status = 'timeout'
```

---

### MEDIUM PRIORITY - ✅ IMPLEMENTED (2025-12-02)

#### 4. ✅ NULL Value Tracking in Critical Fields - IMPLEMENTED

**File**: `shared/validation/validators/base.py`

**Added functions**:
- `query_null_critical_fields()` - Counts NULL values per field
- `DataIntegrityResult` - Dataclass with `null_critical_fields` dict

**Usage**:
```python
from shared.validation.validators import query_null_critical_fields
null_counts = query_null_critical_fields(
    client, dataset, table, date_column, game_date,
    critical_fields=['points', 'minutes', 'team_abbr']
)
# Returns: {'points': 0, 'minutes': 5, 'team_abbr': 0}
```

---

#### 5. Game ID Consistency Validation

**Current behavior**: Counts team_defense rows, doesn't verify game_ids.

**Risk**: Schedule shows 3 games, team_defense has 6 rows but from wrong games.

**Proposed fix**:
```python
def validate_game_id_consistency(schedule_games: Set[str], table_games: Set[str]):
    """Verify game_ids match schedule."""
    missing = schedule_games - table_games
    extra = table_games - schedule_games
```

**Impact**: Medium - Would catch date/game mismatches

---

#### 6. Run History Only Shows Latest Run

**Current behavior** (`run_history.py:141`):
```python
if processor_name in seen_processors:
    continue  # Skips earlier runs
```

**Risk**: Processor ran twice, first run failed, second succeeded - we only see success.

**Proposed fix**: Add option to show all runs, or track "had failures before success".

**Impact**: Low - Latest run is usually what matters

---

### LOW PRIORITY

#### 7. No Schema Validation

**Current behavior**: Query succeeds or fails, no column checks.

**Risk**: Schema drift could silently break downstream consumers.

**Proposed approach**: Periodic schema validation (not per-date).

---

#### 8. No Data Freshness Within Day (Daily Mode)

**Current behavior**: Checks if data exists for today.

**Risk**: Props scraped at 6am, now 8pm - data may be stale.

**Proposed approach**: Track `scraped_at` or `updated_at` timestamps.

---

## Recommendations

### ✅ COMPLETED (2025-12-02)

1. ✅ **Add timeout status** - Timeout now returns `'timeout'` status (not `'missing'`)
2. ✅ **Duplicate detection** - `query_duplicate_count()` and `check_data_integrity()` added
3. ✅ **Cross-phase player consistency** - Automatic check between Phase 3 and Phase 4
4. ✅ **NULL critical field tracking** - `query_null_critical_fields()` added

### Future (Lower Priority)

5. **Game ID validation** - Add schedule/data game_id matching
6. **Full run history option** - Verbose mode shows all runs
7. **Schema validation** - Periodic column/type checks

---

## Current Validation System Strengths

Despite these gaps, the system handles the most critical scenarios well:

1. **Fallback chain awareness** - Knows exactly which source is being used
2. **Quality tier propagation** - Tracks data quality through pipeline
3. **Bootstrap period handling** - Doesn't false-alarm on expected empty data
4. **Mode-aware validation** - Daily vs backfill handled correctly
5. **Virtual source dependencies** - Correctly validates ESPN extraction pattern
6. **Run history integration** - Shows processor errors, alerts, dependencies

The identified gaps are edge cases that rarely occur in normal operation. The system is production-ready as-is.
