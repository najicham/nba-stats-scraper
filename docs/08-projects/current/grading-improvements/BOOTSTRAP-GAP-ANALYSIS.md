# Season-Start Bootstrap Gap Analysis

**Date:** 2026-01-23
**Status:** Analysis Complete
**Priority:** P2 (Enhancement)

---

## Current Behavior

### Bootstrap Period
- **Duration:** 14 days (BOOTSTRAP_DAYS = 14)
- **Purpose:** Allow rolling windows (L5, L7d) to populate with data
- **Impact:** ~14-15 days at start of each season without predictions

### Historical Gaps

| Season | First Game | First Prediction | Gap (Days) |
|--------|------------|------------------|------------|
| 2021-22 | 2021-10-19 | 2021-11-02 | 14 |
| 2022-23 | 2022-10-18 | 2022-11-01 | 14 |
| 2023-24 | 2023-10-24 | 2023-11-08 | 15 |
| 2024-25 | 2024-10-22 | 2024-11-06 | 15 |

---

## Why Bootstrap Exists

### Required Data Windows
1. **L5 (Last 5 Games)** - Primary rolling average
2. **L7d (Last 7 Days)** - Time-based window
3. **Similarity Model** - Needs comparable games to find matches

### Math
- Average team plays ~3.5 games per week
- 14 days = ~7 games = enough for L5 calculation
- Less than L5 = unreliable rolling averages

---

## Potential Improvements

### Option 1: Use Previous Season Data (Recommended)
**Approach:** For returning players, use their last season's stats as initial baseline.

**Implementation:**
```python
def get_bootstrap_estimate(player_lookup, current_season_start):
    # Check current season data first
    current_data = get_rolling_stats(player_lookup, window=5)
    if len(current_data) >= 3:  # At least 3 games
        return calculate_average(current_data)

    # Fall back to previous season if needed
    prev_season_data = get_previous_season_stats(player_lookup)
    if prev_season_data:
        return prev_season_data['points_avg']

    # New player - needs full bootstrap
    return None
```

**Pros:**
- Could reduce bootstrap to 5-7 days for returning players
- Most NBA players (80%+) are returning players
- Previous season is reasonable proxy for early games

**Cons:**
- Accuracy may be lower than current approach
- Player role changes between seasons
- Trades/new teams affect stats

**Impact:** Reduce gap from 14 → 5-7 days for ~80% of predictions

---

### Option 2: Reduce to L3 (Last 3 Games)
**Approach:** Lower the minimum games required for predictions.

**Implementation:**
```python
BOOTSTRAP_DAYS = 7  # Reduce from 14
MIN_GAMES_FOR_PREDICTION = 3  # Instead of 5
```

**Pros:**
- Simple change
- Gap reduced to ~7 days

**Cons:**
- Higher variance in predictions
- L3 is noisier than L5
- May hurt accuracy metrics

**Impact:** Reduce gap from 14 → 7 days

---

### Option 3: Player-Specific Bootstrap
**Approach:** Use different bootstrap periods based on player status.

| Player Type | Bootstrap Days | Rationale |
|-------------|----------------|-----------|
| Returning veteran | 3-5 | Has previous season data |
| New to team | 7 | Different role/system |
| Rookie | 14 | No NBA history |

**Implementation:**
```python
def get_player_bootstrap_days(player_lookup, season):
    player_history = get_player_seasons(player_lookup)

    if len(player_history) == 0:
        return 14  # Rookie
    elif is_new_team(player_lookup, season):
        return 7   # New team
    else:
        return 3   # Returning veteran
```

**Pros:**
- Most granular approach
- Optimizes for each player type
- Fastest reduction for known players

**Cons:**
- More complex logic
- Harder to maintain
- Edge cases (mid-season trades)

**Impact:** Variable, average ~5 days

---

### Option 4: Preseason Data
**Approach:** Use preseason games for initial calibration.

**Challenges:**
- Preseason stats often not representative
- Playing time varies significantly
- Starters rest in preseason
- Not all players play

**Verdict:** Not recommended - preseason is too different from regular season.

---

## Recommendation

### Short-term (Easy Win)
**Option 2: Reduce to L3 with 7-day bootstrap**

```python
# shared/validation/config.py
BOOTSTRAP_DAYS = 7  # Was 14

# predictions/coordinator/player_loader.py
# Reduce minimum games from 5 to 3
```

**Trade-off:** Slightly lower accuracy in exchange for 50% more coverage.

### Long-term (Best Approach)
**Option 1 + Option 3: Previous season fallback with player-specific bootstrap**

1. Returning players: Use previous season average as baseline
2. Calculate confidence tier based on data availability
3. Rookies still get full bootstrap period

---

## Configuration Location

```
BOOTSTRAP_DAYS: predictions/coordinator/shared/validation/config.py:255
MIN_GAMES: predictions/coordinator/player_loader.py (needs to be made configurable)
```

---

## Impact Assessment

| Scenario | Current | With Improvements |
|----------|---------|-------------------|
| First week coverage | 0% | 60-80% |
| First 2 weeks coverage | 50% | 90%+ |
| Accuracy trade-off | N/A | ~2-5% lower |

---

## Action Items

1. [ ] Add `use_previous_season_fallback` config flag
2. [ ] Implement `get_previous_season_stats()` function
3. [ ] Reduce BOOTSTRAP_DAYS to 7 as quick win
4. [ ] Add confidence adjustment for early-season predictions
5. [ ] Test accuracy impact on historical data
