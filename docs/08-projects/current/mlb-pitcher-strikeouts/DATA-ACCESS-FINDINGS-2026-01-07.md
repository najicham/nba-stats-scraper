# MLB Data Access Research Findings

**Date**: 2026-01-07
**Status**: Research Complete
**Conclusion**: We have all the data we need - proceed with historical backfill

---

## Executive Summary

After hands-on testing, here's what works:

| Source | Status | What We Get |
|--------|--------|-------------|
| **MLB Stats API** | WORKS (FREE) | Lineups, Pitcher Ks, Game Data |
| **pybaseball/Statcast** | WORKS (FREE) | Season stats, K rates, Advanced metrics |
| **Ball Don't Lie MLB** | NOT WORKING | Returns "Unauthorized" |
| **The Odds API** | Not tested | Already integrated for NBA |

**Bottom Line**: We can build the complete bottom-up K model with FREE data.

---

## Detailed Findings

### 1. MLB Stats API (PRIMARY SOURCE)

**Tested**: `https://statsapi.mlb.com/api/v1.1/game/{gameId}/feed/live`

**Confirmed Working**:
- Full starting lineups with batting order (1-9)
- Player IDs that can join to other data
- Pitcher strikeouts per game (THE TARGET VARIABLE)
- No authentication required
- Works from cloud (no proxy needed)

**Sample Output from 2024-08-01 game**:
```
=== AWAY LINEUP (Baltimore) ===
  1. Colton Cowser (ID: 681297)
  2. Adley Rutschman (ID: 668939)
  3. Gunnar Henderson (ID: 683002)
  ...

=== STARTING PITCHER ===
  * Trevor Rogers: 4.1 IP, 3 K
```

**Why This Matters**:
- We know EXACTLY which 9 batters face each pitcher
- We have the TARGET variable (strikeouts)
- This enables the bottom-up K model

### 2. pybaseball/Statcast (SECONDARY SOURCE)

**Tested Functions**:
- `pitching_stats(2024, qual=50)` - FanGraphs pitcher stats
- `batting_stats(2024, qual=100)` - FanGraphs batter stats
- `statcast('2024-08-01', '2024-08-01')` - Pitch-level data

**Confirmed Data Available**:

| Data Type | Sample | Rows |
|-----------|--------|------|
| Pitcher Season Stats | K/9, K%, ERA, WHIP | 351 pitchers |
| Batter Season Stats | K%, BB%, OBP | 455 batters |
| Statcast Pitches | Velocity, events, p_throws | ~1400/day |

**Key Fields for Bottom-Up Model**:
```python
# From statcast data:
'p_throws': 'R' or 'L'     # Pitcher handedness
'stand': 'R' or 'L'        # Batter handedness
'events': 'strikeout', 'single', etc.
'batter': player_id
'pitcher': player_id
```

**Why This Matters**:
- We can calculate K% by batter vs LHP/RHP
- We get advanced pitcher metrics (velocity, whiff%)
- This enriches the feature vector

### 3. Ball Don't Lie MLB (NOT WORKING)

**Tested**: `https://api.balldontlie.io/mlb/v1/stats`

**Result**: Returns "Unauthorized" even with valid BDL API key

**Hypothesis**:
- MLB might require a separate subscription
- Or the MLB endpoints are not yet public
- NOT worth pursuing right now

**Impact**: None - MLB Stats API provides everything we need

---

## Data Strategy for Bottom-Up K Model

### The Key Formula

```
Pitcher Expected Ks = SUM(batter_i_K_rate × expected_ABs_i) for i=1 to 9
```

### Where Data Comes From

| Component | Source | How to Get |
|-----------|--------|------------|
| **Lineup (9 batters)** | MLB Stats API | `game/{id}/feed/live` → boxscore.teams.*.batters |
| **Batter K rate vs LHP** | pybaseball/statcast | Aggregate from pitch-level events |
| **Batter K rate vs RHP** | pybaseball/statcast | Aggregate from pitch-level events |
| **Pitcher handedness** | MLB Stats API | Player info or game feed |
| **Expected ABs per batter** | Calculate | Based on lineup position (1-9) |
| **Actual Ks (TARGET)** | MLB Stats API | `game/{id}/feed/live` → pitcher stats |

