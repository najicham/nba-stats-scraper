# Ball Don't Lie MLB API - Endpoint Analysis for Pitcher Strikeouts

**Created**: 2026-01-06
**Source**: https://mlb.balldontlie.io/ and https://www.balldontlie.io/openapi.yml

## Executive Summary

Ball Don't Lie's MLB API provides **all the data we need** for pitcher strikeout predictions. The API structure mirrors their NBA API (which we already use), making integration straightforward.

---

## Recommended Endpoints for Pitcher Strikeouts

### Priority 1: Essential (Must Have)

| Endpoint | Purpose | Key Fields for Strikeouts |
|----------|---------|---------------------------|
| `GET /mlb/v1/stats` | Per-game pitcher stats | `P_K` (strikeouts), `IP` (innings pitched), `PITCH_COUNT`, `STRIKES` |
| `GET /mlb/v1/season_stats` | Season aggregates | `strikeouts_pitched`, `ERA`, `WHIP`, `innings_pitched` |
| `GET /mlb/v1/games` | Game schedule & scores | `date`, `home_team`, `away_team`, `status`, `venue` |
| `GET /mlb/v1/players/active` | Active pitcher roster | `position`, `team_id`, `player_id` |
| `GET /mlb/v1/player_injuries` | Injury status | `status`, `injury_type`, `return_date` |

### Priority 2: Important (Enhances Predictions)

| Endpoint | Purpose | Value for ML Features |
|----------|---------|----------------------|
| `GET /mlb/v1/players/splits` | Performance breakdowns | vs RHP/LHP, by month, by opponent, home/away, day/night |
| `GET /mlb/v1/players/versus` | Head-to-head matchups | Pitcher vs specific batters/teams |
| `GET /mlb/v1/standings` | Team standings | Playoff race context, team strength |
| `GET /mlb/v1/teams/season_stats` | Team-level stats | Team strikeout rates (opponent K%) |

### Priority 3: Nice to Have

| Endpoint | Purpose |
|----------|---------|
| `GET /mlb/v1/players` | Full player database |
| `GET /mlb/v1/teams` | Team metadata |
| `GET /mlb/v1/players/{id}` | Individual player details |

---

## Pitching Statistics Available

### Per-Game Stats (`/mlb/v1/stats`)

```
P_K          - Strikeouts (THIS IS OUR TARGET VARIABLE)
IP           - Innings Pitched
PITCH_COUNT  - Total Pitches Thrown
STRIKES      - Strike Pitches
P_BB         - Walks Allowed
P_HITS       - Hits Allowed
P_HR         - Home Runs Allowed
P_RUNS       - Runs Allowed
ER           - Earned Runs
W            - Win (0/1)
L            - Loss (0/1)
```

### Season Stats (`/mlb/v1/season_stats`)

```
strikeouts_pitched  - Total Ks for season
ERA                 - Earned Run Average
WHIP                - Walks + Hits per IP
innings_pitched     - Total IP
walks_allowed       - Total walks
hits_allowed        - Total hits
home_runs_allowed   - Total HRs
opponent_avg        - Opponent batting average
wins                - Total wins
losses              - Total losses
saves               - Total saves
```

### Splits Data (`/mlb/v1/players/splits`)

Categories available:
- **Venue**: Home vs Away
- **Time**: Day vs Night games
- **Month**: Monthly performance trends
- **Opponent**: Performance by opposing team
- **Count**: Performance by pitch count situations
- **Recent**: Last 7/15/30 days trending

---

## Mapping to NBA Scrapers

We can adapt our existing NBA BDL scrapers:

| NBA Scraper | MLB Equivalent | Changes Needed |
|-------------|----------------|----------------|
| `bdl_box_scores.py` | `mlb_pitcher_stats.py` | Change endpoint, parse pitching stats |
| `bdl_player_averages.py` | `mlb_season_stats.py` | Change endpoint, filter for pitchers |
| `bdl_games.py` | `mlb_games.py` | Minimal changes (structure similar) |
| `bdl_active_players.py` | `mlb_active_players.py` | Filter for pitchers (position check) |
| `bdl_injuries.py` | `mlb_injuries.py` | Nearly identical structure |
| `bdl_standings.py` | `mlb_standings.py` | Structure similar |
| (new) | `mlb_player_splits.py` | New - for split statistics |
| (new) | `mlb_player_versus.py` | New - for head-to-head data |

---

## Feature Engineering Potential

From this API, we can build these ML features:

### From Per-Game Stats
```python
# Recent performance (rolling averages)
strikeouts_last_5_games = mean(P_K over last 5 games)
strikeouts_last_10_games = mean(P_K over last 10 games)
strikeouts_std_last_10 = std(P_K over last 10 games)
innings_pitched_avg = mean(IP over last 10 games)
pitches_per_strikeout = PITCH_COUNT / P_K
strikeout_rate = P_K / IP
```

### From Season Stats
```python
season_k_per_9 = (strikeouts_pitched / innings_pitched) * 9
season_whip = WHIP
season_era = ERA
```

### From Splits
```python
home_k_rate = splits['home'].strikeouts / splits['home'].innings
away_k_rate = splits['away'].strikeouts / splits['away'].innings
day_game_k_rate = splits['day'].strikeouts / splits['day'].innings
vs_opponent_k_rate = splits[opponent].strikeouts / splits[opponent].innings
recent_7_day_k_rate = splits['last_7'].strikeouts / splits['last_7'].innings
```

### From Head-to-Head
```python
vs_team_historical_k_rate = versus[team].strikeouts / versus[team].at_bats
```

---

## API Authentication

Same pattern as NBA:
```
Authorization: YOUR_API_KEY
```

We already have BDL API key in our environment - should work for MLB too with subscription upgrade.

---

## Rate Limits by Tier (MLB-Specific)

| Tier | Requests/Minute | Cost | Endpoints |
|------|-----------------|------|-----------|
| **Free** | 5 | $0 | Teams, Players, Games only |
| **ALL-STAR** | 60 | $9.99/mo | + Injuries, Active Players, Standings, Stats |
| **GOAT** | 600 | $39.99/mo | ALL endpoints including Splits, Versus, Season Stats |

**Important**: Paid tiers do NOT apply across sports. MLB subscription is separate from NBA.

**ALL-ACCESS**: $299.99/mo for all sports (NBA, NFL, MLB, NHL, EPL, etc.)

**Recommendation**:
- **GOAT tier ($39.99/mo)** for MLB pitcher strikeouts - we need splits and season stats
- If already paying for NBA, total would be ~$80/mo for both sports at GOAT level
- Consider ALL-ACCESS ($299.99/mo) if planning to add more sports

---

## Implementation Plan

### Phase 1: Core Scrapers (Week 1-2)
1. `mlb_games.py` - Game schedule
2. `mlb_pitcher_stats.py` - Per-game pitching stats (includes P_K!)
3. `mlb_active_players.py` - Active pitchers
4. `mlb_injuries.py` - Pitcher injuries

### Phase 2: Enhanced Data (Week 2-3)
5. `mlb_season_stats.py` - Season aggregates
6. `mlb_standings.py` - Team standings
7. `mlb_player_splits.py` - Split statistics

### Phase 3: Advanced Features (Week 3-4)
8. `mlb_player_versus.py` - Head-to-head matchups
9. `mlb_team_stats.py` - Team-level strikeout rates

---

## Key Insight

The `P_K` field in `/mlb/v1/stats` is **exactly what we need** - this is the per-game strikeout count that we'll predict. Combined with the splits and season stats, we have everything required to build a prediction model matching our NBA approach.
