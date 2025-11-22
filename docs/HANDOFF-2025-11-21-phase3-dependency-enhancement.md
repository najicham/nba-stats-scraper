# Session Handoff: Phase 3 Dependency Checking Enhanced

**Date**: 2025-11-21 (Session 2)
**Session Type**: Phase 3 Dependency Enhancement
**Status**: ✅ Complete - Hash Tracking + Historical Backfill Support Added
**Previous Session**: Smart Idempotency Implementation (22/22 Phase 2 processors)

---

## 📋 Executive Summary

This session enhanced Phase 3 dependency checking infrastructure to support:

1. **Hash Tracking Integration**: Phase 3 now tracks `data_hash` from all Phase 2 sources (smart idempotency integration)
2. **Historical Backfill Detection**: New method to find games that have Phase 2 data but are missing Phase 3 analytics
3. **Complete Implementation**: player_game_summary processor fully implements the enhanced pattern

### Key Metrics

- **Base Class Methods Enhanced**: 3 (check_table_data, track_source_usage, build_source_tracking_fields)
- **New Methods Added**: 1 (find_backfill_candidates)
- **Tracking Fields Per Source**: 4 (was 3, added hash)
- **Example Processor**: player_game_summary (6 sources × 4 fields = 24 tracking fields)
- **Tests Created**: 3 (field count, hash tracking, backfill detection)
- **Test Status**: ✅ All passing

---

## ✅ Completed Work

### 1. Enhanced Base Class (`analytics_base.py`)

#### A. Hash Tracking in `_check_table_data()`

**File**: `data_processors/analytics/analytics_base.py:415-507`

**Enhancement**: Query now extracts `data_hash` from Phase 2 tables

```python
# BEFORE (3 fields queried)
query = f"""
SELECT
    COUNT(*) as row_count,
    MAX(processed_at) as last_updated
FROM `{self.project_id}.{table_name}`
WHERE {date_field} BETWEEN '{start_date}' AND '{end_date}'
"""

# AFTER (4 fields queried - added data_hash)
query = f"""
SELECT
    COUNT(*) as row_count,
    MAX(processed_at) as last_updated,
    ARRAY_AGG(data_hash IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
FROM `{self.project_id}.{table_name}`
WHERE {date_field} BETWEEN '{start_date}' AND '{end_date}'
"""
```

**Why**: Enables Phase 3 to track upstream data changes via Phase 2 smart idempotency hashes

#### B. Hash Storage in `track_source_usage()`

**File**: `data_processors/analytics/analytics_base.py:509-559`

**Enhancement**: Stores `data_hash` as 4th field per source

```python
# BEFORE (3 attributes per source)
setattr(self, f'{prefix}_last_updated', dep_result.get('last_updated'))
setattr(self, f'{prefix}_rows_found', row_count)
setattr(self, f'{prefix}_completeness_pct', round(completeness_pct, 2))

# AFTER (4 attributes per source - added hash)
setattr(self, f'{prefix}_last_updated', dep_result.get('last_updated'))
setattr(self, f'{prefix}_rows_found', row_count)
setattr(self, f'{prefix}_completeness_pct', round(completeness_pct, 2))
setattr(self, f'{prefix}_hash', data_hash)  # NEW
```

**Why**: Makes hash available to processors for change detection logic

#### C. Hash Output in `build_source_tracking_fields()`

**File**: `data_processors/analytics/analytics_base.py:561-585`

**Enhancement**: Includes hash in output records

```python
# BEFORE (3 fields per source in output)
for table_name, config in self.get_dependencies().items():
    prefix = config['field_prefix']
    fields[f'{prefix}_last_updated'] = getattr(self, f'{prefix}_last_updated', None)
    fields[f'{prefix}_rows_found'] = getattr(self, f'{prefix}_rows_found', None)
    fields[f'{prefix}_completeness_pct'] = getattr(self, f'{prefix}_completeness_pct', None)

# AFTER (4 fields per source in output - added hash)
for table_name, config in self.get_dependencies().items():
    prefix = config['field_prefix']
    fields[f'{prefix}_last_updated'] = getattr(self, f'{prefix}_last_updated', None)
    fields[f'{prefix}_rows_found'] = getattr(self, f'{prefix}_rows_found', None)
    fields[f'{prefix}_completeness_pct'] = getattr(self, f'{prefix}_completeness_pct', None)
    fields[f'{prefix}_hash'] = getattr(self, f'{prefix}_hash', None)  # NEW
```

