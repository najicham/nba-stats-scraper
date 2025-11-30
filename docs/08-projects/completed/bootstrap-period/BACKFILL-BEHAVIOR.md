# Backfill Behavior - Automatic Bootstrap Detection
**Purpose:** Document how backfill handles historical early season periods
**Created:** 2025-11-27
**Status:** ✅ Automatic - No Manual Intervention Needed!

---

## Your Question

**Q:** "When we backfill past 4 seasons, will it automatically detect early season periods? Or do we need to set flags manually?"

**A:** **YES, fully automatic!** ✅ No flags needed, no manual intervention required.

---

## How It Works Automatically

### The Magic: Deterministic Date-Based Detection

Your implementation is already designed for this! Here's what happens:

#### When You Backfill October 24, 2023

```bash
# Run processor for historical date
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
    --analysis_date 2023-10-24
```

**What the code does:**

1. **Determines Season Year**
   ```python
   analysis_date = date(2023, 10, 24)
   season_year = get_season_year_from_date(analysis_date)
   # Returns: 2023 (October = same year)
   ```

2. **Queries Schedule Service for Season Start**
   ```python
   season_start = get_season_start_date(season_year=2023)
   # Queries database OR uses fallback
   # Returns: date(2023, 10, 24)  # From actual schedule!
   ```

3. **Calculates Days Since Season Start**
   ```python
   days_since_start = (analysis_date - season_start).days
   # (2023-10-24) - (2023-10-24) = 0 days
   ```

4. **Checks Early Season Threshold**
   ```python
   is_early = is_early_season(analysis_date, season_year, days_threshold=7)
   # 0 < 7 → TRUE ✅
   ```

5. **Skips Processing Automatically**
   ```python
   if is_early:
       logger.info("🏁 Skipping 2023-10-24: early season period (day 0)")
       return  # No records written
   ```

**Result:** Automatically skips day 0 of 2023 season! ✅

---

## Backfill Timeline Example: 2023 Season

### What Happens for Each Date

| Date | Day of Season | Auto-Detected? | Processor Behavior | Records Written? |
|------|---------------|----------------|-------------------|------------------|
| 2023-10-24 | 0 | ✅ Early season | Skip | ❌ No |
| 2023-10-25 | 1 | ✅ Early season | Skip | ❌ No |
| 2023-10-26 | 2 | ✅ Early season | Skip | ❌ No |
| 2023-10-27 | 3 | ✅ Early season | Skip | ❌ No |
| 2023-10-28 | 4 | ✅ Early season | Skip | ❌ No |
| 2023-10-29 | 5 | ✅ Early season | Skip | ❌ No |
| 2023-10-30 | 6 | ✅ Early season | Skip | ❌ No |
| **2023-10-31** | **7** | ✅ Regular season | **Process** | **✅ Yes** |
| 2023-11-01 | 8 | ✅ Regular season | Process | ✅ Yes |
| ... | ... | ✅ Regular season | Process | ✅ Yes |

**No manual intervention at any point!** Each date is evaluated independently.

---

## Backfill Script Behavior

### Scenario: Backfill Entire 2023 Season

```bash
# Backfill command (example)
for date in $(seq $(date -d "2023-10-24" +%s) 86400 $(date -d "2024-04-15" +%s)); do
    analysis_date=$(date -d "@$date" +%Y-%m-%d)
    python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
        --analysis_date $analysis_date
done
```

**What happens:**

| Date Range | Processor Detects | Action | Result |
|-----------|-------------------|--------|---------|
| Oct 24-30 (7 days) | Early season (days 0-6) | Skip automatically | 0 records |
| Oct 31 - Apr 15 | Regular season (day 7+) | Process automatically | ~167 days of records |

**Zero configuration changes needed!** ✅

---

## Why This Works Automatically

### 1. Schedule Service Has Historical Data ✅

From our earlier query verification:

```sql
SELECT season_year, MIN(DATE(game_date)) as first_game
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE is_regular_season = TRUE
  AND game_status = 3
GROUP BY season_year
ORDER BY season_year;
```

**Results:**
- 2021: 2021-10-19 ✅ In database
- 2022: 2022-10-18 ✅ In database
- 2023: 2023-10-24 ✅ In database
- 2024: 2024-10-22 ✅ In database

### 2. Fallback Dates in Code ✅

If database is unavailable, hardcoded fallbacks in `nba_season_dates.py`:

```python
FALLBACK_SEASON_START_DATES = {
    2024: date(2024, 10, 22),
    2023: date(2023, 10, 24),
    2022: date(2022, 10, 18),
    2021: date(2021, 10, 19),  # Epoch
}
```

**Guarantees it works even without database!** ✅

### 3. Deterministic Logic ✅

```python
def is_early_season(analysis_date: date, season_year: int, days_threshold: int = 7):
    """Pure function - same inputs = same outputs, always."""
    season_start = get_season_start_date(season_year)  # Deterministic
    days_since_start = (analysis_date - season_start).days  # Math
    return 0 <= days_since_start < days_threshold  # Boolean logic
```

