# Session 89: Enhanced Failure Tracking Implementation

**Date:** 2025-12-09
**Focus:** Schema Consolidation and Processor Review for Enhanced Failure Tracking
**Status:** Schema Complete, Processor Integration Pending

---

## Executive Summary

This session consolidated the enhanced failure tracking schema and reviewed all Phase 3/4 processors to understand current failure handling. The schema is complete in BigQuery, but **NO PROCESSORS** have been updated to populate the new enhanced fields.

---

## What Was Completed

### 1. Schema Files Synchronized (3 files updated)

| File | Status | Description |
|------|--------|-------------|
| `schemas/bigquery/processing/precompute_failures_table.sql` | Updated | Now includes all 16 columns |
| `schemas/bigquery/processing/processing_tables.sql` (lines 143-178) | Updated | Synced with enhanced schema |
| `schemas/bigquery/processing/enhanced_failure_tracking.sql` | Reference | ALTER statements + new tables |

### 2. Project Status Updated
- `docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md`
- Changed from "Proposed" to "In Progress (Schema Complete, Processor Integration Pending)"

### 3. BigQuery Tables Verified
All tables exist with correct schema:
- `nba_processing.precompute_failures` - 16 columns (enhanced)
- `nba_processing.analytics_failures` - exists (unused)
- `nba_processing.prediction_failures` - exists (unused)

---

## Key File Paths

### Schema Files
```
schemas/bigquery/processing/precompute_failures_table.sql    # Main schema definition
schemas/bigquery/processing/processing_tables.sql            # Combined processing schemas
schemas/bigquery/processing/enhanced_failure_tracking.sql    # Enhancement reference + ALTER statements
```

### Project Documentation
```
docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md  # Project spec
docs/02-operations/backfill/completeness-failure-guide.md                     # Operations guide
docs/02-operations/backfill/README.md                                         # Backfill hub
```

### Phase 4 Processors (Need Enhancement)
```
data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py
  - Failure handling: Lines 1679-1704 (_save_failures method)
  - Failure categories: EXPECTED_INCOMPLETE, INCOMPLETE_UPSTREAM, INSUFFICIENT_DATA, INCOMPLETE_DATA, PROCESSING_ERROR, CIRCUIT_BREAKER_ACTIVE

data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py
  - Failure handling: Lines 726-740 (save_failures_to_bq via base class)
  - Failure categories: INSUFFICIENT_DATA, INCOMPLETE_DATA, PROCESSING_ERROR, CIRCUIT_BREAKER_ACTIVE

data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
  - Failure handling: Lines 1290-1291 (save_failures_to_bq via base class)
  - Failure categories: INCOMPLETE_DATA, MISSING_UPSTREAM, INSUFFICIENT_DATA, PROCESSING_ERROR, CIRCUIT_BREAKER_ACTIVE

data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
  - Failure handling: Lines 1360-1361 (save_failures_to_bq via base class)
  - Failure categories: INSUFFICIENT_DATA, INCOMPLETE_DATA, PROCESSING_ERROR, CIRCUIT_BREAKER_ACTIVE
  - Special: Multi-window completeness (L5, L10, L7d, L14d)

data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
  - Failure handling: Lines 869-870 (save_failures_to_bq via base class)
  - Failure categories: INSUFFICIENT_DATA, INCOMPLETE_DATA_SKIPPED, UPSTREAM_INCOMPLETE, CIRCUIT_BREAKER_ACTIVE, calculation_error
```

### Phase 3 Processors (Need Enhancement)
```
data_processors/analytics/player_game_summary/player_game_summary_processor.py
  - Uses registry_failures for player lookup issues (Lines 1014-1034, 1168-1188)
  - Does NOT write to analytics_failures table

data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py
  - Uses quality issues logging
  - Does NOT write to analytics_failures table
```

### Base Classes
```
data_processors/precompute/precompute_base.py
  - save_failures_to_bq() method: Lines 1560-1635
  - This is where failure inserts happen for all Phase 4 processors

data_processors/analytics/analytics_base.py
  - save_registry_failures() method: Lines 1687-1757
  - log_quality_issue() method: Lines 1558-1616
```

---

## Current State Summary

### What Exists
| Component | Status | Details |
|-----------|--------|---------|
| BQ Table: precompute_failures | Enhanced | 16 columns including failure_type, is_correctable, etc. |
| BQ Table: analytics_failures | Created | Empty - no processor writes to it |
| BQ Table: prediction_failures | Created | Empty - no processor writes to it |
| Schema Files | Synced | All 3 files now match |
| Project Doc | Updated | Status changed to "In Progress" |

### What's Missing (Next Steps)
| Component | Status | Work Required |
|-----------|--------|---------------|
| Phase 4 Processors | Not Integrated | Update 5 processors to populate new fields |
| Phase 3 Processors | Not Integrated | Update 2 processors to write to analytics_failures |
| DNP Detection Logic | Not Implemented | Need raw box score check function |
| Completeness Checker | Not Updated | Need to add classification logic |

