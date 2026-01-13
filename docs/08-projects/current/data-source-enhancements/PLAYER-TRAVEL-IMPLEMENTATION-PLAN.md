# Player Travel Impact Implementation Plan

**Created:** 2026-01-12
**Status:** Ready for Review
**Estimated Effort:** 4-6 hours
**Priority:** P2 (infrastructure exists, needs wiring)

---

## Executive Summary

The system has complete travel infrastructure but player-level travel impact is **not being calculated or used in predictions**. The static distance matrix exists, team-level travel works, but:

1. `travel_utils.get_travel_last_n_days()` returns zeros (TODO placeholder)
2. Player context has 5 travel fields all set to `None`
3. Composite factors hardcodes `travel_adj = 0.0`

This plan details how to complete the implementation so travel fatigue affects predictions.

---

## Current Architecture

### What EXISTS and WORKS ✅

```
┌─────────────────────────────────────────────────────────────────┐
│ nba_static.travel_distances                                     │
│ ─────────────────────────────                                   │
│ • 870 team pairs (30 × 29)                                      │
│ • distance_miles, time_zones_crossed                            │
│ • travel_direction (east/west/neutral)                          │
│ • jet_lag_factor (eastward=1.5x, westward=1.0x)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ travel_utils.py                                                 │
│ ───────────────                                                 │
│ ✅ get_travel_distance(from, to) - single trip lookup           │
│ ✅ calculate_road_trip_travel(schedule) - cumulative for list   │
│ ❌ get_travel_last_n_days() - TODO, returns zeros               │
│ ✅ Caching implemented                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ upcoming_team_game_context_processor.py                         │
│ ───────────────────────────────────────                         │
│ ✅ Loads travel_distances into memory                           │
│ ✅ Calculates travel_miles for each team                        │
│ ✅ Logic: last_game_location → current_game_location            │
└─────────────────────────────────────────────────────────────────┘
```

### What's BROKEN ❌

```
┌─────────────────────────────────────────────────────────────────┐
│ upcoming_player_game_context_processor.py                       │
│ ───────────────────────────────────────────                     │
│ Schema defines 5 travel fields:                                 │
│   • travel_miles INT64                    → None                │
│   • time_zone_changes INT64               → None                │
│   • consecutive_road_games INT64          → None                │
│   • miles_traveled_last_14_days INT64     → None                │
│   • time_zones_crossed_last_14_days INT64 → None                │
│                                                                 │
│ Lines 2266-2270: All hardcoded to None                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ player_composite_factors_processor.py                           │
│ ─────────────────────────────────────                           │
│ Line 219: travel_adj = 0.0  # HARDCODED                         │
│                                                                 │
│ Fatigue calculation uses:                                       │
│   • days_rest, back_to_back         ✅                          │
│   • games_last_7, minutes_last_7    ✅                          │
│   • back_to_backs_last_14, age      ✅                          │
│   • travel impact                   ❌ NOT INCLUDED             │
│                                                                 │
│ Output includes travel_impact_score but always 0.0              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow (Current vs Target)

### Current Flow (BROKEN)
```
Schedule Data → Team Context (travel_miles ✅) → Player Context (travel = None)
             → Composite Factors (travel_adj = 0.0) → Predictions (no travel impact)
```

### Target Flow (FIXED)
```
Schedule Data → Team Context (travel_miles ✅)
             → Player Context (5 travel fields populated ✅)
             → Composite Factors (travel_adj calculated ✅)
             → Predictions (travel impacts score ✅)
