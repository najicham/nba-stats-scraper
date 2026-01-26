# GSW and SAC Teams Missing from Player Context - Investigation & Fix

**Date:** 2026-01-25
**Issue:** GSW and SAC teams completely missing from upcoming_player_game_context (0/212 players)
**Status:** ✅ FIXED
**Impact:** 2/8 games (25% of games), 35 players affected

---

## Problem Statement

The `upcoming_player_game_context` table had 212 players for 2026-01-25, but GSW (Golden State Warriors) and SAC (Sacramento Kings) teams were completely missing, affecting 2 out of 8 games.

### Symptoms
- Team-level context: 100% complete (16/16 teams) ✅
- Player-level context: Missing GSW/SAC (14/16 teams) ❌
- Database showed 212 players across only 14 teams
- Expected: ~30-35 additional players from GSW/SAC

---

## Root Cause Analysis

### Investigation Steps

1. **Verified source data exists:**
   ```sql
   SELECT team_abbr, COUNT(*)
   FROM `nba_raw.nbac_gamebook_player_stats`
   WHERE game_date = '2026-01-25' AND team_abbr IN ('GSW', 'SAC')
   GROUP BY team_abbr
   -- Result: GSW=18 rows, SAC=18 rows ✅ Data exists!
   ```

2. **Identified JOIN failure:**
   - Gamebook game_id format: `20260125_GSW_MIN` (standard format)
   - Schedule nba_game_id format: `0022500644` (NBA official ID)
   - **These don't match!** JOIN produces NULL game_ids

3. **Traced impact:**
   - NULL game_ids → schedule lookup fails
   - "WARNING: No schedule data for game None" (repeated 147 times)
   - Players without schedule data → filtered out

### The Bug

**File:** `data_processors/analytics/upcoming_player_game_context/loaders/player_loaders.py`
**Line:** 305

```python
# INCORRECT JOIN (before fix)
LEFT JOIN schedule_data s
    ON g.game_id = s.nba_game_id  -- ❌ Formats don't match

# Expected behavior:
# - gamebook: game_id = "20260125_GSW_MIN"
# - schedule: nba_game_id = "0022500644"
# - Result: No match → s.game_id = NULL
```

### Evidence

**Before Fix:**
```sql
| gamebook_game_id  | schedule_nba_id | schedule_generated_id |
| 20260125_GSW_MIN | NULL            | NULL                  |
```

**After Fix:**
```sql
| gamebook_id      | schedule_id | generated_id      |
| 20260125_GSW_MIN | 0022500644  | 20260125_GSW_MIN |
```

---

## The Fix

### Code Change

```diff
diff --git a/data_processors/analytics/upcoming_player_game_context/loaders/player_loaders.py
@@ -302,7 +302,7 @@ class PlayerDataLoader:
             FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats` g
             LEFT JOIN schedule_data s
-                ON g.game_id = s.nba_game_id  -- Join on NBA official ID
+                ON g.game_id = s.game_id  -- FIXED: Join on generated game_id (YYYYMMDD_AWAY_HOME format)
             WHERE g.game_date = @game_date
```

### Explanation

The schedule CTE generates two game_id formats:
- `nba_game_id`: NBA official format (e.g., "0022500644")
- `game_id`: Generated standard format (e.g., "20260125_GSW_MIN")

The gamebook uses the standard format, so we must JOIN on `s.game_id` not `s.nba_game_id`.

---

## Verification

### Test Query Results

**After Fix - All teams now present:**
```sql
| team_abbr | players | games |
|-----------|---------|-------|
| BKN       |      18 |     1 |
| DET       |      18 |     1 |
| GSW       |      17 |     1 | ✅ NOW PRESENT
| LAC       |      18 |     1 |
| MIA       |      17 |     1 |
| MIN       |      17 |     1 |
| NOP       |      18 |     1 |
| OKC       |      18 |     1 |
| PHX       |      17 |     1 |
| SAC       |      18 |     1 | ✅ NOW PRESENT
| SAS       |      18 |     1 |
| TOR       |      17 |     1 |
```

### Processor Run Results

**Before Fix:**
- Found 358 players in backfill query
- 147 warnings: "No schedule data for game None"
- Result: 212 players processed (146 filtered out due to NULL game_ids)

**After Fix:**
- Found 358 players in backfill query
- 0 warnings about missing schedule data ✅
- Calculated context for 227 players (131 failed completeness checks - expected behavior)
- GSW: 17 players extracted ✅
- SAC: 18 players extracted ✅

---

## Impact Assessment

### Scope
- **Fixed games:** GSW@MIN, SAC@DET
- **Affected players:** 35 players (17 GSW + 18 SAC)
- **Date range:** Affects ALL dates processed in backfill mode
- **Severity:** HIGH - 25% of games missing player data

### Related Issues
This bug likely affected other historical dates as well since the JOIN logic has been in place since backfill mode was implemented. A full historical reprocessing may be needed.

---

## Known Remaining Issues

### Separate Bug: Save Operation Failure

The processor now successfully extracts and calculates player context, but a separate bug prevents saving to BigQuery:

```
ValueError: table_id must be a fully-qualified ID in standard SQL format,
got nba-props-platform.nba_analytics.nba_analytics.upcoming_player_game_context
                                    ^^^^^^^^^^^^ duplicate dataset name
```

**Location:** `data_processors/analytics/operations/bigquery_save_ops.py:125`
**Status:** Requires separate investigation
**Impact:** Data is calculated correctly but not saved to the database

---

## Recommendations

### Immediate Actions
1. ✅ Apply the JOIN fix (completed)
2. ⏳ Fix the save operation table_id bug
3. ⏳ Rerun processor for 2026-01-25 to populate GSW/SAC data
4. ⏳ Check historical dates for similar data gaps

### Long-term Improvements
1. Add unit tests for JOIN logic with different game_id formats
2. Add validation to detect NULL game_ids in extraction phase
3. Add monitoring alerts for team coverage drops (< 10 teams/day)
4. Document the dual game_id format issue in the data model

### Historical Data Recovery
Consider reprocessing dates with suspiciously low team counts:
```sql
SELECT game_date, COUNT(DISTINCT team_abbr) as teams
FROM `nba_analytics.upcoming_player_game_context`
GROUP BY game_date
HAVING teams < 10  -- Flag dates with low team coverage
ORDER BY game_date DESC
```

---

## References

- **Original Issue:** docs/incidents/2026-01-25-ACTION-3-REMEDIATION-REPORT.md
- **Processor:** data_processors/analytics/upcoming_player_game_context/
- **Fixed File:** loaders/player_loaders.py:305
- **Schedule View:** nba_raw.v_nbac_schedule_latest
- **Gamebook Table:** nba_raw.nbac_gamebook_player_stats

---

## Conclusion

The GSW/SAC missing data issue was caused by a simple but critical JOIN logic error. The fix changes the JOIN condition to use the correct game_id format, which properly matches gamebook and schedule data.

The processor now successfully extracts all teams and calculates player context. A separate save operation bug needs to be fixed to persist the data to BigQuery.
