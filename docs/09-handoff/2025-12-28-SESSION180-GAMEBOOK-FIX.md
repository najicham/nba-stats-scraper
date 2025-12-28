# Session 180: Gamebook Collection Fix

**Date:** 2025-12-28 (Morning)
**Duration:** ~1 hour
**Status:** Fixed and backfilled

---

## Issue Summary

**Problem:** Dec 27 had 9 games but only 1 gamebook (DAL@SAC) was collected, missing 8 games.

**Root Cause:** The `_resolve_nbac_gamebook_pdf()` function in `orchestration/parameter_resolver.py` was only returning the first game instead of all games. This was a "Phase 1" limitation that was never upgraded.

**Impact:** Gamebook data (DNP reasons, attendance, parsing info) was incomplete for Dec 27.

---

## Fix Applied

### Code Change
**File:** `orchestration/parameter_resolver.py` (lines 530-561)

**Before:**
```python
def _resolve_nbac_gamebook_pdf(self, context: Dict[str, Any]) -> Dict[str, Any]:
    games = context.get('games_today', [])
    if not games:
        return {}
    game = games[0]  # <-- ONLY FIRST GAME!
    # ... return single dict
```

**After:**
```python
def _resolve_nbac_gamebook_pdf(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    games = context.get('games_today', [])
    if not games:
        return []
    params_list = []
    for game in games:  # <-- ALL GAMES!
        # ... build params
        params_list.append({'game_code': game_code})
    return params_list
```

### Deployment
- Deployed to `nba-phase1-scrapers` (revision 00053-522)
- Took ~6 minutes

### Backfill
- Ran `scripts/backfill_gamebooks.py --date 2025-12-27`
- Duration: ~4 minutes (9 games, ~25 sec/game)
- Result: 315 player rows loaded to BigQuery

---

## Why This Wasn't Caught

### 1. No Gamebook Completeness Check
The cleanup_processor checks for missing Phase 2 processing but doesn't verify:
- Expected games vs actual gamebooks collected
- Compare schedule (9 games) vs gamebook data (1 game)

### 2. Logging Showed "Success"
Each individual run logged success:
```
nbac_gamebook_pdf: 2025-12-27 - success (3 records)
```
But only 1 game was processed - this looked normal in logs.

### 3. Self-Heal Focus on Predictions
The self-heal function (`orchestration/cloud_functions/self_heal/`) checks for missing predictions, not missing gamebook data.

---

## Improvements Needed

### 1. Add Gamebook Completeness Check (HIGH)
Add to cleanup_processor or daily health summary:
```python
def check_gamebook_completeness(target_date):
    """Compare schedule games vs gamebook rows collected."""
    query = """
    SELECT
        s.game_date,
        COUNT(DISTINCT s.game_id) as expected_games,
        COUNT(DISTINCT g.game_id) as actual_games
    FROM nba_raw.nbac_schedule s
    LEFT JOIN nba_raw.nbac_gamebook_player_stats g
        ON s.game_id = g.game_id
    WHERE s.game_date = @date AND s.game_status = 3
    GROUP BY s.game_date
    """
    # Alert if actual < expected
```

### 2. Fix Similar Resolvers (MEDIUM)
These resolvers have the same "first game only" issue:
- `_resolve_nbac_play_by_play()`
- `_resolve_game_specific()` (used by nbac_player_boxscore, bigdataball_pbp)
- `_resolve_game_specific_with_game_date()` (used by nbac_team_boxscore)

**Note:** These may work differently - some scrapers fetch all games at once by date.

### 3. Add Self-Heal for Gamebooks (LOW)
Extend self-heal function to check gamebook completeness and trigger backfills.

### 4. Monitoring Dashboard (LOW)
Add gamebook completeness to daily health summary email.

---

## Verification

### Before Fix
```
Dec 27 gamebooks: 1 game, 36 rows
```

### After Fix + Backfill
```
Dec 27 gamebooks: 9 games, 315 rows
```

---

## Related Files

- `orchestration/parameter_resolver.py` - Fixed resolver
- `scripts/backfill_gamebooks.py` - Backfill script used
- `orchestration/cleanup_processor.py` - Could add completeness check
- `orchestration/cloud_functions/self_heal/main.py` - Could extend for gamebooks

---

## Timeline

| Time (ET) | Action |
|-----------|--------|
| 10:54 AM | Started morning check, found issue |
| 11:15 AM | Identified root cause in parameter resolver |
| 11:19 AM | Applied fix, started deploy |
| 11:25 AM | Deploy complete (6 min) |
| 11:40 AM | Started backfill |
| 11:44 AM | Backfill complete (4 min) |
| 11:49 AM | Verified 9/9 games in BigQuery |

---

## Commits

```
TBD - Will commit after session
```
