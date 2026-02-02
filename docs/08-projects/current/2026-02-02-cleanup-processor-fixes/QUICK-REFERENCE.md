# BigQuery Partition Filter Error - Quick Reference

**Quick diagnosis and fix guide for 400 partition filter errors**

---

## Instant Diagnosis

### Symptom
```
400 BadRequest: Cannot query over table 'nba_raw.TABLE_NAME'
without a filter over column(s) 'game_date' that can be used
for partition elimination
```

### Cause
BigQuery table requires partition filter but query doesn't have one

### Fix Pattern
```sql
-- Add partition filter to WHERE clause
AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- or for espn_team_rosters:
AND roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

---

## Quick Commands

### 1. Check if Table Requires Partition Filter
```bash
bq show --format=json nba-props-platform:nba_raw.TABLE_NAME | \
  jq '{requirePartitionFilter: .requirePartitionFilter,
       partitionField: .timePartitioning.field}'
```

**If `requirePartitionFilter: true`** → Must add filter

### 2. Find Recent Partition Filter Errors
```bash
gcloud logging read 'resource.type="cloud_run_revision"
  AND severity>=ERROR
  AND textPayload=~"partition elimination"' \
  --limit=5 --format=json | \
  jq -r '.[] | {time: .timestamp, table: .textPayload}'
```

### 3. Test Cleanup Endpoint After Fix
```bash
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/cleanup \
  -H "Content-Type: application/json" -w "\nStatus: %{http_code}\n"
```

**Expected**: Status 200, no errors

### 4. Verify Scheduler Runs After Fix
```bash
gcloud logging read 'resource.labels.job_id="cleanup-processor"
  AND timestamp>="YYYY-MM-DDTHH:MM:00Z"' \
  --limit=3 --format=json | \
  jq -r '.[] | {time: .timestamp, status: .httpRequest.status}'
```

**Expected**: All Status 200

---

## Tables Requiring Partition Filters

| Table | Partition Field | Filter Example |
|-------|----------------|----------------|
| bdl_player_boxscores | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| espn_scoreboard | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| **espn_team_rosters** | **roster_date** | `roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| espn_boxscores | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| bigdataball_play_by_play | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| odds_api_game_lines | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| bettingpros_player_points_props | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| nbac_schedule | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| nbac_team_boxscore | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| nbac_play_by_play | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| nbac_scoreboard_v2 | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |
| nbac_referee_game_assignments | game_date | `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)` |

**Note**: espn_team_rosters uses `roster_date` instead of `game_date`

---

## Code Fix Template

### Single Table Query
```python
# Before (causes 400):
query = f"""
    SELECT * FROM `nba_raw.bdl_player_boxscores`
    WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
"""

# After (works):
query = f"""
    SELECT * FROM `nba_raw.bdl_player_boxscores`
    WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
"""
```

### UNION Query (Multiple Tables)
```python
# Partition field mapping
partition_fields = {
    'espn_team_rosters': 'roster_date',  # Non-standard!
}

# Tables requiring filters
partitioned_tables = [
    'bdl_player_boxscores', 'espn_scoreboard', 'espn_team_rosters',
    # ... (full list above)
]

# Build conditional query
for table in all_tables:
    if table in partitioned_tables:
        partition_field = partition_fields.get(table, 'game_date')
        partition_filter = f"AND {partition_field} >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
    else:
        partition_filter = ""

    queries.append(f"""
        SELECT * FROM `nba_raw.{table}`
        WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        {partition_filter}
    """)

final_query = f"SELECT * FROM ({' UNION ALL '.join(queries)})"
```

---

## Common Mistakes

### ❌ Wrong: Using processing lookback for partition filter
```sql
-- TOO NARROW - might miss edge cases
WHERE game_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
```

### ✅ Right: Using wider lookback for partition filter
```sql
-- SAFE - provides margin while satisfying BigQuery
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

### ❌ Wrong: Assuming all tables use game_date
```python
# Will fail for espn_team_rosters
partition_filter = "AND game_date >= ..."
```

### ✅ Right: Checking table-specific partition field
```python
partition_field = partition_fields.get(table, 'game_date')
partition_filter = f"AND {partition_field} >= ..."
```

### ❌ Wrong: Testing only individual tables
```bash
# Might miss UNION query issues
bq query "SELECT * FROM nba_raw.bdl_player_boxscores WHERE ..."
```

### ✅ Right: Testing full UNION query
```bash
# Tests actual production query
curl -X POST https://SERVICE_URL/cleanup
```

---

## Deployment Checklist

- [ ] Add partition filter to query
- [ ] Check for espn_team_rosters (uses roster_date)
- [ ] Use 7-day lookback for partition filter
- [ ] Keep existing processed_at filter
- [ ] Commit changes with descriptive message
- [ ] Deploy service: `./bin/deploy-service.sh SERVICE_NAME`
- [ ] Test manual endpoint (should return 200)
- [ ] Wait for scheduled run (check logs for 200)
- [ ] Monitor for 400 errors (should be 0)
- [ ] Update documentation

---

## When to Use This Guide

**Use this guide when you see**:
- 400 BadRequest errors mentioning "partition elimination"
- Errors about missing `game_date` or `roster_date` filter
- UNION queries across multiple Phase 2 tables failing
- Cleanup processor returning 400 errors

**Don't use this guide for**:
- Permission errors (use Section 6.1 in troubleshooting-matrix.md)
- Table not found errors (use Section 6.1)
- Other BigQuery errors (check error message)

---

## Full Documentation

- **Complete Analysis**: `README.md` (this directory)
- **Session Handoffs**: `docs/09-handoff/2026-02-02-SESSION-73-HANDOFF.md` and `SESSION-74-HANDOFF.md`
- **CLAUDE.md**: Common Issues section
- **Troubleshooting**: `docs/02-operations/troubleshooting-matrix.md` Section 6.5

---

## Emergency Contacts

**If you can't resolve**:
1. Check Session 73-74 handoff documents
2. Review cleanup_processor.py lines 306-338
3. Verify all 12 tables in partitioned_tables list
4. Check if new tables were added to Phase 2 (might need partition filters)

**Last Resort**:
- Manually trigger player movement: See CLAUDE.md "Manual Scraper Triggers"
- System works with manual triggers while investigating automation

---

**Created**: Feb 2, 2026 (Sessions 73-74)
**Last Verified**: Feb 2, 2026 04:30 UTC
