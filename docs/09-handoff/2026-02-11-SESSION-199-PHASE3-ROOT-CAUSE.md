# Session 199 - Phase 3 Missing Players Root Cause Investigation

**Date:** February 11, 2026
**Session:** 199 - Phase 3 Data Quality Deep Dive
**Status:** 🟡 **QUERY WORKING, WRITE ISSUE SUSPECTED**
**Investigator:** Sonnet (with Opus oversight)

---

## Executive Summary

**Initial Problem:** 10 players with betting lines missing from Phase 3 analytics, including star players like Paolo Banchero, Jalen Suggs, Desmond Bane, and Myles Turner.

**Opus Correction:** Initial investigation incorrectly identified game_id format mismatch as root cause. Opus correctly noted this is a known, handled architectural pattern with CTE-level normalization already in place.

**Actual Finding:** Phase 3's SQL query **WORKS PERFECTLY** and returns all 17 ORL players including the missing stars. However, only 5 players end up in the `upcoming_player_game_context` table. Something is filtering/dropping records **AFTER** the query executes.

**Next Steps:** Investigate post-query processing (DataFrame filtering, write logic, MERGE_UPDATE strategy).

---

## Investigation Timeline

### Phase 1: Game ID Wild Goose Chase ❌

**Hypothesis:** Game ID format mismatch between tables causing JOIN failures.
- Schedule uses: `0022500777` (NBA official)
- Phase 3 uses: `20260211_MIL_ORL` (date-based)

**Opus Verdict:** WRONG. This is a known, handled pattern with three layers of defense:
1. CTE-level normalization in `shared_ctes.py`
2. `game_id_reversed` dual matching
3. Dedicated converter utility in `shared/utils/game_id_converter.py`
4. Documented in CLAUDE.md Common Issues table

**Time Wasted:** ~2 hours
**Lesson:** Always check existing architecture before assuming bugs.

---

### Phase 2: Understanding Phase 3 Architecture ✅

**Discovery:** Phase 3 uses TWO query modes:

1. **DAILY mode** (for upcoming games):
   - Source: `espn_team_rosters` (roster data)
   - Query: `roster_players_with_games_cte()`
   - Filters: Injury status (removes 'Out', 'Doubtful')
   - Use case: Pre-game predictions when gamebook doesn't exist

2. **BACKFILL mode** (for historical games):
   - Source: `nbac_gamebook_player_stats` (actual game data)
   - Query: `gamebook_players_with_games_cte()`
   - Filters: None (uses who actually played)
   - Use case: Post-game analytics

**For Feb 11:** Phase 3 ran in DAILY mode because games haven't been played yet.

---

### Phase 3: Roster Data Verification ✅

**Checked:** Are missing players in ESPN roster?

**Result:** YES - All missing players exist in roster:
```
Orlando Magic roster (Feb 8, 2026):
- paolobanchero ✅
- jalensuggs ✅
- franzwagner ✅
- colincastleton ✅
- (+ 13 more, 17 total)
```

**Conclusion:** Roster data is complete and correct.

---

### Phase 4: Injury Filter Investigation ✅

**Hypothesis:** Daily mode injury filter removing these players.

**Filter logic:**
```sql
WHERE i.injury_status IS NULL
   OR i.injury_status NOT IN ('Out', 'OUT', 'Doubtful', 'DOUBTFUL')
```

**Findings:**
- Missing players: **NOT in injury report** (injury_status = NULL)
- NULL values: **PASS** the filter (first condition)
- Injury report uses lowercase: 'out', 'doubtful', 'questionable'
- Filter checks mixed-case: 'Out', 'OUT', 'Doubtful', 'DOUBTFUL'
- Lowercase values: **PASS** the filter (NOT IN mixed-case list)

**Conclusion:** Injury filter should let ALL 17 ORL players through.

---

### Phase 5: SQL Query Execution Test ✅✅✅

**Test:** Ran the EXACT Phase 3 daily mode query with actual parameters:
- game_date = '2026-02-11'
- roster_start = '2025-11-13' (90 days before)
- roster_end = '2026-02-11'
- team = 'ORL'

**Query Result:**
```
31 rows returned (multiple prop lines per player)
17 UNIQUE players including:
- anthonyblack ✅ (has betting line 16.5)
- colincastleton ✅
- desmondbane ✅ (has betting line 18.5)
- franzwagner ✅ (has betting line 14.5)
- gogabitadze ✅
- jalensuggs ✅ (has betting line 13.5)
- jamalcain ✅
- paolobanchero ✅ (has betting line 20.5)
- wendellcarterjr ✅ (has betting line 9.5)
+ 8 more

ALL 17 players have NULL or 'out' (lowercase) injury_status
ALL 17 players PASS the injury filter
```

**Database Reality:**
```
upcoming_player_game_context for ORL on Feb 11:
- colincastleton ✅
- franzwagner ✅
- gogabitadze ✅
- jamalcain ✅
- orlandorobinson ✅

MISSING: 12 players including all the stars!
```

