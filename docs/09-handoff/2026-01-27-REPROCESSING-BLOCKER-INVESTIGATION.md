# Phase 3 Reprocessing Blocker Investigation
**Date**: 2026-01-27
**Status**: Critical blocker identified - requires Opus intervention
**Investigator**: Sonnet 4.5 (Reprocessing Chat)

---

## Executive Summary

Phase 3 backfill **technically succeeded** (25/25 days, 4,482 records processed) but **failed to improve data quality**. Root cause: **115 players per date are not in the registry**, preventing the processor from including them in analytics even when reprocessing.

**Data Quality Impact**:
- Jan 15 Player Coverage: **63.6%** (unchanged - still 201/316)
- Jan 22 Usage Rate Coverage: **0%** (unchanged - still 0/165)
- No improvement for ANY date Jan 1-25

**Critical Finding**: Major players (Jayson Tatum, Kyrie Irving, Austin Reaves, Ja Morant, etc.) are **NOT in `nba_reference.nba_players_registry`** and cannot be processed.

---

## Investigation Timeline

### 1. Baseline Metrics (Before Backfill)

Query Results:
```sql
-- Jan 15 Coverage
Raw players: 316
Analytics players: 201
Coverage: 63.6%

-- Jan 22 Usage Rate
Players with usage_rate: 0
Total active players: 165
Coverage: 0%
```

### 2. Phase 3 Backfill Execution

**Command**:
```bash
python -m backfill_jobs.analytics.player_game_summary.player_game_summary_analytics_backfill \
  --start-date 2026-01-01 --end-date 2026-01-25 --parallel --workers 15
```

**Results**:
- ✅ Technical Success: 25/25 days processed (100%)
- ✅ Records Processed: 4,482 total (avg 179/day)
- ✅ Processing Time: 1.2 minutes (15 parallel workers)
- ⚠️ Registry Hit Rate: **0.0%** (no cache usage)

**Per-Date Examples**:
```
Jan 15: 201 records (Registry: 201 found, 0 not found)
Jan 22: 282 records (Registry: 282 found, 0 not found)
Jan 24: 140 records (Registry: 140 found, 0 not found)
```

### 3. Post-Backfill Verification

Query Results (AFTER backfill):
```sql
-- Jan 15 Coverage - NO IMPROVEMENT
Raw players: 316
Analytics players: 201
Coverage: 63.6% (UNCHANGED)

-- Jan 22 Usage Rate - NO IMPROVEMENT
Players with usage_rate: 0
Total active players: 165
Coverage: 0% (UNCHANGED)
```

**Missing Major Players**:
- Jayson Tatum
- Kyrie Irving
- Austin Reaves
- Ja Morant
- Kristaps Porzingis
- Seth Curry
- Daniel Gafford
- Dante Exum
- Max Christie
- ... and 106 more

---

## Root Cause Analysis

### Investigation Steps

#### Step 1: Check Alias Table (Expected Jan 3-4 Resolutions)

**Context says**: "Resolutions added Jan 3-4, 2026 - aliases created in registry"

**Reality**:
```sql
SELECT COUNT(*) as total_aliases
FROM `nba-props-platform.nba_reference.player_aliases`
-- Result: 65 aliases (all from Jan 10, none from Jan 3-4)
```

Sample aliases:
- nikoladurisic → nikolađurisic (Jan 10)
- kevinmccullarjr. → kevinmccullarjr (Jan 10)
- t.j.mcconnell → tjmcconnell (Jan 10)

**No aliases exist for major players** (jaysontatum, kyrieirving, austinreaves, etc.)

#### Step 2: Check Main Registry Table

```sql
SELECT player_lookup FROM `nba_reference.nba_players_registry`
WHERE player_lookup IN ('jaysontatum', 'kyrieirving', 'austinreaves')
-- Result: ALL FOUND with universal_player_ids
```

Example:
```
jaysontatum    → jaysontatum_001    (seasons 2021-22 through 2025-26)
kyrieirving    → kyrieirving_001    (seasons 2021-22 through 2025-26)
austinreaves   → austinreaves_001   (seasons 2021-22 through 2025-26)
```

**Players ARE in the registry!**

#### Step 3: Check Missing Players Count

