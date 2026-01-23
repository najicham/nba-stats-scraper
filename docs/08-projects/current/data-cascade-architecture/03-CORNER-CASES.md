# Corner Cases and Edge Scenarios

**Document:** 03-CORNER-CASES.md
**Created:** January 22, 2026

---

## Overview

This document catalogs all edge cases, corner cases, and special scenarios that the data cascade system must handle correctly. Each case includes the scenario, expected behavior, and implementation considerations.

---

## Category 1: Player-Specific Scenarios

### Case 1.1: New Player (Rookie/First NBA Game)

**Scenario:** Player's first NBA game ever. No historical data exists.

**Current behavior:** Returns empty rolling window, features use defaults.

**Expected behavior:**
- `games_found = 0`
- `is_complete = False` (no history exists)
- `is_new_player = True` (special flag)
- Features should use league averages or be flagged as unreliable

**Implementation note:** Distinguish between "no data because missing" vs "no data because player is new". New players are NOT incomplete - they're a special case.

```python
if games_found == 0:
    if is_first_career_game(player_lookup, game_date):
        return {'is_complete': True, 'is_new_player': True}
    else:
        return {'is_complete': False, 'missing_reason': 'no_historical_data'}
```

---

### Case 1.2: Returning from Long Injury

**Scenario:** Player was injured for 30+ days, returns to play. Their last 10 games span 2+ months.

**Example:**
- LeBron injured Nov 15
- Returns Jan 15
- Last 10 games: Jan 15, Nov 14, Nov 12, Nov 10...
- Window span: 62 days

**Expected behavior:**
- `is_complete = True` (we have all 10 games from before injury)
- `is_stale = True` (window spans > 21 days)
- `staleness_reason = 'player_injury_return'`

**Question:** Is this incomplete or just stale?
**Answer:** It's COMPLETE (we have the games) but STALE (data is old). Different from MISSING.

---

### Case 1.3: Mid-Season Trade

**Scenario:** Player traded Jan 10. Playing for new team Jan 15.

**Complications:**
- Schedule lookup uses current team
- Historical games were with different team
- Team-specific features (pace, offensive rating) may be mismatched

**Expected behavior:**
- Track team at time of each contributing game
- Flag if contributing games span multiple teams
- `teams_in_window = ['LAL', 'BOS']` (for example)

**Implementation note:** May need to handle team context differently for traded players.

---

### Case 1.4: Player Waived and Re-Signed

**Scenario:** Player cut Jan 5, re-signed Jan 15, plays Jan 20.

**Complications:**
- Gap in roster membership
- Games before waiver still valid
- But schedule-based expectation might be off

**Expected behavior:**
- Use actual games played (from `player_game_summary`)
- Don't expect games during waiver period
- `was_waived_in_window = True`

---

### Case 1.5: DNP (Did Not Play) Games

