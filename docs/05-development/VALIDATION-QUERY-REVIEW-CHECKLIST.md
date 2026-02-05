# Validation Query Review Checklist

**Purpose:** Prevent validation query logic errors like the Session 123 DNP pollution incident

**When to use:** Before committing any SQL query that validates data quality

---

## Pre-Commit Checklist

Every validation query MUST pass this 5-phase review:

### Phase A: Data Model Understanding ✅

- [ ] **Identify all date columns in the tables being joined**
  - What is the semantic meaning of each date column?
  - Document the relationship (e.g., `cache_date` = analysis date, `game_date` = event date)

- [ ] **Verify join condition semantics match your intent**
  - Cache tables: games are FROM BEFORE cache_date, not ON cache_date
  - Aggregation tables: may contain data from multiple source dates
  - Document the expected relationship (1:1, 1:N, N:M)

- [ ] **Check partition filter requirements**
  - All BigQuery queries need partition filters for performance
  - Verify both tables in a JOIN have appropriate filters

**Common Date Column Meanings:**
| Column | Meaning | Example Usage |
|--------|---------|---------------|
| `cache_date` | Analysis date (when cache was generated) | `game_date < cache_date` |
| `game_date` | Event date (when game was played) | `game_date = '2026-02-04'` |
| `analysis_date` | Processing date (when analysis ran) | `analysis_date >= '2026-02-01'` |
| `scrape_date` | Collection date (when data was scraped) | `scrape_date = CURRENT_DATE()` |

### Phase B: Logic Verification ✅

- [ ] **Test with known-bad data FIRST**
  - Before testing that "good data passes", test that "bad data fails"
  - If your validation returns 0 issues, that's a RED FLAG
  - Create or identify test data that SHOULD fail validation

- [ ] **Verify non-zero baseline**
  - Run query against historical data where issues existed
  - If it returns 0 when you KNOW issues existed, the query is broken

- [ ] **Check boundary conditions**
  - What happens when tables are empty?
  - What happens when JOIN returns no rows?
  - What happens at date boundaries?

**Example: Test Against Known-Bad Data**
```sql
-- If checking for DNP pollution, test against Feb 4, 2026
-- (known to have 78% pollution before fix)
SELECT ... WHERE cache_date = '2026-02-04'
-- Should return ~172 DNP players, NOT 0
```

### Phase C: Query Structure Review ✅

- [ ] **LEFT JOIN vs INNER JOIN semantics**
  - LEFT JOIN: returns NULL for non-matches (may hide issues)
  - INNER JOIN: drops non-matches (may undercount)
  - Document which is correct for your validation

- [ ] **Aggregation correctness**
  - COUNT(*) vs COUNT(DISTINCT ...)
  - Verify grouping doesn't mask issues
  - Use NULLIF to prevent division by zero

- [ ] **NULL handling**
  - NULLs in join conditions can silently drop rows
  - Add explicit NULL checks where needed
  - Use COALESCE or IFNULL for safe defaults

**Common Query Patterns:**
```sql
-- ✅ CORRECT: Safe division
ROUND(100.0 * bad_count / NULLIF(total_count, 0), 1) as pct

-- ❌ WRONG: Unsafe division
ROUND(100.0 * bad_count / total_count, 1) as pct  -- Fails if total = 0

-- ✅ CORRECT: Cache date check
WHERE game_date < cache_date  -- Games BEFORE cache date

-- ❌ WRONG: Session 123 anti-pattern
WHERE cache_date = game_date  -- Always returns 0 for caches
```

### Phase D: Documentation Requirements ✅

- [ ] **Document the data model assumptions**
  - Add comment: "Cache_date is the analysis date, not the game date"
  - Explain join semantics: "This query checks games BEFORE cache_date"

- [ ] **Include expected results comment**
  ```sql
  -- Expected: Should return ~0% for clean data, 50-70% for polluted data
  -- If this returns 0% consistently, the query may be broken
  ```

