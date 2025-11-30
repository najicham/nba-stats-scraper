# Smart Idempotency Implementation Guide (Pattern #14)
**Version**: 1.0
**Date**: 2025-11-21
**Status**: ✅ COMPLETE - Deployed to all 22 Phase 2 processors

> **📚 Main Documentation:** For the authoritative pattern reference,
> see [`docs/05-development/guides/processor-patterns/01-smart-idempotency.md`](../../../05-development/guides/processor-patterns/01-smart-idempotency.md)
>
> This project document contains original design decisions and implementation planning.

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [SmartIdempotencyMixin API](#smartidempotencymixin-api)
4. [Integration Guide](#integration-guide)
5. [Implementation Phases](#implementation-phases)
6. [Testing Strategy](#testing-strategy)
7. [Monitoring & Metrics](#monitoring--metrics)
8. [Troubleshooting](#troubleshooting)

---

## Overview

### Problem Statement
Phase 2 raw processors scrape data 4-6x daily (injuries, props), triggering cascade processing through Phase 3/4/5 even when source data hasn't meaningfully changed.

**Current Impact:**
- Injury reports scraped 4-6x daily with no status changes
- 450+ players × 3 downstream phases = 1350+ unnecessary operations
- Wastes compute, storage, increases costs
- Creates false "data updated" signals

### Solution: Smart Idempotency
Compute hash of meaningful fields only (exclude metadata like `processed_at`, `scrape_timestamp`, `confidence_score`). Before writing, compare new hash to existing hash. Skip write if match.

**Expected Impact:**
- 50% reduction in cascade processing (2-3 scrapes → 1 write when data unchanged)
- Faster processing (skip time vs full write time)
- Cleaner audit trail (only writes when data actually changed)
- Phase 3/4/5 processors can also use hash tracking to skip reprocessing

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Phase 2 Processor                        │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  SmartIdempotencyMixin                                 │ │
│  │  - compute_data_hash(record) → "a3f2b1c9..."         │ │
│  │  - add_data_hash() → adds hash to all records         │ │
│  │  - query_existing_hash(keys) → existing hash          │ │
│  │  - should_skip_write() → True/False                   │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ↓                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  ProcessorBase                                         │ │
│  │  - load_data()                                         │ │
│  │  - transform_data() ← calls add_data_hash()           │ │
│  │  - save_data() ← calls should_skip_write()            │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                           ↓
           ┌───────────────────────────────┐
           │    BigQuery Phase 2 Table     │
           │  - data_hash STRING (new)     │
           │  - processed_at TIMESTAMP     │
           │  - [meaningful fields...]     │
           └───────────────────────────────┘
                           ↓
           ┌───────────────────────────────┐
           │   Phase 3 Analytics Processor │
           │  - Reads source_*_hash fields │
           │  - Compares to last run       │
           │  - Skips if unchanged         │
           └───────────────────────────────┘
```

### Hash Computation Algorithm

1. **Extract Field Values**: Extract values for `HASH_FIELDS` from record
2. **Normalize**: Convert to canonical string (handle None, numbers, strings consistently)
3. **Sort**: Sort field:value pairs alphabetically for consistency
4. **Concatenate**: Join with `|` delimiter → `"field1:value1|field2:value2|..."`
5. **Hash**: Compute SHA256 hash
6. **Truncate**: Return first 16 characters (sufficient uniqueness, compact)

**Collision Probability**: ~1 in 18 quintillion for 16 hex chars (2^64 combinations)

---

## SmartIdempotencyMixin API

### Class Variables

```python
class MyProcessor(SmartIdempotencyMixin, ProcessorBase):
    # REQUIRED: Define which fields to include in hash
    HASH_FIELDS = [
        'player_lookup',      # Primary key
        'game_id',            # Primary key
        'injury_status',      # Meaningful field
        'reason',             # Meaningful field
        'reason_category'     # Meaningful field
        # EXCLUDE: processed_at, scrape_timestamp, confidence_score
    ]
```

### Methods

#### `compute_data_hash(record: Dict) -> str`
Compute SHA256 hash (16 chars) from meaningful fields only.

**Args:**
- `record`: Single data record (dict)

**Returns:**
- `str`: 16-character hash

**Raises:**
- `ValueError`: If `HASH_FIELDS` not defined or hash field missing

**Example:**
```python
record = {
    'player_lookup': 'lebronjames',
    'injury_status': 'out',
    'reason': 'left ankle',
    'processed_at': '2025-01-15 10:00:00'  # NOT included in hash
}

hash_value = self.compute_data_hash(record)
# Returns: "a3f2b1c9d4e5f6a7"
```

#### `add_data_hash() -> None`
Add `data_hash` field to each record in `self.transformed_data`.

**Call this at the end of `transform_data()`** after all meaningful fields populated.

**Modifies:**
- `self.transformed_data`: Adds 'data_hash' field to each record

**Example:**
```python
def transform_data(self):
    # Normal transformation
    self.transformed_data = [
        {'player': 'lebron', 'status': 'out', ...},
        {'player': 'curry', 'status': 'probable', ...}
    ]

    # Add hashes (call this last)
    self.add_data_hash()
```

#### `query_existing_hash(primary_keys: Dict, table_id: str) -> Optional[str]`
Query existing `data_hash` from BigQuery for given primary keys.

**Args:**
- `primary_keys`: Dict of primary key field names and values
- `table_id`: Full table ID (defaults to `self.table_name`)

**Returns:**
- `str`: Existing hash value if record exists, None otherwise

**Example:**
```python
existing_hash = self.query_existing_hash({
    'game_id': '0022400561',
    'player_lookup': 'lebronjames'
})

if existing_hash == computed_hash:
    # Skip write
    pass
```

#### `should_skip_write() -> bool`
Determine if write should be skipped based on hash comparison.

**Decision logic depends on processing strategy:**

- **MERGE_UPDATE**: Query existing hash, compare, skip if match
- **APPEND_ALWAYS**: Never skip (hash is for monitoring only)

**Returns:**
- `bool`: True if write should be skipped, False otherwise

**Example (MERGE_UPDATE):**
```python
def save_data(self):
    if self.should_skip_write():
        logger.info("Skipping write - data unchanged")
        return

    super().save_data()
```

**Example (APPEND_ALWAYS):**
```python
def save_data(self):
    # APPEND_ALWAYS always writes (hash is for monitoring)
    super().save_data()
```

#### `get_idempotency_stats() -> Dict`
Return smart idempotency statistics for monitoring.

**Returns:**
```python
{
    'hashes_computed': 450,
    'hashes_matched': 425,
    'rows_skipped': 425,
    'strategy': 'MERGE_UPDATE',
    'skip_check_performed': True
}
```

---

## Integration Guide

### Step 1: Add Mixin Inheritance

```python
# Before
from data_processors.raw.processor_base import ProcessorBase

class MyProcessor(ProcessorBase):
    pass

# After
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

class MyProcessor(SmartIdempotencyMixin, ProcessorBase):
    pass
```

**⚠️ Order matters!** Mixin must come BEFORE ProcessorBase.

### Step 2: Define HASH_FIELDS

```python
class MyProcessor(SmartIdempotencyMixin, ProcessorBase):
    # Define meaningful fields for hash computation
    HASH_FIELDS = [
        'player_lookup',      # Primary key
        'game_id',            # Primary key
        'injury_status',      # Meaningful data field
        'reason',             # Meaningful data field
        'reason_category'     # Meaningful data field
    ]

    # EXCLUDE from hash:
    # - processed_at (metadata)
    # - scrape_timestamp (metadata)
    # - confidence_score (derived, not source data)
    # - source_file_path (metadata)
```

**Guidelines for choosing HASH_FIELDS:**
- ✅ Include: Primary keys, meaningful business data
- ❌ Exclude: Metadata (timestamps, file paths), derived fields (confidence scores)
- ❌ Exclude: Fields that change every scrape without business meaning

### Step 3: Call add_data_hash() in transform_data()

```python
def transform_data(self):
    # Transform data normally
    self.transformed_data = []

    for injury in self.raw_data['injuries']:
        record = {
            'player_lookup': self.normalize_name(injury['player']),
            'game_id': injury['game_id'],
            'injury_status': injury['status'],
            'reason': injury['reason'],
            'reason_category': self.categorize_reason(injury['reason']),
            'processed_at': datetime.now()  # NOT in hash
        }
        self.transformed_data.append(record)

    # Add hashes (call this LAST, after all fields populated)
    self.add_data_hash()
```

### Step 4: Implement Skip Logic in save_data()

**For MERGE_UPDATE strategy:**
```python
def save_data(self):
    # Check idempotency
    if self.should_skip_write():
        logger.info("Skipping write - all records unchanged")
        self.stats['rows_skipped'] = len(self.transformed_data)
        return

    # Proceed with write
    super().save_data()

    # Log idempotency stats
    stats = self.get_idempotency_stats()
    logger.info(f"Idempotency stats: {stats}")
```

**For APPEND_ALWAYS strategy:**
```python
def save_data(self):
    # APPEND_ALWAYS always writes (hash is for monitoring/auditing)
    # Downstream Phase 3 can use hash to detect duplicates
    super().save_data()

    # Log stats (should show 0 skips for APPEND_ALWAYS)
    stats = self.get_idempotency_stats()
    logger.info(f"Idempotency stats: {stats}")
```

### Step 5: Update Processor Documentation

Add to processor docstring:
```python
"""
MyProcessor - Processes XYZ data from GCS to BigQuery

Processing Strategy: MERGE_UPDATE
Smart Idempotency: Enabled (Pattern #14)
    Hash Fields: player_lookup, game_id, injury_status, reason, reason_category
    Expected Skip Rate: 50% (4-6 scrapes → 2-3 writes when status unchanged)
"""
```

---

## Implementation Phases

### Phase 1: Critical Processors (Week 1) - 5 processors
**Target**: 50% cascade reduction for highest-impact tables

1. **nbac_injury_report_processor** (APPEND_ALWAYS)
   - Hash fields: `player_lookup, team, game_date, game_id, injury_status, reason, reason_category`
   - Expected impact: 450 players × 4 scrapes → 2 writes = 900 ops saved daily

2. **bdl_injuries_processor** (APPEND_ALWAYS)
   - Hash fields: `player_lookup, team_abbr, injury_status_normalized, return_date, reason_category`
   - Expected impact: Similar to nbac_injury_report

3. **odds_api_props_processor** (APPEND_ALWAYS)
   - Hash fields: `player_lookup, game_date, game_id, bookmaker, points_line, snapshot_timestamp`
   - Expected impact: 450 players × 6 scrapes → 3 writes = 1350 ops saved daily

4. **bettingpros_props_processor** (APPEND_ALWAYS)
   - Hash fields: `player_lookup, game_date, market_type, bookmaker, bet_side, points_line, is_best_line`
   - Expected impact: Similar to odds_api_props

5. **odds_api_game_lines_processor** (APPEND_ALWAYS)
   - Hash fields: `game_id, game_date, bookmaker_key, market_key, outcome_name, outcome_point, snapshot_timestamp`
   - Expected impact: 15 games × 6 scrapes → 3 writes = 45 ops saved daily

### Phase 2: Medium Priority (Week 2) - 7 processors
**Target**: Optimize post-game data processing

- nbac_play_by_play_processor
- nbac_player_boxscores_processor
- nbac_team_boxscore_processor (when table created)
- nbac_gamebook_processor
- bdl_boxscores_processor
- espn_scoreboard_processor
- espn_boxscores_processor

### Phase 3: Low Priority (Week 3+) - 9 processors
**Target**: Complete coverage for all Phase 2 tables

- nbac_schedule_processor
- nbac_player_list_processor
- nbac_player_movement_processor
- nbac_referee_processor
- bdl_active_players_processor
- bdl_standings_processor
- espn_team_rosters_processor
- bigdataball_pbp_processor
- br_rosters_processor

---

## Testing Strategy

### Unit Tests

**File**: `tests/processors/test_smart_idempotency_mixin.py`

```python
def test_compute_data_hash_consistency():
    """Hash should be deterministic for same input."""
    mixin = SmartIdempotencyMixin()
    mixin.HASH_FIELDS = ['field1', 'field2']

    record = {'field1': 'value1', 'field2': 'value2'}
    hash1 = mixin.compute_data_hash(record)
    hash2 = mixin.compute_data_hash(record)

    assert hash1 == hash2
    assert len(hash1) == 16

def test_compute_data_hash_different_for_different_data():
    """Hash should differ for different meaningful data."""
    mixin = SmartIdempotencyMixin()
    mixin.HASH_FIELDS = ['status']

    hash1 = mixin.compute_data_hash({'status': 'out'})
    hash2 = mixin.compute_data_hash({'status': 'probable'})

    assert hash1 != hash2

def test_compute_data_hash_ignores_non_hash_fields():
    """Hash should ignore fields not in HASH_FIELDS."""
    mixin = SmartIdempotencyMixin()
    mixin.HASH_FIELDS = ['status']

    hash1 = mixin.compute_data_hash({'status': 'out', 'timestamp': '2025-01-15'})
    hash2 = mixin.compute_data_hash({'status': 'out', 'timestamp': '2025-01-16'})

    assert hash1 == hash2  # Different timestamps, same hash

def test_add_data_hash():
    """add_data_hash should add hash to all records."""
    class TestProcessor(SmartIdempotencyMixin):
        HASH_FIELDS = ['field1']

    processor = TestProcessor()
    processor.transformed_data = [
        {'field1': 'value1'},
        {'field1': 'value2'}
    ]

    processor.add_data_hash()

    assert 'data_hash' in processor.transformed_data[0]
    assert 'data_hash' in processor.transformed_data[1]
    assert len(processor.transformed_data[0]['data_hash']) == 16
```

### Integration Tests

**File**: `tests/processors/test_bdl_injuries_with_idempotency.py`

```python
def test_bdl_injuries_skip_unchanged_data(mock_bq_client, mock_gcs_client):
    """Processor should skip write when hash matches."""
    processor = BdlInjuriesProcessor()

    # Setup: existing data with hash
    existing_hash = "a3f2b1c9d4e5f6a7"
    mock_bq_client.query.return_value.result.return_value = [
        type('obj', (object,), {'data_hash': existing_hash})()
    ]

    # Load same data (should produce same hash)
    processor.load_data()
    processor.transform_data()  # adds hash

    # Verify hash matches
    assert processor.transformed_data[0]['data_hash'] == existing_hash

    # save_data should skip
    processor.save_data()

    # Verify no write occurred
    assert processor.stats.get('rows_skipped', 0) > 0
    mock_bq_client.load_table_from_file.assert_not_called()
```

### End-to-End Tests

**Manual Test Procedure:**
1. Run processor twice with identical source data
2. Verify first run writes data
3. Verify second run skips write (logs "Skipping write - data unchanged")
4. Verify stats show `rows_skipped > 0`
5. Change meaningful field in source data
6. Verify third run writes data (hash changed)

---

## Monitoring & Metrics

### Key Metrics to Track

```sql
-- Daily skip rate by processor
SELECT
  processor_name,
  DATE(processing_timestamp) as date,
  COUNT(*) as total_runs,
  SUM(rows_skipped) as total_skipped,
  SUM(rows_inserted) as total_inserted,
  ROUND(SUM(rows_skipped) / (SUM(rows_skipped) + SUM(rows_inserted)) * 100, 1) as skip_rate_pct
FROM `nba_monitoring.processor_execution_log`
WHERE DATE(processing_timestamp) >= CURRENT_DATE() - 7
  AND processor_name IN ('nbac_injury_report', 'bdl_injuries', 'odds_api_props')
GROUP BY processor_name, date
ORDER BY date DESC, processor_name;
```

### Expected Metrics (Phase 1)

| Processor | Scrapes/Day | Expected Skips | Skip Rate | Ops Saved/Day |
|-----------|-------------|----------------|-----------|---------------|
| nbac_injury_report | 4-6 | 50% | 50% | 900+ |
| odds_api_props | 6 | 50% | 50% | 1350+ |
| bdl_injuries | 4-6 | 50% | 50% | 900+ |
| bettingpros_props | 6 | 50% | 50% | 1350+ |
| odds_game_lines | 6 | 50% | 50% | 45+ |

**Total Expected Impact**: 4500+ operations saved daily across Phase 1 processors

### Alerts

**Low Skip Rate Alert** (indicates issue with hash logic):
```sql
-- Alert if skip rate < 30% for processors expected to skip 50%
SELECT processor_name, skip_rate_pct
FROM daily_skip_rates
WHERE date = CURRENT_DATE()
  AND processor_name IN ('nbac_injury_report', 'odds_api_props')
  AND skip_rate_pct < 30;
```

---

## Troubleshooting

### Issue: Hash changes every run despite identical data

**Symptom**: `should_skip_write()` always returns False, skip rate = 0%

**Possible Causes:**
1. **Non-deterministic field included in hash**
   - Check for timestamp fields in `HASH_FIELDS`
   - Check for random/UUID fields in `HASH_FIELDS`

2. **Whitespace/formatting differences**
   - Verify `compute_data_hash()` normalizes strings (strips whitespace)

3. **Float precision issues**
   - Verify float fields are rounded consistently

**Solution:**
```python
# Review HASH_FIELDS - remove any non-deterministic fields
HASH_FIELDS = [
    'player_lookup',
    'injury_status',
    # 'processed_at',  # ❌ Remove - changes every scrape!
    # 'confidence_score'  # ❌ Remove - derived field!
]
```

### Issue: Hash collisions

**Symptom**: Different data produces same hash

**Likelihood**: Extremely low (~1 in 18 quintillion for 16 hex chars)

**If it happens:**
1. Log collision details (both records, hash value)
2. Increase hash length from 16 to 32 characters
3. Report to team for investigation

### Issue: Performance degradation

**Symptom**: Processor takes longer to run after adding mixin

**Possible Causes:**
1. **Hash computation overhead** (negligible for <10k records)
2. **BigQuery query for existing hash** (one query per record for MERGE_UPDATE)

**Solution:**
- Batch hash lookups (query multiple primary keys in one query)
- Cache results for records with same primary keys
- For APPEND_ALWAYS: No query overhead (hash is metadata only)

---

## Next Steps

1. **Implement Phase 1** (5 critical processors) - Week 1
2. **Monitor metrics** - Verify 50% skip rate
3. **Implement Phase 2** (7 medium priority) - Week 2
4. **Create comprehensive dependency checking documentation** - Future
5. **Implement Phase 3** (9 low priority) - Week 3+

---

## References

- Schema Update Plan: `docs/implementation/02-schema-update-plan-smart-idempotency.md`
- Dependency Tracking Guide: `docs/implementation/04-dependency-checking-strategy.md`
- Mixin Source Code: `data_processors/raw/smart_idempotency_mixin.py`
- Migration Files: `monitoring/schemas/migrations/add_data_hash_to_*.sql`