**Scenario:** Player on roster but DNP (coach's decision, rest, minor injury).

**Example:**
- Team played Jan 10, 12, 14, 16, 18
- Player played Jan 10, 12, 16, 18 (DNP on Jan 14)
- Looking for last 5 games on Jan 20

**Expected behavior:**
- DNP games should NOT be in expected count
- If player has 4 games out of 4 played, that's 100% complete
- Need to check raw boxscore to confirm DNP vs missing data

**Current handling:** The completeness checker has DNP-aware mode that excludes 0-minute games.

```python
# From completeness_checker.py
def _get_dnp_games(player_lookup, window_start, window_end):
    # Query raw boxscores for games where player had 0 minutes
    # These are DNP, not missing data
```

---

### Case 1.6: Player Suspended

**Scenario:** Player suspended for 5 games. Returns and plays.

**Similar to injury but:**
- Suspension is known in advance
- Games missed are "expected" to be missing

**Expected behavior:**
- Don't count suspended games as "missing"
- Track `suspension_games_in_window = 3`
- Still `is_complete = True` if we have all non-suspended games

---

## Category 2: Schedule-Related Scenarios

### Case 2.1: All-Star Break

**Scenario:** Processing games around All-Star break (typically 5-7 day gap).

**Example:**
- Last game before break: Feb 14
- First game after break: Feb 21
- Looking for last 10 games on Feb 22

**Expected behavior:**
- Window span will be larger than normal (~28 days instead of ~21)
- This is EXPECTED, not a problem
- `is_all_star_break_affected = True`

**Implementation note:** Need calendar awareness for All-Star break dates.

---

### Case 2.2: Season Start (First 10 Games)

**Scenario:** October 25, player has only played 5 games total.

**Expected behavior:**
- `games_found = 5`
- `games_expected = 5` (can't expect more than played)
- `is_complete = True` (we have all available games)
- `is_early_season = True`

**Current handling:** Bootstrap mode exists but only for first 7 days.

**Needed:** Extend to handle "player has < 10 career games" case.

---

### Case 2.3: Playoffs (Irregular Schedule)

**Scenario:** Playoff series where teams play every 2-3 days vs. opponents.

**Differences:**
- Same opponent repeatedly
- Potentially 4-7 games against single team
- Window span is shorter (10 games in ~3 weeks)

**Expected behavior:**
- Same completeness rules apply
- But opponent_history features are unusual (multiple recent games vs same team)
- Consider flagging playoff features differently

---

### Case 2.4: Postponed/Cancelled Games

**Scenario:** Game scheduled but postponed (COVID, weather, etc.).

**Expected behavior:**
- Postponed game NOT in expected count until actually played
- If rescheduled, track both dates
- `postponed_games = [{'original': '2026-01-15', 'rescheduled': '2026-01-25'}]`

---

### Case 2.5: Back-to-Back Games

**Scenario:** Team plays two consecutive days.

**Not really a corner case but:**
- Window might have clustered games
- Fatigue patterns different
- Both games need to be present

**Expected behavior:** Standard completeness check, no special handling needed.

---

## Category 3: Data Source Scenarios

### Case 3.1: Primary Source Missing, Fallback Available

**Scenario:** `nbac_team_boxscore` missing, but `bdl_boxscores` has data.

**Current behavior:** Feature extraction falls back to Phase 3 sources.

**Expected behavior:**
- Still track completeness
- Note data source: `data_source = 'bdl_fallback'`
- Completeness should reflect the source actually used

---

### Case 3.2: Partial Game Data

**Scenario:** Game exists but some columns are NULL (API returned partial data).

**Example:**
- Game on Jan 15 exists
- But `paint_attempts = NULL`
- Features using `paint_attempts` can't be calculated

**Expected behavior:**
- Game counts as "present" for completeness
- But feature-specific quality flags needed
- `features_with_null_inputs = ['pct_paint']`

---

### Case 3.3: Duplicate Games in Source

**Scenario:** Same game appears twice in `player_game_summary` (processing bug).

**Expected behavior:**
- Deduplication before counting
- `games_found` should be unique game count
- Log warning about duplicates

---

### Case 3.4: Wrong Data (Correction Needed)

**Scenario:** Game data exists but is incorrect (later corrected by NBA).

**Example:**
- Jan 15 game recorded with wrong stats
- NBA issues correction Jan 17
- Data re-scraped Jan 18

**Expected behavior:**
- Features using Jan 15 data need cascade flag
- Track `data_version` or `scraped_at` timestamp
- When data is updated, mark dependent features for re-run

**Implementation consideration:** This is different from "missing" - data existed but was wrong.

---

## Category 4: Temporal Scenarios

### Case 4.1: Same-Day Predictions

**Scenario:** Generating features for a game happening TODAY.

**Complication:**
- Player hasn't played today's game yet
- Rolling window should NOT include today
- But today's game is what we're predicting

**Expected behavior:**
- Rolling window ends at yesterday
- Completeness check uses yesterday as cutoff
- Same-day mode already handles this

---

### Case 4.2: Future Game Predictions

**Scenario:** Generating predictions for games 2-3 days out.

**Expected behavior:**
- Use most recent completed games for window
- Clearly mark as future prediction
- Completeness based on games through yesterday

---

### Case 4.3: Backfill of Historical Dates

**Scenario:** Running feature generation for Jan 1 (3 weeks ago).

**Complications:**
- Need to use data AS IT WAS on Jan 1, not current data
- Players may have been traded since then
- Rosters were different

**Expected behavior:**
- Use historical roster snapshot
- Schedule query uses historical context
- Flag features as `is_backfill = True`

---

### Case 4.4: Re-running After Cascade

**Scenario:** Backfilled Jan 5, now re-running features for Jan 6-25.

**Expected behavior:**
- Jan 6-25 features should now be complete
- Old records should be replaced (not duplicated)
- Verify completeness improved after re-run

---

## Category 5: Scale and Performance Scenarios

### Case 5.1: Large Gap (26+ Days)

**Scenario:** Very long data gap (like Dec 27 - Jan 21 incident).

**Complications:**
- Many dates affected
- Cascade spans 26 days gap + 21 days forward = 47 days
- ~500 players × 47 days = 23,500 feature records to re-run

**Expected behavior:**
- Handle in batches (date by date)
- Track progress
- Provide ETA

---

### Case 5.2: Multiple Gaps

**Scenario:** Two separate gaps: Jan 1-3 AND Jan 10-12.

**Complications:**
- Cascade windows overlap
- Need to merge affected date ranges
- Re-run once, not twice for overlapping dates

**Expected behavior:**
```
Gap 1: Jan 1-3 → affects Jan 4-24
Gap 2: Jan 10-12 → affects Jan 13-Feb 2

Merged cascade: Jan 4 - Feb 2 (need to re-run all)
```

---

### Case 5.3: Single Player Affected

**Scenario:** Gap only affects one player (e.g., their specific games missing).

**Expected behavior:**
- Cascade only for that player
- Don't re-run all 500 players
- `affected_players = ['player_abc']`

---

### Case 5.4: Concurrent Processing

**Scenario:** Feature generation running while completeness check running.

**Expected behavior:**
- Use transaction-safe reads
- Completeness metadata reflects state at generation time
- Don't overwrite with stale completeness data

---

## Category 6: Boundary Conditions

### Case 6.1: Exactly 10 Games, Exactly 21 Days

**Scenario:** Edge of threshold.

**Decision needed:**
- `games_found = 10 AND window_span = 21` → Complete? YES
- `games_found = 10 AND window_span = 22` → Stale? YES
- `games_found = 9 AND window_span = 21` → Incomplete? YES

**Thresholds:**
```python
GAMES_THRESHOLD = 10  # Must have at least this many
SPAN_THRESHOLD = 21   # Must not exceed this many days
```

---

### Case 6.2: Zero Games Found

**Scenario:** Query returns no games at all.

**Causes:**
- Brand new player
- Player from different league
- Data completely missing
- Query bug

**Expected behavior:**
- `games_found = 0`
- `is_complete = False`
- `zero_games_reason` should be determined

---

### Case 6.3: More Than 10 Games in Window

**Scenario:** Due to query bug, got 12 games instead of 10.

**Expected behavior:**
- Should never happen with QUALIFY clause
- If it does, log error and truncate
- Investigate query logic

---

## Category 7: Feature-Specific Scenarios

### Case 7.1: Opponent History (Zero Games)

**Scenario:** First time playing this opponent this season.

**Example:**
- Lakers vs. Celtics on Jan 15
- No previous LAL vs BOS games this season

**Expected behavior:**
- `games_vs_opponent = 0`
- `avg_points_vs_opponent = NULL` or league average
- This is NOT incomplete, it's expected

---

### Case 7.2: Vegas Lines Missing

**Scenario:** Vegas lines not yet available for game.

**Expected behavior:**
- `has_vegas_line = False`
- Features can still be generated
- Mark as `vegas_data_missing = True`

---

### Case 7.3: Team Defense Stats Missing

**Scenario:** Playing against a team whose defense stats are missing.

**Example:**
- Playing vs DEN on Jan 20
- DEN's team_defense_game_summary missing for Jan 15-19

**Expected behavior:**
- Opponent's defensive context is stale
- Flag: `opponent_stats_stale = True`
- Still generate features but mark reliability

---

## Summary Table

| Category | Case | Severity | Handling |
|----------|------|----------|----------|
| Player | New player | LOW | Special flag, use defaults |
| Player | Injury return | MEDIUM | Mark as stale, not incomplete |
| Player | Trade | MEDIUM | Track teams in window |
| Player | DNP | LOW | Exclude from expected count |
| Schedule | All-Star break | LOW | Calendar awareness |
| Schedule | Season start | LOW | Bootstrap mode |
| Schedule | Playoffs | LOW | Standard rules apply |
| Data | Fallback source | MEDIUM | Track source used |
| Data | Partial data | MEDIUM | Feature-specific flags |
| Temporal | Same-day | LOW | Already handled |
| Temporal | Backfill | MEDIUM | Historical context |
| Scale | Large gap | HIGH | Batch processing |
| Scale | Multiple gaps | HIGH | Merge cascades |
| Boundary | Zero games | HIGH | Determine reason |

---

## Implementation Checklist

- [ ] Handle new player vs missing data distinction
- [ ] Track staleness separately from incompleteness
- [ ] Support DNP-aware counting
- [ ] Calendar awareness for All-Star break
- [ ] Multi-team tracking for traded players
- [ ] Batch cascade processing for large gaps
- [ ] Merge overlapping cascade windows
- [ ] Per-player cascade granularity
- [ ] Feature-specific missing data flags

---

**Document Status:** Complete