**CRITICAL FINDING:** The SQL query returns 17 players, but only 5 end up in the database.

---

## The Mystery: Where Are the Missing 12 Players?

### What We Know

1. ✅ **Roster data exists** - All 17 players in `espn_team_rosters`
2. ✅ **SQL query works** - Returns all 17 players correctly
3. ✅ **Injury filter works** - All 17 players pass (NULL or lowercase 'out')
4. ✅ **Betting lines exist** - For Paolo, Jalen, Desmond, Wendell, Anthony
5. ❌ **Database has only 5** - 12 players disappear after query execution

### Potential Causes

#### Option 1: Post-Query Python Filtering

**Location:** `data_processors/analytics/upcoming_player_game_context/loaders/player_loaders.py`

**Code flow:**
```python
df = self.bq_client.query(daily_query, job_config=job_config).to_dataframe()  # Returns 17 players?

# Convert DataFrame to list of dicts
self.players_to_process.extend([...])  # Does this filter somehow?
```

**Questions:**
- Is there filtering between DataFrame creation and `players_to_process`?
- Are there any conditions that skip certain players?
- Does the DataFrame → dict conversion drop records?

#### Option 2: Write/MERGE Logic Issue

**Processing strategy:** `MERGE_UPDATE`

**Questions:**
- Is the MERGE matching on wrong keys and dropping records?
- Are there duplicate detection issues?
- Do certain records fail to write?
- Is there a primary key conflict?

#### Option 3: Timing Issue - Stale Data

**Observation:** Phase 3 records created:
- First: Feb 10 22:00:51 UTC (5 PM ET yesterday)
- Last: Feb 11 15:55:45 UTC (10:55 AM ET today)

**Questions:**
- Did Phase 3 run BEFORE roster was updated?
- Are we looking at stale records from yesterday's run?
- Did today's 10:30 AM run actually process all players but write failed?

#### Option 4: Processing Mode Confusion

**Question:**
- Is Phase 3 running in BACKFILL mode instead of DAILY mode?
- If it used `gamebook_players_with_games_cte()`, gamebook is EMPTY → 0 players
- But we have 200 total players across all teams, so it's definitely using DAILY mode

---

## Evidence Summary

### Roster Data (Source)
| Table | Team | Date | Player Count | Includes Paolo/Jalen? |
|-------|------|------|--------------|----------------------|
| `espn_team_rosters` | ORL | Feb 8 | 17 | ✅ YES |

### SQL Query Output (Tested)
| Players Returned | Includes Paolo/Jalen? | Passes Injury Filter? |
|------------------|----------------------|---------------------|
| 17 unique | ✅ YES | ✅ YES (all NULL or lowercase 'out') |

### Database Reality (Problem)
| Table | Team | Date | Player Count | Includes Paolo/Jalen? |
|-------|------|------|--------------|----------------------|
| `upcoming_player_game_context` | ORL | Feb 11 | 5 | ❌ NO |

### Missing Players (10 with betting lines)
1. paolobanchero - line: 20.5 ✅ in query, ❌ not in DB
2. jalensuggs - line: 13.5 ✅ in query, ❌ not in DB
3. desmondbane - line: 18.5 ✅ in query, ❌ not in DB
4. wendellcarterjr - line: 9.5 ✅ in query, ❌ not in DB
5. anthonyblack - line: 16.5 ✅ in query, ❌ not in DB
6. mylesturner - line: 11.5 (need to test MEM/IND)
7. ajgreen, kevinporterjr, ryanrollins (need to test other teams)

---

## Next Investigation Steps

### Priority 1: Check Phase 3 Logs

**Look for:**
```bash
# Check if Phase 3 logged how many players it found
gcloud logging read "resource.labels.service_name=nba-phase3-analytics-processors
  AND jsonPayload.message=~\"DAILY MODE.*Found\"
  AND timestamp>=\"2026-02-11T15:20:00Z\"" \
  --limit=10

# Expected log: "[DAILY MODE] Found X players for 2026-02-11"
# If X = 200, query worked
# If X = 5, query failed or was filtered
```

### Priority 2: Check DataFrame Processing

**File:** `data_processors/analytics/upcoming_player_game_context/loaders/player_loaders.py` (lines 130-154)

**Questions:**
- Does `df` have 200+ rows or only 5?
- Does `players_to_process` get all records or only some?
- Is there any filtering logic between query and extend?

### Priority 3: Check Write Operation

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Questions:**
- Does `transform_raw_data()` filter out records?
- Does `load_to_destination()` fail for some players?
- Does MERGE_UPDATE strategy cause issues?
- Are there primary key conflicts?

### Priority 4: Check Actual vs Expected

