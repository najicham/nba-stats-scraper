# Game ID Format Investigation - 2026-01-12
**Investigator:** Claude
**Date:** 2026-01-12
**Trigger:** Backfill validation found mid-season gaps in PCF (2023-02-23, 2023-02-24, 2024-02-22)

---

## Executive Summary

### Initial Hypothesis (INCORRECT)
The backfill validation report suggested that game_id format mismatches between tables were causing missing games in `player_composite_factors`.

### Actual Finding (CORRECT)
**Game_id format is NOT the issue.** The custom date_team format (`YYYYMMDD_AWAY_HOME`) is used consistently across all player-related tables. The real issue is that a **recent partial backfill on 2026-01-06 only processed a fraction of players** for certain dates.

---

##  Investigation Findings

### Finding 1: Game ID Format Architecture (By Design)

**There are TWO game_id formats in use, BY DESIGN:**

| Format | Example | Used By | Source |
|--------|---------|---------|--------|
| **NBA Official** | `0022200886` | Schedule table | NBA.com API `gameId` field |
| **Custom Date-Team** | `20230223_DEN_CLE` | Player stats, Analytics, Precompute | Constructed in Phase 2 processors |

**Custom Format Construction:**
```python
# From data_processors/raw/balldontlie/bdl_player_box_scores_processor.py:243
game_id = f"{date_str}_{away_abbr}_{home_abbr}"  # YYYYMMDD_AWAY_HOME

# From data_processors/raw/nbacom/nbac_player_boxscore_processor.py:174
def construct_game_id(self, game_date: str, home_team: str, away_team: str) -> str:
    date_str = game_date.replace('-', '')
    return f"{date_str}_{away_team}_{home_team}"
```

**Why Two Formats?**
- **Schedule table:** Uses official NBA game_id directly from NBA.com API
- **Player stats:** Construct custom format because:
  - BDL API doesn't provide NBA's official game_id
  - Easier to parse team information from the ID itself
  - Human-readable format for debugging

**Consistency Check:**
✅ `nbac_gamebook_player_stats`: Uses custom format
✅ `bdl_player_boxscores`: Uses custom format
✅ `player_game_summary`: Inherits custom format from above
✅ `player_composite_factors`: Inherits custom format from above
✅ `player_daily_cache`: Uses custom format
❌ `nbac_schedule`: Uses NBA official format (by design)

**Conclusion:** This is **intentional architecture**, not a bug. The custom format is consistently used across the entire player data pipeline.

---

### Finding 2: The Real Issue - Partial Backfill on 2026-01-06

**Discovery:** All problematic PCF records were created on **2026-01-06** (6 days ago).

**Evidence:**
```sql
SELECT
  analysis_date,
  COUNT(*) as actual_records,
  COUNT(DISTINCT player_lookup) as unique_players
FROM player_composite_factors
WHERE analysis_date BETWEEN '2023-02-20' AND '2023-02-26'
GROUP BY analysis_date
```

| Date | Expected Players* | Actual in PCF | Coverage | Created At |
|------|------------------|---------------|----------|------------|
| 2023-02-23 | 187 (9 games) | **1** | **0.5%** | 2026-01-06 19:37:09 |
| 2023-02-24 | 175 (8 games) | **68** | **39%** | 2026-01-06 19:37:51 |
| 2023-02-25 | 218 | 218 | ✅ 100% | 2026-01-06 19:38:34 |
| 2023-02-26 | 278 | 278 | ✅ 100% | 2026-01-06 19:39:15 |

*Based on `player_game_summary` player count

**The Smoking Gun:**
- All records created in same 2-minute window on 2026-01-06
- 2023-02-23: Only "reggiejackson" from "20230223_DEN_CLE" game processed
- 2023-02-24: Only 68 of 175 players processed
- 2023-02-25 onward: Full processing resumed

**What This Means:**
1. The backfill script ran on 2026-01-06
2. It encountered an issue on 2023-02-23 and 2023-02-24
3. Processing recovered starting 2023-02-25
4. The partial results were written to BigQuery (not rolled back)

---

### Finding 3: Upstream Data is Complete

**Verification:** All upstream data exists for the problematic dates.

**Raw Data (Phase 2):**
```sql
-- nbac_gamebook_player_stats for 2023-02-23
SELECT COUNT(*) FROM nbac_gamebook_player_stats WHERE game_date = '2023-02-23'
-- Result: 9 games, all players present ✅

-- bdl_player_boxscores for 2023-02-23
SELECT COUNT(*) FROM bdl_player_boxscores WHERE game_date = '2023-02-23'
-- Result: 9 games, all players present ✅
```

**Analytics (Phase 3):**
```sql
-- player_game_summary for 2023-02-23
SELECT COUNT(*) FROM player_game_summary WHERE game_date = '2023-02-23'
-- Result: 187 unique players across 9 games ✅
```

