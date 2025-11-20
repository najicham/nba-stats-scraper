# 10 - Week 1: Schema and Code Changes Plan

**Created:** 2025-11-19 10:52 PM PST
**Last Updated:** 2025-11-19 10:52 PM PST
**Status:** Planning
**Related:** 09-phase2-phase3-implementation-roadmap.md (Week 1 implementation)

## Purpose

This document details the specific schema and code changes needed for Week 1 implementation of the Phase 2→3 roadmap. It serves as a reference to maintain context if work is interrupted.

---

## Overview

**Goal:** Add change detection and waste tracking to analytics processors

**Changes Required:**
1. Extend `nba_processing.analytics_processor_runs` schema (add 9 new fields)
2. Update `analytics_base.py` to track and log new metrics
3. Deploy schema changes before code changes

**Estimated Time:** 12-15 hours total

---

## Current State

### Schema Location
```
schemas/bigquery/processing/processing_tables.sql
```

### Current Table
```sql
`nba-props-platform.nba_processing.analytics_processor_runs`
```

**Current Fields (22 fields):**
- Execution identifiers: processor_name, run_id, run_date
- Results: success, duration_seconds
- Scope: date_range_start, date_range_end, records_processed, records_inserted, records_updated, records_skipped
- Errors: errors_json, warning_count
- Resources: bytes_processed, slot_ms
- Source info: source_files_count, source_data_freshness_hours
- Metadata: processor_version, config_hash, created_at

### Code Location
```
data_processors/analytics/analytics_base.py
```

**Current Logging:** Line 908-927 - `log_processing_run()` method

---

## Schema Changes

### New Fields to Add (9 fields)

#### 1. Entity Tracking (for waste metrics)
```sql
entities_in_scope INT64,           -- Total entities that could be processed for date range
entities_processed INT64,          -- How many entities we actually processed
entities_changed INT64,            -- How many entities actually changed (KEY METRIC!)
```

**Purpose:** Enable calculation of waste percentage for decision query

**Example Values:**
- entities_in_scope: 450 (all players for date)
- entities_processed: 450 (we processed all)
- entities_changed: 3 (only 3 actually changed)
- waste_pct: 99.3% (449/450 wasted)

#### 2. Waste Percentage (calculated in code, not generated column)
```sql
waste_pct FLOAT64,                 -- Percentage of wasted processing
```

**Note:** Originally planned as GENERATED column, but calculating in code is simpler and more flexible.

**Calculation:**
```python
waste_pct = ((entities_processed - entities_changed) / entities_processed) * 100
```

#### 3. Processing Mode
```sql
processing_mode STRING DEFAULT 'date_range',  -- 'date_range' or 'entity_level'
```

**Values:**
- `'date_range'` - Phase 1 (process all entities for date range)
- `'entity_level'` - Phase 3 (process only changed entities)

#### 4. Skip Tracking
```sql
skip_reason STRING,                -- Why processing was skipped
```

**Values:**
- `'no_changes'` - Change detection found no changes
- `'dependencies_missing'` - Required dependencies not ready
- `'recent_run'` - Processed recently (idempotency)
- `'no_games'` - No games scheduled for date
- `'circuit_breaker_open'` - Circuit breaker preventing retry
- NULL - Not skipped (normal processing)

#### 5. Context Tracking (for debugging)
```sql
change_signature STRING,           -- Hash of source data (for next run comparison)
trigger_chain STRING,              -- Sequence: "source:nbac_injury → change_detection"
decisions_made STRING,             -- "dependencies_verified, processing_completed"
optimizations_used STRING,         -- "change_detection, early_exit"
```

**Purpose:** 10x faster debugging - see entire decision chain in one log entry

---

## Migration Strategy

### Option A: ALTER TABLE ✅ (Recommended - Non-Breaking)

**Advantages:**
- ✅ No data loss
- ✅ Backward compatible
- ✅ Existing code continues working
- ✅ Can run multiple times safely