### Sample Calculation

For a game where Clayton Kershaw (LHP) faces the Cardinals:

```
Lineup Position | Batter         | K% vs LHP | Exp ABs | Expected Ks
----------------|----------------|-----------|---------|-------------
1               | Tommy Edman    | 0.22      | 4.2     | 0.92
2               | Brendan Donovan| 0.18      | 4.0     | 0.72
3               | Nolan Arenado  | 0.24      | 3.8     | 0.91
4               | Paul Goldschmidt| 0.26     | 3.6     | 0.94
5               | Willson Contreras| 0.28    | 3.4     | 0.95
6               | Lars Nootbaar  | 0.25      | 3.2     | 0.80
7               | Brendan Donovan| 0.18      | 3.0     | 0.54
8               | Masyn Winn     | 0.22      | 2.8     | 0.62
9               | Pitcher spot   | 0.35      | 2.6     | 0.91
                |                |           |         | --------
                | **TOTAL**      |           |         | **7.3 Ks**
```

---

## Historical Backfill Plan

### What We Need to Collect

| Dataset | Source | Date Range | Estimated Size |
|---------|--------|------------|----------------|
| Game Boxscores | MLB Stats API | 2022-2024 | ~7,300 games |
| Pitcher Stats | MLB Stats API | 2022-2024 | ~16,000 starts |
| Lineups | MLB Stats API | 2022-2024 | ~7,300 × 2 = 14,600 |
| Batter K Rates | pybaseball | 2022-2024 | ~1,500 batters |
| Statcast (optional) | pybaseball | 2024 only | ~750,000 pitches |

### Recommended Order

1. **Week 1**: Collect 2024 season data (most recent, best for validation)
2. **Week 2**: Collect 2023 season data (more training data)
3. **Week 3**: Collect 2022 season data (if needed)

### API Rate Limits

| Source | Rate Limit | Daily Capacity |
|--------|------------|----------------|
| MLB Stats API | ~60 req/min | ~86,000 req/day |
| pybaseball (Statcast) | Moderate | ~100 days/hour |

**Estimated Backfill Time**: 2-3 days for 2024 season, 1 week for all 3 seasons.

---

## Next Steps

### Immediate (This Session)

1. Create a simple backfill script for MLB Stats API
2. Test with 1 week of 2024 data
3. Validate lineup extraction works correctly

### Short-term

1. Calculate batter K rates vs LHP/RHP from statcast
2. Run bottom-up formula on test games
3. Measure baseline accuracy before ML

### Medium-term

1. Create ML training script
2. Train XGBoost model on 2024 data
3. Build prediction workers

---

## Command Reference

### MLB Stats API

```bash
# Get schedule for a date
curl -s "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2024-08-01&gameTypes=R"

# Get game boxscore with lineups
curl -s "https://statsapi.mlb.com/api/v1.1/game/746607/feed/live"
```

### pybaseball

```python
from pybaseball import pitching_stats, batting_stats, statcast

# Season pitcher stats
pitchers = pitching_stats(2024, qual=50)

# Season batter stats
batters = batting_stats(2024, qual=100)

# Pitch-level data
data = statcast('2024-08-01', '2024-08-01')
```

---

## Appendix: Sample API Responses

### MLB Stats API - Lineup Structure

```json
{
  "battingOrder": 100,  // Position 1
  "player": {
    "id": 681297,
    "fullName": "Colton Cowser"
  },
  "position": {"abbreviation": "CF"}
}
```

### MLB Stats API - Pitcher Stats

```json
{
  "inningsPitched": "6.0",
  "strikeOuts": 8,
  "hits": 4,
  "earnedRuns": 2
}
```

### pybaseball - Statcast Row

```python
{
  'game_pk': 746607,
  'batter': 681297,
  'pitcher': 657376,
  'p_throws': 'R',
  'stand': 'L',
  'events': 'strikeout',
  'description': 'called_strike'
}
```