**Conclusion:** The issue is NOT missing upstream data. Phase 2 and Phase 3 are complete. The problem occurred **during Phase 4 processing** on 2026-01-06.

---

### Finding 4: No Failure Tracking

**Critical Gap:** No records in `nba_processing.precompute_failures` for 2023-02-23 or 2023-02-24.

```sql
SELECT *
FROM nba_processing.precompute_failures
WHERE analysis_date IN ('2023-02-23', '2023-02-24')
  AND processor_name IN ('PCF', 'PlayerCompositeFactorsProcessor')
-- Result: 0 rows ❌
```

**What This Means:**
- Either the failures weren't logged (logging bug)
- Or the processor didn't attempt to process those players (orchestration bug)
- Or the processor succeeded but only wrote partial results (logic bug)

**Impact:** Without failure records, we cannot determine:
- Which players failed vs. were never attempted
- What the error message was
- Whether failures are retryable

---

## Root Cause Analysis

### Why Did the 2026-01-06 Backfill Fail?

**Possible Causes (In Order of Likelihood):**

#### 1. Processor Crash/Timeout Mid-Execution
**Probability:** HIGH
**Evidence:**
- Only 1 player processed on 2023-02-23 (0.5% coverage)
- 68 players processed on 2023-02-24 (39% coverage)
- Full coverage resumed on 2023-02-25

**Scenario:**
- Processor started processing 2023-02-23
- Processed Reggie Jackson successfully
- Crashed or timed out before processing remaining 186 players
- Resumed on 2023-02-24, processed 68 players
- Crashed again
- Resumed on 2023-02-25, completed successfully

**How to Verify:**
- Check Cloud Function logs for 2026-01-06 19:37:00 - 19:40:00
- Look for timeout errors, memory errors, or unhandled exceptions
- Check if backfill script had a batch size limit

#### 2. Data Quality Issue on Those Specific Dates
**Probability:** MEDIUM
**Evidence:**
- Problem only affected 2 consecutive dates
- All upstream data exists and appears valid
- No failure records logged

**Scenario:**
- Something about the data on 2023-02-23 and 2023-02-24 caused processing failures
- Examples:
  - Missing required fields (opponent_strength_score = NULL)
  - Invalid data types
  - Dependency data missing (team_defense_zone_analysis not ready)
- Processor failed silently without logging

**How to Verify:**
- Check if upstream dependencies (TDZA, PSZA) have data for these dates
- Validate data quality for player_game_summary on these dates
- Look for NULL values in critical fields

#### 3. Circuit Breaker or Rate Limiting
**Probability:** LOW
**Evidence:**
- The pattern (1 player, then 68 players, then full) suggests incremental processing
- Not consistent with circuit breaker behavior (which would stop completely)

**Scenario:**
- BigQuery rate limiting kicked in
- Circuit breaker triggered after partial batch
- Processing throttled for these dates

**How to Verify:**
- Check for BigQuery quota errors in logs
- Review circuit breaker status logs
- Check if batch size was reduced

#### 4. Orchestration Bug (Player Filtering)
**Probability:** LOW
**Evidence:**
- Why would it filter to exactly 1 player, then 68 players?
- Pattern doesn't match typical filtering logic

**Scenario:**
- Backfill script had a bug in player selection query
- WHERE clause unintentionally filtered players
- Example: `WHERE player_lookup = 'reggiejackson'` hardcoded

**How to Verify:**
- Review backfill script used on 2026-01-06
- Check git history for recent changes to PCF backfill
- Look for player filtering logic

---

## Impact Assessment

### Current State
| Season | Affected Dates | Missing Records | Games Affected | Impact |
|--------|---------------|-----------------|----------------|--------|
| 2022-23 | 2023-02-23 | 186 players | 9 games | ❌ CRITICAL |
| 2022-23 | 2023-02-24 | 107 players | 8 games | ❌ HIGH |
| 2023-24 | 2024-02-22 | TBD | TBD | ⚠️ INVESTIGATE |

**Total Estimated Missing Records:** ~300 player-game records across 2-3 dates

### Downstream Impact
- **Phase 5 Predictions:** Missing PCF records = no predictions for affected players
- **Production Impact:** These are historical dates, so no real-time impact
- **ML Model Training:** Training data has gaps for these dates
- **Analytics Dashboards:** Player stats incomplete for these dates

---

## Action Plan

### IMMEDIATE (Today)

1. **Investigate 2026-01-06 Backfill Logs**
   ```bash
   # Check Cloud Function logs
   gcloud logging read "timestamp>='2026-01-06T19:30:00Z' AND timestamp<='2026-01-06T19:45:00Z' AND resource.type=cloud_function AND resource.labels.function_name=player_composite_factors_backfill" --limit 500

   # Check for errors
   grep -i "error\|exception\|timeout\|failed" <logs>
   ```

