# MLB Scrapers Complete Implementation - Handoff Document

**Date**: 2026-01-06
**Status**: 28 MLB Scrapers Complete, Ready for Data Collection
**Project Goal**: Predict pitcher strikeout over/under using bottom-up batter K rates

---

## Executive Summary

We've built a comprehensive MLB data collection system with **28 scrapers** across 5 data sources. All scrapers are implemented, tested, and ready for production deployment.

```
TOTAL MLB SCRAPERS: 28
├── Ball Don't Lie API:     13 scrapers
├── MLB Stats API:           3 scrapers
├── Odds API:                8 scrapers (4 current + 4 historical)
├── Statcast (pybaseball):   1 scraper
└── External Sources:        3 scrapers
```

---

## Scraper Inventory by Category

### Ball Don't Lie API (13 scrapers)

| Scraper | File | Historical? | K Prediction Value |
|---------|------|-------------|-------------------|
| `MlbPitcherStatsScraper` | `mlb_pitcher_stats.py` | ✅ Yes (by date) | **CRITICAL** - Target variable |
| `MlbBatterStatsScraper` | `mlb_batter_stats.py` | ✅ Yes (by date) | **HIGH** - Bottom-up model |
| `MlbGamesScraper` | `mlb_games.py` | ✅ Yes (by date) | MEDIUM - Game context |
| `MlbActivePlayersScraper` | `mlb_active_players.py` | ❌ Current only | MEDIUM - Roster validation |
| `MlbSeasonStatsScraper` | `mlb_season_stats.py` | ✅ Yes (by season) | **HIGH** - Baseline features |
| `MlbInjuriesScraper` | `mlb_injuries.py` | ❌ Current only | **HIGH** - Filter injured |
| `MlbPlayerSplitsScraper` | `mlb_player_splits.py` | ✅ Yes (by season) | **HIGH** - Split adjustments |
| `MlbStandingsScraper` | `mlb_standings.py` | ✅ Yes (by season) | MEDIUM - Playoff context |
| `MlbBoxScoresScraper` | `mlb_box_scores.py` | ✅ Yes (by date) | **HIGH** - Grading |
| `MlbLiveBoxScoresScraper` | `mlb_live_box_scores.py` | ❌ Live only | **HIGH** - Live betting |
| `MlbTeamSeasonStatsScraper` | `mlb_team_season_stats.py` | ✅ Yes (by season) | **HIGH** - Team K rates |
| `MlbPlayerVersusScraper` | `mlb_player_versus.py` | ✅ Yes (by season) | **HIGH** - H2H matchups |
| `MlbTeamsScraper` | `mlb_teams.py` | ❌ Reference data | LOW - Team metadata |

### MLB Stats API (3 scrapers)

| Scraper | File | Historical? | K Prediction Value |
|---------|------|-------------|-------------------|
| `MlbScheduleScraper` | `mlb_schedule.py` | ✅ Yes (by date) | **CRITICAL** - Probable pitchers |
| `MlbLineupsScraper` | `mlb_lineups.py` | ✅ Yes (by date/game) | **CRITICAL** - Bottom-up model |
| `MlbGameFeedScraper` | `mlb_game_feed.py` | ✅ Yes (by game_pk) | **HIGH** - Pitch sequences |

### Odds API (8 scrapers)

| Scraper | File | Historical? | K Prediction Value |
|---------|------|-------------|-------------------|
| `MlbEventsOddsScraper` | `mlb_events.py` | ❌ Current only | MEDIUM - Join key |
| `MlbGameLinesScraper` | `mlb_game_lines.py` | ❌ Current only | **HIGH** - Game context |
| `MlbPitcherPropsScraper` | `mlb_pitcher_props.py` | ❌ Current only | **CRITICAL** - Target line |
| `MlbBatterPropsScraper` | `mlb_batter_props.py` | ❌ Current only | **HIGH** - Bottom-up |
| `MlbEventsHistoricalScraper` | `mlb_events_his.py` | ✅ Yes (6 months) | MEDIUM - Training data |
| `MlbGameLinesHistoricalScraper` | `mlb_game_lines_his.py` | ✅ Yes (6 months) | **HIGH** - Training data |
| `MlbPitcherPropsHistoricalScraper` | `mlb_pitcher_props_his.py` | ✅ Yes (6 months) | **HIGH** - Training data |
| `MlbBatterPropsHistoricalScraper` | `mlb_batter_props_his.py` | ✅ Yes (6 months) | **HIGH** - Training data |

### Statcast via pybaseball (1 scraper)

| Scraper | File | Historical? | K Prediction Value |
|---------|------|-------------|-------------------|
| `MlbStatcastPitcherScraper` | `mlb_statcast_pitcher.py` | ✅ Yes (2008-present) | **HIGH** - SwStr%, chase rate |

**Requirements**: `pip install pybaseball`

### External Sources (3 scrapers)