**No state, no flags, no configuration!** Just pure deterministic logic.

---

## Edge Cases and Special Scenarios

### Scenario 1: Backfill in Non-Chronological Order

```bash
# Backfill day 20 first, then day 5
python processor.py --analysis_date 2023-11-13  # Day 20
python processor.py --analysis_date 2023-10-29  # Day 5
```

**Behavior:**
- Day 20: Processes (day 20 > 7) ✅
- Day 5: Skips (day 5 < 7) ✅

**Each date is independent!** Order doesn't matter.

### Scenario 2: Reprocess Historical Early Season

```bash
# Accidentally reprocess day 3
python processor.py --analysis_date 2023-10-27
```

**Behavior:**
- Detects: Early season (day 3 < 7)
- Action: Skips automatically ✅
- Result: No records written (idempotent!)

**Safe to run multiple times!**

### Scenario 3: Different Threshold for Testing

```bash
# Want to test with 3-day threshold instead of 7
# NO CODE CHANGE NEEDED! Just pass parameter:
```

```python
# In processor:
if is_early_season(analysis_date, season_year, days_threshold=3):
    # Skip first 3 days instead of 7
```

**Flexible and configurable!**

### Scenario 4: Lockout Season (2020-2021)

```bash
# 2020-21 season started December 22, 2020 (late due to COVID)
python processor.py --analysis_date 2020-12-22
```

**Behavior:**
- Queries schedule service: Returns 2020-12-22 (if in database)
- Fallback: Might estimate Oct 22 (wrong!)
- **Solution:** Add to fallback dates:

```python
FALLBACK_SEASON_START_DATES = {
    2024: date(2024, 10, 22),
    2023: date(2023, 10, 24),
    2022: date(2022, 10, 18),
    2021: date(2021, 10, 19),
    2020: date(2020, 12, 22),  # ← Add lockout season
}
```

---

## Verification Queries for Backfill

### Query 1: Verify Early Season Skips

```sql
-- Check that days 0-6 have NO records for 2023 season
SELECT
    cache_date,
    COUNT(*) as record_count
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2023-10-24' AND '2023-10-30'  -- Days 0-6
GROUP BY cache_date
ORDER BY cache_date;
```

**Expected:** 0 records for all dates (empty result set)

### Query 2: Verify Day 7+ Has Records

```sql
-- Check that day 7+ HAS records for 2023 season
SELECT
    cache_date,
    COUNT(*) as record_count,
    AVG(feature_quality_score) as avg_quality,
    AVG(completeness_percentage) as avg_completeness
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2023-10-31' AND '2023-11-07'  -- Days 7-14
GROUP BY cache_date
ORDER BY cache_date;
```

**Expected:**
- All dates have 300-400 records (active players)
- Quality scores: 70-90 (partial windows early on)
- Completeness: 70-100% (improving over time)

### Query 3: Compare All 4 Seasons

```sql
-- Verify consistent early season handling across seasons
WITH season_starts AS (
    SELECT 2024 as season, DATE '2024-10-22' as start_date
    UNION ALL SELECT 2023, DATE '2023-10-24'
    UNION ALL SELECT 2022, DATE '2022-10-18'
    UNION ALL SELECT 2021, DATE '2021-10-19'
)

SELECT
    s.season,
    s.start_date,
    DATE_ADD(s.start_date, INTERVAL 6 DAY) as last_skip_date,
    DATE_ADD(s.start_date, INTERVAL 7 DAY) as first_process_date,

    -- Count records in skip period (should be 0)
    (SELECT COUNT(*)
     FROM `nba-props-platform.nba_precompute.player_daily_cache`
     WHERE cache_date BETWEEN s.start_date
       AND DATE_ADD(s.start_date, INTERVAL 6 DAY)
    ) as skip_period_records,

    -- Count records on day 7 (should be >0)
    (SELECT COUNT(*)
     FROM `nba-props-platform.nba_precompute.player_daily_cache`
     WHERE cache_date = DATE_ADD(s.start_date, INTERVAL 7 DAY)
    ) as day_7_records

FROM season_starts s
ORDER BY s.season DESC;
```

**Expected:**
| Season | Start Date | Skip Period Records | Day 7 Records |
|--------|-----------|---------------------|---------------|
| 2024 | 2024-10-22 | 0 | 300-400 |
| 2023 | 2023-10-24 | 0 | 300-400 |
| 2022 | 2022-10-18 | 0 | 300-400 |
| 2021 | 2021-10-19 | 0 | 300-400 |

---

## Backfill Command Examples

### Full Season Backfill (with automatic skip)

```bash
#!/bin/bash
# Backfill 2023 season

START_DATE="2023-10-24"  # Season opener
END_DATE="2024-04-15"    # Regular season end

# Loop through all dates
current_date="$START_DATE"
while [[ "$current_date" < "$END_DATE" ]]; do
    echo "Processing $current_date..."

    # Run processor (will auto-skip days 0-6)
    python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
        --analysis_date "$current_date"

    # Next date
    current_date=$(date -I -d "$current_date + 1 day")
done

echo "Backfill complete!"
```