**Migration Script:**
```sql
-- File: schemas/bigquery/processing/migrations/001_add_entity_tracking.sql

ALTER TABLE `nba-props-platform.nba_processing.analytics_processor_runs`
ADD COLUMN IF NOT EXISTS entities_in_scope INT64,
ADD COLUMN IF NOT EXISTS entities_processed INT64,
ADD COLUMN IF NOT EXISTS entities_changed INT64,
ADD COLUMN IF NOT EXISTS waste_pct FLOAT64,
ADD COLUMN IF NOT EXISTS processing_mode STRING DEFAULT 'date_range',
ADD COLUMN IF NOT EXISTS skip_reason STRING,
ADD COLUMN IF NOT EXISTS change_signature STRING,
ADD COLUMN IF NOT EXISTS trigger_chain STRING,
ADD COLUMN IF NOT EXISTS decisions_made STRING,
ADD COLUMN IF NOT EXISTS optimizations_used STRING;
```

### Option B: CREATE OR REPLACE ❌ (Not Recommended)
- Would lose all existing data
- Breaking change
- Don't do this!

---

## Code Changes - analytics_base.py

### 1. Add Context Tracking (30 min)

**Location:** `__init__()` method

**Add:**
```python
def __init__(self):
    # ... existing code ...

    # NEW: Context tracking for debugging
    self.context = {
        'trigger_chain': [],      # Sequence of processing triggers
        'skip_reasons': [],       # Why processing was skipped
        'decisions_made': [],     # Decisions made during processing
        'optimizations_used': []  # Which patterns were used
    }
```

### 2. Add Change Detection Methods (4-6 hours)

**Location:** After dependency checking methods (around line 500)

**Add these methods:**

```python
def _count_entities_in_scope(self, start_date: str, end_date: str) -> int:
    """
    Count total entities that could be processed for date range.
    Child classes override based on their entity type.

    Default: count distinct entities from first dependency table.
    """
    dependencies = self.get_dependencies()
    if not dependencies:
        return 0

    # Get first dependency table as proxy
    first_table = list(dependencies.keys())[0]
    config = dependencies[first_table]
    date_field = config.get('date_field', 'game_date')

    query = f"""
    SELECT COUNT(DISTINCT universal_player_id) as count
    FROM `{self.project_id}.{first_table}`
    WHERE {date_field} BETWEEN '{start_date}' AND '{end_date}'
    """

    result = list(self.bq_client.query(query).result())
    return int(result[0].count) if result else 0

def _get_current_data_signature(self, start_date: str, end_date: str) -> str:
    """
    Get a hash/signature of current source data.

    Simple approach: COUNT + MAX(processed_at) from dependencies
    """
    signatures = []

    for table_name, config in self.get_dependencies().items():
        date_field = config.get('date_field', 'game_date')

        query = f"""
        SELECT
            COUNT(*) as cnt,
            MAX(processed_at) as max_ts
        FROM `{self.project_id}.{table_name}`
        WHERE {date_field} BETWEEN '{start_date}' AND '{end_date}'
        """

        result = list(self.bq_client.query(query).result())
        if result:
            row = result[0]
            signatures.append(f"{table_name}:{row.cnt}:{row.max_ts}")

    # Hash all signatures
    import hashlib
    combined = "|".join(signatures)
    return hashlib.md5(combined.encode()).hexdigest()

def _get_previous_run_signature(self, start_date: str, end_date: str) -> Optional[str]:
    """Get signature from last successful run."""
    query = f"""
    SELECT change_signature
    FROM nba_processing.analytics_processor_runs
    WHERE processor_name = '{self.__class__.__name__}'
      AND date_range_start = '{start_date}'
      AND date_range_end = '{end_date}'
      AND success = TRUE
    ORDER BY run_date DESC
    LIMIT 1
    """

    result = list(self.bq_client.query(query).result())
    if result and result[0].change_signature:
        return result[0].change_signature
    return None

def _detect_changes_snapshot(self, start_date: str, end_date: str) -> dict:
    """
    Detect changes by comparing current data signature with previous run.

    Returns:
        {
            'entities_in_scope': int,
            'entities_changed': int,
            'has_changes': bool,
            'change_summary': dict
        }
    """
    entities_in_scope = self._count_entities_in_scope(start_date, end_date)

    if entities_in_scope == 0:
        return {
            'entities_in_scope': 0,
            'entities_changed': 0,
            'has_changes': False,
            'change_summary': {}
        }

    # Get signatures
    current_sig = self._get_current_data_signature(start_date, end_date)
    previous_sig = self._get_previous_run_signature(start_date, end_date)

    if previous_sig is None:
        # First run - all entities are "changed"
        entities_changed = entities_in_scope
        has_changes = True
        logger.info(f"First run for {start_date} to {end_date}, processing all {entities_in_scope} entities")
    elif current_sig == previous_sig:
        # No changes
        entities_changed = 0
        has_changes = False
        logger.info(f"No changes detected (signature match)")
    else:
        # Changed - for Phase 1, conservatively assume all changed
        entities_changed = entities_in_scope
        has_changes = True
        logger.info(f"Changes detected (signature mismatch)")

    return {
        'entities_in_scope': entities_in_scope,
        'entities_changed': entities_changed,
        'has_changes': has_changes,
        'change_summary': {
            'current_signature': current_sig,
            'previous_signature': previous_sig
        }
    }
```

