# Final Design: Historical Completeness Tracking

**Document:** 09-FINAL-DESIGN.md
**Created:** January 22, 2026
**Status:** APPROVED

---

## Summary

This document captures the final agreed-upon design for tracking historical data completeness in the ML feature pipeline.

---

## Core Principles

1. **100% completeness is the goal** - Flag anything less
2. **Flag, don't block** - Generate features but track issues
3. **Store what we used** - `contributing_game_dates` for cascade detection
4. **Distinguish bootstrap from gaps** - Early season vs missing data
5. **Keep it simple** - Don't over-engineer investigation logic

---

## Data Model

### What We Store Per Feature Record

```python
historical_completeness = {
    # Core counts
    'games_found': 8,                    # How many games we got
    'games_expected': 10,                # How many they COULD have (capped at window size)

    # Status flags
    'is_complete': False,                # games_found >= games_expected
    'is_bootstrap': False,               # games_expected < window_size (less available)

    # Lineage (for cascade detection)
    'contributing_game_dates': [         # The dates we actually used
        '2026-01-20',
        '2026-01-18',
        '2026-01-15',
        ...
    ]
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `games_found` | INT64 | Number of games retrieved from player_game_summary |
| `games_expected` | INT64 | Number of games player could have (min of available games, window size) |
| `is_complete` | BOOL | True if games_found >= games_expected |
| `is_bootstrap` | BOOL | True if games_expected < window_size (player has limited history) |
| `contributing_game_dates` | ARRAY<DATE> | Dates of games used in calculation |

---

## Completeness Logic

### Step 1: Get Player's Games

Query `player_game_summary` for the player's last N games:

```sql
SELECT game_date, team_abbr, points, minutes_played, ...
FROM player_game_summary
WHERE player_lookup = @player
  AND game_date < @target_date
  AND game_date >= DATE_SUB(@target_date, INTERVAL 60 DAY)
ORDER BY game_date DESC
LIMIT @window_size  -- 10
```

### Step 2: Determine Expected Games

```python
def get_games_expected(player_lookup, target_date, window_size=10):
    """
    Determine how many games this player COULD have.

    This accounts for:
    - Season just started (bootstrap)
    - Player is new/rookie (their own bootstrap)
    - Player was called up mid-season
    - Player was traded (still has history from both teams)
    """
    # Count total games this player has in the lookback window
    total_available = count_player_games_in_window(
        player_lookup,
        target_date,
        lookback_days=60
    )

    # Expected is the minimum of available and window size
    return min(total_available, window_size)
```

### Step 3: Assess Completeness

```python
def assess_completeness(games_found, games_expected, window_size=10):
    """
    Determine completeness status.
    """
    is_complete = games_found >= games_expected
    is_bootstrap = games_expected < window_size  # Less than full window available

    return {
        'games_found': games_found,
        'games_expected': games_expected,
        'is_complete': is_complete,
        'is_bootstrap': is_bootstrap
    }
```

---

## Status Matrix

| games_expected | games_found | is_complete | is_bootstrap | Meaning |
|----------------|-------------|-------------|--------------|---------|
| 10 | 10 | True | False | Full window, all data present |
| 10 | 8 | **False** | False | **DATA GAP** - missing 2 games |
| 10 | 5 | **False** | False | **DATA GAP** - missing 5 games |
| 5 | 5 | True | True | Bootstrap - only 5 games exist, all present |
| 5 | 3 | **False** | False | **DATA GAP** - missing 2 of 5 available |
| 0 | 0 | True | True | New player - no history yet |

---

## Minimum Threshold

**If games_found < 5, don't generate a feature** - the data is too sparse to be useful.

| games_found | Action |
|-------------|--------|
| 0-4 | **Skip** - Don't generate feature |
| 5-9 | Generate with `is_complete = False` (unless bootstrap) |
| 10 | Generate with `is_complete = True` |

Players without features can be queried: "Players who played on date X but have no feature record"

---

## Bootstrap Detection

### Season-Level Bootstrap

Using existing infrastructure:

```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

season_year = get_season_year_from_date(target_date)
is_season_bootstrap = is_early_season(target_date, season_year, days_threshold=14)
```

### Player-Level Bootstrap

A player can be in "bootstrap" even mid-season:
- Rookie called up in December
- Player traded and only played 3 games with new team
- Player returning from long injury

**Detection:** If `games_expected < window_size`, the player has limited history.

---

## Cascade Detection

### Why We Store `contributing_game_dates`

When data is backfilled, we need to know which features to re-run.

**Query: Find features affected by backfilling Jan 1:**

```sql
SELECT game_date, player_lookup
FROM ml_feature_store_v2
WHERE DATE('2026-01-01') IN UNNEST(historical_completeness.contributing_game_dates)
  AND game_date > '2026-01-01'
