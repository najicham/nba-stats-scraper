# MLB Pitcher Strikeouts - Data Sources Analysis

**Updated**: 2026-01-06

## Executive Summary

After comprehensive research, here's the recommended data source hierarchy for MLB pitcher strikeout predictions:

| Priority | Source | Type | Status |
|----------|--------|------|--------|
| **P0** | Ball Don't Lie | API | Already integrated for NBA - just add MLB |
| **P0** | MLB Stats API | Official API | Free, no auth, cloud-friendly |
| **P1** | Baseball Savant/Statcast | Official | Best for advanced pitcher metrics |
| **P1** | The Odds API | API | Already integrated - supports `pitcher_strikeouts` |
| **P2** | FanGraphs | Scrape | K/9, K%, xFIP, WAR |
| **P2** | Baseball Reference | Scrape | Historical game logs |
| **NOT** | ESPN | Deprecated | API deprecated since 2013, no advanced stats |

---

## 1. Ball Don't Lie (RECOMMENDED)

### Status: YES - MLB Supported!

Ball Don't Lie supports **all major sports** including MLB:
- NBA, NFL, MLB, NHL, EPL, WNBA, NCAAF, NCAAB, MMA, World Cup

### Why This Is Great
- **Already integrated** - 16 NBA scrapers in your codebase
- **Same API patterns** - Consistent structure across sports
- **Same auth** - Bearer token (optional for free tier)
- **Same pagination** - Cursor-based

### Likely MLB Endpoints
```
https://api.balldontlie.io/v1/games?sport=mlb
https://api.balldontlie.io/v1/stats?sport=mlb
https://api.balldontlie.io/v1/players?sport=mlb
https://api.balldontlie.io/v1/teams?sport=mlb
https://api.balldontlie.io/v1/standings?sport=mlb
https://api.balldontlie.io/v1/odds?sport=mlb
https://api.balldontlie.io/v1/box_scores?sport=mlb
```

### Implementation
Copy existing BDL scrapers, change sport parameter:
```python
# scrapers/mlb/balldontlie/bdl_mlb_games.py
class BdlMlbGamesScraper(ScraperBase, ScraperFlaskMixin):
    _API_ROOT = "https://api.balldontlie.io/v1/games"

    def set_url(self):
        self.url = f"{self._API_ROOT}?sport=mlb&..."
```

---

## 2. MLB Stats API (RECOMMENDED)

### Comparison: MLB.com vs NBA.com

| Feature | MLB.com | NBA.com |
|---------|---------|---------|
| **Public API** | YES (statsapi.mlb.com) | YES (stats.nba.com) |
| **Auth Required** | NO | User-Agent headers |
| **Cloud IP Blocking** | NO | YES (aggressive) |
| **Proxy Needed** | NO | YES for cloud |
| **Rate Limiting** | Moderate | Aggressive Cloudflare |
| **Developer Friendly** | VERY | Difficult |

### Key Endpoints
```
Base: https://statsapi.mlb.com/api/v1/

/schedule?sportId=1&season=2024&gameTypes=R
/game/{gameId}/feed/live
/game/{gameId}/boxscore
/teams
/people/{playerId}
/standings
```

### Python Package
```bash
pip install MLB-StatsAPI
```

```python
from statsapi import statsapi

# Get pitcher stats
pitcher = statsapi.lookup_player("Clayton Kershaw")
game_logs = statsapi.player_stat_data(pitcher[0]['id'], 'pitching', 'season')
```

### Why Better Than NBA.com
- No proxy infrastructure needed
- Works from GCP/AWS directly
- More sustainable rate limiting
- Official API support

---

## 3. Baseball Savant / Statcast (RECOMMENDED)

### Best For: Advanced Pitcher Metrics

**Unique Data Available:**
- Pitch velocity (peak and effective)
- Spin rate (RPM at release)
- Pitch movement (horizontal/vertical)
- Extension (release point distance)
- Whiff rates (swinging strikes)
- Run value per pitch type