---

## Implementation Guide for Next Session

### Step 1: Update PrecomputeProcessorBase (Recommended First)

Location: `data_processors/precompute/precompute_base.py` around line 1560

The `save_failures_to_bq()` method currently writes basic fields. Update to include:
```python
# Add to failure record construction
failure_record['failure_type'] = entity.get('failure_type', 'UNKNOWN')
failure_record['is_correctable'] = entity.get('is_correctable')
failure_record['expected_game_count'] = entity.get('expected_count')
failure_record['actual_game_count'] = entity.get('actual_count')
failure_record['missing_game_dates'] = json.dumps(entity.get('missing_dates', []))
failure_record['raw_data_checked'] = entity.get('raw_data_checked', False)
failure_record['resolution_status'] = 'UNRESOLVED'
```

### Step 2: Implement DNP Detection Logic

Add to `shared/utils/completeness_checker.py`:
```python
def classify_failure(player_lookup: str, analysis_date: date, expected_games: List[date], actual_games: List[date]) -> dict:
    """Determine if missing games are due to DNP or data gaps."""
    # See docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md
    # for full implementation
```

### Step 3: Update Each Processor

For each Phase 4 processor, update the failure recording to include classification:
```python
# When recording a failure, add:
failure_info['failure_type'] = classification['failure_type']
failure_info['is_correctable'] = classification['is_correctable']
failure_info['expected_count'] = len(expected_games)
failure_info['actual_count'] = len(actual_games)
failure_info['missing_dates'] = classification['missing_dates']
failure_info['raw_data_checked'] = True
```

---

## Quick Validation Queries

### Check current failure data
```sql
-- See what failures exist
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count,
  COUNTIF(failure_type IS NOT NULL) as has_type
FROM nba_processing.precompute_failures
WHERE analysis_date >= '2021-10-01'
GROUP BY 1, 2
ORDER BY 1, 2;
```

### Verify schema has all columns
```sql
SELECT column_name
FROM `nba-props-platform.nba_processing.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'precompute_failures'
ORDER BY ordinal_position;
```

### Check if new tables are being used
```sql
SELECT 'analytics_failures' as tbl, COUNT(*) FROM nba_processing.analytics_failures
UNION ALL
SELECT 'prediction_failures', COUNT(*) FROM nba_processing.prediction_failures;
```

---

## Processor Integration Checklist

### Phase 4 Precompute Processors

- [ ] **PSZA** (player_shot_zone_analysis_processor.py)
  - File: `data_processors/precompute/player_shot_zone_analysis/`
  - Key method: `_save_failures()` at line 1679
  - Has own implementation, not using base class

- [ ] **TDZA** (team_defense_zone_analysis_processor.py)
  - File: `data_processors/precompute/team_defense_zone_analysis/`
  - Key method: Uses `save_failures_to_bq()` from base

- [ ] **PCF** (player_composite_factors_processor.py)
  - File: `data_processors/precompute/player_composite_factors/`
  - Key method: Uses `save_failures_to_bq()` from base

- [ ] **PDC** (player_daily_cache_processor.py)
  - File: `data_processors/precompute/player_daily_cache/`
  - Key method: Uses `save_failures_to_bq()` from base
  - Note: Has multi-window completeness (most complex)

- [ ] **MLFS** (ml_feature_store_processor.py)
  - File: `data_processors/precompute/ml_feature_store/`
  - Key method: Uses `save_failures_to_bq()` from base

### Phase 3 Analytics Processors

- [ ] **PGS** (player_game_summary_processor.py)
  - File: `data_processors/analytics/player_game_summary/`
  - Currently uses: `registry_failures` table
  - Needs: Integration with `analytics_failures` table

- [ ] **TDGS** (team_defense_game_summary_processor.py)
  - File: `data_processors/analytics/team_defense_game_summary/`
  - Currently uses: Quality issues logging
  - Needs: Integration with `analytics_failures` table

---

## Related Sessions

- **Session 86-87**: Initial enhanced failure tracking design
- **Session 88**: Schema applied to BigQuery, Oct 2021 backfills
- **Session 89** (this): Schema consolidation, processor review

---

## Commands to Start Next Session

```bash
# 1. Verify no backfills are running
ps aux | grep -E "backfill|processor" | grep python | grep -v grep

# 2. Check current schema
bq show --schema --format=prettyjson nba-props-platform:nba_processing.precompute_failures | head -50

# 3. Read the project doc
cat docs/08-projects/current/processor-optimization/enhanced-failure-tracking.md

# 4. Start implementation from base class
code data_processors/precompute/precompute_base.py +1560
```

---

## Success Criteria

1. All Phase 4 processors populate `failure_type`, `is_correctable` fields
2. Phase 3 processors write to `analytics_failures` table
3. DNP detection correctly distinguishes player didn't play vs missing data
4. Resolution tracking enables marking failures as resolved