### 3. Modify run() Method (2 hours)

**Location:** `run()` method (around line 95-220)

**Changes:**

```python
def run(self, opts: Optional[Dict] = None) -> bool:
    """Main entry point with change detection."""
    if opts is None:
        opts = {}

    try:
        # ... existing init code ...

        # Setup
        self.set_opts(opts)
        self.validate_opts()

        start_date = self.opts['start_date']
        end_date = self.opts['end_date']

        # NEW: Change detection BEFORE dependency check
        self.mark_time("change_detection")
        change_info = self._detect_changes_snapshot(start_date, end_date)
        change_detection_seconds = self.get_elapsed_seconds("change_detection")

        # Track for logging
        self.stats["entities_in_scope"] = change_info['entities_in_scope']
        self.stats["entities_changed"] = change_info['entities_changed']
        self.stats["processing_mode"] = "date_range"
        self.stats["change_detection_time"] = change_detection_seconds
        self.stats["change_signature"] = change_info['change_summary'].get('current_signature')

        # If no changes, skip
        if not change_info['has_changes']:
            logger.info("No changes detected - skipping processing")
            self.context['skip_reasons'].append('no_changes')
            self.context['optimizations_used'].append('change_detection')
            self.stats['skip_reason'] = 'no_changes'
            self.log_processing_run(success=True)
            return True
        else:
            self.context['decisions_made'].append(
                f"changes_detected:{change_info['entities_changed']}/{change_info['entities_in_scope']}"
            )

        # EXISTING: Dependency check
        if hasattr(self, 'get_dependencies') and callable(self.get_dependencies):
            dep_check = self.check_dependencies(start_date, end_date)

            if not dep_check['all_critical_present']:
                self.context['skip_reasons'].append('dependencies_missing')
                self.context['decisions_made'].append(
                    f"missing:{','.join(dep_check['missing'])}"
                )
                self.stats['skip_reason'] = 'dependencies_missing'
                # ... existing error handling ...
            else:
                self.context['decisions_made'].append('dependencies_verified')

        # ... rest of existing processing ...

        # Track entities processed
        self.stats["entities_processed"] = self.stats.get('rows_processed', 0)
        self.context['decisions_made'].append('processing_completed')

        # Log with new metrics
        self.log_processing_run(success=True)
        return True

    except Exception as e:
        # ... existing error handling ...
```

### 4. Update log_processing_run() Method (1 hour)

**Location:** Line 908-927

**Changes:**

```python
def log_processing_run(self, success: bool, error: str = None) -> None:
    """Log processing run with new entity metrics."""

    # Calculate waste percentage
    entities_processed = self.stats.get('entities_processed', 0)
    entities_changed = self.stats.get('entities_changed', 0)

    if entities_processed > 0 and entities_changed is not None:
        waste_pct = ((entities_processed - entities_changed) / entities_processed) * 100
    else:
        waste_pct = None

    run_record = {
        # EXISTING fields
        'processor_name': self.__class__.__name__,
        'run_id': self.run_id,
        'run_date': datetime.now(timezone.utc).isoformat(),
        'success': success,
        'date_range_start': self.opts.get('start_date'),
        'date_range_end': self.opts.get('end_date'),
        'records_processed': self.stats.get('rows_processed', 0),
        'duration_seconds': self.stats.get('total_runtime', 0),
        'errors_json': json.dumps([error] if error else []),

        # NEW fields - Entity tracking
        'entities_in_scope': self.stats.get('entities_in_scope'),
        'entities_processed': self.stats.get('entities_processed'),
        'entities_changed': self.stats.get('entities_changed'),
        'waste_pct': waste_pct,

        # NEW fields - Processing mode
        'processing_mode': self.stats.get('processing_mode', 'date_range'),
        'skip_reason': self.stats.get('skip_reason'),

        # NEW fields - Context tracking
        'change_signature': self.stats.get('change_signature'),
        'trigger_chain': ' → '.join(self.context['trigger_chain']) if self.context.get('trigger_chain') else None,
        'decisions_made': ', '.join(self.context['decisions_made']) if self.context.get('decisions_made') else None,
        'optimizations_used': ', '.join(self.context['optimizations_used']) if self.context.get('optimizations_used') else None,

        'created_at': datetime.now(timezone.utc).isoformat()
    }

    try:
        table_id = f"{self.project_id}.nba_processing.analytics_processor_runs"
        self.bq_client.insert_rows_json(table_id, [run_record])
    except Exception as e:
        logger.warning(f"Failed to log processing run: {e}")
```