| Scraper | File | Historical? | K Prediction Value |
|---------|------|-------------|-------------------|
| `MlbUmpireStatsScraper` | `mlb_umpire_stats.py` | ✅ Yes (2015-present) | MEDIUM - Zone tendencies |
| `MlbBallparkFactorsScraper` | `mlb_ballpark_factors.py` | ✅ Static (annual) | MEDIUM - Park adjustments |
| `MlbWeatherScraper` | `mlb_weather.py` | ❌ Current only | LOW - Weather effects |

**Requirements**:
- Umpire stats: `pip install beautifulsoup4`
- Weather: `OPENWEATHERMAP_API_KEY` environment variable

---

## Historical vs Current-Day Capabilities

### Scrapers with Historical Capability (19 total)

These scrapers can fetch historical data for model training:

```
HISTORICAL DATA SOURCES:
├── Ball Don't Lie (dates go back full season)
│   ├── mlb_pitcher_stats --date 2024-06-15
│   ├── mlb_batter_stats --date 2024-06-15
│   ├── mlb_games --date 2024-06-15
│   ├── mlb_season_stats --season 2024
│   ├── mlb_player_splits --season 2024
│   ├── mlb_standings --season 2024
│   ├── mlb_box_scores --date 2024-06-15
│   ├── mlb_team_season_stats --season 2024
│   └── mlb_player_versus --player_id 12345 --season 2024
│
├── MLB Stats API (unlimited history)
│   ├── mlb_schedule --date 2024-06-15
│   ├── mlb_lineups --date 2024-06-15
│   └── mlb_game_feed --game_pk 745263
│
├── Odds API (6 months max)
│   ├── mlb_events_his --date 2024-06-15
│   ├── mlb_game_lines_his --date 2024-06-15
│   ├── mlb_pitcher_props_his --date 2024-06-15
│   └── mlb_batter_props_his --date 2024-06-15
│
├── Statcast (2008-present)
│   └── mlb_statcast_pitcher --start_date 2024-06-01 --end_date 2024-06-30
│
└── External
    ├── mlb_umpire_stats --season 2024
    └── mlb_ballpark_factors --season 2024
```

### Current-Day Only Scrapers (9 total)

These scrapers only return live/current data:

```
CURRENT-DAY ONLY:
├── mlb_active_players    - Today's active roster
├── mlb_injuries          - Current injury list
├── mlb_live_box_scores   - Games in progress
├── mlb_teams             - Reference data (rarely changes)
├── mlb_events            - Today's event IDs
├── mlb_game_lines        - Today's betting lines
├── mlb_pitcher_props     - Today's K lines
├── mlb_batter_props      - Today's batter K lines
└── mlb_weather           - Current stadium weather
```

---

## Data Collection Workflows

### Morning Workflow (6-7 AM ET)

```bash
# 1. Get today's schedule with probable pitchers
python scrapers/mlb/mlbstatsapi/mlb_schedule.py --date today

# 2. Get injury reports
python scrapers/mlb/balldontlie/mlb_injuries.py

# 3. Get standings for playoff context
python scrapers/mlb/balldontlie/mlb_standings.py

# 4. Get today's K lines
python scrapers/mlb/oddsapi/mlb_pitcher_props.py

# 5. Get weather for all stadiums
python scrapers/mlb/external/mlb_weather.py --all_stadiums true
```

### Pre-Game Workflow (1-2 hours before each game)

```bash
# 1. Get starting lineups (released ~1-2 hours before)
python scrapers/mlb/mlbstatsapi/mlb_lineups.py --date today

# 2. Get batter K lines (for bottom-up model)
python scrapers/mlb/oddsapi/mlb_batter_props.py

# 3. Run feature processor and make predictions
# (uses data from above)
```

### Post-Game Workflow (after games complete)

```bash
# 1. Get final box scores for grading
python scrapers/mlb/balldontlie/mlb_box_scores.py --date today

# 2. Update model accuracy tracking
```

### Historical Backfill Workflow (for training data)

```bash
# 1. Backfill pitcher stats (2-3 seasons)
for date in 2024-04-01 to 2024-10-01:
    python scrapers/mlb/balldontlie/mlb_pitcher_stats.py --date $date

# 2. Backfill batter stats
for date in 2024-04-01 to 2024-10-01:
    python scrapers/mlb/balldontlie/mlb_batter_stats.py --date $date

# 3. Backfill historical props (6 months max)
for date in last_6_months:
    python scrapers/mlb/oddsapi/mlb_pitcher_props_his.py --date $date

# 4. Backfill Statcast data
python scrapers/mlb/statcast/mlb_statcast_pitcher.py --season 2024
```

---

## API Requirements & Rate Limits

| Source | Auth Required | Rate Limits | Historical Depth |
|--------|---------------|-------------|------------------|
| Ball Don't Lie MLB | API Key | 60/min | Full season+ |
| MLB Stats API | None | None | Unlimited |
| Odds API | API Key | Usage-based | 6 months |
| Baseball Savant | None | 30k rows/query | 2008-present |
| UmpScorecards | None | Be respectful | 2015-present |
| OpenWeatherMap | API Key | 1000/day (free) | Current only |

### Environment Variables Needed