```

---

## Implementation Tasks

### Task 1: Calculate Cumulative Travel in Player Context Processor

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**What to do:**
1. Add method `_calculate_player_travel_context()`
2. Reuse travel distance data (already loaded in team context, need to load here too)
3. Calculate cumulative metrics for last 14 days
4. Populate the 5 existing schema fields

**Logic:**
```python
def _calculate_player_travel_context(self, player_row: dict, game: dict) -> dict:
    """
    Calculate travel context for a player's upcoming game.

    Uses player's team schedule to determine:
    1. Single-game travel (from last location to current game)
    2. Cumulative travel over last 14 days
    3. Consecutive road games count
    """
    team_abbr = player_row['team_abbr']
    game_date = game['game_date']
    is_home = (game['home_team_abbr'] == team_abbr)

    # Home games = 0 travel for this game
    if is_home:
        return {
            'travel_miles': 0,
            'time_zone_changes': 0,
            'consecutive_road_games': 0,
            'miles_traveled_last_14_days': self._calc_cumulative_miles(team_abbr, game_date, 14),
            'time_zones_crossed_last_14_days': self._calc_cumulative_tz(team_abbr, game_date, 14)
        }

    # Away games - calculate travel from last location
    last_location = self._get_last_game_location(team_abbr, game_date)
    current_location = game['home_team_abbr']  # Playing at opponent's arena

    travel_info = self._lookup_travel(last_location, current_location)

    return {
        'travel_miles': travel_info['distance_miles'],
        'time_zone_changes': travel_info['time_zones_crossed'],
        'consecutive_road_games': self._count_consecutive_road_games(team_abbr, game_date),
        'miles_traveled_last_14_days': self._calc_cumulative_miles(team_abbr, game_date, 14),
        'time_zones_crossed_last_14_days': self._calc_cumulative_tz(team_abbr, game_date, 14)
    }
```

**Helper methods needed:**
```python
def _get_last_game_location(self, team_abbr: str, before_date: date) -> str:
    """Find where team played their last game."""

def _calc_cumulative_miles(self, team_abbr: str, end_date: date, days: int) -> int:
    """Sum travel miles over last N days."""

def _calc_cumulative_tz(self, team_abbr: str, end_date: date, days: int) -> int:
    """Sum time zones crossed over last N days."""

def _count_consecutive_road_games(self, team_abbr: str, game_date: date) -> int:
    """Count consecutive road games including this one."""

def _lookup_travel(self, from_team: str, to_team: str) -> dict:
    """Lookup travel distance from cache/table."""
```

**Data dependency:** Schedule data is already loaded in this processor (`self.schedule_data`), so we can reuse that.

---

### Task 2: Add Travel Adjustment to Composite Factors

**File:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**What to change:**

Replace line 219:
```python
# BEFORE
travel_adj = 0.0

# AFTER
travel_adj = self._calculate_travel_adjustment(player_row_dict)
```

**Add new method:**
```python
def _calculate_travel_adjustment(self, player_row: dict) -> float:
    """
    Calculate point adjustment for travel fatigue.

    Based on research, travel affects performance:
    - Cumulative mileage causes physical fatigue
    - Time zone changes disrupt circadian rhythm
    - Eastward travel is harder (takes longer to adjust)
    - Back-to-back with travel compounds effect

    Returns: -3.0 to 0.0 (negative = predicted point reduction)
    """
    miles_14d = player_row.get('miles_traveled_last_14_days', 0) or 0
    tz_14d = player_row.get('time_zones_crossed_last_14_days', 0) or 0
    consecutive_road = player_row.get('consecutive_road_games', 0) or 0
    is_back_to_back = player_row.get('back_to_back', False)
    travel_miles = player_row.get('travel_miles', 0) or 0

    adj = 0.0

    # === CUMULATIVE MILEAGE FATIGUE ===
    # Average NBA team travels ~50,000 miles/season = ~3,500 miles/14 days
    # Heavy travel: West coast team on eastern swing
    if miles_14d >= 6000:
        adj -= 1.5  # Extreme travel (double normal)
    elif miles_14d >= 4500:
        adj -= 1.0  # Heavy travel
    elif miles_14d >= 3000:
        adj -= 0.5  # Above average travel
    # Below 3000 = normal or light, no penalty

    # === JET LAG (TIME ZONE DISRUPTION) ===
    # Body adjusts ~1 day per time zone crossed
    # 6+ zones in 14 days = significant disruption
    if tz_14d >= 8:
        adj -= 1.0  # Severe jet lag accumulation
    elif tz_14d >= 5:
        adj -= 0.5  # Moderate jet lag
    elif tz_14d >= 3:
        adj -= 0.25  # Mild jet lag

    # === ROAD TRIP LENGTH ===
    # Long road trips (4+ games) compound fatigue
    if consecutive_road >= 5:
        adj -= 0.75  # Very long road trip
    elif consecutive_road >= 4:
        adj -= 0.5   # Long road trip
    elif consecutive_road >= 3:
        adj -= 0.25  # Moderate road trip

    # === COMPOUND EFFECT: BACK-TO-BACK WITH TRAVEL ===
    # Flying after a game, playing next day = worst case
    if is_back_to_back and travel_miles > 500:
        adj -= 0.5  # Flew after game, playing next day

    # Cap total adjustment
    return max(adj, -3.0)