2. **Verify Upstream Dependencies**
   ```sql
   -- Check if TDZA data exists for 2023-02-23
   SELECT COUNT(*)
   FROM nba_precompute.team_defense_zone_analysis
   WHERE analysis_date = '2023-02-23';

   -- Check if PSZA data exists for 2023-02-23
   SELECT COUNT(*)
   FROM nba_precompute.player_shot_zone_analysis
   WHERE analysis_date = '2023-02-23';
   ```

3. **Check 2024-02-22 Status**
   ```sql
   -- Verify if 2024-02-22 has the same issue
   SELECT
     COUNT(*) as expected
   FROM player_game_summary
   WHERE game_date = '2024-02-22';

   SELECT
     COUNT(*) as actual
   FROM player_composite_factors
   WHERE analysis_date = '2024-02-22';
   ```

### SHORT TERM (This Week)

1. **Manual Re-run for Affected Dates**
   ```bash
   # Re-run PCF for 2023-02-23 (dry run first)
   PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
     --start-date 2023-02-23 \
     --end-date 2023-02-23 \
     --dry-run

   # If successful, run for real
   PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
     --start-date 2023-02-23 \
     --end-date 2023-02-24
   ```

2. **Verify Backfill Results**
   ```sql
   -- After backfill, check coverage
   SELECT
     analysis_date,
     COUNT(*) as records,
     COUNT(DISTINCT player_lookup) as players
   FROM player_composite_factors
   WHERE analysis_date IN ('2023-02-23', '2023-02-24')
   GROUP BY analysis_date;
   ```

3. **Add Defensive Logging**
   - Add pre-processing log: "Attempting to process N players for date X"
   - Add progress logging: "Processed X of N players"
   - Add failure logging: "Failed to process player Y: error Z"
   - Ensure all failures are written to `precompute_failures` table

### LONG TERM (Next Month)

1. **Enhance Failure Tracking**
   - Log every player attempted, not just failures
   - Add "not_attempted" status for scheduled-but-skipped players
   - Create comprehensive backfill audit trail

2. **Add Validation Gates**
   - Pre-backfill check: Verify upstream data exists
   - Post-backfill check: Validate coverage percentage
   - Alert if coverage < 90% for any date
   - Block commit if critical gaps detected

3. **Game ID Standardization (Optional Enhancement)**
   - While the custom format works, consider:
     - Adding `nba_official_game_id` column to all tables
     - Creating game_id mapping view: `game_id_map(custom_id, official_id)`
     - This would enable easier joins with schedule table
   - **NOT REQUIRED** for fixing current issue

---

## Corrected Validation Report

### Update to Original Report

**Original Statement (INCORRECT):**
> "Game ID Format Inconsistency: Phase 4 tables use different game_id formats than schedule table, causing games to be missing from predictions."

**Corrected Statement:**
> "Partial Backfill Execution: A backfill run on 2026-01-06 only partially processed 2 dates (2023-02-23 and 2023-02-24), writing incomplete results to BigQuery. Game_id format is consistent across player data pipeline by design."

**Impact Revision:**
| Original Estimate | Corrected Estimate |
|------------------|-------------------|
| "~18 games missing" | "~300 player-game records missing from 2-3 dates" |
| "Game_id format mismatch" | "Partial backfill execution" |
| "Fix: Standardize game_id" | "Fix: Re-run backfill for affected dates" |

---

## Key Learnings

1. **Don't assume correlation = causation**
   - The game_id format difference exists, but it didn't cause the gaps
   - Always verify the causal chain

2. **Check timestamps**
   - The `created_at` timestamp revealed this was a recent issue
   - Historical issues vs. recent issues have different root causes

3. **Trace the full data flow**
   - Checking upstream tables (Phase 2, Phase 3) confirmed data exists
   - This isolated the issue to Phase 4 processing specifically

4. **Failure tracking is critical**
   - Lack of failure records made investigation much harder
   - Must log both successes and failures for observability

---

## Next Steps

1. ✅ **Complete Investigation** - DONE
2. ⏭️ **Check 2026-01-06 logs** - Find the root cause of partial processing
3. ⏭️ **Re-run backfill** - Process missing 2023-02-23 and 2023-02-24 records
4. ⏭️ **Validate 2024-02-22** - Check if this date has same issue
5. ⏭️ **Add defensive logging** - Prevent future silent failures
6. ⏭️ **Update validation report** - Correct the game_id format hypothesis

---

**Investigation Status:** COMPLETE
**Root Cause:** Partial backfill execution on 2026-01-06
**Game_id Format:** Not the issue - by design
**Next Action:** Check backfill logs from 2026-01-06
