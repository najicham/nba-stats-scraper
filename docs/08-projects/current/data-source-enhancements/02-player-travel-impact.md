# Player-Level Travel Impact Enhancement

## Current State

**What we have:**
- `schemas/bigquery/static/travel_distances_table.sql` - All 870 team pairs
- `data_processors/analytics/utils/travel_utils.py` - NBATravel class
- Team-level `travel_miles` in `upcoming_team_game_context`
- Fatigue scoring (0-100 scale) in `player_composite_factors`

**What's NOT working:**
```python
# In player_composite_factors_processor.py
travel_adj = 0.0  # Hardcoded to zero - NOT CALCULATED
```

Schema fields exist but aren't populated:
- `travel_miles` (player level)
- `time_zone_changes`
- `consecutive_road_games`
- `miles_traveled_last_14_days`
- `time_zones_crossed_last_14_days`

## Why This Matters

Cumulative travel fatigue is real:
- West coast team on 4-game eastern road trip performs worse
- Back-to-back with cross-country travel = compounded fatigue
- Jet lag (eastward worse than westward) affects performance

Current system has the data but doesn't use it for player predictions.

## Implementation Plan

### Step 1: Complete travel_utils.py

The `get_travel_last_n_days()` method exists but isn't implemented:

```python
def get_travel_last_n_days(self, team: str, game_date: str, n_days: int = 14) -> dict:
    """
    Calculate cumulative travel metrics for last N days.

    Returns:
        {
            'total_miles': int,
            'time_zones_crossed': int,
            'games_played': int,
            'road_games': int,
            'back_to_backs': int,
            'jet_lag_factor': float
        }
    """
    # TODO: Implement - query schedule, calculate cumulative travel
    pass
```

### Step 2: Update upcoming_player_game_context_processor

Add travel calculations:

```python
# Calculate player's team travel context
travel_context = travel_utils.get_travel_last_n_days(
    team=player['team'],
    game_date=game_date,
    n_days=14
)

row['travel_miles'] = travel_context['total_miles']
row['time_zone_changes'] = travel_context['time_zones_crossed']
row['miles_traveled_last_14_days'] = travel_context['total_miles']
row['consecutive_road_games'] = travel_context['road_games']
```

### Step 3: Update player_composite_factors

Replace hardcoded `travel_adj = 0.0` with actual calculation:

```python
def calculate_travel_adjustment(travel_context: dict) -> float:
    """
    Calculate point adjustment based on travel fatigue.

    Returns: -3.0 to 0.0 (negative = fatigue penalty)
    """
    adj = 0.0

    # Heavy travel penalty (3000+ miles in 14 days)
    if travel_context['total_miles'] > 3000:
        adj -= 1.5
    elif travel_context['total_miles'] > 2000:
        adj -= 0.75

    # Jet lag penalty (3+ time zones crossed)
    if travel_context['time_zones_crossed'] >= 3:
        adj -= 1.0
    elif travel_context['time_zones_crossed'] >= 2:
        adj -= 0.5

    # Long road trip penalty
    if travel_context['consecutive_road_games'] >= 4:
        adj -= 0.5

    return max(adj, -3.0)  # Cap at -3 points
```

## Effort Estimate

- Step 1: 2-3 hours (complete travel_utils)
- Step 2: 1-2 hours (wire into processor)
- Step 3: 1 hour (enable travel adjustment)

**Total: ~0.5 day of work**

## Success Metrics

- Travel adjustment no longer hardcoded to 0
- Predictions improve for teams on long road trips
- Validate against historical: heavy-travel games should show lower actuals
