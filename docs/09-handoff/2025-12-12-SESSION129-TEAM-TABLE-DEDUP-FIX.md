# Session 129 Handoff - Team Table Deduplication Fix

**Date:** 2025-12-12
**Focus:** Fixed critical 4x data duplication in team_defense/offense_game_summary tables
**Duration:** ~1 hour

---

## Executive Summary

During Phase 3 validation, discovered that `team_defense_game_summary` and `team_offense_game_summary` had **4x data duplication** (40,382 rows instead of ~10,400). Root cause traced to duplicate rows in the raw source `nbac_team_boxscore`.

**Fix Applied:**
1. Added ROW_NUMBER() deduplication to both processors
2. Cleaned up existing analytics tables (deleted 59,940 duplicate rows total)

---

## Root Cause Analysis

### The Problem

```
Raw source: nbac_team_boxscore
- 5,294 unique games
- 20,756 total rows (should be ~10,588)
- ~2x duplicates per team-game (different processed_at timestamps)
- Bulk load on 2025-11-26 created the duplicates
```

### How It Cascaded to 4x

Both team processors do a **self-join** to flip perspective:
- Team A's defense = Team B's offense (and vice versa)
- With 2 duplicates per team: `2 rows × 2 opponent rows = 4 rows` per team-game

### Why It Wasn't Caught

- `MERGE_UPDATE` strategy deletes by date range before insert
- But duplicates were generated **within** a single batch (Cartesian product in the JOIN)
- All 4 rows had identical timestamps

---

## Fix Details

### 1. Processor Changes

**Files Modified:**
- `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`
- `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`

**Change:** Added ROW_NUMBER() deduplication CTE before self-join:

```sql
WITH game_teams_raw AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY game_id, team_abbr
            ORDER BY processed_at DESC
        ) as rn
    FROM nbac_team_boxscore
    WHERE game_date BETWEEN ...
),
game_teams AS (
    SELECT * EXCEPT(rn) FROM game_teams_raw WHERE rn = 1
),
-- ... rest of query uses deduplicated game_teams
```

### 2. Data Cleanup

```sql
-- Deleted duplicates keeping most recent created_at
DELETE FROM team_defense_game_summary
WHERE STRUCT(game_id, defending_team_abbr, created_at) NOT IN (
    SELECT AS STRUCT game_id, defending_team_abbr, MAX(created_at)
    FROM team_defense_game_summary
    GROUP BY game_id, defending_team_abbr
)
-- Result: 29,970 rows deleted

-- Same for team_offense_game_summary
-- Result: 29,970 rows deleted
```

### 3. Verification

| Table | Before | After | Status |
|-------|--------|-------|--------|
| team_defense_game_summary | 40,382 | 10,412 | NO_DUPLICATES |
| team_offense_game_summary | 40,382 | 10,412 | NO_DUPLICATES |

---

## Other Issues Found (Not Fixed This Session)

| Issue | Severity | Notes |
|-------|----------|-------|
| `nbac_team_boxscore` has 2x duplicates | Medium | Root cause - processors now handle it |
| `player_game_summary` has 99.6% NULL minutes_played | Low | **Investigated - see below** |
| 137 playoff dates missing from Phase 3 | Expected | Backfill scope was regular season |
| 17-40% player coverage gaps | Medium | Registry failures - known issue |

### minutes_played NULL Investigation

**Diagnosis:** The backfill was run before the minutes parsing code was fully working.

- 423 records WITH minutes_played - processed on 2025-12-11 (recent production runs)
- 106,968 records WITHOUT minutes_played - from bulk backfill (older code)

**Evidence:**
- Raw source `nbac_gamebook_player_stats` has 100% valid minutes data
- Processor code DOES have minutes parsing (`_parse_minutes_to_decimal`)
- Recent runs correctly populate minutes_played

**Fix:** Re-run player_game_summary backfill with current processor code.
**Priority:** Low - minutes_played not critical for Phase 4 predictions.

---

## Lessons Learned

1. **Always validate data quality before Phase 4** - duplicates cascade downstream
2. **Raw data can have duplicates** - processors should be defensive with ROW_NUMBER()
3. **Self-joins amplify duplicates** - N duplicates × N opponent duplicates = N² rows

---

## Follow-Up Recommendations

1. **Consider deduplicating `nbac_team_boxscore`** - prevents issue for any future processors
2. **Add unique constraints** or validation to analytics tables
3. **Investigate minutes_played NULL** issue in player_game_summary

---

## Current Status

- Phase 3 backfill: ~50% complete (32/66 dates for upcoming_player_game_context)
- Team tables: Fixed and validated
- Ready for Phase 4 once Phase 3 completes