**Output:**
```
Processing 2023-10-24...
🏁 Skipping 2023-10-24: early season period (day 0-6 of season 2023)

Processing 2023-10-25...
🏁 Skipping 2023-10-25: early season period (day 0-6 of season 2023)

...

Processing 2023-10-31...
✅ Processing 2023-10-31: day 7 of season (regular processing)
Extracted 1200 player game records
Created 350 player cache records

Processing 2023-11-01...
✅ Processing 2023-11-01: day 8 of season (regular processing)
...
```

### Selective Backfill (skip early season entirely)

```bash
#!/bin/bash
# Backfill only days that will process (skip early season in script)

SEASON_START="2023-10-24"
FIRST_PROCESS_DATE=$(date -I -d "$SEASON_START + 7 days")  # Day 7
END_DATE="2024-04-15"

# Start from day 7 directly
current_date="$FIRST_PROCESS_DATE"
while [[ "$current_date" < "$END_DATE" ]]; do
    python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
        --analysis_date "$current_date"
    current_date=$(date -I -d "$current_date + 1 day")
done
```

**More efficient!** Skips days 0-6 in the script itself.

---

## Testing the Backfill Behavior

### Test 1: Dry Run Single Date

```bash
# Test day 0 (should skip)
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
    --analysis_date 2023-10-24 \
    --dry-run  # If supported

# Expected output:
# 🏁 Skipping 2023-10-24: early season period (day 0 of season 2023)
```

### Test 2: Dry Run Day 7

```bash
# Test day 7 (should process)
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
    --analysis_date 2023-10-31 \
    --dry-run

# Expected output:
# ✅ Processing 2023-10-31: day 7 of season 2023
# (Extraction logs, transformation logs, etc.)
```

### Test 3: Small Date Range

```bash
# Test 10 days (days 3-12)
for day in {3..12}; do
    date=$(date -I -d "2023-10-24 + $day days")
    echo "=== Testing $date (day $day) ==="
    python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
        --analysis_date "$date"
done
```

**Expected:**
- Days 3-6: Skip (4 skips)
- Days 7-12: Process (6 successes)

---

## Summary Table: Backfill Behavior

| Aspect | Behavior | Manual Intervention? |
|--------|----------|---------------------|
| **Detect early season** | ✅ Automatic | ❌ No |
| **Determine season year** | ✅ Automatic | ❌ No |
| **Query season start date** | ✅ Automatic | ❌ No |
| **Calculate days since start** | ✅ Automatic | ❌ No |
| **Skip days 0-6** | ✅ Automatic | ❌ No |
| **Process day 7+** | ✅ Automatic | ❌ No |
| **Works for all 4 seasons** | ✅ Yes | ❌ No |
| **Works in any order** | ✅ Yes | ❌ No |
| **Safe to rerun** | ✅ Yes | ❌ No |
| **Configuration needed** | ❌ None | ❌ No |

---

## Gotchas and Considerations

### ⚠️ Gotcha 1: ML Feature Store Behaves Differently

Remember: **Other processors skip, ML Feature Store creates placeholders**

```bash
# When backfilling ML Feature Store for day 0:
python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor \
    --analysis_date 2023-10-24
```

**Behavior:**
- Detects: Early season (day 0)
- Action: Creates placeholder records (not skip!)
- Result: Records with NULL features, early_season_flag=TRUE

This is correct! ML Feature Store needs placeholders for Phase 5.

### ⚠️ Gotcha 2: Upstream Dependencies

When backfilling Phase 4 processors:

```bash
# This WILL fail if Phase 3 data doesn't exist
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
    --analysis_date 2023-10-31
```

**Requirement:** Phase 3 analytics must have data for 2023 season!

**Solution:** Backfill in correct order:
1. Phase 2 (raw data)
2. Phase 3 (analytics)
3. Phase 4 (precompute) ← Now works!

### ⚠️ Gotcha 3: Timezone Considerations

If schedule service queries use timestamps:

```sql
-- This might have timezone issues:
WHERE game_date >= '2023-10-24 00:00:00 UTC'

-- Better:
WHERE DATE(game_date) >= '2023-10-24'
```

Your implementation already handles this correctly with DATE casting! ✅

---

## Bottom Line

**🎉 FULLY AUTOMATIC!** 🎉

1. ✅ No manual flags needed
2. ✅ No configuration changes needed
3. ✅ Works for all 4 historical seasons
4. ✅ Each date is evaluated independently
5. ✅ Safe to run in any order
6. ✅ Safe to rerun (idempotent)
7. ✅ Schedule service provides truth
8. ✅ Fallback dates ensure reliability

**Just run your backfill script and it works!**

The deterministic date-based logic ensures consistent behavior whether you're processing live data or backfilling historical data.

---

**Next Steps:**

1. Test with single historical date (day 0 and day 7)
2. Run small backfill (10 days)
3. Verify with SQL queries above
4. Run full season backfill

Everything should "just work"! ✅