**Why**: Persists hash to Phase 3 tables for historical tracking and debugging

#### D. New Method: `find_backfill_candidates()`

**File**: `data_processors/analytics/analytics_base.py:587-696`

**Purpose**: Find games with Phase 2 data but missing Phase 3 analytics

**Signature**:
```python
def find_backfill_candidates(self, lookback_days: int = 30,
                             primary_source_only: bool = True) -> List[Dict]:
```

**Returns**: List of games needing processing
```python
[
    {
        'game_date': '2025-11-15',
        'game_id': '20251115_BKN_MIL',
        'phase2_last_updated': '2025-11-16T08:30:00',
        'phase2_row_count': 28
    },
    # ... more games
]
```

**Query Pattern** (from dependency docs):
```sql
SELECT DISTINCT
    p2.game_date,
    p2.game_id,
    MAX(p2.processed_at) as phase2_last_updated,
    COUNT(*) as phase2_row_count
FROM `nba_raw.{source_table}` p2
LEFT JOIN `nba_analytics.{phase3_table}` p3
    ON p2.game_id = p3.game_id
    AND p2.game_date = p3.game_date
WHERE p3.game_id IS NULL  -- Phase 3 doesn't exist yet
    AND p2.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
    AND p2.game_date < CURRENT_DATE()
GROUP BY p2.game_date, p2.game_id
ORDER BY p2.game_date ASC
```

**Why**: Implements historical backfill awareness pattern from dependency documentation

---

### 2. Test Suite Created

**File**: `tests/unit/patterns/test_historical_backfill_detection.py`

**Tests**:
1. ✅ **Source Tracking Field Count**: Validates 6 sources × 4 fields = 24 tracking fields
2. ✅ **Hash Tracking**: Validates data_hash is queried and stored from Phase 2 sources
3. ✅ **Backfill Detection**: Validates find_backfill_candidates() method works

**Test Results**:
```
✅ PASSED: Source Tracking Field Count
✅ PASSED: Hash Tracking
✅ PASSED: Backfill Detection
🎉 ALL TESTS PASSED
```

**Usage**:
```bash
python tests/unit/patterns/test_historical_backfill_detection.py
```

---

### 3. Processor Implementation Status

#### player_game_summary ✅ COMPLETE

**File**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Dependencies Configured**: 6 Phase 2 sources
- ✅ `nba_raw.nbac_gamebook_player_stats` (PRIMARY - critical)
- ✅ `nba_raw.bdl_player_boxscores` (FALLBACK - critical)
- ✅ `nba_raw.bigdataball_play_by_play` (optional)
- ✅ `nba_raw.nbac_play_by_play` (optional)
- ✅ `nba_raw.odds_api_player_points_props` (optional)
- ✅ `nba_raw.bettingpros_player_points_props` (optional)

**Tracking Fields**: 24 (6 sources × 4 fields each)

**get_dependencies() Implementation**: Lines 125-202
**Uses base class methods**: check_dependencies(), track_source_usage(), build_source_tracking_fields()

**Hash tracking**: ✅ Working (via base class enhancement)
**Backfill detection**: ✅ Available (via base class method)

#### Other Phase 3 Processors

**Status**: Can use enhanced base class immediately (no changes needed)

- `upcoming_player_game_context_processor.py` - ready to use
- `team_offense_game_summary_processor.py` - ready to use
- `team_defense_game_summary_processor.py` - ready to use
- `upcoming_team_game_context_processor.py` - ready to use

---

## 🎯 Expected Impact

### Smart Idempotency Integration

**Before Enhancement**:
- Phase 3 had no visibility into Phase 2 data changes
- Reprocessed all games even if Phase 2 data unchanged
- No way to detect if dependencies were stale

**After Enhancement**:
- Phase 3 tracks `data_hash` from Phase 2 sources
- Can detect when Phase 2 data changed (future enhancement)
- Enables smart reprocessing: only process when Phase 2 data changes

**Future Optimization**:
```python
# Phase 3 can now check if Phase 2 data changed
if phase3_record.source_nbac_hash == current_phase2_hash:
    logger.info("Phase 2 data unchanged, skipping reprocessing")
    return  # Skip processing
```

### Historical Backfill Support

**Before Enhancement**:
- No automatic detection of backfilled games
- Manual queries needed to find missing Phase 3 data
- Risk of missing historical games

