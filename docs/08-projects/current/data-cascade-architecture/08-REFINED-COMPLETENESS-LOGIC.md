# Refined Completeness Logic: What Data Should We Expect?

**Document:** 08-REFINED-COMPLETENESS-LOGIC.md
**Created:** January 22, 2026
**Status:** Discussion Draft

---

## The Core Question

When we say "this player's rolling window is incomplete," what does that actually mean?

**Current approach:** Schedule-based inference
- Look at player's current team
- Look at that team's schedule
- Assume player should have played in most games

**Problem:** This doesn't account for:
- Mid-season trades (player wasn't on this team for old games)
- Injuries (player was on roster but didn't play)
- DNP (coach's decision)
- Suspensions

---

## What Data Do We Actually Have?

| Table | What It Contains | Useful For |
|-------|------------------|------------|
| `player_game_summary` | **Actual games played** with `team_abbr` | Source of truth for player history |
| `nbac_gamebook` | All players on roster for each game (incl. DNP) | Distinguishing DNP vs missing |
| `bdl_player_boxscores` | Box scores with minutes (0 min = DNP) | DNP detection |
| `nbac_schedule` | Game dates by team | Team-level completeness |
| `nbac_team_boxscore` | Team box scores | Raw data verification |

**Key insight:** `player_game_summary.team_abbr` tells us what team the player was on FOR EACH SPECIFIC GAME. We don't need to infer from rosters.

---

## Two Types of Completeness

### Type 1: Raw Data Completeness (Batch Level)

**Question:** Do we have the raw source data for all games that happened?

**Check:**
- For each date in the window
- Verify `nbac_team_boxscore` has records
- Verify `nbac_gamebook` has records

**If missing:** This is a SYSTEM FAILURE. We need to backfill.

This is **batch-level** because it's about the raw data, not specific players.

---

### Type 2: Player Analytics Completeness (Player Level)

**Question:** For games this player actually played in, do we have their analytics data?

**Check:**
- Query `nbac_gamebook` for games where player appears (with minutes > 0)
- Verify `player_game_summary` has matching records

**If analytics missing but gamebook present:** This is a PROCESSING GAP.

This is **player-level** because it's about specific player records.

---

## The Refined Logic

### Step 1: Determine Player's Actual Game History

Don't predict. Just look at what games they played:

```python
def get_player_game_history(player_lookup, target_date, lookback_days=60):
    """
    Get games this player ACTUALLY played in.
    Uses player_game_summary which has team_abbr per game.
    Handles trades automatically - no inference needed.
    """
    query = """
    SELECT
        game_date,
        team_abbr,  -- Player's team for THIS game (handles trades)
        minutes_played,
        points
    FROM nba_analytics.player_game_summary
    WHERE player_lookup = @player
      AND game_date < @target_date
      AND game_date >= DATE_SUB(@target_date, INTERVAL @lookback DAY)
      AND minutes_played > 0  -- Exclude any 0-minute records
    ORDER BY game_date DESC
    """
```

**This gives us:** The games the player actually played, with their team at that time.

---

### Step 2: Assess Window Quality

Now we have the player's actual game history. Assess quality:

```python
def assess_window_quality(games, window_size=10):
    """
    Assess the quality of a player's rolling window.
    """
    games_found = len(games)

    if games_found == 0:
        return {
            'status': 'NO_HISTORY',
            'reason': 'new_player_or_no_recent_games',
            'is_complete': False,
            'needs_investigation': False  # Expected for new players
        }

    if games_found < window_size:
        return {
            'status': 'INCOMPLETE_WINDOW',
            'reason': 'fewer_games_than_window',
            'games_found': games_found,
            'games_expected': window_size,
            'is_complete': False,
            'needs_investigation': True  # Why fewer games?
        }

    # Check window span
    oldest = games[-1]['game_date']
    newest = games[0]['game_date']
    span_days = (newest - oldest).days

    if span_days > 28:  # More than 4 weeks for 10 games
        return {
            'status': 'STALE_WINDOW',
            'reason': 'window_spans_too_long',
            'window_span_days': span_days,
            'is_complete': True,  # We have the games
            'is_stale': True,
            'needs_investigation': True  # Why so spread out?
        }

    return {
        'status': 'COMPLETE',
        'games_found': games_found,
        'window_span_days': span_days,
        'is_complete': True,
        'is_stale': False
    }
```

---

### Step 3: Investigate Gaps (When Needed)

Only when `needs_investigation = True`, dig deeper:

```python
def investigate_gap(player_lookup, target_date, expected_span_days=21):
    """
    Investigate WHY a player has fewer games or a stale window.

    Possible reasons:
    - New player (first career games)
    - Injury/illness
    - Trade (switched teams)
    - Suspension
    - Raw data gap (system failure)
    """

    # 1. Check if player is new
    career_start = get_career_start_date(player_lookup)
    if career_start and (target_date - career_start).days < 60:
        return {'reason': 'NEW_PLAYER', 'expected': True}

    # 2. Check for DNP games (gamebook shows player but 0 minutes)
    dnp_games = get_dnp_games(player_lookup, target_date, expected_span_days)
    if dnp_games:
        return {
            'reason': 'DNP_GAMES',
            'dnp_dates': dnp_games,
            'expected': True  # DNP is a valid absence
        }

    # 3. Check for team schedule gaps (team didn't play)
    team_abbr = get_most_recent_team(player_lookup, target_date)
    team_schedule = get_team_schedule(team_abbr, target_date, expected_span_days)
    # Compare to player games...

    # 4. Check for raw data gaps (system failure)
    raw_gaps = check_raw_data_gaps(target_date, expected_span_days)
    if raw_gaps:
        return {
            'reason': 'RAW_DATA_GAP',
            'missing_dates': raw_gaps,
            'expected': False,  # This is a problem!
            'needs_backfill': True
        }

    return {'reason': 'UNKNOWN', 'needs_manual_review': True}
```

---

## The Key Distinction

### Expected Absences (NOT a data problem)

| Reason | How We Know | Action |
|--------|-------------|--------|
| **New player** | Career start date recent | Flag `is_new_player = True` |
| **Injury/illness** | DNP in gamebook (0 min) | Flag `reason = 'injury_dnp'` |
| **Rest day** | DNP in gamebook (0 min) | Flag `reason = 'rest_dnp'` |
| **Trade** | Different team_abbr in recent games | Flag `teams_in_window = ['LAL', 'BOS']` |
| **Suspension** | Not in gamebook, then returns | Flag `reason = 'suspension'` |
| **All-Star break** | Calendar date range | Flag `is_allstar_break = True` |

**These are legitimate. Rolling average uses fewer games but that's CORRECT.**

---

### Unexpected Absences (DATA PROBLEM)

| Reason | How We Know | Action |
|--------|-------------|--------|
| **Raw data gap** | `nbac_team_boxscore` missing for dates | **BACKFILL NEEDED** |
| **Processing gap** | Gamebook has player, analytics doesn't | **REPROCESS NEEDED** |
| **Unknown gap** | Can't determine reason | **INVESTIGATE** |

**These are problems. Features calculated with missing data are BIASED.**

---

## Handling Trades Specifically

**The trade scenario:**
- Player on Team A through Jan 10
- Player on Team B from Jan 11

**Old approach (problematic):**
1. Look up current team → Team B
2. Look at Team B's schedule
3. "Player should have 15 games" (wrong - only with Team B since Jan 11)

**New approach (correct):**
1. Query `player_game_summary` for player's actual games
2. Each game has `team_abbr` showing which team
3. 10-game window might include: 7 games with Team B, 3 games with Team A
4. All games are valid - trade doesn't create a "gap"

**The insight:** We don't need to know WHEN the trade happened. The `team_abbr` field in each game record tells us everything.

```python
# Example: Player's 10-game window after trade
[
    {'date': '2026-01-20', 'team': 'BOS', 'points': 28},  # New team
    {'date': '2026-01-18', 'team': 'BOS', 'points': 24},
    {'date': '2026-01-15', 'team': 'BOS', 'points': 31},
    {'date': '2026-01-12', 'team': 'BOS', 'points': 22},
    {'date': '2026-01-08', 'team': 'LAL', 'points': 27},  # Old team
    {'date': '2026-01-05', 'team': 'LAL', 'points': 25},
    {'date': '2026-01-03', 'team': 'LAL', 'points': 30},
    {'date': '2026-01-01', 'team': 'LAL', 'points': 29},
    {'date': '2025-12-28', 'team': 'LAL', 'points': 26},
    {'date': '2025-12-26', 'team': 'LAL', 'points': 24},
]
# is_complete = True
# teams_in_window = ['BOS', 'LAL']
```

---

## Handling Injuries

**The injury scenario:**
- Player injured Jan 5-15
- Missed 5 team games during that period

**How we detect:**
1. Gamebook shows player with 0 minutes (or not in gamebook at all)
2. `bdl_player_boxscores` shows minutes = '00'

**Action:**
- These games are NOT expected to be in `player_game_summary`
- Rolling window correctly excludes them
- Flag: `dnp_games_in_window = 5`

**The insight:** If a player was injured, their 10-game window should span MORE calendar days. This is CORRECT behavior, not a bug.

```python
# Example: Player's 10-game window with injury
# Injured Jan 5-15, missed 5 games

# 10 games spanning 30 days (instead of usual 21 days)
# is_complete = True (we have all games they played)
# is_stale = True (window spans > 21 days)
# reason = 'injury_period'
# dnp_dates = ['2026-01-05', '2026-01-07', '2026-01-10', '2026-01-12', '2026-01-14']
```

---

## Refined Completeness Categories

| Category | Meaning | is_complete | Action |
|----------|---------|-------------|--------|
| **COMPLETE** | Have all games, window healthy | True | None |
| **COMPLETE_STALE** | Have all games, but span > 21 days | True | Flag for review |
| **COMPLETE_TRADED** | Have all games, multiple teams | True | Informational |
| **INCOMPLETE_NEW** | Player is new, <10 career games | False | Expected, use what we have |
| **INCOMPLETE_INJURY** | DNP games detected in window | False | Expected, use what we have |
| **INCOMPLETE_GAP** | Raw data missing (system failure) | False | **NEEDS BACKFILL** |
| **INCOMPLETE_UNKNOWN** | Can't determine reason | False | **INVESTIGATE** |

---

## Implementation Change

### Old: Schedule-based expectation

```python
# What we were doing
expected_games = count_team_schedule_games(player_team, window_days)
actual_games = count_player_games(player)
is_complete = actual_games >= expected_games * 0.8
```

### New: Actual-game-based with investigation

```python
# What we should do
player_games = get_player_actual_games(player, window_size=10)
games_found = len(player_games)
window_span = calculate_window_span(player_games)

if games_found < 10:
    # Investigate why
    reason = investigate_gap(player, target_date)
    if reason.expected:
        # DNP, new player, injury - legitimate
        is_complete = True  # Complete for what we can expect
        completeness_reason = reason.type
    else:
        # Data gap - problem
        is_complete = False
        needs_backfill = True
else:
    if window_span > 21:
        # Have games but spread out - likely injury period
        is_complete = True
        is_stale = True
    else:
        # Normal complete window
        is_complete = True
```

---

## Summary

| Question | Old Answer | New Answer |
|----------|------------|------------|
| "What games should exist?" | Team schedule - player roster | Player's actual games from player_game_summary |
| "How handle trades?" | Infer from current team | team_abbr in each game record |
| "How handle injuries?" | Unknown/assumed missing | DNP detection from gamebook/boxscores |
| "What's incomplete?" | <80% of schedule | Can't find expected games after investigation |

**Key principle:** Don't PREDICT what should exist. VERIFY what does exist, then INVESTIGATE anomalies.

---

## Questions for Discussion

1. **DNP data quality:** How reliable is our DNP detection? If gamebook is missing, we can't distinguish DNP from data gap.

2. **New player threshold:** How many games before we consider a player "established" vs "new"?

3. **Stale window threshold:** Is 21 days right? 28 days? Should it be configurable?

4. **Investigation cost:** Should we investigate all anomalies or only flag for later?

---

**Document Status:** Draft for Discussion
