# BettingPros Fallback Fix & Pre-Execution Tasks

**Created:** 2025-11-30
**Status:** ✅ COMPLETE
**Completed:** 2025-11-30
**Completion Document:** `docs/09-handoff/2025-11-30-bettingpros-fallback-complete.md`
**Impact:** Increased historical coverage from 40% to 99.7%

---

## 🎯 Objective

Fix the `upcoming_player_game_context` processor to use BettingPros as a fallback when Odds API data is missing, increasing historical data coverage from 40% to 99.7%.

---

## 📊 The Problem

### Current State

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Current behavior:**
- Only queries `nba_raw.odds_api_player_points_props`
- Odds API has 271/675 dates (40% coverage)
- BettingPros has 673/675 dates (99.7% coverage)

**Impact:**
- Without this fix: `upcoming_player_game_context` will only have data for 40% of historical dates
- With this fix: 99.7% coverage

### Data Coverage Comparison

| Source | Dates | Coverage |
|--------|-------|----------|
| Odds API | 271 | 40% |
| **BettingPros** | **673** | **99.7%** |

---

## 🔧 The Fix

### Locations to Modify

Search for `odds_api_player_points_props` in the processor file:

1. **Line ~335:** Driver query (determines which players to process)
2. **Line ~540:** Props extraction
3. **Line ~554:** Props extraction

### Implementation Option A: SQL UNION (Recommended)

Replace single-source queries with UNION that prefers Odds API but falls back to BettingPros:

```sql
WITH odds_api_props AS (
    SELECT
        player_lookup,
        game_id,
        game_date,
        points_line,
        bookmaker,
        'odds_api' as source
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date = '{target_date}'
),
bettingpros_props AS (
    SELECT
        player_lookup,
        game_id,
        game_date,
        points_line,
        'pinnacle' as bookmaker,  -- BettingPros default
        'bettingpros' as source
    FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
    WHERE game_date = '{target_date}'
      -- Only use BettingPros if Odds API has no data for this date
      AND game_date NOT IN (
          SELECT DISTINCT game_date
          FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
          WHERE game_date = '{target_date}'
      )
)
SELECT * FROM odds_api_props
UNION ALL
SELECT * FROM bettingpros_props
```

### Implementation Option B: Python Fallback

```python
def get_player_props(self, target_date: date) -> pd.DataFrame:
    """Get player props with BettingPros fallback."""

    # Try Odds API first
    query_odds_api = f"""
    SELECT player_lookup, game_id, points_line, bookmaker
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date = '{target_date}'
    """

    props_df = self.bq_client.query(query_odds_api).to_dataframe()

    # If empty, fall back to BettingPros
    if props_df.empty:
        logger.info(f"No Odds API data for {target_date}, using BettingPros fallback")
        query_bettingpros = f"""
        SELECT player_lookup, game_id, points_line, 'pinnacle' as bookmaker
        FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
        WHERE game_date = '{target_date}'
        """
        props_df = self.bq_client.query(query_bettingpros).to_dataframe()

    return props_df
```

---

## 🧪 Testing

### Test 1: Verify BettingPros Data Exists

```bash
# Check that BettingPros has data where Odds API doesn't
bq query --use_legacy_sql=false "
SELECT
  bp.game_date,
  COUNT(DISTINCT bp.player_lookup) as bettingpros_players,
  COUNT(DISTINCT oa.player_lookup) as odds_api_players
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\` bp
LEFT JOIN \`nba-props-platform.nba_raw.odds_api_player_points_props\` oa
  ON bp.game_date = oa.game_date
WHERE bp.game_date BETWEEN '2021-10-19' AND '2022-04-10'
GROUP BY bp.game_date
HAVING COUNT(DISTINCT oa.player_lookup) = 0
ORDER BY bp.game_date
LIMIT 10
"

# Expected: Shows dates where BettingPros has data but Odds API doesn't
```

### Test 2: Dry Run Before Fix

```bash
# Pick a date that only has BettingPros data
TEST_DATE="2021-11-01"

# Check data availability
bq query --use_legacy_sql=false "
SELECT 'Odds API' as source, COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date = '$TEST_DATE'
UNION ALL
SELECT 'BettingPros', COUNT(DISTINCT player_lookup)
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '$TEST_DATE'
"

# If Odds API = 0 and BettingPros > 0, this is a good test date
```

### Test 3: Dry Run After Fix

```bash
# After implementing the fix, test with backfill job
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --dry-run --dates $TEST_DATE

# Expected: Should show players available (from BettingPros)
# Before fix: Would show 0 players
```

### Test 4: Single Date Execution

```bash
# Actually process the date
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --dates $TEST_DATE

# Verify data written
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records, COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '$TEST_DATE'
"

# Expected: Should have records for multiple players
```

---

## 📝 Implementation Checklist

- [ ] **Identify all query locations**
  ```bash
  grep -n "odds_api_player_points_props" \
    data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
  ```

