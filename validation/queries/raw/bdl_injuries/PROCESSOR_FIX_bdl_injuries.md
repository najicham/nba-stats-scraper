# BDL Injuries Processor - Fix Specification

## 🐛 Issue Summary

**Problem:** BdlInjuriesProcessor inserts duplicate records during a single processing run.

**Evidence:**
- August 22, 2025 test data shows 230 records for 115 unique players
- All duplicates have identical timestamps: `2025-08-22 00:57:28+00`
- All duplicates from same source file (1 unique file)
- **Every single player** inserted exactly twice

**Impact:**
- Test data has 100% duplication rate
- Will occur in production if not fixed
- Wastes storage (2x records)
- Complicates queries (need COUNT DISTINCT everywhere)

---

## 🎯 Required Changes

### Change 1: Switch from APPEND_ALWAYS to MERGE_UPDATE

**Current Strategy:**
```python
class BdlInjuriesProcessor(BaseProcessor):
    def __init__(self):
        super().__init__()
        self.processing_strategy = ProcessingStrategy.APPEND_ALWAYS
```

**New Strategy:**
```python
class BdlInjuriesProcessor(BaseProcessor):
    def __init__(self):
        super().__init__()
        self.processing_strategy = ProcessingStrategy.MERGE_UPDATE
```

**Rationale:**
- BDL Injuries is a **daily snapshot** (current state, not historical)
- Each scrape_date should have exactly ONE record per player
- MERGE_UPDATE will replace existing date data if reprocessed
- Matches pattern of other current-state tables (e.g., `bdl_active_players_current`, `nbac_player_list_current`)

---

### Change 2: Implement Date-Level Deduplication

**Add DELETE Logic Before Insert:**

```python
def delete_existing_data(self, records: List[Dict]) -> None:
    """
    Delete existing records for the same scrape_date before inserting new data.
    This ensures reprocessing the same date doesn't create duplicates.
    """
    if not records:
        return
    
    # Get unique scrape_dates from records
    scrape_dates = set(record['scrape_date'] for record in records)
    
    for scrape_date in scrape_dates:
        delete_query = f"""
        DELETE FROM `{self.project_id}.{self.dataset}.{self.table}`
        WHERE scrape_date = '{scrape_date}'
        """
        
        self.logger.info(f"Deleting existing data for scrape_date: {scrape_date}")
        
        try:
            query_job = self.bq_client.query(delete_query)
            query_job.result()  # Wait for completion
            
            self.logger.info(f"Successfully deleted existing data for {scrape_date}")
        except Exception as e:
            self.logger.error(f"Error deleting data for {scrape_date}: {e}")
            raise
```

**Call DELETE Before Insert:**

```python
def insert_to_bigquery(self, records: List[Dict]) -> None:
    """Insert records to BigQuery after deleting existing date data."""
    if not records:
        self.logger.warning("No records to insert")
        return
    
    # Delete existing data for these dates first
    self.delete_existing_data(records)
    
    # Then insert new data
    super().insert_to_bigquery(records)
```

---

### Change 3: Add In-Memory Deduplication (Safety Check)

Even with MERGE_UPDATE, add deduplication within a single processing run:

```python
def deduplicate_records(self, records: List[Dict]) -> List[Dict]:
    """
    Remove duplicate records within the same batch.
    Keep the first occurrence of each (scrape_date, bdl_player_id) combination.
    """
    seen_keys = set()
    deduplicated = []
    
    for record in records:
        key = (record['scrape_date'], record['bdl_player_id'])
        
        if key not in seen_keys:
            seen_keys.add(key)
            deduplicated.append(record)
        else:
            self.logger.warning(
                f"Duplicate detected: {record['player_full_name']} on {record['scrape_date']} - skipping"
            )
    
    original_count = len(records)
    final_count = len(deduplicated)
    
    if original_count != final_count:
        self.logger.warning(
            f"Deduplication: {original_count} → {final_count} records "
            f"({original_count - final_count} duplicates removed)"
        )
    
    return deduplicated

def process_file(self, file_path: str) -> List[Dict]:
    """Process a single file and return deduplicated records."""
    # ... existing file processing logic ...
    
    records = self.transform_records(raw_data)
    
    # Add deduplication before returning
    deduplicated_records = self.deduplicate_records(records)
    
    return deduplicated_records
```

