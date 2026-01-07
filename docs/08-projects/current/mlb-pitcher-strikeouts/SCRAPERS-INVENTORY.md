# MLB Scrapers Inventory

**Last Updated**: 2026-01-06
**Total Scrapers**: 28
**Status**: All implemented and tested

---

## Overview

The MLB data collection system consists of 28 scrapers across 5 data sources:

| Source | Scrapers | Auth Required |
|--------|----------|---------------|
| Ball Don't Lie API | 13 | API Key |
| MLB Stats API | 3 | None |
| Odds API | 8 | API Key |
| Statcast (pybaseball) | 1 | None |
| External Sources | 3 | Varies |

---

## Scraper Details

### Ball Don't Lie API (13 scrapers)

| Scraper | Purpose | Historical | Priority |
|---------|---------|------------|----------|
| `mlb_pitcher_stats` | Per-game pitching stats | ✅ Date range | **CRITICAL** |
| `mlb_batter_stats` | Per-game batting stats | ✅ Date range | **HIGH** |
| `mlb_games` | Game schedule/scores | ✅ Date range | MEDIUM |
| `mlb_active_players` | Active roster | ❌ Current | MEDIUM |
| `mlb_season_stats` | Season aggregates | ✅ Season | **HIGH** |
| `mlb_injuries` | Injury reports | ❌ Current | **HIGH** |
| `mlb_player_splits` | H/A, D/N splits | ✅ Season | **HIGH** |
| `mlb_standings` | Division standings | ✅ Season | MEDIUM |
| `mlb_box_scores` | Final box scores | ✅ Date | **HIGH** |
| `mlb_live_box_scores` | Live game data | ❌ Live | **HIGH** |
| `mlb_team_season_stats` | Team K rates | ✅ Season | **HIGH** |
| `mlb_player_versus` | H2H matchups | ✅ Season | **HIGH** |
| `mlb_teams` | Team reference | ❌ Static | LOW |

### MLB Stats API (3 scrapers)

| Scraper | Purpose | Historical | Priority |
|---------|---------|------------|----------|
| `mlb_schedule` | Probable pitchers | ✅ Date range | **CRITICAL** |
| `mlb_lineups` | Starting 9 batters | ✅ Date/game | **CRITICAL** |
| `mlb_game_feed` | Pitch-by-pitch | ✅ Game ID | **HIGH** |

### Odds API (8 scrapers)

| Scraper | Purpose | Historical | Priority |
|---------|---------|------------|----------|
| `mlb_events` | Event IDs | ❌ Current | MEDIUM |
| `mlb_game_lines` | ML/spread/totals | ❌ Current | **HIGH** |
| `mlb_pitcher_props` | K lines | ❌ Current | **CRITICAL** |
| `mlb_batter_props` | Batter K lines | ❌ Current | **HIGH** |
| `mlb_events_his` | Historical events | ✅ 6 months | MEDIUM |
| `mlb_game_lines_his` | Historical lines | ✅ 6 months | **HIGH** |
| `mlb_pitcher_props_his` | Historical K props | ✅ 6 months | **HIGH** |
| `mlb_batter_props_his` | Historical batter | ✅ 6 months | **HIGH** |

### Statcast (1 scraper)

| Scraper | Purpose | Historical | Priority |
|---------|---------|------------|----------|
| `mlb_statcast_pitcher` | SwStr%, velocity, spin | ✅ 2008+ | **HIGH** |

**Requires**: `pip install pybaseball`

### External Sources (3 scrapers)

| Scraper | Source | Purpose | Historical |
|---------|--------|---------|------------|
| `mlb_umpire_stats` | UmpScorecards | K zone tendencies | ✅ 2015+ |
| `mlb_ballpark_factors` | Static data | Park K adjustments | ✅ Annual |
| `mlb_weather` | OpenWeatherMap | Game-time weather | ❌ Current |

---

## Historical Data Capabilities

### Training Data Sources

For model training, use these scrapers with historical capability:

```
HIGH PRIORITY (must backfill):
├── mlb_pitcher_stats (2-3 seasons)
├── mlb_batter_stats (2-3 seasons)
├── mlb_schedule (2-3 seasons)
├── mlb_lineups (2-3 seasons)
├── mlb_season_stats (by season)
├── mlb_pitcher_props_his (6 months max)
└── mlb_batter_props_his (6 months max)

MEDIUM PRIORITY (enhances model):
├── mlb_player_splits (by season)
├── mlb_team_season_stats (by season)
├── mlb_player_versus (by player/season)
├── mlb_statcast_pitcher (full seasons)
├── mlb_umpire_stats (by season)
└── mlb_ballpark_factors (annual update)
```

### Data Retention Limits

| Source | Historical Limit |
|--------|------------------|
| Ball Don't Lie | Full seasons available |
| MLB Stats API | Unlimited (public) |
| Odds API | 6 months rolling |
| Statcast | 2008-present |
| UmpScorecards | 2015-present |

---

## Usage Examples

### Test a Scraper
```bash
# BDL scraper
SPORT=mlb PYTHONPATH=. .venv/bin/python \
  scrapers/mlb/balldontlie/mlb_standings.py --debug

# Ballpark factors (no API needed)
SPORT=mlb PYTHONPATH=. .venv/bin/python \
  scrapers/mlb/external/mlb_ballpark_factors.py --team_abbr NYY --debug

# Statcast (requires pybaseball)
SPORT=mlb PYTHONPATH=. .venv/bin/python \
  scrapers/mlb/statcast/mlb_statcast_pitcher.py --season 2025 --debug
```

### Historical Backfill
```bash
# Pitcher stats for a date range
for date in 2024-06-{01..30}; do
  python scrapers/mlb/balldontlie/mlb_pitcher_stats.py --date $date
  sleep 1  # Rate limit
done

# Historical props (6 months)
python scrapers/mlb/oddsapi/mlb_pitcher_props_his.py --date 2024-06-15
```

---

## Environment Variables

```bash
# Required for BDL
BDL_API_KEY=your_key
BDL_MLB_API_KEY=your_key  # Alternative

# Required for Odds API
ODDS_API_KEY=your_key

# Optional for weather
OPENWEATHERMAP_API_KEY=your_key
```

---

## Rate Limits

| Source | Limit | Recommendation |
|--------|-------|----------------|
| Ball Don't Lie | 60/min | 1 req/sec |
| MLB Stats API | None | Be reasonable |
| Odds API | Usage-based | Check quota |
| Statcast | 30k rows/query | Chunk date ranges |
| UmpScorecards | Unknown | Cache results |
| OpenWeatherMap | 1000/day (free) | Cache per game |

---

## K Prediction Value Summary

**CRITICAL** (must have for predictions):
- `mlb_schedule` - WHO is pitching
- `mlb_lineups` - WHICH batters (bottom-up)
- `mlb_pitcher_props` - TARGET betting line
- `mlb_pitcher_stats` - Actual K data

**HIGH** (significantly improves model):
- `mlb_batter_stats` - Individual K rates
- `mlb_season_stats` - Baseline features
- `mlb_player_splits` - Adjustments
- `mlb_statcast_pitcher` - SwStr%, chase rate
- `mlb_team_season_stats` - Opponent tendencies

**MEDIUM** (nice to have):
- `mlb_standings` - Playoff context
- `mlb_ballpark_factors` - Park effects
- `mlb_umpire_stats` - Zone tendencies

**LOW** (minimal impact):
- `mlb_weather` - Environmental factors
- `mlb_teams` - Reference only
