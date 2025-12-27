# Challenge System Backend - Schema Alignment

**Created:** 2025-12-27
**Status:** In Progress
**Frontend Requirements Doc:** `/home/naji/code/props-web/docs/06-projects/current/challenge-system/BACKEND-DATA-REQUIREMENTS.md`

---

## Executive Summary

The Challenge System frontend requires specific data from two GCS endpoints. This document tracks the alignment between frontend requirements and backend implementation.

**Current State:** Several schema mismatches identified that need resolution before the Challenge System can function correctly.

---

## Endpoints Analyzed

| Endpoint | Backend File | Status |
|----------|--------------|--------|
| `/tonight/all-players.json` | `tonight_all_players_exporter.py` | Needs fixes |
| `/live/latest.json` | `live_scores_exporter.py` | Minor fixes |

---

## Issue Summary

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | `game_time` is NULL | **CRITICAL** | Open |
| 2 | Field name: `player_full_name` → `name` | High | Open |
| 3 | Field name: `team_abbr` → `team` | High | Open |
| 4 | Missing `props` array structure | High | Open |
| 5 | Missing `over_odds`/`under_odds` | Medium | Open |
| 6 | `game_id` format differs between endpoints | Low | Investigate |

---

## Detailed Issue Analysis

### Issue 1: `game_time` is NULL (CRITICAL)

**Impact:** Frontend cannot calculate challenge lock time

**Frontend Expects:**
```json
{
  "game_time": "7:30 PM ET"
}
```

**Backend Produces:**
```json
{
  "game_time": null
}
```

**Root Cause:**
`tonight_all_players_exporter.py:91-109` - The `_query_games()` method doesn't select any time field from the schedule table.

**Data Available:**
`nbac_schedule.game_date_est` contains game datetime as TIMESTAMP.

**Fix Required:**
```sql
-- Add to _query_games() SELECT clause:
FORMAT_TIMESTAMP('%I:%M %p ET', game_date_est, 'America/New_York') as game_time
```

**Verification:**
```sql
SELECT
  game_id,
  FORMAT_TIMESTAMP('%I:%M %p ET', game_date_est, 'America/New_York') as game_time
FROM nba_raw.nbac_schedule
WHERE game_date = '2025-12-27'
-- Returns: "07:00 PM ET", "08:00 PM ET", etc.
```

---

### Issue 2-3: Field Name Mismatches

**Location:** `tonight_all_players_exporter.py:338-341`

| Frontend Expects | Backend Produces | Fix |
|------------------|------------------|-----|
| `name` | `player_full_name` | Rename key |
| `team` | `team_abbr` | Rename key |

**Current Code:**
```python
player_data = {
    'player_lookup': player_lookup,
    'player_full_name': p.get('player_full_name', player_lookup),  # Wrong
    'team_abbr': p.get('team_abbr'),  # Wrong
    ...
}
```

**Fixed Code:**
```python
player_data = {
    'player_lookup': player_lookup,
    'name': p.get('player_full_name', player_lookup),  # Correct
    'team': p.get('team_abbr'),  # Correct
    ...
}
```

---

### Issue 4: Missing `props` Array Structure

**Frontend Expects:**
```json
{
  "props": [{
    "stat_type": "points",
    "line": 24.5,
    "over_odds": -110,
    "under_odds": -110
  }]
}
```

**Backend Produces:**
```json
{
  "current_points_line": 24.5,
  "predicted_points": 26.2,
  "confidence_score": 0.75,
  "recommendation": "OVER"
}
```

**Decision Needed:**
- Option A: Restructure backend to match frontend expectation
- Option B: Frontend adapts to current flat structure
- Option C: Provide both formats during transition

**Recommendation:** Option A - The `props` array is more extensible for future stat types (rebounds, assists, etc.)

---

### Issue 5: Missing Odds Data

**Frontend Expects:** `over_odds`, `under_odds` in props
**Backend Provides:** Neither field

**Data Available:**
`nba_raw.bettingpros_player_points_props` contains:
- `bet_side`: "over" or "under"
- `points_line`: The line value
- `odds_american`: American odds (e.g., -110, +100)
- `is_best_line`: Boolean for consensus line

**Query to Get Best Odds:**
```sql
WITH best_lines AS (
  SELECT
    player_lookup,
    game_date,
    points_line as line,
    MAX(CASE WHEN bet_side = 'over' THEN odds_american END) as over_odds,
    MAX(CASE WHEN bet_side = 'under' THEN odds_american END) as under_odds
  FROM nba_raw.bettingpros_player_points_props
  WHERE is_best_line = TRUE
    AND game_date = @target_date
  GROUP BY player_lookup, game_date, points_line
)
SELECT * FROM best_lines
```

**Implementation:** Add join to `_query_players()` in exporter.

---

### Issue 6: game_id Format Mismatch

**Tonight's Players:**
```json
{"game_id": "20251226_BOS_IND"}
```
Format: `YYYYMMDD_AWAY_HOME`

**Live Scores:**
```json
{"game_id": "18447237"}
```
Format: BallDontLie internal ID

**Impact Assessment:**
- If frontend matches picks by `game_id`: **BREAKING**
- If frontend matches picks by `player_lookup`: **OK**

**Investigation Needed:** Check frontend pick matching logic.

**Potential Fix:** Add formatted `game_id` to live scores using:
```python
# In live_scores_exporter.py, compute:
game_id = f"{game_date}_{away_abbr}_{home_abbr}".replace("-", "")
```

---

## player_lookup Consistency Analysis

**GOOD NEWS:** `player_lookup` IS consistent across endpoints!

| Source | Format | Example |
|--------|--------|---------|
| Tonight (BigQuery) | lowercase, no hyphens | `traeyoung` |
| Live (BDL cache) | lowercase, no hyphens | `traeyoung` |
| Live (fallback) | lowercase, alphanumeric | `traeyoung` |

**Note:** Frontend doc examples show `lebron-james` (with hyphen) but actual format is `lebronjames`.

---

## Implementation Plan

### Phase 1: Critical Fixes (Tonight's Players)
1. Add `game_time` to schedule query with proper formatting
2. Rename `player_full_name` → `name`
3. Rename `team_abbr` → `team`

### Phase 2: Props Structure
4. Restructure output to use `props` array
5. Add odds query and join to bettingpros data
6. Include `over_odds`/`under_odds` in props

### Phase 3: Live Scores Alignment
7. Investigate frontend game_id matching behavior
8. Add formatted game_id to live scores if needed

### Phase 4: Testing & Verification
9. Test with real data export
10. Verify frontend consumes updated format
11. Update mock data in props-web to match

---

## Files to Modify

| File | Changes |
|------|---------|
| `data_processors/publishing/tonight_all_players_exporter.py` | game_time, field renames, props array, odds join |
| `data_processors/publishing/live_scores_exporter.py` | game_id format (if needed) |

---

## Testing Commands

**Verify tonight's endpoint:**
```bash
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | jq '.games[0] | {game_id, game_time, first_player: .players[0]}'
```

**Verify live endpoint:**
```bash
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/live/latest.json" | jq '.games[0] | {game_id, status, first_player: .players[0]}'
```

---

## Changelog

| Date | Change |
|------|--------|
| 2025-12-27 | Initial analysis and documentation |