**After Enhancement**:
- `find_backfill_candidates()` automatically detects gaps
- Can be run as daily/weekly maintenance job
- Ensures all Phase 2 data gets processed

**Example Usage**:
```python
# Daily maintenance job
processor = PlayerGameSummaryProcessor()
candidates = processor.find_backfill_candidates(lookback_days=7)

for game in candidates:
    logger.info(f"Processing backfilled game: {game['game_date']} - {game['game_id']}")
    processor.run({
        'start_date': game['game_date'],
        'end_date': game['game_date']
    })
```

---

## 📂 Files Modified

### Enhanced (3 files)

```
data_processors/analytics/
└── analytics_base.py (3 methods enhanced, 1 method added)
    ├── _check_table_data()          (enhanced: +hash query)
    ├── track_source_usage()         (enhanced: +hash storage)
    ├── build_source_tracking_fields() (enhanced: +hash output)
    └── find_backfill_candidates()   (NEW)
```

### Created (2 files)

```
tests/unit/patterns/
└── test_historical_backfill_detection.py (NEW - 3 tests)

docs/
└── HANDOFF-2025-11-21-phase3-dependency-enhancement.md (THIS FILE)
```

### Already Complete (no changes needed)

```
data_processors/analytics/player_game_summary/
└── player_game_summary_processor.py
    └── get_dependencies() already defined (lines 125-202)
```

---

## 🚫 Known Issues / Limitations

### 1. Some Phase 2 Tables Missing `processed_at` Column

**Issue**: `odds_api_player_points_props` table query failed with:
```
Unrecognized name: processed_at at [4:25]
```

**Impact**: Hash tracking query fails for this specific table

**Workaround**: Code gracefully handles this by setting hash to None

**Resolution Needed**: Add `processed_at` column to Phase 2 tables that are missing it

**Tables to Check**:
- ✅ `nbac_gamebook_player_stats` - has processed_at
- ✅ `bdl_player_boxscores` - has processed_at
- ❓ `odds_api_player_points_props` - MISSING processed_at
- ❓ `bettingpros_player_points_props` - needs verification
- ❓ Other Phase 2 tables - needs verification

### 2. Some Phase 2 Tables Missing `data_hash` Column

**Issue**: Not all Phase 2 tables have smart idempotency implemented

**Impact**: Hash field will be NULL for these sources

**Resolution**: Previous session implemented smart idempotency for 22/22 Phase 2 processors, but schemas may not be deployed

**Action Required**: Deploy updated Phase 2 schemas with `data_hash` column (see next section)

### 3. Phase 3 Schemas May Not Be Deployed

**Issue**: BigQuery tables may not exist or may be missing new hash tracking fields

**Impact**: Processors will fail at runtime when trying to write hash fields

**Resolution Needed**: Deploy Phase 3 schemas (see next section)

---

## 🔧 Schema Deployment Required

### Phase 2 Schemas (Smart Idempotency)

**Status**: ⚠️ Implemented in code, deployment status unknown

**What to Deploy**:
```bash
# All Phase 2 raw table schemas should have data_hash column
schemas/bigquery/raw/*.sql

# Example fields that should exist:
processed_at TIMESTAMP,
data_hash STRING,  # Added by smart idempotency
```

**How to Check**:
```bash
# Check if data_hash column exists in Phase 2 tables
bq show --schema --format=prettyjson nba-props-platform:nba_raw.bdl_player_boxscores | grep data_hash
```

**How to Deploy**:
```bash
# Apply schema updates (requires bq command-line tool)
for schema_file in schemas/bigquery/raw/*.sql; do
    echo "Deploying $schema_file..."
    bq query --use_legacy_sql=false < $schema_file
done
```

### Phase 3 Schemas (Hash Tracking)

**Status**: ⚠️ Schema files have hash fields, deployment status unknown

**What to Deploy**:
```bash
# Phase 3 analytics table schemas with 4 fields per source
schemas/bigquery/analytics/player_game_summary_tables.sql
schemas/bigquery/analytics/upcoming_player_game_context_tables.sql
schemas/bigquery/analytics/team_offense_game_summary_tables.sql
schemas/bigquery/analytics/team_defense_game_summary_tables.sql
schemas/bigquery/analytics/upcoming_team_game_context_tables.sql
```

**How to Check**:
```bash
# Check if hash columns exist in Phase 3 tables
bq show --schema --format=prettyjson nba-props-platform:nba_analytics.player_game_summary | grep "_hash"
```