### Access Methods
1. **Web CSV Export** - https://baseballsavant.mlb.com/statcast_search
2. **pybaseball Package** - Python wrapper
3. **Direct scraping** - Statcast search pages

### Python Integration
```bash
pip install pybaseball
```

```python
from pybaseball import statcast_pitcher

# Get pitcher's Statcast data
data = statcast_pitcher(
    start_dt='2024-04-01',
    end_dt='2024-09-30',
    player_id=477132  # Clayton Kershaw
)
```

### Limitation
- 25,000 row query limit per request
- Need multiple queries for full season

---

## 4. The Odds API (Already Integrated)

### MLB Pitcher Strikeouts: SUPPORTED!

```python
# Already in codebase - just change parameters
sport_key = 'baseball_mlb'
markets = 'pitcher_strikeouts'

# Existing pattern in scrapers/oddsapi/oddsa_player_props.py
```

### Available Markets
- `pitcher_strikeouts` - Direct strikeout O/U
- `pitcher_hits_allowed`
- `pitcher_walks`
- `pitcher_earned_runs`

---

## 5. FanGraphs (Backup)

### Best For: Advanced Calculated Metrics

**Key Metrics:**
- K/9 (Strikeouts per 9 innings)
- K% (Strikeout percentage)
- xFIP (Expected FIP)
- WAR (Wins Above Replacement)

### Access Method
```python
from pybaseball import pitching_stats

# Season pitching stats from FanGraphs
stats = pitching_stats(2024, qual=50)  # min 50 IP
```

---

## 6. ESPN - NOT RECOMMENDED

### Why NOT ESPN

| Issue | Details |
|-------|---------|
| **Deprecated** | Official API deprecated since 2013 |
| **No Advanced Stats** | Missing Statcast data |
| **Unstable** | Endpoints can change without notice |
| **No Support** | No documentation or developer support |
| **TOS Risk** | Heavy automation may violate terms |

### What ESPN Has
- Basic stats only (K, ERA, WHIP, IP)
- No pitch velocity, spin rate, movement
- No per-pitch data

### Verdict
**Do not use ESPN** - MLB Stats API and Baseball Savant are superior in every way.

---

## Recommended Architecture

```
MLB Data Sources
├── PRIMARY LAYER (Real-time + Stats)
│   ├── Ball Don't Lie API ─── Games, Box Scores, Stats, Odds
│   ├── MLB Stats API ──────── Schedule, Rosters, Game Data
│   └── The Odds API ───────── Pitcher Strikeout Lines
│
├── ADVANCED METRICS LAYER
│   └── Baseball Savant ────── Statcast: velocity, spin, movement
│
└── BACKUP LAYER (Historical)
    ├── FanGraphs ──────────── K/9, K%, xFIP, WAR
    └── Baseball Reference ─── Historical game logs
```

---

## Implementation Priority

### Week 1: Core Data
1. **Ball Don't Lie MLB** - Adapt existing BDL scrapers
2. **Odds API MLB** - Add `baseball_mlb` sport key

### Week 2: Official Sources
3. **MLB Stats API** - New scrapers using `MLB-StatsAPI` package
4. **Baseball Savant** - `pybaseball` integration

### Week 3: Backup Sources
5. **FanGraphs** - Advanced metrics via `pybaseball`
6. **Baseball Reference** - Historical game logs

---

## Package Requirements

```
# New packages for MLB
pybaseball>=2.0.0
MLB-StatsAPI>=1.0.0
```

---

## Key Differences from NBA

| Aspect | NBA | MLB |
|--------|-----|-----|
| **Primary API** | stats.nba.com (needs proxy) | statsapi.mlb.com (open) |
| **Cloud Friendly** | No (IP blocking) | Yes |
| **Best Stats Source** | NBA.com | Baseball Savant |
| **Existing BDL Support** | Yes (16 scrapers) | Yes (same API) |
| **Odds API Support** | Yes | Yes (`pitcher_strikeouts`) |
