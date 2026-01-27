# Sonnet Fix Task: Duplicate Record Prevention

## Objective
Prevent duplicate records from being inserted into analytics tables.

## Problem
Jan 8 has 19 duplicates, Jan 13 has 74 duplicates. All were created during a backfill on 2026-01-27 20:16:53. Same player_lookup + game_id inserted twice with identical data.

## Root Cause Analysis

The MERGE operation in `BigQuerySaveOpsMixin._save_with_proper_merge()` has a fallback:
```python
# Line ~467-495 in bigquery_save_ops.py
except Exception as e:
    logger.warning(f"MERGE failed, falling back to DELETE+INSERT: {e}")
    self._save_with_delete_insert(...)
```

And the DELETE+INSERT has this issue (line ~582-583):
```python
# If streaming buffer blocks DELETE, we proceed with INSERT anyway
if "streaming buffer" in str(e).lower():
    logger.warning("Delete blocked by streaming buffer - proceeding with INSERT")
```

This creates duplicates when:
1. MERGE fails (syntax error, timeout, etc.)
2. DELETE+INSERT fallback triggered
3. Streaming buffer blocks DELETE
4. INSERT proceeds → duplicates

## Solution Design

### Part 1: Fix the Fallback Behavior

**File**: `data_processors/analytics/operations/bigquery_save_ops.py`

**Change**: Don't proceed with INSERT when DELETE is blocked. Instead, raise an error or return and retry.

```python
# In _save_with_delete_insert(), around line 582:

# OLD:
if "streaming buffer" in str(e).lower():
    logger.warning("Delete blocked by streaming buffer - proceeding with INSERT")
    # continues to INSERT

# NEW:
if "streaming buffer" in str(e).lower():
    logger.warning(
        "Delete blocked by streaming buffer. "
        "Aborting to prevent duplicates. Will retry on next trigger."
    )
    raise StreamingBufferActiveError(
        f"Cannot delete due to streaming buffer for {table_id}. "
        "Data will be processed on next trigger when buffer flushes."
    )
```

Add the exception class:
```python
class StreamingBufferActiveError(Exception):
    """Raised when streaming buffer prevents safe DELETE operation."""
    pass
```

### Part 2: Add Pre-Save Deduplication

**File**: `data_processors/analytics/analytics_base.py` or `bigquery_save_ops.py`

Add deduplication before save:
```python
def _deduplicate_records(self, records: List[Dict]) -> List[Dict]:
    """
    Deduplicate records by PRIMARY_KEY_FIELDS before saving.

    Keeps the record with the latest processed_at timestamp.
    """
    if not self.PRIMARY_KEY_FIELDS:
        return records

    # Group by primary key
    from collections import defaultdict
    grouped = defaultdict(list)

    for record in records:
        key = tuple(record.get(f) for f in self.PRIMARY_KEY_FIELDS)
        grouped[key].append(record)

    # Keep latest by processed_at
    deduplicated = []
    duplicates_removed = 0

    for key, group in grouped.items():
        if len(group) > 1:
            duplicates_removed += len(group) - 1
            # Sort by processed_at descending, take first
            group.sort(key=lambda r: r.get('processed_at', ''), reverse=True)

        deduplicated.append(group[0])

    if duplicates_removed > 0:
        logger.warning(
            f"Pre-save deduplication: removed {duplicates_removed} duplicate records "
            f"(keys: {self.PRIMARY_KEY_FIELDS})"
        )

    return deduplicated
```

Call this in `save_analytics()`:
```python
def save_analytics(self):
    # ... existing code ...

    # Deduplicate before save
    self.transformed_data = self._deduplicate_records(self.transformed_data)

    # ... continue with save ...
```

### Part 3: Add Extract Query Deduplication

**File**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

The `combined_data` CTE already does a UNION ALL. Add explicit deduplication:

```sql
-- After combined_data CTE, add:
deduplicated_combined AS (
    SELECT * EXCEPT(rn) FROM (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY game_id, player_lookup
                ORDER BY source_processed_at DESC
            ) as rn
        FROM combined_data
    ) WHERE rn = 1
)
```

Then use `deduplicated_combined` instead of `combined_data` in subsequent CTEs.

### Part 4: Cleanup Existing Duplicates

Create a one-time cleanup script:

**File**: `scripts/maintenance/cleanup_duplicates.py`

```python
#!/usr/bin/env python3
"""
Cleanup duplicate records in player_game_summary.
One-time maintenance script.
"""

from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'

def cleanup_duplicates(dry_run: bool = True):
    client = bigquery.Client(project=PROJECT_ID)

    # Find and delete duplicates, keeping the one with latest processed_at
    cleanup_query = """
    CREATE OR REPLACE TABLE `{project}.nba_analytics.player_game_summary` AS
    SELECT * EXCEPT(rn) FROM (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY game_id, player_lookup
                ORDER BY processed_at DESC
            ) as rn
        FROM `{project}.nba_analytics.player_game_summary`
    ) WHERE rn = 1
    """.format(project=PROJECT_ID)

    if dry_run:
        # Count duplicates instead
        count_query = """
        SELECT COUNT(*) as duplicate_count FROM (
            SELECT game_id, player_lookup, COUNT(*) as cnt
            FROM `{project}.nba_analytics.player_game_summary`
            GROUP BY game_id, player_lookup
            HAVING cnt > 1
        )
        """.format(project=PROJECT_ID)

        result = client.query(count_query).result()
        count = next(result).duplicate_count
        print(f"DRY RUN: Would remove duplicates from {count} player-game combinations")
        return

    # Execute cleanup
    print("Executing cleanup...")
    client.query(cleanup_query).result()
    print("Cleanup complete")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true', help='Actually execute cleanup')
    args = parser.parse_args()

    cleanup_duplicates(dry_run=not args.execute)
```

## Testing

1. Run cleanup script in dry-run mode:
```bash
python scripts/maintenance/cleanup_duplicates.py
# Should show: "DRY RUN: Would remove duplicates from 93 player-game combinations"
```

2. Execute cleanup:
```bash
python scripts/maintenance/cleanup_duplicates.py --execute
```

3. Verify no duplicates remain:
```sql
SELECT game_date, COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup,'_',game_id)) as dupes
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2026-01-01'
GROUP BY game_date
HAVING dupes > 0
-- Should return empty
```

## Validation
After implementation, run a backfill and verify no duplicates created:
```bash
python scripts/backfill_player_game_summary.py --start-date 2026-01-08 --end-date 2026-01-08

# Then check:
bq query "SELECT COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup,'_',game_id)) FROM nba_analytics.player_game_summary WHERE game_date = '2026-01-08'"
# Should return 0
```