---

## Implementation Steps

### Step 1: Update Schema File (Documentation) - 15 min

**File:** `schemas/bigquery/processing/processing_tables.sql`

**Action:** Add new columns to CREATE TABLE statement (lines 8-48)

**Add after line 41 (before `created_at`):**
```sql
  -- Entity tracking for waste metrics (Phase 2→3 optimization)
  entities_in_scope INT64,                      -- Total entities for date range
  entities_processed INT64,                     -- Entities actually processed
  entities_changed INT64,                       -- Entities that changed (KEY!)
  waste_pct FLOAT64,                           -- Wasted processing percentage

  -- Processing mode and skip tracking
  processing_mode STRING DEFAULT 'date_range',  -- 'date_range' or 'entity_level'
  skip_reason STRING,                          -- Why processing was skipped

  -- Context tracking for debugging
  change_signature STRING,                      -- Hash for change detection
  trigger_chain STRING,                        -- Processing trigger sequence
  decisions_made STRING,                       -- Decisions during run
  optimizations_used STRING,                   -- Patterns used
```

**Update description:**
```sql
OPTIONS (
  description = "Analytics processor execution logs with entity-level tracking for waste metrics and optimization decisions"
);
```

### Step 2: Create Migration Script - 10 min

**File:** `schemas/bigquery/processing/migrations/001_add_entity_tracking.sql` (NEW FILE)

**Content:**
```sql
-- Migration: Add entity tracking for Phase 2→3 optimization
-- Created: 2025-11-19
-- Safe to run multiple times (IF NOT EXISTS)

ALTER TABLE `nba-props-platform.nba_processing.analytics_processor_runs`
ADD COLUMN IF NOT EXISTS entities_in_scope INT64,
ADD COLUMN IF NOT EXISTS entities_processed INT64,
ADD COLUMN IF NOT EXISTS entities_changed INT64,
ADD COLUMN IF NOT EXISTS waste_pct FLOAT64,
ADD COLUMN IF NOT EXISTS processing_mode STRING DEFAULT 'date_range',
ADD COLUMN IF NOT EXISTS skip_reason STRING,
ADD COLUMN IF NOT EXISTS change_signature STRING,
ADD COLUMN IF NOT EXISTS trigger_chain STRING,
ADD COLUMN IF NOT EXISTS decisions_made STRING,
ADD COLUMN IF NOT EXISTS optimizations_used STRING;
```

### Step 3: Test Migration (Dev) - 15 min

```bash
# Run migration on dev
bq query --use_legacy_sql=false < schemas/bigquery/processing/migrations/001_add_entity_tracking.sql

# Verify columns added
bq show --schema nba-props-platform:nba_processing.analytics_processor_runs | grep entities

# Expected output:
# entities_in_scope, INTEGER, NULLABLE
# entities_processed, INTEGER, NULLABLE
# entities_changed, INTEGER, NULLABLE
# ...
```

### Step 4: Update analytics_base.py - 6-8 hours

**Changes:**
1. Add `self.context = {}` to `__init__()` (5 min)
2. Add change detection methods (4 hours)
3. Modify `run()` method (2 hours)
4. Update `log_processing_run()` (1 hour)
5. Test with one processor (1 hour)

### Step 5: Test with One Processor - 2 hours

**File:** Pick a simple processor (e.g., PlayerGameSummaryProcessor)

**Add:**
```python
def _count_entities_in_scope(self, start_date: str, end_date: str) -> int:
    """Count player-game combinations."""
    query = f"""
    SELECT COUNT(DISTINCT CONCAT(universal_player_id, '|', game_date)) as count
    FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    result = list(self.bq_client.query(query).result())
    return int(result[0].count) if result else 0
```

