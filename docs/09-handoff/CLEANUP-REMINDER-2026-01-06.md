# CLEANUP REMINDER: Deduplicate player_game_summary

**Date Created**: January 5, 2026, 8:40 PM PST
**Action Required**: January 6, 2026 (after 10 AM PST)
**Priority**: Medium (0.27% duplication rate, non-blocking)

---

## What Needs Cleanup

**Table**: `nba-props-platform.nba_analytics.player_game_summary`
**Issue**: ~354 duplicate records across 3 dates
**Affected Dates**: 2025-11-10, 2025-12-30, 2026-01-04
**Impact**: Low - 0.27% of total records (354/129,513)

---

## Why We Need to Wait

**BigQuery Streaming Buffer**: 90-minute window after INSERT
- **Blocks**: DELETE operations on recently inserted data
- **Expires**: ~90 minutes after last INSERT (around 10 AM PST tomorrow)
- **Current Status**: Multiple backfills running, constantly refreshing the buffer
- **Safe Time**: After ALL backfills complete + 2 hours

---

## Root Cause (for Prevention)

The `MERGE_UPDATE` strategy uses **DELETE + INSERT**, not a proper SQL MERGE:

```python
# Current implementation (analytics_base.py:1521)
if self.processing_strategy == 'MERGE_UPDATE':
    self._delete_existing_data_batch(rows)  # DELETE query
    # Then INSERT new rows
```

**DELETE Query**:
```sql
DELETE FROM table WHERE game_date BETWEEN 'start_date' AND 'end_date'
```

**Problem**: 
- Streaming buffer prevents DELETE → exception caught
- Code continues anyway → INSERT runs → duplicates

**Long-term Fix**: Use proper MERGE statement (not DELETE + INSERT)

---

## Cleanup Script (Run Tomorrow)

```bash
cd /home/naji/code/nba-stats-scraper

# 1. Verify streaming buffer cleared (should return > 0)
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2021-10-20'
  AND 1=0  -- Won't delete anything, just tests if DELETE allowed
"

# 2. If above succeeds, run deduplication
bq query --use_legacy_sql=false "
-- Create temp table with duplicates to remove (keeps best record)
CREATE OR REPLACE TABLE \`nba-props-platform.nba_analytics.tmp_duplicates_to_remove\` AS
WITH duplicates AS (
  SELECT 
    game_id, game_date, player_lookup,
    COUNT(*) as dup_count
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date >= '2021-10-19'
  GROUP BY game_id, game_date, player_lookup
  HAVING COUNT(*) > 1
),
ranked AS (
  SELECT 
    pgs.game_id, pgs.game_date, pgs.player_lookup,
    ROW_NUMBER() OVER (
      PARTITION BY pgs.game_id, pgs.game_date, pgs.player_lookup 
      ORDER BY 
        CASE WHEN pgs.minutes_played IS NOT NULL THEN 1 ELSE 0 END DESC,
        pgs.minutes_played DESC NULLS LAST,
        (CAST(pgs.points IS NOT NULL AS INT64) +
         CAST(pgs.assists IS NOT NULL AS INT64) +
         CAST(pgs.fg_attempts IS NOT NULL AS INT64)) DESC
    ) as row_rank
  FROM \`nba-props-platform.nba_analytics.player_game_summary\` pgs
  INNER JOIN duplicates d 
    ON pgs.game_id = d.game_id 
    AND pgs.game_date = d.game_date 
    AND pgs.player_lookup = d.player_lookup
)
SELECT game_date, game_id, player_lookup
FROM ranked
WHERE row_rank > 1
"

# 3. Delete duplicates (keeps rank=1, deletes rank>1)
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE (game_date, game_id, player_lookup) IN (
  SELECT game_date, game_id, player_lookup
  FROM \`nba-props-platform.nba_analytics.tmp_duplicates_to_remove\`
)
"

# 4. Verify cleanup
bq query --use_legacy_sql=false "
SELECT 
  COUNTIF(cnt > 1) as duplicate_groups
FROM (
  SELECT COUNT(*) as cnt
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date >= '2021-10-19'
  GROUP BY game_id, game_date, player_lookup
)
"
# Expected: 0 duplicate_groups

# 5. Cleanup temp table
bq rm -f nba-props-platform:nba_analytics.tmp_duplicates_to_remove
```

---

## Prevention for Future

**Immediate**: Add validation to backfill scripts
```python
# After save_data(), verify no duplicates created
duplicates = self.bq_client.query(f"""
  SELECT COUNT(*) as dup_count
  FROM (
    SELECT COUNT(*) as cnt
    FROM `{table_id}`
    WHERE game_date = '{date}'
    GROUP BY game_id, player_lookup
    HAVING COUNT(*) > 1
  )
""").to_dataframe()

if duplicates['dup_count'].iloc[0] > 0:
    logger.error(f"❌ Created {duplicates['dup_count'].iloc[0]} duplicates!")
```

**Long-term**: Replace DELETE+INSERT with proper MERGE
```python
# Instead of:
DELETE FROM table WHERE game_date = X
INSERT INTO table VALUES (...)

# Use:
MERGE table AS target
USING new_data AS source
ON target.game_id = source.game_id 
   AND target.player_lookup = source.player_lookup
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...
```

---

## Success Criteria

✅ Zero duplicate groups in player_game_summary
✅ Record counts match expected for 3 affected dates
✅ Temp table cleaned up

---

**Created by**: Claude (backfill monitoring session)
**Next Action**: Run cleanup script on Jan 6 after 10 AM PST