**Test query:**
```sql
-- Compare what SHOULD be vs what IS
WITH expected AS (
  -- Run the full Phase 3 daily query
  ...
),
actual AS (
  SELECT player_lookup
  FROM nba_analytics.upcoming_player_game_context
  WHERE game_date = '2026-02-11'
)
SELECT
  e.player_lookup,
  CASE WHEN a.player_lookup IS NULL THEN 'MISSING' ELSE 'EXISTS' END as status
FROM expected e
FULL OUTER JOIN actual a ON e.player_lookup = a.player_lookup
WHERE a.player_lookup IS NULL
```

---

## Questions for Opus

### 1. Diagnostic Strategy

**Question:** Should I:
- **Option A:** Check Phase 3 logs first (fastest, might show immediate issue)
- **Option B:** Add debug logging to player_loaders.py and re-run Phase 3
- **Option C:** Run Phase 3 manually in debug mode to trace execution
- **Option D:** Check if there's a simpler explanation I'm missing

**My recommendation:** Option A (check logs first)

### 2. Write Operation Suspicion

**Question:** The MERGE_UPDATE strategy - could this be silently dropping records?

**Considerations:**
- Primary key: `['game_date', 'player_lookup']`
- If records exist from yesterday with same keys, MERGE would UPDATE not INSERT
- Could yesterday's records be "locked" somehow?
- Should we check if Phase 3 is UPDATE-ing instead of INSERT-ing?

### 3. Broader Pattern

**Question:** Is this Phase 3 incompleteness issue broader than just ORL?

**Test:**
```sql
-- For each team, compare roster count vs Phase 3 count
SELECT
  r.team_abbr,
  COUNT(DISTINCT r.player_lookup) as roster_count,
  COUNT(DISTINCT p.player_lookup) as phase3_count,
  COUNT(DISTINCT r.player_lookup) - COUNT(DISTINCT p.player_lookup) as missing_count
FROM nba_raw.espn_team_rosters r
LEFT JOIN nba_analytics.upcoming_player_game_context p
  ON r.player_lookup = p.player_lookup AND p.game_date = '2026-02-11'
WHERE r.roster_date = '2026-02-08'
  AND r.team_abbr IN (SELECT DISTINCT home_team_tricode FROM nba_raw.nbac_schedule WHERE game_date = '2026-02-11')
GROUP BY r.team_abbr
HAVING missing_count > 0
```

If ALL teams are missing ~70% of their players, it's systemic.
If only some teams, it's team-specific (roster data quality?).

### 4. Quick Fix vs Root Cause

**Question:** Should we:
- **Quick fix:** Re-run Phase 3 for Feb 11 and see if it works this time?
- **Root cause:** Fully trace the code path to understand why 12 players dropped?

**Trade-off:**
- Quick fix: 5 min, might work, doesn't explain WHY
- Root cause: 1-2 hours, explains and prevents recurrence

---

## Files Referenced

### Code Files
- `data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py` - SQL query definitions
- `data_processors/analytics/upcoming_player_game_context/loaders/player_loaders.py` - Query execution and DataFrame processing
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` - Transform and write logic

### Data Tables
- `nba_raw.espn_team_rosters` - Player roster source (17 ORL players ✅)
- `nba_raw.v_nbac_schedule_latest` - Schedule view (14 games for Feb 11 ✅)
- `nba_raw.nbac_injury_report` - Injury status (missing players have NULL ✅)
- `nba_raw.odds_api_player_points_props` - Betting lines (10 players have lines ✅)
- `nba_analytics.upcoming_player_game_context` - **PROBLEM TABLE** (only 5 ORL players ❌)

### Related Docs
- `docs/09-handoff/2026-02-11-GAME-ID-MISMATCH-INVESTIGATION.md` - Initial (incorrect) investigation
- `docs/09-handoff/2026-02-11-SESSION-195-HANDOFF.md` - Original problem report
- `CLAUDE.md` - Documents game_id format handling

---

## Key Learnings

### 1. Always Verify Architecture Understanding First ✅

**Mistake:** Assumed game_id mismatch was a bug.
**Reality:** It's a known, handled pattern.
**Lesson:** Check existing architecture docs and Opus guidance before investigating.

### 2. Test the SQL Directly ✅

**Approach:** Ran exact Phase 3 query in BigQuery.
**Result:** Immediately showed query works, problem is elsewhere.
**Lesson:** Always test queries in isolation before blaming joins/filters.

### 3. Distinguish Query vs Processing Issues ✅

**Discovery:** Query returns 17 players, DB has 5 players.
**Insight:** Bug is in Python processing or write operation, not SQL.
**Lesson:** Test each layer independently (SQL → DataFrame → processing → write).

---

## Status

**Current State:** SQL query verified working. Post-query processing is suspect.

**Blocked On:** Need to check Phase 3 logs or trace code execution to find where 12 players disappear.

**Confidence Level:** HIGH that the issue is in Python code between query execution and database write.

**Estimated Fix Time:** 30min - 2 hours depending on root cause complexity.

---

**Next Steps:** Awaiting Opus direction on diagnostic strategy.