**How to Deploy**:
```bash
# Apply schema updates
for schema_file in schemas/bigquery/analytics/*_tables.sql; do
    echo "Deploying $schema_file..."
    bq query --use_legacy_sql=false < $schema_file
done
```

### Phase 4 & 5 Schemas

**Status**: ⚠️ Unknown - may also need hash tracking fields

**Action Required**: Review and deploy if needed

---

## 🔄 Next Steps (Priority Order)

### Immediate (This Session or Next)

1. **✅ DONE: Enhance base class for hash tracking**
2. **✅ DONE: Add historical backfill detection**
3. **✅ DONE: Test implementation**
4. **🔲 TODO: Deploy Phase 2 schemas** (ensure data_hash column exists)
5. **🔲 TODO: Deploy Phase 3 schemas** (ensure hash tracking fields exist)
6. **🔲 TODO: Verify Phase 4-5 schemas**

### Short-Term (Next 1-2 Sessions)

7. **Test with Real Data** (High Priority)
   - Run player_game_summary with actual date ranges
   - Verify hash tracking populates correctly
   - Test find_backfill_candidates() on production data

8. **Create Maintenance Job** (Medium Priority)
   - Daily cron job to find and process backfill candidates
   - Notification when backfill candidates found
   - Dashboard showing backfill queue size

9. **Document Remaining Processors** (Medium Priority)
   - Fill in docs/dependency-checks/02-analytics-processors.md
   - Add examples for other 4 Phase 3 processors
   - Update Phase 4-5 documentation as needed

### Medium-Term (Next Week)

10. **Implement Smart Reprocessing** (High Value)
    - Skip Phase 3 processing when Phase 2 hash unchanged
    - Measure performance improvement
    - Document skip rate metrics

11. **Add Monitoring Dashboard** (High Value)
    - Track hash tracking coverage per source
    - Monitor backfill queue depth
    - Alert on missing dependencies

---

## 📖 Reference Documentation

### Key Patterns Implemented

**Pattern 1: Hash Tracking (Phase 3 + Phase 2 Integration)**
- Location: `analytics_base.py:415-585`
- Documentation: This handoff document
- Example: player_game_summary (6 sources × hash tracking)

**Pattern 2: Historical Backfill Detection**
- Location: `analytics_base.py:587-696`
- Documentation: `docs/dependency-checks/00-overview.md` lines 218-264
- Query example: Lines 651-666 in analytics_base.py

**Pattern 3: Dependency Check Function (Phase 3)**
- Location: `analytics_base.py:319-413`
- Documentation: `docs/dependency-checks/00-overview.md` lines 269-293
- Returns: Dict with all_critical_present, details, stale checks

---

## 🤝 Handoff Checklist

- ✅ Hash tracking implemented in base class (4 fields per source)
- ✅ Historical backfill detection method added
- ✅ Test suite created and passing
- ✅ player_game_summary processor fully configured
- ✅ Documentation created (this handoff + test file)
- ⚠️ Phase 2 schemas need deployment verification
- ⚠️ Phase 3 schemas need deployment verification
- ⏳ Other 4 Phase 3 processors ready but not documented
- ⏳ Smart reprocessing logic not yet implemented (future enhancement)

---

## 💡 Tips for Next Developer

1. **Start with Schema Deployment**: Before running any processors, ensure all schemas are deployed with hash tracking fields

2. **Test with Real Data**: Use a recent date (yesterday) to test dependency checking and hash tracking

3. **Monitor Query Costs**: The hash tracking queries use ARRAY_AGG which may be expensive on large tables

4. **Graceful Degradation**: Code handles missing `processed_at` and `data_hash` columns gracefully (sets to NULL)

5. **Use find_backfill_candidates()**: Great for maintenance jobs and ensuring complete data coverage

6. **Documentation Pattern**: Use player_game_summary as template for documenting other Phase 3 processors

---

## 📞 Questions?

- **Hash Tracking Pattern**: See `analytics_base.py:415-585`
- **Backfill Detection**: See `analytics_base.py:587-696`
- **Phase 3 Examples**: See `player_game_summary_processor.py:125-202`
- **Testing**: See `tests/unit/patterns/test_historical_backfill_detection.py`
- **Dependency Docs**: See `docs/dependency-checks/00-overview.md`

---

**Session End**: 2025-11-21
**Status**: ✅ Ready for schema deployment + testing
**Next Developer**: Deploy schemas, then test with real data