---

### Change 4: Update Primary Key Definition

**Current Primary Key (Inferred):**
```python
# Unclear - likely allowing duplicates
# (scrape_date, bdl_player_id, scrape_timestamp) ?
```

**New Primary Key:**
```python
# Composite key for uniqueness
PRIMARY_KEY = ['scrape_date', 'bdl_player_id']
```

**Add Validation:**
```python
def validate_unique_key(self, records: List[Dict]) -> bool:
    """
    Validate that records have unique (scrape_date, bdl_player_id) combinations.
    """
    keys = [(r['scrape_date'], r['bdl_player_id']) for r in records]
    
    if len(keys) != len(set(keys)):
        self.logger.error(
            f"Duplicate keys detected! {len(keys)} records, {len(set(keys))} unique keys"
        )
        return False
    
    return True
```

---

## 📋 Implementation Checklist

### Code Changes
- [ ] Change `processing_strategy` from APPEND_ALWAYS to MERGE_UPDATE
- [ ] Implement `delete_existing_data()` method
- [ ] Implement `deduplicate_records()` method
- [ ] Update `insert_to_bigquery()` to call delete first
- [ ] Update `process_file()` to call deduplication
- [ ] Add `validate_unique_key()` validation
- [ ] Add logging for deduplication statistics

### Testing
- [ ] Test on August 22 data (currently duplicated)
- [ ] Verify result: 115 records (not 230)
- [ ] Test reprocessing same date multiple times
- [ ] Verify: No duplicates after reprocessing
- [ ] Test with multiple dates in single run
- [ ] Verify: Each date deduplicated independently

### Validation Queries
- [ ] Run `SELECT COUNT(*), COUNT(DISTINCT bdl_player_id)` - should match
- [ ] Run duplicate check query - should return 0 rows
- [ ] Run `./scripts/validate-bdl-injuries quality` - should pass
- [ ] Verify all validation queries work correctly

---

## 🔍 Root Cause Investigation

**Why did duplicates happen?**

Likely causes:
1. **JSON parsing issue** - Players array processed twice
2. **Loop bug** - Iterating over players twice  
3. **APPEND_ALWAYS + no deduplication** - Just inserts everything

**Check these in processor code:**
```python
# Look for something like this (WRONG):
for injury in data['injuries']:
    records.append(transform(injury))
for injury in data['injuries']:  # DUPLICATE LOOP!
    records.append(transform(injury))

# Or JSON structure parsed incorrectly:
# If BDL returns players nested in two different fields
injuries_1 = data.get('injuries', [])
injuries_2 = data.get('active_injuries', [])  # Same data, different key?
all_injuries = injuries_1 + injuries_2  # DUPLICATES!
```

---

## 📊 Expected Results After Fix

### Before Fix (Current)
```sql
SELECT 
  scrape_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT bdl_player_id) as unique_players
FROM `nba-props-platform.nba_raw.bdl_injuries`
WHERE scrape_date = '2025-08-22'
GROUP BY scrape_date;

-- Results:
-- scrape_date: 2025-08-22
-- total_records: 230
-- unique_players: 115
```

### After Fix (Expected)
```sql
SELECT 
  scrape_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT bdl_player_id) as unique_players
FROM `nba-props-platform.nba_raw.bdl_injuries`
WHERE scrape_date = '2025-08-22'
GROUP BY scrape_date;

-- Results:
-- scrape_date: 2025-08-22
-- total_records: 115  ✅ Matches unique_players!
-- unique_players: 115
```

---

## 🚀 Deployment Steps

1. **Clean existing test data first:**
```bash
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = '2025-08-22'
  AND (scrape_date, bdl_player_id) IN (
    SELECT scrape_date, bdl_player_id
    FROM \`nba-props-platform.nba_raw.bdl_injuries\`
    WHERE scrape_date = '2025-08-22'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY scrape_date, bdl_player_id ORDER BY processed_at) > 1
  );
"
```