**Test:**
```python
# Run processor
processor = PlayerGameSummaryProcessor()
result = processor.run({
    'start_date': '2025-11-15',
    'end_date': '2025-11-15'
})

# Check logs
bq query --use_legacy_sql=false '
SELECT
    processor_name,
    entities_in_scope,
    entities_processed,
    entities_changed,
    waste_pct,
    skip_reason,
    decisions_made
FROM nba_processing.analytics_processor_runs
WHERE processor_name = "PlayerGameSummaryProcessor"
  AND date_range_start = "2025-11-15"
ORDER BY run_date DESC
LIMIT 1'
```

### Step 6: Deploy to Production - 1 hour

**Schema deployment:**
```bash
# 1. Run migration on production
bq query --use_legacy_sql=false < schemas/bigquery/processing/migrations/001_add_entity_tracking.sql

# 2. Verify
bq show --schema nba-props-platform:nba_processing.analytics_processor_runs
```

**Code deployment:**
```bash
# Deploy updated analytics processors
gcloud builds submit --config cloudbuild-processors.yaml
```

### Step 7: Verify - 30 min

```bash
# Wait for next processor run, then check
bq query --use_legacy_sql=false '
SELECT
    processor_name,
    run_date,
    success,
    entities_in_scope,
    entities_changed,
    waste_pct,
    skip_reason
FROM nba_processing.analytics_processor_runs
WHERE DATE(run_date) = CURRENT_DATE()
  AND entities_in_scope IS NOT NULL
ORDER BY run_date DESC
LIMIT 10'
```

**Expected output:**
- ✅ All new fields populated
- ✅ waste_pct calculated correctly
- ✅ change_signature present
- ✅ decisions_made logged

---

## Validation Checklist

- [ ] Schema migration runs without errors
- [ ] New columns appear in table
- [ ] Existing data not affected (NULL for new columns)
- [ ] analytics_base.py changes compile without errors
- [ ] Test processor logs new fields correctly
- [ ] waste_pct calculation is correct
- [ ] change_signature enables change detection
- [ ] No regressions in existing functionality
- [ ] Can run decision query successfully
- [ ] Production deployment successful

---

## Rollback Plan

**If issues occur:**

1. **Code rollback:**
   ```bash
   # Revert to previous analytics_base.py
   git revert <commit_hash>
   gcloud builds submit --config cloudbuild-processors.yaml
   ```

2. **Schema rollback:**
   ```sql
   -- Remove columns (if absolutely necessary - prefer leaving them)
   ALTER TABLE `nba-props-platform.nba_processing.analytics_processor_runs`
   DROP COLUMN IF EXISTS entities_in_scope,
   DROP COLUMN IF EXISTS entities_processed,
   DROP COLUMN IF EXISTS entities_changed,
   -- ... etc
   ```

**Note:** Prefer leaving schema changes in place even if reverting code. NULL columns don't hurt anything.

---

## Success Criteria

**Week 1 complete when:**
- ✅ Schema has new columns
- ✅ analytics_base.py tracks entity metrics
- ✅ Can detect when data hasn't changed
- ✅ Waste percentage logged for all runs
- ✅ Context tracking aids debugging
- ✅ Decision query returns results
- ✅ Zero regressions in data quality

---

## Next Steps (Week 2)

After Week 1 implementation:
1. Create decision query script
2. Test with multiple processors
3. Document findings
4. Start Week 3 monitoring

See: [09-phase2-phase3-implementation-roadmap.md](09-phase2-phase3-implementation-roadmap.md)

---

## Notes

**Why snapshot comparison instead of processed_at comparison?**
- Our Phase 2 does DELETE+INSERT all rows
- All rows have same `processed_at` timestamp
- Can't distinguish which entities actually changed
- Snapshot comparison works with our existing pattern

**Why calculate waste_pct in code instead of GENERATED column?**
- Simpler to implement
- More flexible (can change calculation logic)
- BigQuery GENERATED columns have limitations
- Can still query/aggregate the same way

**Why context tracking is valuable:**
- Debugging: See entire decision chain in one log entry
- Monitoring: Understand which optimizations are helping
- Auditing: Know exactly why processing happened/skipped
- Planning: Data for future optimization decisions