- [ ] **Add validation query test instructions**
  - How to verify the query works
  - Known dates with issues for testing

**Example Documentation:**
```sql
-- DNP Pollution Check (Session 123 Corrected Query)
--
-- DATA MODEL ASSUMPTIONS:
-- - cache_date is the ANALYSIS date, not the game date
-- - Cache contains games from BEFORE cache_date
-- - LEFT JOIN ensures we count all cached players even if no PGS match
--
-- EXPECTED RESULTS:
-- - Clean cache: 0% DNP pollution
-- - Polluted cache (pre-fix): 50-80% DNP pollution
--
-- TEST DATA:
-- - Feb 4, 2026 (pre-fix): Should show ~172 DNP players (78%)
-- - Feb 4, 2026 (post-fix): Should show 0 DNP players (0%)
--
-- CRITICAL: If this returns 0 when you know issues exist,
-- the join condition is likely wrong (Session 123 lesson)
```

### Phase E: Post-Commit Verification ✅

- [ ] **Run against known-bad historical data**
  - Identify a date range where you KNOW issues existed
  - Query should detect those issues
  - If it returns 0, investigate immediately

- [ ] **Set up alerting for "always-zero" results**
  - If validation returns 0 for 7+ consecutive days, alert
  - This may indicate a broken validation query

- [ ] **Add to monitoring dashboard**
  - Track validation results over time
  - Look for suspiciously stable patterns (always 0, always 100)

---

## Session 123 Anti-Patterns

**❌ DO NOT USE:**

### 1. Cache Date Equality Join
```sql
-- WRONG: Session 123 anti-pattern
WHERE pdc.cache_date = pgs.game_date
-- Problem: cache_date is analysis date, not game date
-- Result: Always returns 0 for cache validation
```

**✅ USE INSTEAD:**
```sql
-- CORRECT: Check historical games
WHERE pgs.game_date < pdc.cache_date
-- Explanation: Cache contains games BEFORE the cache_date
```

### 2. Missing Partition Filters
```sql
-- WRONG: No partition filter
FROM player_game_summary
WHERE player_lookup = 'stephencurry'
-- Problem: Scans entire table, expensive and slow
```

**✅ USE INSTEAD:**
```sql
-- CORRECT: With partition filter
FROM player_game_summary
WHERE game_date >= '2026-01-01'  -- Partition filter
  AND player_lookup = 'stephencurry'
```

### 3. Unsafe Division
```sql
-- WRONG: No NULL handling
SELECT COUNT(*) / total_count as pct
-- Problem: Fails if total_count is 0
```

**✅ USE INSTEAD:**
```sql
-- CORRECT: Safe division
SELECT COUNT(*) / NULLIF(total_count, 0) as pct
```

### 4. Assuming "0 = Good"
```sql
-- WRONG: Trusting zero results
if validation_count == 0:
    print("✅ All good!")
-- Problem: Query might be broken, returning false negatives
```

**✅ USE INSTEAD:**
```sql
-- CORRECT: Verify with known-bad data first
-- Test against Feb 4, 2026 (known pollution)
-- Should return >0, then test against clean data
if validation_count == 0:
    if not tested_against_known_bad:
        print("⚠️  Verify query works - test with known-bad data")
```

---

## Quick Reference

### Validation Query Template

```sql
-- [QUERY NAME] Validation Check
--
-- DATA MODEL:
-- - [Explain date column semantics]
-- - [Explain join relationships]
--
-- EXPECTED RESULTS:
-- - Good data: [expected values]
-- - Bad data: [expected values]
--
-- TEST DATA:
-- - [Date/scenario with known issues]
--
-- CRITICAL CHECKS:
-- - join_count > 0 (verifies JOIN is working)
-- - Result is non-zero for known-bad data

WITH validation_data AS (
  SELECT
    ...,
    COUNT(*) OVER() as join_count  -- Meta-check: JOIN produced results
  FROM [primary_table] p
  LEFT JOIN [validation_table] v
    ON p.key = v.key
    AND v.date_field [< or = or >] p.date_field  -- Document the relationship!
  WHERE p.partition_field >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)  -- Partition filter
)
SELECT
  ...,
  ROUND(100.0 * bad_count / NULLIF(total_count, 0), 1) as issue_pct,
  join_count  -- Should be > 0, otherwise JOIN is broken
FROM validation_data
GROUP BY ...
```