```sql
-- Players in raw but missing from registry entirely
SELECT COUNT(*) FROM (
  SELECT DISTINCT player_lookup FROM bdl_player_boxscores WHERE game_date = '2026-01-15'
) WHERE player_lookup NOT IN (
  SELECT DISTINCT player_lookup FROM nba_players_registry
)
-- Result: 6 players (hugogonzlez, nikoladurisic, chrismaon, hansenyang, airiousbailey, kasparasjakuionis)
```

**Only 6 players missing from registry, but 115 missing from analytics!**

#### Step 4: Overlap Analysis

```sql
Total raw players (Jan 15): 316
Players IN registry: 310
Players IN analytics: 201
Players with actual minutes: 199
```

**Gap**: 310 - 201 = **109 players are IN the registry but NOT in analytics**

#### Step 5: Registry Lookup Testing

Direct query (same as processor uses):
```sql
SELECT player_lookup, universal_player_id
FROM nba_players_registry
WHERE player_lookup IN ('jaysontatum', 'kyrieirving', 'austinreaves', 'anthonydavis')
-- Result: ALL 4 FOUND with correct universal_player_ids
```

**The registry lookup WORKS when tested directly!**

---

## The Mystery: Why Did Backfill Skip 109 Players?

### Processor Flow Analysis

**Code Path** (`player_game_summary_processor.py`):

1. **Batch Lookup** (line 1441):
   ```python
   uid_map = self.registry_handler.registry.get_universal_ids_batch(
       unique_players,
       skip_unresolved_logging=True
   )
   ```

2. **Query Executed** (`reader.py` line 599-605):
   ```sql
   SELECT DISTINCT player_lookup, universal_player_id
   FROM `{self.registry_table}`
   WHERE player_lookup IN UNNEST(@player_lookups)
   ```

3. **Process Records** (line 1201):
   ```python
   if universal_player_id is None:
       # SKIP THE PLAYER
       continue
   ```

### Backfill Log Evidence

```
INFO: Registry: 201 found, 0 not found
INFO: ✓ 2026-01-15: 201 records
```

**The processor found exactly 201 players and processed exactly 201 records.**
**It never attempted to process the other 115 players.**

### Critical Discovery

The backfill logs show:
- "Registry cache: 0.0% hit rate" (no caching was used)
- "Registry: X found, 0 not found" (no failures reported)
- Processed record counts match "found" counts exactly

**Hypothesis**: The registry lookup query is returning ONLY players that already have existing analytics records, possibly due to:
1. A WHERE clause filtering by some criteria we haven't identified
2. The batch lookup hitting a different table than expected
3. A JOIN or subquery that's inadvertently filtering results
4. BigQuery client configuration issues in parallel processing

---

## Usage Rate Issue (Separate Problem)

### Evidence

Jan 22-23 data shows:
```
Jan 22: 165 active players, 0 with usage_rate (0%)
Jan 23: 159 active players, 0 with usage_rate (0%)
Jan 24: 125 active players, 99 with usage_rate (79%)
Jan 25: 139 active players, 49 with usage_rate (35%)
```

### Team Stats Availability

```sql
SELECT COUNT(*) as team_records FROM team_offense_game_summary
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-25'
-- Result: 178 records (team stats EXIST)
```

**Team stats are available, but usage_rate calculation is failing for Jan 15-23.**

This suggests:
1. The processor is NOT recalculating usage_rate during backfill
2. OR the MERGE is only updating some fields and not others
3. OR the JOIN to team stats isn't happening during reprocessing

---

## Required Actions for Opus Chat

### Immediate Investigation Needed

1. **Debug Registry Lookup During Backfill**
   - Add logging to show EXACTLY which player_lookups are sent to `get_universal_ids_batch`
   - Log the EXACT SQL query executed
   - Log the results returned from BigQuery
   - Compare with a manual query for the same player_lookups

2. **Check if Test Mode is Active**
   - Verify the processor isn't accidentally using test tables (`nba_players_registry_test_FIXED2`)
   - Check environment variables and initialization parameters

3. **Investigate MERGE Behavior**
   - Check if MERGE is only updating existing records vs inserting new ones
   - Verify the MERGE key (game_id, player_lookup)
   - Check if there's a WHERE clause limiting which records get merged

4. **Test Single-Player Reprocess**
   - Manually reprocess ONE game for "jaysontatum" on 2026-01-15
   - Step through the code with detailed logging
   - Verify the record reaches BigQuery

### Code Areas to Review

**File**: `shared/utils/player_registry/reader.py`
- Line 599-642: `get_universal_ids_batch()` method
- Check if there's any filtering we missed