```

**Update fatigue context to include travel:**
```python
# In the fatigue_context dict (around line 268-277), add:
fatigue_context = {
    'days_rest': days_rest,
    'back_to_back': back_to_back,
    'games_last_7': games_last_7,
    'minutes_last_7': minutes_last_7,
    'avg_minutes_pg_last_7': avg_mpg_last_7,
    'back_to_backs_last_14': recent_b2bs,
    'player_age': age,
    'final_score': fatigue_score,
    # NEW: Travel context
    'miles_traveled_last_14_days': player_row_dict.get('miles_traveled_last_14_days', 0),
    'time_zones_crossed_last_14_days': player_row_dict.get('time_zones_crossed_last_14_days', 0),
    'consecutive_road_games': player_row_dict.get('consecutive_road_games', 0),
    'travel_adjustment': travel_adj
}
```

---

### Task 3: Load Travel Distances in Player Context Processor

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

The team context processor already loads travel distances. We need to do the same here.

**Add to `__init__`:**
```python
self.travel_distances: Optional[Dict] = None
```

**Add to extraction phase (around line 500):**
```python
# Load travel distances (same as team context processor)
logger.info("Loading travel distances...")
self.travel_distances = self._load_travel_distances()
logger.info(f"✓ Loaded {len(self.travel_distances)} travel distance mappings")
```

**Add method (copy from team context processor):**
```python
def _load_travel_distances(self) -> Dict:
    """Load travel distance mappings from static table."""
    query = f"""
    SELECT
        from_team,
        to_team,
        distance_miles,
        time_zones_crossed,
        travel_direction,
        jet_lag_factor
    FROM `{self.project_id}.nba_static.travel_distances`
    """

    try:
        df = self.bq_client.query(query).to_dataframe()
        # Create lookup dict: "LAL_BOS" -> {distance_miles: 2592, ...}
        return {
            f"{row['from_team']}_{row['to_team']}": {
                'distance_miles': int(row['distance_miles']),
                'time_zones_crossed': int(row['time_zones_crossed']),
                'travel_direction': row['travel_direction'],
                'jet_lag_factor': float(row['jet_lag_factor'])
            }
            for _, row in df.iterrows()
        }
    except Exception as e:
        logger.error(f"Error loading travel distances: {e}")
        return {}
```

---

## Testing Plan

### Unit Tests

1. **Travel distance lookup**
   - LAL → BOS = ~2,592 miles, 3 time zones
   - LAL → LAC = 0 miles (same city)
   - NYK → BKN = ~20 miles (same metro)
   - LAL → GSW = ~380 miles, 0 time zones

2. **Cumulative calculation**
   - Team with 4 road games in 14 days: sum all travel
   - Team at home all 14 days: 0 cumulative miles
   - Verify time zones don't double-count

3. **Consecutive road games**
   - Road game after road game = 2
   - Home game resets counter to 0
   - First road game of trip = 1

4. **Travel adjustment calculation**
   - 6000+ miles = -1.5 adjustment
   - 0 miles (home stretch) = 0 adjustment
   - Back-to-back with travel = extra -0.5

### Integration Tests

1. **Full pipeline run**
   - Process a date with known travel (e.g., GSW on east coast road trip)
   - Verify travel fields populated in player context
   - Verify travel_adj not 0.0 in composite factors

2. **Edge cases**
   - Season opener (no previous games)
   - All-Star break (gap in schedule)
   - Missing schedule data (graceful fallback)

### Validation Queries

```sql
-- Check travel fields are populated
SELECT
  player_name, team_abbr, game_date,
  travel_miles, time_zone_changes,
  miles_traveled_last_14_days, consecutive_road_games
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-13'
  AND travel_miles IS NOT NULL
ORDER BY miles_traveled_last_14_days DESC
LIMIT 20;

-- Check composite factors has non-zero travel
SELECT
  player_lookup, game_date,
  travel_impact_score, total_composite_adjustment
FROM nba_precompute.player_composite_factors
WHERE game_date = '2026-01-13'
  AND travel_impact_score != 0
