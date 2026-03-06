# Player Profile Signals -- Implementation Plan

*Session 417, March 5 2026*

## Signal Summary

### P0 -- Implement Now

| Signal | Type | Trigger | HR | N |
|--------|------|---------|-----|---|
| `bounce_back_over` | Positive signal | Bad miss (<70% of line) + AWAY game | 56.2% raw, 60%+ with model | 379 |
| `under_after_streak` | Negative filter | 3+ consecutive unders + model UNDER | 44.7% (anti) | 515 |

### P1 -- Implement Next

| Signal | Type | Trigger | HR | N |
|--------|------|---------|-----|---|
| `over_streak_reversion_under` | Positive signal | 4+ overs in last 5 games | ~56% UNDER | 366 |
| `bad_shooting_bounce_over` | Positive signal | FG% < 35% last game + AWAY | 54.5% | 220 |
| `starter_over_boost` | Confidence modifier | Player tier = starter + OVER + edge 3+ | 61.1% | 1,050 |
| `role_player_under_boost` | Confidence modifier | Player tier = role_player + UNDER + edge 3+ | 60.0% | 4,041 |

### P2 -- Validate Then Implement

| Signal | Type | Trigger | HR | N |
|--------|------|---------|-----|---|
| `volatile_high_edge_boost` | Confidence modifier | CoV > 0.35 + edge 5+ | 61.9% | 3,005 |
| `scoring_shape_modifier` | Signal modifier | Skewness x direction interaction | varies | 20K+ |
| `player_variance_tier` | Ultra bets filter | CoV-based tier classification | 56.6% top | 290 |

---

## Infrastructure Needed

### 1. Previous Game Context Lookup

The bounce-back and streak signals need to know what happened in the player's last game(s). This data lives in `player_game_summary` and needs to be available at prediction time.

**Where to compute:** In the signal evaluator (`ml/signals/`), query the player's last 1-5 games from `player_game_summary` at signal evaluation time. The aggregator already fetches supplemental data from BQ.

**Data needed per player:**
- Last game: points, points_line, fg_makes, fg_attempts, minutes_played, is_home
- Last 5 games: points vs points_line results (for streak counting)

**Implementation:** Add a `player_recent_context` query to `supplemental_data.py` that fetches last 5 games for all players being evaluated.

### 2. Player Profile Table

Rolling 30-game player profile stats. Updated daily as part of Phase 4 or as a standalone computation.

**Fields:**
- `player_lookup`, `game_date` (as-of date)
- `scoring_cv` (coefficient of variation)
- `scoring_skew` (mean - median proxy)
- `minutes_cv` (minutes stability)
- `avg_points`, `median_points`
- `player_tier` (star/starter/role_player based on avg_points)
- `bounce_coefficient` (avg scoring delta after bad games)

**Where to store:** New BQ table `nba_predictions.player_profiles` or compute inline.

### 3. Signal Registration

Each new signal needs to be registered in the signal system:
- Signal definition in `ml/signals/`
- Weight assignment in signal weights config
- Shadow mode first, then promote after validation

---

## Implementation Steps

### Step 1: Add previous game context to supplemental data

File: `ml/signals/supplemental_data.py`

Add query to fetch last 5 games for each player:
```sql
SELECT
  player_lookup,
  game_date,
  points,
  points_line,
  fg_makes,
  fg_attempts,
  minutes_played,
  ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as game_num
FROM nba_analytics.player_game_summary
WHERE player_lookup IN UNNEST(@player_lookups)
  AND game_date < @target_date
  AND points IS NOT NULL AND points > 0
  AND (is_dnp IS NULL OR is_dnp = FALSE)
QUALIFY game_num <= 5
```

### Step 2: Implement bounce_back_over signal

File: `ml/signals/player_profile_signals.py` (new)

