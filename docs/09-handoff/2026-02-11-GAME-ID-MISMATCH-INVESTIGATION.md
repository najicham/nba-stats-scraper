# Game ID Format Mismatch - Systemic Investigation Request

**Date:** February 11, 2026
**Session:** 199 - Phase 3 Data Quality Investigation
**Status:** 🔴 **ROOT CAUSE IDENTIFIED - SYSTEMIC ISSUE SUSPECTED**
**Severity:** HIGH - Breaks joins across multiple tables

---

## Executive Summary

**Problem:** Phase 3 analytics has only 7/12 players with betting lines, missing key starters like Paolo Banchero, Jalen Suggs, Desmond Bane, and Myles Turner.

**Root Cause:** Game ID format mismatch between tables:
- **NBA Schedule:** Uses official NBA IDs (`0022500777`, `0022500776`)
- **Phase 3 Analytics:** Uses synthesized date format (`20260211_MIL_ORL`, `20260211_ATL_CHA`)

**Impact:** All joins between Phase 3 and other tables (betting lines, schedule, predictions) fail due to mismatched game_ids.

**Systemic Concern:** User reports seeing this game_id issue "pop up many times" - suggests this may be a widespread architectural problem affecting multiple parts of the pipeline.

---

## Investigation Timeline

### Starting Point
- Only 7/12 players with betting lines got predictions on Feb 11
- 10 players with betting lines missing from Phase 3
- 200 total players in Phase 3, but using wrong game_ids

### Discovery Process

1. **Initial Hypothesis:** Phase 3 not running
   - ❌ **Rejected:** Phase 3 ran successfully twice (5 PM yesterday, 10:30 AM today)
   - Evidence: 200 players created across 28 teams

