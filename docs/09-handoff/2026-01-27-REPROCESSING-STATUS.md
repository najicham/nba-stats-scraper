# Reprocessing Status - Jan 27, 2026
**Chat**: Data Reprocessing (Sonnet 4.5)
**Status**: ⚠️ BLOCKED - Awaiting Opus Investigation

---

## Quick Status

### ✅ Completed
- [x] Baseline metrics captured
- [x] Phase 3 backfill executed (25/25 days, 4,482 records, 1.2 minutes)
- [x] Post-backfill verification
- [x] Root cause investigation

### ❌ Failed
- [ ] Data quality improvement (no change)
- [ ] Player coverage increase (stuck at 63.6%)
- [ ] Usage rate fix (still 0%)

### ⏸️ Blocked
- [ ] Phase 4 cache regeneration (waiting for Phase 3 fix)
- [ ] Final verification
- [ ] Success criteria validation

---

## Critical Issue

**Problem**: Backfill technically succeeded but didn't improve data quality.

**Root Cause**: 109 players per date are IN the registry but NOT being picked up by the backfill processor.

**Evidence**:
```
Jan 15 Breakdown:
- Raw players: 316
- In registry: 310
- Backfill processed: 201
- Gap: 109 players (34%)
```

**Missing Players Include**:
- Jayson Tatum (37 min)
- Kyrie Irving (34 min)
- Austin Reaves (29 min)
- Ja Morant (36 min)
- ... and 105 more

---

## What We Know

### Registry Lookup Mystery

**Direct Query Works**:
```sql
SELECT player_lookup, universal_player_id
FROM nba_players_registry
WHERE player_lookup = 'jaysontatum'
-- ✅ Returns: jaysontatum → jaysontatum_001
```

**But Processor Doesn't Find Them**:
```
Backfill Log for Jan 15:
  Registry: 201 found, 0 not found
  Processed: 201 records
  (Missing 109 players that ARE in registry!)
```

### Possible Causes

1. **Batch Lookup Issue**: `get_universal_ids_batch()` returning subset
2. **Test Mode Active**: Using wrong registry table
3. **MERGE Problem**: Only updating existing records, not inserting new ones
4. **Hidden Filter**: Some WHERE clause filtering results
5. **Thread Safety**: Parallel processing causing registry issues

---

## Required Actions (Opus Chat)

### 1. Debug Registry Batch Lookup

Add logging to show:
```python
# In get_universal_ids_batch()
logger.info(f"Query: {query}")
logger.info(f"Parameters: {chunk}")
logger.info(f"Results returned: {len(results)}")
logger.info(f"Players found: {results['player_lookup'].tolist()}")
```

### 2. Test Single Player

```python
# Test script
registry = RegistryReader(source_name='debug_test')
uid = registry.get_universal_id('jaysontatum')
print(f"Found: {uid}")  # Should be jaysontatum_001
```

### 3. Check MERGE Behavior

Review `_save_with_proper_merge()` to ensure it:
- ✅ Inserts new records (not just updates)
- ✅ Uses correct MERGE keys
- ✅ No WHERE clause limiting scope

### 4. Verify No Test Mode

```python
# Check in processor __init__
print(f"Registry table: {self.registry_handler.registry.registry_table}")
# Should be: nba-props-platform.nba_reference.nba_players_registry
# NOT: nba_players_registry_test_FIXED2
```

---

## Full Investigation

See: `docs/09-handoff/2026-01-27-REPROCESSING-BLOCKER-INVESTIGATION.md`

---

## Backfill Command (For Re-run After Fix)

```bash
cd /home/naji/code/nba-stats-scraper

# Phase 3: Player Game Summary Analytics
python -m backfill_jobs.analytics.player_game_summary.player_game_summary_analytics_backfill \
  --start-date 2026-01-01 --end-date 2026-01-25 \
  --parallel --workers 15

# Verify improvement
bq query --use_legacy_sql=false "
WITH raw AS (
  SELECT DISTINCT player_lookup FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
  WHERE game_date = '2026-01-15'
),
analytics AS (
  SELECT DISTINCT player_lookup FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date = '2026-01-15'
)
SELECT
  (SELECT COUNT(*) FROM raw) as raw_players,
  (SELECT COUNT(*) FROM analytics) as analytics_players,
  ROUND(100.0 * (SELECT COUNT(*) FROM analytics) / (SELECT COUNT(*) FROM raw), 1) as coverage_pct"

# Expected: 85-95% coverage (currently 63.6%)

# Phase 4: Player Daily Cache (DO NOT RUN UNTIL PHASE 3 FIXED)
# python -m backfill_jobs.precompute.player_daily_cache.player_daily_cache_precompute_backfill \
#   --start-date 2026-01-01 --end-date 2026-02-13 \
#   --parallel --workers 15
```

---

## Success Criteria

Before moving to Phase 4:

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Jan 15 Player Coverage | 63.6% | >85% | ❌ |
| Jan 22 Usage Rate Coverage | 0% | >80% | ❌ |
| Jayson Tatum Records (Jan 1-25) | 0 | 10+ | ❌ |
| Austin Reaves Records (Jan 1-25) | 0 | 10+ | ❌ |

---

## Timeline

- **08:12 UTC**: Started reprocessing investigation
- **08:12 UTC**: Captured baseline metrics
- **08:13 UTC**: Ran Phase 3 backfill (completed in 1.2 min)
- **08:14 UTC**: Discovered no improvement in metrics
- **08:15-08:45 UTC**: Deep investigation of registry system
- **08:45 UTC**: Documented findings for Opus
- **Next**: Awaiting Opus fix + re-run

---

## Contact

**Current Chat**: Data Reprocessing (Sonnet 4.5)
**Next Chat**: Code Fixes (Opus)
**Then**: Resume Data Reprocessing (this chat)