```python
def evaluate_bounce_back_over(player_data, recent_games, is_home):
    """
    Trigger: Last game scored < 70% of line AND current game is AWAY
    HR: 56.2% raw (N=379), 60%+ with model OVER confirmation
    """
    if not recent_games or is_home:
        return None

    last_game = recent_games[0]
    if last_game['points_line'] and last_game['points_line'] > 0:
        ratio = last_game['points'] / last_game['points_line']
        if ratio < 0.7:
            return {
                'signal': 'bounce_back_over',
                'direction': 'OVER',
                'strength': min(1.0, (0.7 - ratio) * 5),  # Stronger signal for worse misses
                'context': {
                    'prev_pts': last_game['points'],
                    'prev_line': last_game['points_line'],
                    'miss_ratio': round(ratio, 2),
                }
            }
    return None
```

### Step 3: Implement under_after_streak negative filter

File: `ml/signals/player_profile_signals.py`

```python
def evaluate_under_after_streak(player_data, recent_games, recommendation):
    """
    Trigger: 3+ consecutive unders AND model recommends UNDER
    HR: 44.7% (anti-signal) -- BLOCK these picks
    """
    if recommendation != 'UNDER' or len(recent_games) < 3:
        return None

    consecutive_unders = 0
    for game in recent_games:
        if game['points_line'] and game['points'] < game['points_line']:
            consecutive_unders += 1
        else:
            break

    if consecutive_unders >= 3:
        return {
            'filter': 'under_after_streak',
            'reason': f'{consecutive_unders} consecutive unders -- bounce-back likely',
            'anti_hr': 0.447,
        }
    return None
```

### Step 4: Implement over_streak_reversion_under

```python
def evaluate_over_streak_reversion(player_data, recent_games):
    """
    Trigger: 4+ overs in last 5 games
    HR: ~56% UNDER (N=366)
    """
    if len(recent_games) < 5:
        return None

    overs_last_5 = sum(
        1 for g in recent_games[:5]
        if g['points_line'] and g['points'] > g['points_line']
    )

    if overs_last_5 >= 4:
        return {
            'signal': 'over_streak_reversion_under',
            'direction': 'UNDER',
            'strength': 0.6 if overs_last_5 == 5 else 0.4,
        }
    return None
```

### Step 5: Wire into signal evaluator

File: `ml/signals/signal_evaluator.py`

- Import player_profile_signals
- Call evaluate functions during signal evaluation loop
- Add signals to SIGNAL_WEIGHTS and UNDER_SIGNAL_WEIGHTS
- Start in SHADOW mode

### Step 6: Batch deep dive runner

File: `bin/analysis/batch_player_deep_dive.py`

Simple wrapper that:
1. Queries BQ for all players with 50+ predictions
2. Runs `player_deep_dive.py` for each
3. Stores results in `results/player_profiles/`

---

## Validation Plan

All signals start in SHADOW mode for 2 weeks (minimum 10 game days):

1. **Shadow period:** Signals fire and log but don't affect picks
2. **Grading:** Track shadow signal HR via `signal_health_daily`
3. **Promotion criteria:** HR >= 55% at N >= 30 for positive signals; anti-HR <= 48% at N >= 30 for filters
4. **Review date:** ~March 19 for P0 signals

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Supplemental query adds latency | Batch fetch for all players in single query |
| Previous game data missing | Graceful fallback -- signal returns None |
| Streak data stale (game not processed) | Use game_date < target_date filter |
| Signal interaction with existing signals | Shadow mode first, monitor for conflicts |
| Home/away feature not available | Fall back to feature_15_value from feature store |

---

## Timeline

- **Day 1:** Add previous game context query to supplemental_data.py
- **Day 1:** Implement P0 signals (bounce_back_over + under_after_streak)
- **Day 2:** Implement P1 signals (over_streak_reversion, bad_shooting_bounce, tier modifiers)
- **Day 2:** Run batch deep dives for all 262 players
- **Day 3:** Deploy to shadow mode
- **Days 4-17:** Shadow validation period
- **Day 18:** Review shadow results, promote validated signals
