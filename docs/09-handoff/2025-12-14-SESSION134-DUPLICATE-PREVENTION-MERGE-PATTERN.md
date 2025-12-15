# Session 134 Handoff - Duplicate Prevention & MERGE Pattern Implementation

**Date:** 2025-12-14
**Session:** 134
**Focus:** Data deduplication cleanup and implementing atomic MERGE pattern to prevent future duplicates

---

## Summary

Cleaned up 35,894 duplicate records across Phase 3-4 tables and implemented the atomic MERGE pattern in two Phase 3 analytics processors to prevent future duplicates.

**Key Outcomes:**
- Cleaned 34,728 duplicates from `upcoming_player_game_context`
- Cleaned 1,001 NULL `universal_player_id` records
- Cleaned 165 duplicates from `ml_feature_store_v2`
- Implemented atomic MERGE pattern in 2 processors
- Added comprehensive documentation to BigQuery best practices guide

---

## Data Cleanup Completed

### Phase 3: `upcoming_player_game_context`
| Metric | Before | After |
|--------|--------|-------|
| Total rows | 130,556 | 95,828 |
| Unique records | 95,828 | 95,828 |
| Duplicates | 34,728 | 0 |
| NULL player_id | 1,001 | 0 |

**Backup created:** `upcoming_player_game_context_backup_20241214`

### Phase 4: `ml_feature_store_v2`
| Metric | Before | After |
|--------|--------|-------|
| Duplicate pairs | 165 | 0 |

---

## Root Cause Analysis

### Why Duplicates Occurred

**Primary cause:** Non-atomic DELETE + INSERT pattern

```python
# Vulnerable pattern (before fix)
delete_query = f"DELETE FROM table WHERE game_date = '{date}'"
bq_client.query(delete_query).result()  # Step 1
load_job = bq_client.load_table_from_json(data, table_id)  # Step 2
```

**Race condition scenario:**
1. Run #1 DELETE succeeds
2. Run #2 starts before Run #1 INSERT completes
3. Run #2 DELETE sees empty table (Run #1 data not yet inserted)
4. Both INSERTs succeed → **duplicates**

**Evidence from data:**
- Timestamps 1-2 seconds apart (within same batch)
- Same player-game inserted 2-8 times
- All from Dec 12, 2025 backfill

### Secondary cause: Query-level duplicates

The extraction query could return the same player multiple times when they had props from multiple sources (odds_api + bettingpros).

---

## Code Changes

### 1. `upcoming_player_game_context` - MERGE Pattern

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Changes:**
- Added imports: `uuid`, `io`, `time`
- Replaced `save_analytics()` method with atomic MERGE pattern
- Merge keys: `(player_lookup, game_id)`

**Key features:**
- Creates temp table → loads data → atomic MERGE → cleanup
- ROW_NUMBER() deduplication in source query
- Streaming buffer handling
- Timing instrumentation

### 2. `upcoming_team_game_context` - MERGE Pattern

**File:** `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

**Changes:**
- Added imports: `uuid`, `io`, `time`
- Replaced `save_analytics()` method with atomic MERGE pattern
- Merge keys: `(team_abbr, game_id)`

### 3. Documentation Update

**File:** `docs/05-development/guides/bigquery-best-practices.md`

**Added:** Section 11 - "Duplicate Prevention with Atomic MERGE Pattern"
- Problem explanation
- Solution code template
- Merge keys by table
- Migration checklist
- Validation queries

---

## MERGE Pattern Explained

```python
# Atomic MERGE pattern (after fix)
def save_analytics(self):
    # 1. Create temp table
    temp_table_id = f"{table_id}_temp_{uuid.uuid4().hex[:8]}"

    # 2. Load data to temp table
    load_job = bq_client.load_table_from_file(data, temp_table_id)

    # 3. Atomic MERGE (single DML operation)
    merge_query = """
    MERGE target
    USING (
        SELECT * EXCEPT(row_num) FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY player_lookup, game_id
                ORDER BY processed_at DESC
            ) as row_num
            FROM temp_table
        ) WHERE row_num = 1  -- Deduplicate source
    ) AS source
    ON target.player_lookup = source.player_lookup
       AND target.game_id = source.game_id
    WHEN MATCHED THEN UPDATE SET ...
    WHEN NOT MATCHED THEN INSERT ROW
    """

    # 4. Cleanup temp table (in finally block)
    bq_client.delete_table(temp_table_id, not_found_ok=True)
```

**Why this prevents duplicates:**
- MERGE is a single atomic operation
- ROW_NUMBER() deduplicates source data
- No race condition possible
- Idempotent: run N times, same result

---

## Processors Status

### Fixed (Atomic MERGE)
| Processor | Table | Merge Keys |
|-----------|-------|------------|
| `UpcomingPlayerGameContextProcessor` | `upcoming_player_game_context` | `(player_lookup, game_id)` |
| `UpcomingTeamGameContextProcessor` | `upcoming_team_game_context` | `(team_abbr, game_id)` |
| `MLFeatureStoreProcessor` | `ml_feature_store_v2` | `(player_lookup, game_date)` |

### Still Using DELETE+INSERT (No Issues Observed)
| Processor | Table | Notes |
|-----------|-------|-------|
| `PlayerGameSummaryProcessor` | `player_game_summary` | Base class pattern |
| `TeamOffenseGameSummaryProcessor` | `team_offense_game_summary` | Base class pattern |
| `TeamDefenseGameSummaryProcessor` | `team_defense_game_summary` | Base class pattern |
| Phase 4 Precompute Processors | Various | Base class pattern |

**Recommendation:** Monitor these tables. If duplicates appear, migrate to MERGE pattern.

---

## Validation Queries

### Check for duplicates

```sql
-- Run this periodically to verify no duplicates
SELECT
  'upcoming_player_game_context' as table_name,
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(player_lookup, '-', game_id)) as unique_records,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '-', game_id)) as duplicates
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`

UNION ALL

SELECT
  'upcoming_team_game_context' as table_name,
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(team_abbr, '-', game_id)) as unique_records,
  COUNT(*) - COUNT(DISTINCT CONCAT(team_abbr, '-', game_id)) as duplicates
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`;

-- Expected: duplicates = 0 for all tables
```

---

## Next Steps (For Future Sessions)

1. **Run Phase 5 backfill** - System is now clean and ready
   ```bash
   PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
     --start-date 2021-11-02 --end-date 2024-04-14
   ```

2. **Monitor for duplicates** - Run validation queries weekly

3. **Consider migrating other processors** - If duplicates appear in:
   - `player_game_summary`
   - `team_offense_game_summary`
   - `team_defense_game_summary`

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | MERGE pattern |
| `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py` | MERGE pattern |
| `docs/05-development/guides/bigquery-best-practices.md` | Added Section 11 |

---

## Session Context

- Previous session (133) completed comprehensive validation
- This session (134) cleaned duplicates and implemented prevention
- System is now production-ready with duplicate protection
- Phase 5 backfill can proceed safely

**Last Updated By:** Claude Code Session 134
**Date:** 2025-12-14 ~13:00 PST