2. **Second Hypothesis:** Injury reports filtering out starters
   - ❌ **Rejected:** Missing players have betting lines (sportsbooks think they'll play)
   - Pattern: Only bench players in Phase 3, starters missing

3. **Third Hypothesis:** Gamebook data missing for today's games
   - ✅ **CONFIRMED:** Gamebook is empty for Feb 11 (games scheduled but not played)
   - But Phase 3 still created 200 records - how?

4. **Root Cause Discovery:** Game ID format mismatch
   - ✅ **CONFIRMED:** Phase 3 and Schedule use different game_id formats
   - All joins fail, breaking the entire pipeline

---

## Technical Details

### Game ID Format Comparison

| Source | Format | Example | Count (Feb 11) |
|--------|--------|---------|----------------|
| **nba_raw.nbac_schedule** | NBA Official | `0022500777` | 14 games |
| **nba_analytics.upcoming_player_game_context** | Date-Based | `20260211_MIL_ORL` | 14 games |
| **nba_raw.odds_api_player_points_props** | NBA Official | `0022500777` | 12 players |
| **nba_raw.nbac_gamebook_player_stats** | Date-Based | `20260211_MIL_ORL` | 0 (games not played) |

### Join Failure Example

**Orlando Magic Game:**
- **Schedule game_id:** `0022500777` (MIL @ ORL)
- **Phase 3 game_id:** `20260211_MIL_ORL`
- **Betting lines game_id:** `0022500777` (uses schedule)

**Phase 3 Players (wrong game_id):**
```
colincastleton, franzwagner, gogabitadze, jamalcain, orlandorobinson
```

**Missing Players (have betting lines but not in Phase 3):**
```
paolobanchero (line: 20.5), jalensuggs (line: 13.5)
```

**Why missing:** Betting lines use schedule game_id `0022500777`, Phase 3 uses `20260211_MIL_ORL` - join fails.

---

## Code Location

### Phase 3 Game ID Source

**File:** `data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py`

**Function:** `gamebook_players_with_games_cte()`

```python
def gamebook_players_with_games_cte(project_id: str) -> str:
    return f"""players_with_games AS (
        SELECT DISTINCT
            g.player_lookup,
            s.game_id,  -- ❌ Uses schedule game_id but...
            g.team_abbr,
            ...
        FROM `{project_id}.nba_raw.nbac_gamebook_player_stats` g  -- ❌ This is EMPTY for future dates
        LEFT JOIN schedule_data s
            ON g.game_id = s.game_id  -- ❌ g.game_id is date-based, s.game_id is NBA official
        WHERE g.game_date = @game_date
    )"""
```

**Problems:**
1. Gamebook uses date-based game_ids (`20260211_MIL_ORL`)
2. Schedule uses NBA official game_ids (`0022500777`)
3. JOIN on mismatched formats fails
4. For upcoming games, gamebook is EMPTY, so entire CTE returns 0 rows
5. Yet somehow Phase 3 creates 200 records with wrong game_ids

---

## Mystery: How Did 200 Records Get Created?

**Observed Behavior:**
- Gamebook for Feb 11: **0 players, 0 games** (verified)
- Phase 3 for Feb 11: **200 players** (verified)
- Records created: Feb 10 22:00 UTC (5 PM ET yesterday)

**Question:** If gamebook is empty and it's the DRIVER query, where did the 200 players come from?

**Hypothesis:** There may be a fallback mechanism or alternate code path we haven't discovered yet. Need to investigate:
1. Is there a roster-based fallback when gamebook is empty?
2. Is there a different query for "upcoming" vs "historical" mode?
3. Is the processor incorrectly synthesizing game_ids when joins fail?

---

## Systemic Impact Assessment

### Tables Known to Use Date-Based Game IDs

1. ✅ **nba_raw.nbac_gamebook_player_stats** - `20260211_MIL_ORL`
2. ✅ **nba_analytics.upcoming_player_game_context** - `20260211_MIL_ORL`
3. ❓ **nba_analytics.player_game_summary** - Need to verify
4. ❓ **nba_predictions.player_prop_predictions** - Need to verify
5. ❓ **Other Phase 3 tables** - Need to audit

### Tables Known to Use NBA Official IDs

1. ✅ **nba_raw.nbac_schedule** - `0022500777`
2. ✅ **nba_raw.odds_api_player_points_props** - `0022500777`
3. ✅ **nba_raw.odds_api_game_lines** - `0022500777`
4. ❓ **Phase 4 precompute tables** - Need to verify
5. ❓ **Phase 5 prediction tables** - Need to verify

### Known Join Failures

1. ✅ **Phase 3 ↔ Betting Lines** - Confirmed broken (this investigation)
2. ✅ **Phase 3 ↔ Schedule** - Likely broken
3. ❓ **Phase 3 ↔ Phase 4** - Need to verify
4. ❓ **Phase 4 ↔ Phase 5** - Need to verify
5. ❓ **Predictions ↔ Grading** - Need to verify (could explain hit rate issues?)

---

## Questions for Opus

### 1. Scope of the Problem

**Question:** Should we do a comprehensive audit of game_id usage across all 6 phases?

**Approach:**
- Search all BigQuery schemas for game_id columns
- Identify which format each table uses
- Map all JOINs that cross format boundaries
- Estimate impact on pipeline

**Estimated effort:** 2-3 hours for full audit

### 2. Historical Context

**Question:** When did the schedule switch from date-based to NBA official IDs?

**Importance:**
- Historical data may have inconsistent game_ids
- Backfills may fail silently
- ML model training data could be corrupted
- Grading accuracy could be affected

**Investigation needed:**
```sql
-- Check when format changed
SELECT
  game_date,
  COUNT(CASE WHEN game_id LIKE '002250%' THEN 1 END) as nba_official,
  COUNT(CASE WHEN game_id LIKE '202%' THEN 1 END) as date_based
FROM nba_raw.nbac_schedule
WHERE game_date >= '2025-11-01'
GROUP BY 1
ORDER BY 1
```

### 3. Fix Strategy

**Option A: Standardize on NBA Official IDs**
- **Pros:** Matches NBA.com, official source of truth
- **Cons:** Requires migrating all date-based tables (gamebook, Phase 3, etc.)
- **Risk:** High - breaks existing data, requires backfills

**Option B: Standardize on Date-Based IDs**
- **Pros:** Simpler format, easier to construct
- **Cons:** Not official, conflicts with NBA.com sources
- **Risk:** Medium - requires transforming schedule and odds data

**Option C: Dual-Format Support**
- **Pros:** No migration needed, backward compatible
- **Cons:** Complexity, ongoing maintenance burden
- **Risk:** Low - add conversion functions, use in JOINs

**Recommendation needed:** Which strategy aligns with long-term architecture?

### 4. Immediate Fix for Feb 11

**Question:** Should we fix just Phase 3 for today, or wait for systemic fix?

**Quick fix approach:**
- Modify Phase 3 query to convert schedule game_ids to date format
- Re-run Phase 3 for Feb 11
- Get predictions working for tonight's games

**Risk:** Band-aid fix that doesn't solve systemic issue

**Alternative:** Fix comprehensively but delay today's predictions

### 5. Related Issues

**Question:** Could this explain other pipeline failures we've seen?

**Potential connections:**
- Session 195 scheduler bug (processes wrong date) - related to game_id confusion?
- Model hit rate decay - grading joins failing due to game_id mismatch?
- Phase 4 occasional gaps - upstream joins failing?
- Prediction coverage variance - inconsistent game_id matching?

---

## Proposed Investigation Plan

### Phase 1: Audit (2-3 hours)
1. **Map all game_id usage across BigQuery**
   - Query information_schema for all tables with game_id column
   - Sample data to identify format
   - Document findings in spreadsheet

2. **Identify all JOINs on game_id**
   - Grep codebase for "ON.*game_id"
   - Classify as same-format or cross-format
   - Flag high-risk joins (critical pipeline paths)

3. **Check historical consistency**
   - Query schedule for format change date
   - Verify gamebook format over time
   - Check if Phase 3 format has changed

### Phase 2: Impact Analysis (1-2 hours)
1. **Test known failures**
   - Verify Phase 3 ↔ Betting Lines join
   - Check Phase 3 ↔ Schedule join
   - Test Phase 4 ↔ Phase 3 join

2. **Quantify data loss**
   - Count predictions lost due to mismatches
   - Calculate revenue impact
   - Identify affected date ranges

3. **Check ML model training**
   - Verify grading data integrity
   - Check if training joins succeeded
   - Assess model quality impact

### Phase 3: Solution Design (1 hour)
1. **Choose standardization strategy**
   - Option A, B, or C above
   - Get user approval

2. **Design migration plan**
   - Identify tables to modify
   - Plan backfill strategy
   - Define rollout phases

3. **Create conversion utilities**
   - Build game_id format converter
   - Add to shared utils
   - Write tests

### Phase 4: Implementation (2-4 hours)
1. **Fix Phase 3 query**
   - Update shared_ctes.py
   - Add format conversion
   - Test with Feb 11 data

2. **Fix other critical joins**
   - Phase 4 queries
   - Prediction coordinator
   - Grading queries

3. **Backfill affected dates**
   - Re-run Phase 3 for recent dates
   - Verify predictions improve
   - Check grading accuracy

### Phase 5: Prevention (1 hour)
1. **Add validation**
   - Pre-commit hook to check game_id JOINs
   - Schema validator for format consistency
   - Integration tests for cross-phase joins

2. **Document standards**
   - Update CLAUDE.md with game_id format rules
   - Add to schema design guidelines
   - Create troubleshooting guide

**Total Estimated Effort:** 7-11 hours for comprehensive fix

---

## Immediate Action Items

### For Tonight's Games (Feb 11)

**Option 1: Quick Fix**
```bash
# Fix Phase 3 query to use schedule game_ids
# Re-run Phase 3
gcloud scheduler jobs run same-day-phase3

# Verify predictions
bq query "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = '2026-02-11'"
```

**Option 2: Wait for Systemic Fix**
- Accept reduced coverage for tonight
- Fix comprehensively starting tomorrow
- Prevents band-aid fixes

### For Long-Term Health

1. **Get Opus direction** on fix strategy (this doc)
2. **Audit game_id usage** across all tables
3. **Design migration plan** with user approval
4. **Implement systematically** across all phases
5. **Add prevention** mechanisms

---

## Key Questions Requiring Decisions

1. ❓ **Audit scope:** Full 6-phase audit or just fix Phase 3?
2. ❓ **Standardization strategy:** Option A (NBA official), B (date-based), or C (dual-format)?
3. ❓ **Timeline:** Quick fix for tonight or comprehensive fix over 2-3 days?
4. ❓ **Historical data:** Backfill all affected dates or just fix going forward?
5. ❓ **Prevention:** What validation should we add to prevent recurrence?

---

## Next Steps

**Waiting for Opus to:**
1. Review this analysis
2. Provide direction on fix strategy
3. Approve audit scope and timeline
4. Guide on historical investigation depth

**Once direction received:**
1. Execute chosen approach
2. Document findings
3. Update architecture docs
4. Add prevention mechanisms

---

## Files Referenced

### Code Files
- `data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py` (Line 13-35)
- `data_processors/analytics/upcoming_player_game_context/loaders/player_loaders.py`
- `data_processors/analytics/main_analytics_service.py` (Line 772-850)

### Related Documentation
- `docs/09-handoff/2026-02-11-SESSION-195-HANDOFF.md` - Phase 3 data gap investigation
- `docs/09-handoff/2026-02-11-SESSION-198-HANDOFF.md` - Phase 2→3 orchestrator fix
- `CLAUDE.md` - Project architecture

### BigQuery Tables Affected
- `nba_raw.nbac_schedule` - NBA official IDs
- `nba_raw.nbac_gamebook_player_stats` - Date-based IDs
- `nba_analytics.upcoming_player_game_context` - Date-based IDs (BROKEN)
- `nba_raw.odds_api_player_points_props` - NBA official IDs
- `nba_predictions.player_prop_predictions` - Format unknown

---

**Status:** Awaiting Opus review and strategic direction
**Priority:** HIGH - Blocking predictions for 10+ players daily
**Complexity:** MEDIUM-HIGH - Systemic issue across multiple phases