ORDER BY game_date
```

**Query: Find incomplete features that might need Jan 1:**

```sql
SELECT game_date, player_lookup
FROM ml_feature_store_v2
WHERE NOT historical_completeness.is_complete
  AND game_date BETWEEN '2026-01-02' AND '2026-01-22'
```

---

## Schema Change

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS historical_completeness STRUCT<
    games_found INT64,
    games_expected INT64,
    is_complete BOOL,
    is_bootstrap BOOL,
    contributing_game_dates ARRAY<DATE>
>;
```

---

## Example Scenarios

### Scenario 1: Normal Complete

```python
# LeBron on Jan 15 (mid-season, veteran)
{
    'games_found': 10,
    'games_expected': 10,
    'is_complete': True,
    'is_bootstrap': False,
    'contributing_game_dates': ['2026-01-13', '2026-01-11', '2026-01-09', ...]
}
```

### Scenario 2: Data Gap

```python
# LeBron on Jan 15, but Jan 1 data is missing
{
    'games_found': 8,
    'games_expected': 10,
    'is_complete': False,  # <-- FLAG: Missing data
    'is_bootstrap': False,
    'contributing_game_dates': ['2026-01-13', '2026-01-11', ...]  # Jan 1 not here
}
```

### Scenario 3: Early Season Bootstrap

```python
# LeBron on Oct 30 (Day 8 of season, only 4 games played)
{
    'games_found': 4,
    'games_expected': 4,  # Only 4 games exist
    'is_complete': True,  # Have all available
    'is_bootstrap': True, # <-- Less than full window
    'contributing_game_dates': ['2026-10-28', '2026-10-26', '2026-10-24', '2026-10-22']
}
```

### Scenario 4: New Player Bootstrap

```python
# Rookie called up Jan 10, processing Jan 15 (only 3 games played)
{
    'games_found': 3,
    'games_expected': 3,  # Only 3 games exist for this player
    'is_complete': True,  # Have all available
    'is_bootstrap': True, # <-- Less than full window
    'contributing_game_dates': ['2026-01-14', '2026-01-12', '2026-01-10']
}
```

### Scenario 5: Too Sparse (Skip)

```python
# Player with only 2 games
# games_found = 2, games_expected = 2
# Action: DON'T GENERATE FEATURE
# Player will not have a record in ml_feature_store_v2 for this date
```

---

## Querying Completeness

### Daily Summary

```sql
SELECT
    game_date,
    COUNT(*) as total_features,
    COUNTIF(historical_completeness.is_complete) as complete,
    COUNTIF(NOT historical_completeness.is_complete) as incomplete,
    COUNTIF(historical_completeness.is_bootstrap) as bootstrap
FROM ml_feature_store_v2
WHERE game_date >= '2026-01-01'
GROUP BY game_date
ORDER BY game_date DESC
```

### Find Data Gaps (Not Bootstrap)

```sql
SELECT game_date, player_lookup,
    historical_completeness.games_found,
    historical_completeness.games_expected
FROM ml_feature_store_v2
WHERE NOT historical_completeness.is_complete
  AND NOT historical_completeness.is_bootstrap
ORDER BY game_date DESC
```

### Find Players Missing Features

```sql
-- Players who played but have no feature record
SELECT DISTINCT pgs.player_lookup, pgs.game_date
FROM nba_analytics.player_game_summary pgs
LEFT JOIN nba_predictions.ml_feature_store_v2 mf
  ON pgs.player_lookup = mf.player_lookup
  AND pgs.game_date = mf.game_date
WHERE pgs.game_date = '2026-01-22'
  AND mf.player_lookup IS NULL
```

---

## Implementation Checklist

- [ ] Add `historical_completeness` column to schema
- [ ] Modify feature extractor to return game dates
- [ ] Modify processor to build completeness metadata
- [ ] Add minimum threshold (skip if < 5 games)
- [ ] Add logging for incomplete features
- [ ] Create cascade detection queries
- [ ] Create monitoring views

---

## What We're NOT Doing

1. **Not storing "missing_game_dates"** - Can be derived when needed
2. **Not explaining WHY data is missing** - That's a separate investigation
3. **Not blocking on incomplete data** - Just flag it
4. **Not tracking window span/staleness** - If we have the games, we have them

---

**Document Status:** APPROVED
**Ready for Implementation:** YES