ORDER BY travel_impact_score ASC
LIMIT 20;
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Schedule data gaps | Medium | High | Fall back to team-level travel; log warning |
| Performance (many queries) | Low | Medium | Travel distances are cached; schedule already loaded |
| Travel adjustment too aggressive | Medium | Medium | Start conservative (-3 max), tune with backtesting |
| Time zone calculation errors | Low | Low | Use static table (already validated) |

---

## Rollout Plan

### Phase 1: Development (Day 1)
1. Implement `_calculate_player_travel_context()` in player context processor
2. Add travel distance loading to player context processor
3. Implement `_calculate_travel_adjustment()` in composite factors
4. Unit tests

### Phase 2: Testing (Day 1-2)
1. Run locally for single date
2. Verify fields populate correctly
3. Check adjustment values are reasonable
4. Integration test full pipeline

### Phase 3: Deployment (Day 2)
1. Deploy to Cloud Run
2. Run backfill for recent dates (1 week)
3. Monitor for errors
4. Validate predictions show travel impact

### Phase 4: Validation (Week 1-2)
1. Compare predictions before/after travel
2. Track if travel improves accuracy
3. Tune adjustment formula if needed

---

## Success Criteria

1. ✅ All 5 travel fields populated (not None) for player context
2. ✅ `travel_impact_score` non-zero for players with heavy travel
3. ✅ Total adjustment reflects travel fatigue
4. ✅ No errors in production pipeline
5. ✅ Backtest shows travel correlates with performance variance

---

## Files to Modify

| File | Changes |
|------|---------|
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | Add travel calculation methods, populate 5 fields |
| `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` | Add `_calculate_travel_adjustment()`, replace hardcoded 0.0 |

**Optional cleanup:**
| File | Changes |
|------|---------|
| `data_processors/analytics/utils/travel_utils.py` | Implement `get_travel_last_n_days()` or add deprecation note |

---

## Appendix A: Research on Travel Impact

Studies on NBA travel and performance:

1. **Jet lag effect**: Performance drops ~1% per time zone crossed, recovers in 1-2 days
2. **Eastward vs westward**: Eastward travel is ~1.5x harder on circadian rhythm
3. **Cumulative fatigue**: West coast teams on eastern road trips show 2-3% drop
4. **Back-to-back with travel**: Worst case scenario, compounds all effects
5. **Altitude (Denver)**: Separate issue - 1-2% visitor disadvantage at altitude

**For prop betting impact:**
- 2-3% scoring drop = 0.5-1.0 points for 25 PPG player
- Heavy travel scenarios = up to 3 point adjustment warranted

---

## Appendix B: Example Scenarios

### Scenario 1: Lakers at Home (Low Travel)
```
miles_traveled_last_14_days: 800
time_zones_crossed_last_14_days: 0
consecutive_road_games: 0
is_home_game: true

travel_adj = 0.0 (no penalty, light travel, playing at home)
```

### Scenario 2: Warriors on East Coast Road Trip
```
miles_traveled_last_14_days: 5,500
time_zones_crossed_last_14_days: 6
consecutive_road_games: 4
is_back_to_back: true
travel_miles: 400 (Boston → Philadelphia)

travel_adj = -1.0 (heavy miles) + -0.5 (jet lag) + -0.5 (long road trip) + -0.5 (b2b with travel)
           = -2.5 points
```

### Scenario 3: Celtics Short Road Trip
```
miles_traveled_last_14_days: 2,200
time_zones_crossed_last_14_days: 2
consecutive_road_games: 2
is_back_to_back: false
travel_miles: 200 (NYC → Boston)

travel_adj = 0.0 (normal travel, no penalties triggered)
```

---

## Reviewer Notes

**Questions for reviewer:**

1. Is the -3.0 max adjustment appropriate? Could tune to -2.0 or -4.0 based on backtesting.

2. Should we add travel to the fatigue_score calculation (0-100 scale) in addition to separate travel_adj?

3. The team context processor already calculates `travel_miles`. Should player context just inherit from team context instead of recalculating?

4. Consider: Should consecutive_road_games be capped? (e.g., after 5 games, fatigue doesn't increase linearly)

5. Edge case: International games (London, Mexico City) - currently would return 0 from lookup. Need special handling?
