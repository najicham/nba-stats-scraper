<!-- File: validation/PARTITION_FILTER_GUIDE.md -->
<!-- Description: Guide explaining BigQuery partition filtering requirements and how the validation framework handles them -->

# Partition Filter Guide

## What is `require_partition_filter`?

When a BigQuery table has `require_partition_filter = true` in its schema, **every query MUST include a WHERE clause filtering on the partition column**, or BigQuery will reject it.

### Example Error (Without Partition Filter)

```sql
-- ❌ THIS WILL FAIL
SELECT * FROM `nba_raw.espn_scoreboard`
WHERE home_team_abbr = 'LAL'
```

```
Error: Cannot query over table 'nba_raw.espn_scoreboard' 
without a filter over column(s) 'game_date' that can be used 
for partition elimination
```

### Correct Query (With Partition Filter)

```sql
-- ✅ THIS WORKS
SELECT * FROM `nba_raw.espn_scoreboard`
WHERE game_date >= '2024-11-01'
  AND game_date <= '2024-11-30'
  AND home_team_abbr = 'LAL'
```

---

## Why This Exists

**Purpose:** Cost and performance optimization

BigQuery is charged based on data scanned. Partition filtering:
- **Reduces cost** by scanning only relevant partitions
- **Improves performance** by limiting data processed
- **Prevents accidents** where you accidentally scan entire table

**Example:**
- Without partition filter: Scan 4 years of data = $$$
- With partition filter: Scan 1 month of data = $

---

## Which Tables Require This?

Check your config file:

```yaml
processor:
  name: "espn_scoreboard"
  table: "nba_raw.espn_scoreboard"
  partition_required: true          # ⚠️ This means partition filter required!
  partition_field: "game_date"      # Must filter on this field
```

### Tables with `require_partition_filter = true`

Based on your schemas:
- ✅ `nba_raw.espn_scoreboard` - partitioned by `game_date`
- ✅ `nba_raw.bdl_player_boxscores` - partitioned by `game_date`
- ✅ `nba_raw.odds_api_player_points_props` - partitioned by `game_date`
- ✅ `nba_raw.nbac_schedule` - partitioned by `game_date`
- ✅ Most other raw data tables

---

## How the Validation Framework Handles This

### Automatic Partition Filter Injection

The `PartitionFilterHandler` automatically adds partition filters to queries:

```python
from validation.utils.partition_filter import PartitionFilterHandler

# Create handler
handler = PartitionFilterHandler(
    table='nba_raw.espn_scoreboard',
    partition_field='game_date',
    required=True
)

# Your query (missing partition filter)
query = "SELECT * FROM `nba_raw.espn_scoreboard` WHERE home_team_abbr = 'LAL'"

# Handler adds partition filter automatically
safe_query = handler.ensure_partition_filter(
    query,
    start_date='2024-11-01',
    end_date='2024-11-30'
)

# Result:
# SELECT * FROM `nba_raw.espn_scoreboard` 
# WHERE game_date >= '2024-11-01' AND game_date <= '2024-11-30' 
# AND home_team_abbr = 'LAL'
```

### Integrated in Base Validator

The `BaseValidator` automatically handles this:

```python
class BaseValidator:
    def __init__(self, config_path):
        # ...
        self.partition_handler = self._init_partition_handler()
    
    def _execute_query(self, query, start_date, end_date):
        """Execute query with automatic partition filtering"""
        if self.partition_handler:
            query = self.partition_handler.ensure_partition_filter(
                query, start_date, end_date
            )
        return self.bq_client.query(query).result()
```

**You don't need to worry about it!** Just use `self._execute_query()` in your validators.

---

## Valid Partition Filter Patterns

The handler recognizes these patterns:

### ✅ Range Filter (Most Common)
```sql
WHERE game_date >= '2024-11-01' AND game_date <= '2024-11-30'
```

### ✅ BETWEEN
```sql
WHERE game_date BETWEEN '2024-11-01' AND '2024-11-30'
```

### ✅ Single Date
```sql
WHERE game_date = '2024-11-15'
```

### ✅ IN Clause
```sql
WHERE game_date IN ('2024-11-15', '2024-11-16', '2024-11-17')
```

### ✅ Greater Than/Less Than
```sql
WHERE game_date > '2024-11-01'
```

---

## Common Scenarios

### Scenario 1: Simple Query

```python
# Your validation check
def _check_completeness(self, config, start_date, end_date):
    query = """
    SELECT COUNT(*) as game_count
    FROM `nba_raw.espn_scoreboard`
    WHERE is_completed = TRUE
    """
    
    # ✅ Use _execute_query - it adds partition filter automatically
    result = self._execute_query(query, start_date, end_date)
```

### Scenario 2: CTE Query