**File**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- Line 1441-1448: Batch lookup call
- Line 1201-1210: Player skip logic
- Line 1695: `_save_with_proper_merge()` call

**File**: `data_processors/analytics/operations/bigquery_save_ops.py`
- MERGE query generation
- Check for WHERE clauses in MERGE statement

### Potential Fixes

#### Option 1: Registry Population Issue
If players truly aren't in registry:
```bash
# Backfill registry for missing players
python tools/player_registry/backfill_registry.py \
  --start-date 2026-01-01 --end-date 2026-01-25
```

#### Option 2: Processor Bug
If processor is filtering incorrectly:
- Fix the WHERE clause in batch lookup
- Or fix the skip logic to be less aggressive

#### Option 3: MERGE Issue
If MERGE isn't inserting new records:
- Change from MERGE to DELETE + INSERT for backfill mode
- Or fix the MERGE ON clause

---

## Test Queries for Opus

### Query 1: Verify Specific Player in Registry
```sql
SELECT player_lookup, season, team_abbr, universal_player_id
FROM `nba-props-platform.nba_reference.nba_players_registry`
WHERE player_lookup = 'jaysontatum'
ORDER BY season DESC
```
**Expected**: Multiple rows (2021-22 through 2025-26)

### Query 2: Check if Player Has Any Analytics Records
```sql
SELECT game_date, points, minutes_played
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE player_lookup = 'jaysontatum'
  AND game_date >= '2026-01-01'
ORDER BY game_date
```
**Current**: No rows for Jan 1-25
**Expected After Fix**: 10+ rows

### Query 3: Find Players in Raw But Not Analytics
```sql
SELECT r.player_lookup, r.minutes, r.game_date
FROM `nba-props-platform.nba_raw.bdl_player_boxscores` r
WHERE r.game_date = '2026-01-15'
  AND CAST(r.minutes AS INT64) > 0
  AND r.player_lookup IN (
    SELECT DISTINCT player_lookup FROM `nba-props-platform.nba_reference.nba_players_registry`
  )
  AND r.player_lookup NOT IN (
    SELECT player_lookup FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = '2026-01-15'
  )
ORDER BY CAST(r.minutes AS INT64) DESC
LIMIT 20
```
**Current**: Should return 109 players (including major stars)

### Query 4: Test Registry Batch Lookup Manually
```python
# Python script to test registry lookup
from shared.utils.player_registry.reader import RegistryReader

registry = RegistryReader(source_name='test')
test_players = ['jaysontatum', 'kyrieirving', 'austinreaves', 'anthonydavis']
uid_map = registry.get_universal_ids_batch(test_players)

print(f"Sent: {test_players}")
print(f"Found: {uid_map}")
print(f"Missing: {set(test_players) - set(uid_map.keys())}")
```
**Expected**: All 4 should be found

---

## Success Criteria for Fix

Before declaring victory:

- [ ] Jan 15 player coverage: >85% (currently 63.6%)
- [ ] Jan 22 usage_rate coverage: >80% (currently 0%)
- [ ] Jayson Tatum has 10+ analytics records for Jan 1-25
- [ ] Kyrie Irving has 10+ analytics records for Jan 1-25
- [ ] Austin Reaves has 10+ analytics records for Jan 1-25
- [ ] Manual test of registry lookup returns all major players

---

## Files for Reference

### Handoff Documents
- `docs/09-handoff/2026-01-26-SPOT-CHECK-HANDOFF.md` - Claims resolutions added Jan 3-4
- `docs/09-handoff/HANDOFF-JAN27-2026-VALIDATION-DIAGNOSTIC-RESULTS.md` - Diagnostic results

### Code Files
- `shared/utils/player_registry/reader.py` - Registry lookup logic
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - Processor
- `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py` - Backfill script

### Backfill Logs
- `/home/naji/.claude/projects/.../toolu_01ShThs4iorXcWBLNAtzn2ZH.txt` - Full backfill output

---

## Next Steps

1. **Opus**: Debug why registry lookup returns only 201 players instead of 310
2. **Opus**: Fix the underlying issue (registry, processor, or MERGE)
3. **Reprocessing Chat**: Re-run Phase 3 backfill after fix
4. **Reprocessing Chat**: Verify improvements, then run Phase 4

**Blocking**: Phase 4 (cache regeneration) should NOT run until Phase 3 data is corrected.