```bash
# Required
BDL_API_KEY=your_ball_dont_lie_key
BDL_MLB_API_KEY=your_ball_dont_lie_mlb_key  # or use BDL_API_KEY
ODDS_API_KEY=your_odds_api_key

# Optional
OPENWEATHERMAP_API_KEY=your_weather_key  # for weather data
```

---

## File Structure

```
scrapers/mlb/
├── __init__.py                    # Main package exports (28 scrapers)
├── balldontlie/                   # Ball Don't Lie API (13 scrapers)
│   ├── __init__.py
│   ├── mlb_pitcher_stats.py
│   ├── mlb_batter_stats.py
│   ├── mlb_games.py
│   ├── mlb_active_players.py
│   ├── mlb_season_stats.py
│   ├── mlb_injuries.py
│   ├── mlb_player_splits.py
│   ├── mlb_standings.py          # NEW
│   ├── mlb_box_scores.py         # NEW
│   ├── mlb_live_box_scores.py    # NEW
│   ├── mlb_team_season_stats.py  # NEW
│   ├── mlb_player_versus.py      # NEW
│   └── mlb_teams.py              # NEW
├── mlbstatsapi/                   # Official MLB API (3 scrapers)
│   ├── __init__.py
│   ├── mlb_schedule.py
│   ├── mlb_lineups.py
│   └── mlb_game_feed.py          # NEW
├── oddsapi/                       # Odds API (8 scrapers)
│   ├── __init__.py
│   ├── mlb_events.py
│   ├── mlb_game_lines.py
│   ├── mlb_pitcher_props.py
│   ├── mlb_batter_props.py
│   ├── mlb_events_his.py
│   ├── mlb_game_lines_his.py
│   ├── mlb_pitcher_props_his.py
│   └── mlb_batter_props_his.py
├── statcast/                      # Statcast via pybaseball (1 scraper)
│   ├── __init__.py
│   └── mlb_statcast_pitcher.py   # NEW
└── external/                      # External sources (3 scrapers)
    ├── __init__.py
    ├── mlb_umpire_stats.py       # NEW (UmpScorecards)
    ├── mlb_ballpark_factors.py   # NEW (static data)
    └── mlb_weather.py            # NEW (OpenWeatherMap)
```

---

## Verification Commands

```bash
# Verify all 28 MLB scrapers import
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from scrapers.mlb import *
print(f'Total scrapers exported: {len(__all__)}')
for name in sorted(__all__):
    print(f'  - {name}')
"

# Quick test of a scraper
SPORT=mlb PYTHONPATH=. .venv/bin/python scrapers/mlb/balldontlie/mlb_standings.py --debug

# Test ballpark factors (no API needed)
SPORT=mlb PYTHONPATH=. .venv/bin/python scrapers/mlb/external/mlb_ballpark_factors.py --debug
```

---

## What's Next

### Immediate Priorities

1. **Create BigQuery Tables**
   ```bash
   bq mk --dataset nba-props-platform:mlb_raw
   bq mk --dataset nba-props-platform:mlb_analytics
   # Run all schema SQL files
   ```

2. **Run Historical Backfill**
   - Need 2-3 seasons of data for model training
   - Start with pitcher_stats, batter_stats, schedule

3. **Create XGBoost Training Script**
   - Template: `ml/train_real_xgboost.py`
   - Target: `ml/train_pitcher_strikeouts_xgboost.py`

4. **Deploy Cloud Functions**
   - Morning workflow scheduler
   - Pre-game lineup checker
   - Post-game grading

### Feature Processor Updates

The `pitcher_features_processor.py` can now use these new data sources:

| Feature | Data Source |
|---------|-------------|
| `f14_vs_opponent_k_rate` | `MlbPlayerVersusScraper` |
| `f15_opponent_team_k_rate` | `MlbTeamSeasonStatsScraper` |
| `f17_ballpark_k_factor` | `MlbBallparkFactorsScraper` |
| `f_umpire_zone_tendency` | `MlbUmpireStatsScraper` |
| `f_weather_k_factor` | `MlbWeatherScraper` |

---

## Copy-Paste Prompt for New Chat

```
Continue the MLB pitcher strikeouts project.

Read the handoff: docs/09-handoff/2026-01-06-MLB-SCRAPERS-COMPLETE-HANDOFF.md

STATUS:
- 28 MLB scrapers COMPLETE and tested
- Layers 1-4 code complete (scrapers, processors, analytics, features)
- BigQuery tables NOT YET CREATED (blocker)
- Layer 5 (Model Training) is NEXT

WHAT WAS JUST COMPLETED:
- 11 new scrapers added this session
- External data sources: umpire stats, ballpark factors, weather
- Historical capability analysis complete
- Full documentation updated

NEXT STEPS:
1. Create BigQuery datasets and tables (run schema SQL)
2. Run historical backfill for training data
3. Create ml/train_pitcher_strikeouts_xgboost.py
4. Deploy Cloud Functions for scheduling

VERIFY SCRAPERS:
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "from scrapers.mlb import *; print(f'{len(__all__)} scrapers')"
```

---

**Last Updated**: 2026-01-06
**Total Scrapers**: 28
**Session Work**: Added 11 new scrapers, external data sources, comprehensive documentation