- [ ] **Understand schema differences**
  ```bash
  # Check if schemas match between Odds API and BettingPros
  bq show --schema nba-props-platform:nba_raw.odds_api_player_points_props
  bq show --schema nba-props-platform:nba_raw.bettingpros_player_points_props
  ```

- [ ] **Implement fallback logic**
  - Choose Option A (SQL UNION) or Option B (Python fallback)
  - Update all 3 query locations
  - Add logging to indicate which source was used

- [ ] **Test with dry-run**
  - Test date with only Odds API data
  - Test date with only BettingPros data
  - Test date with both sources

- [ ] **Test actual execution**
  - Process one date with BettingPros data
  - Verify records written to BigQuery
  - Check data quality

- [ ] **Update documentation**
  - Add comment in code explaining fallback logic
  - Update processor docstring

---

## 🚨 Edge Cases to Handle

### Edge Case 1: Schema Differences

BettingPros and Odds API may have different column names or structures.

**Solution:** Map BettingPros columns to match Odds API schema in the SELECT statement.

### Edge Case 2: Both Sources Have Data

When both Odds API and BettingPros have data for the same date, prefer Odds API.

**Solution:** Use `NOT IN` or `NOT EXISTS` in BettingPros query to exclude dates that have Odds API data.

### Edge Case 3: Different Bookmakers

Odds API has multiple bookmakers, BettingPros has different bookmaker names.

**Solution:** Normalize bookmaker names or use a default like 'pinnacle' for BettingPros.

### Edge Case 4: Data Quality Differences

BettingPros lines might be slightly different from Odds API lines.

**Solution:** Accept this as normal variance. The processor should handle either source.

---

## ✅ Success Criteria

Fix is successful when:

1. **Dry-run shows increased coverage**
   ```bash
   # Before: ~40% of dates show available players
   # After: ~99.7% of dates show available players
   ```

2. **Historical backfill produces more data**
   ```sql
   -- After fixing and running backfill for a season
   SELECT COUNT(DISTINCT game_date) as dates_with_data
   FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
   WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'

   -- Expected: ~170 dates (full season)
   -- Before fix: ~70 dates (40% of season)
   ```

3. **Logging shows fallback usage**
   ```
   Processing 2021-11-01...
   INFO: No Odds API data for 2021-11-01, using BettingPros fallback
   INFO: Found 150 players from BettingPros
   ```

4. **No errors or data quality issues**
   - Records have valid player_lookup values
   - Points lines are reasonable (5-35 points typically)
   - No NULL values in critical fields

---

## 📦 Additional Pre-Execution Tasks

While fixing BettingPros, also check:

### 1. Verify Phase 3 Backfill Jobs Work

```bash
# Test one Phase 3 job with dry-run
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --dry-run --start-date 2023-11-01 --end-date 2023-11-07

# Expected: Shows data availability, no errors
```

### 2. Verify Phase 4 Backfill Jobs Work

```bash
# Test bootstrap skip
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --dates 2023-10-24

# Expected: Skips with message "⏭️  Skipping 2023-10-24 (bootstrap period)"

# Test normal date
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --dry-run --dates 2023-11-15

# Expected: Shows would process, checks Phase 3 availability
```

### 3. Verify Schemas Match Deployed Tables

```bash
./bin/verify_schemas.sh

# Expected: ✅ All schemas verified
```

---

## 📞 Deliverables

When complete:

1. **Updated processor file**
   - `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
   - All 3 query locations updated
   - Fallback logic implemented
   - Logging added

2. **Test results documented**
   - Dry-run test showing increased coverage
   - Single date execution successful
   - Data quality verified

3. **Handoff document**
   ```
   docs/09-handoff/2025-11-30-bettingpros-fallback-complete.md
   ```
   - What was changed
   - Test results
   - Coverage improvement
   - Any issues encountered
   - Ready for backfill

---

## 🔗 Related Documentation

- `docs/08-projects/current/backfill/BACKFILL-PRE-EXECUTION-HANDOFF.md` - Pre-execution checklist
- `docs/08-projects/current/backfill/BACKFILL-MASTER-PLAN.md` - Infrastructure gaps section
- `docs/08-projects/current/backfill/BACKFILL-RUNBOOK.md` - Execution guide

---

## 🚀 After This Fix

Once BettingPros fallback is implemented and tested:

✅ **All prerequisites complete:**
- Phase 3 backfill jobs exist
- Phase 4 backfill jobs exist
- BettingPros fallback implemented
- Schemas verified
- v1.0 infrastructure deployed

🚀 **Ready to execute backfill:**
- Follow `BACKFILL-RUNBOOK.md`
- Start with Season 2021-22
- Season-by-season with validation gates

---

**Task Created:** 2025-11-30
**Status:** Ready for New Chat Session
**Priority:** HIGH - Recommended before backfill execution
**Estimated Impact:** +59.7% coverage improvement (40% → 99.7%)