### Pre-commit Hook

The SQL validation pre-commit hook automatically checks for:
- 🚨 CRITICAL: `cache_date = game_date` pattern
- ⚠️ WARNING: Missing partition filters
- ⚠️ WARNING: Division without NULLIF

```bash
# Test your query
python .pre-commit-hooks/validate_sql_queries.py your_query.sql
```

### Validation Framework

Use the test-driven validation framework:

```python
from shared.validation.validation_query_framework import (
    ValidationQueryTester,
    ValidationQuerySpec,
    ValidationTestCase
)

# Define your validation spec with test cases
spec = ValidationQuerySpec(
    name='your_validation',
    query_template='...',
    test_cases=[
        ValidationTestCase(
            name='known_bad_data',
            test_parameters={'date': '2026-02-04'},
            expected_result='should_find_issues',
            minimum_issues=10
        )
    ]
)

# Test it
tester = ValidationQueryTester(bq_client)
passed, errors = tester.test_validation_query(spec)
```

---

## Examples

### Good Validation Query (Session 123 Corrected)

```sql
-- DNP Pollution Check
-- Checks for players with ONLY DNP games and no active games

WITH player_game_stats AS (
  SELECT
    player_lookup,
    COUNT(*) as total_games,
    COUNTIF(is_dnp = TRUE) as dnp_games,
    COUNTIF(is_dnp = FALSE) as active_games
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB('2026-02-04', INTERVAL 30 DAY)  -- Partition filter
    AND game_date < '2026-02-04'  -- Games BEFORE cache date
  GROUP BY player_lookup
)
SELECT
  pdc.cache_date,
  COUNT(DISTINCT pdc.player_lookup) as cached_players,
  COUNT(DISTINCT CASE
    WHEN pgs.active_games = 0 AND pgs.dnp_games > 0
    THEN pdc.player_lookup
  END) as dnp_only_players,  -- Only count DNP-only players
  ROUND(100.0 * COUNT(DISTINCT CASE
    WHEN pgs.active_games = 0 AND pgs.dnp_games > 0
    THEN pdc.player_lookup
  END) / NULLIF(COUNT(DISTINCT pdc.player_lookup), 0), 1) as dnp_pct
FROM `nba-props-platform.nba_precompute.player_daily_cache` pdc
LEFT JOIN player_game_stats pgs ON pdc.player_lookup = pgs.player_lookup
WHERE pdc.cache_date = '2026-02-04'
GROUP BY pdc.cache_date
```

**Why this is good:**
- ✅ Documents data model assumptions
- ✅ Uses partition filter
- ✅ Correct date relationship (game_date < cache_date)
- ✅ Safe division with NULLIF
- ✅ Checks for specific issue (DNP-only, not any-DNP)

---

## When in Doubt

1. **Test against known-bad data first**
2. **Document your assumptions**
3. **Use the pre-commit hook**
4. **Ask for review** from someone familiar with the data model

---

## References

- **Session 123:** DNP validation emergency (the incident that created this checklist)
- **Validation Framework:** `shared/validation/validation_query_framework.py`
- **SQL Pre-commit Hook:** `.pre-commit-hooks/validate_sql_queries.py`
- **Audit Script:** `bin/audit/audit_cache_dnp_pollution.py`

**Remember:** Validation infrastructure needs validation. A query that always returns 0 is probably broken, not measuring perfection.