```python
query = """
WITH expected AS (
  SELECT DISTINCT game_date
  FROM `nba_raw.nbac_schedule`
  WHERE game_date >= '{start_date}'
    AND game_date <= '{end_date}'
)
SELECT * FROM expected
"""

# ✅ Already has partition filter in CTE - handler detects this
result = self._execute_query(query.format(...), start_date, end_date)
```

### Scenario 3: Custom Validator

```python
class EspnScoreboardValidator(BaseValidator):
    def _run_custom_validations(self, start_date, end_date, season_year):
        # Custom query
        query = """
        SELECT home_team_abbr, COUNT(*) as games
        FROM `nba_raw.espn_scoreboard`
        WHERE is_completed = TRUE
        GROUP BY home_team_abbr
        """
        
        # ✅ Use inherited _execute_query method
        result = self._execute_query(query, start_date, end_date)
```

---

## Troubleshooting

### Error: "Cannot query over table without partition filter"

**Cause:** Query doesn't have partition filter and handler couldn't inject it.

**Solution 1:** Use `self._execute_query()` instead of direct BigQuery client
```python
# ❌ Bad
result = self.bq_client.query(query).result()

# ✅ Good
result = self._execute_query(query, start_date, end_date)
```

**Solution 2:** Add partition filter manually to complex queries
```python
query = f"""
WITH complex_cte AS (...)
SELECT *
FROM `nba_raw.espn_scoreboard`
WHERE game_date >= '{start_date}'  -- ✅ Manual filter
  AND game_date <= '{end_date}'
  AND ...
"""
```

### Error: "Could not inject partition filter into complex query"

**Cause:** Query is too complex for automatic injection (nested subqueries, multiple CTEs).

**Solution:** Add partition filter manually:
```python
query = """
WITH base AS (
  SELECT *
  FROM `nba_raw.espn_scoreboard`
  WHERE game_date >= '2024-11-01'  -- ✅ Add here
    AND game_date <= '2024-11-30'
),
processed AS (
  SELECT * FROM base WHERE ...
)
SELECT * FROM processed
"""
```

### Data Freshness Check Exception

**Special case:** MAX(processed_at) queries don't need date range:

```python
def _check_data_freshness(self, config):
    query = """
    SELECT MAX(processed_at) as last_processed
    FROM `nba_raw.espn_scoreboard`
    """
    
    # ✅ Use direct client - freshness check is special case
    result = self.bq_client.query(query).result()
```

---

## Testing Partition Filtering

### Test Script

```python
# File: validation/tests/test_partition_filter.py

from validation.utils.partition_filter import PartitionFilterHandler

def test_partition_filter_injection():
    handler = PartitionFilterHandler(
        table='nba_raw.espn_scoreboard',
        partition_field='game_date',
        required=True
    )
    
    # Test 1: Query without WHERE
    query1 = "SELECT * FROM `nba_raw.espn_scoreboard`"
    result1 = handler.ensure_partition_filter(
        query1, 
        start_date='2024-11-01',
        end_date='2024-11-30'
    )
    assert 'game_date >=' in result1
    assert '2024-11-01' in result1
    
    # Test 2: Query with WHERE but no partition filter
    query2 = """
    SELECT * FROM `nba_raw.espn_scoreboard`
    WHERE home_team_abbr = 'LAL'
    """
    result2 = handler.ensure_partition_filter(
        query2,
        start_date='2024-11-01',
        end_date='2024-11-30'
    )
    assert 'game_date >=' in result2
    assert 'AND home_team_abbr' in result2
    
    # Test 3: Query already has partition filter
    query3 = """
    SELECT * FROM `nba_raw.espn_scoreboard`
    WHERE game_date >= '2024-11-01'
      AND game_date <= '2024-11-30'
    """
    result3 = handler.ensure_partition_filter(
        query3,
        start_date='2024-11-01',
        end_date='2024-11-30'
    )
    # Should be unchanged
    assert result3 == query3.strip()
    
    print("✅ All partition filter tests passed!")

if __name__ == '__main__':
    test_partition_filter_injection()
```

---

## Quick Reference

### DO ✅

```python
# Use the provided helper
result = self._execute_query(query, start_date, end_date)

# Or add partition filter manually
query = f"""
SELECT * FROM `table`
WHERE game_date >= '{start_date}'
  AND game_date <= '{end_date}'
"""
```

### DON'T ❌

```python
# Don't bypass the partition filter handler
result = self.bq_client.query(query).result()  # ❌ Might fail

# Don't forget date range
result = self._execute_query(query, None, None)  # ❌ Can't add filter
```

---

## Summary

1. **Partition filters are required** on most tables to control costs
2. **The framework handles this automatically** via `_execute_query()`
3. **You rarely need to think about it** - just use the provided methods
4. **For complex queries**, add filters manually in the WHERE clause
5. **Always include date ranges** when calling validation methods

**Golden Rule:** Use `self._execute_query(query, start_date, end_date)` for all BigQuery queries in validators!