2. **Update processor code** with all changes above

3. **Reprocess August 22 test data:**
```bash
gcloud run jobs execute bdl-injuries-processor-backfill \
  --region=us-west2 \
  --args="--start-date=2025-08-22,--end-date=2025-08-22"
```

4. **Verify fix:**
```bash
# Should show 115 records, not 230
bq query --use_legacy_sql=false "
SELECT 
  scrape_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT bdl_player_id) as unique_players
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = '2025-08-22'
GROUP BY scrape_date;
"

# Should return 0 rows (no duplicates)
bq query --use_legacy_sql=false "
SELECT 
  scrape_date,
  bdl_player_id,
  player_full_name,
  COUNT(*) as count
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = '2025-08-22'
GROUP BY scrape_date, bdl_player_id, player_full_name
HAVING COUNT(*) > 1;
"
```

5. **Test reprocessing same date:**
```bash
# Run processor again on same date
gcloud run jobs execute bdl-injuries-processor-backfill \
  --region=us-west2 \
  --args="--start-date=2025-08-22,--end-date=2025-08-22"

# Verify still only 115 records (MERGE_UPDATE replaced, not appended)
```

---

## 📖 Reference Implementations

**Similar Processors Using MERGE_UPDATE:**

### 1. BdlActivePlayersProcessor
```python
class BdlActivePlayersProcessor(BaseProcessor):
    def __init__(self):
        super().__init__()
        self.processing_strategy = ProcessingStrategy.MERGE_UPDATE  # ✅
        # Current state snapshot - replaces daily data
```

### 2. NbacPlayerListProcessor
```python
class NbacPlayerListProcessor(BaseProcessor):
    def __init__(self):
        super().__init__()
        self.processing_strategy = ProcessingStrategy.MERGE_UPDATE  # ✅
        # Current roster - replaces all data daily
```

### 3. BdlStandingsProcessor
```python
class BdlStandingsProcessor(BaseProcessor):
    def __init__(self):
        super().__init__()
        self.processing_strategy = ProcessingStrategy.MERGE_UPDATE  # ✅
        # Daily standings snapshot - replaces date data
```

**Pattern:** All "current state" tables use MERGE_UPDATE, not APPEND_ALWAYS.

---

## ⚠️ Important Notes

### When to Use APPEND_ALWAYS vs MERGE_UPDATE

**APPEND_ALWAYS (Preserve History):**
- ✅ Line movement tracking (odds_api_player_points_props)
- ✅ Multiple snapshots per game/day (nbac_injury_report - hourly)
- ✅ Historical audit trail needed
- ✅ Every scrape is valuable historical data

**MERGE_UPDATE (Current State):**
- ✅ Daily snapshots (bdl_injuries - one per day) ← **THIS ONE**
- ✅ Current rosters (nbac_player_list_current)
- ✅ Current standings (bdl_standings)
- ✅ Latest snapshot only matters

**BDL Injuries is current state** - only care about who's injured TODAY, not historical injury progression.

---

## 🎯 Success Criteria

After implementing fix:

✅ **No duplicates:** `COUNT(*) = COUNT(DISTINCT bdl_player_id)` per date  
✅ **Reprocessing safe:** Running twice on same date = same record count  
✅ **Storage efficient:** ~115 records/day, not 230+  
✅ **Query simplification:** No need for COUNT DISTINCT everywhere  
✅ **Validation passing:** All validation queries work correctly  

---

## 📝 Questions for Implementation

1. **Check JSON structure:** Does BDL return players in multiple fields?
2. **Check parsing logic:** Are we looping over injuries twice?
3. **Check transformation:** Any duplication in transform_records()?
4. **Verify scrape_timestamp:** Should it be set once at batch level, not per record?

---

**Priority:** HIGH - Fix before NBA season starts (October 22, 2025)  
**Effort:** Medium - ~2-3 hours including testing  
**Risk:** Low - Pattern proven in other processors  
**Impact:** High - Prevents data bloat and query complexity

---

**Last Updated:** October 13, 2025  
**Status:** Specification Ready for Implementation  
**Target Completion:** Before Season Start (October 2025)
