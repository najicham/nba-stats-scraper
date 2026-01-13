# NBA.com Tracking Stats Enhancement

## Current State

We do NOT currently scrape NBA.com's player tracking data (Second Spectrum derived).

## What's Available (Free via NBA.com)

NBA.com exposes Second Spectrum tracking data through their stats API:

### Speed & Distance
- `DIST_FEET` - Total distance traveled
- `DIST_MILES` - Distance in miles
- `DIST_MILES_OFF` - Offensive distance
- `DIST_MILES_DEF` - Defensive distance
- `AVG_SPEED` - Average speed
- `AVG_SPEED_OFF` - Offensive speed
- `AVG_SPEED_DEF` - Defensive speed

### Touches & Possession
- `TOUCHES` - Total touches
- `FRONT_CT_TOUCHES` - Front court touches
- `TIME_OF_POSS` - Time of possession
- `AVG_SEC_PER_TOUCH` - Seconds per touch
- `AVG_DRIB_PER_TOUCH` - Dribbles per touch
- `PTS_PER_TOUCH` - Points per touch

### Paint Activity
- `PAINT_TOUCHES` - Touches in paint
- `POST_TOUCHES` - Post touches
- `ELBOW_TOUCHES` - Elbow touches
- `DRIVES` - Drives to basket
- `DRIVE_PTS` - Points from drives

### Shot Quality
- `CONTESTED_SHOTS` - Contested shot attempts
- `CONTESTED_2PT` - Contested 2-pointers
- `CONTESTED_3PT` - Contested 3-pointers
- `UNCONTESTED_SHOTS` - Open shot attempts

### Rebounding
- `REB_CHANCES` - Rebound chances
- `REB_CHANCE_PCT` - Rebound chance conversion
- `DEF_REB_CHANCE_PCT` - Defensive rebound %
- `OFF_REB_CHANCE_PCT` - Offensive rebound %

## Why This Matters for Prop Betting

These metrics capture **how** a player scores, not just **that** they scored:

1. **Touches** - More touches = more scoring opportunities
2. **Paint touches** - Paint scorers are more consistent
3. **Drives** - Drive-heavy players get to the line more
4. **Contested vs uncontested** - Shot difficulty affects variance
5. **Speed/distance** - Fatigue indicator, effort level

## Implementation Plan

### Step 1: New Scraper

Create `scrapers/nbacom/nbac_player_tracking.py`

**Endpoints:**
```
# Speed & Distance
https://stats.nba.com/stats/leaguedashptstats?PtMeasureType=SpeedDistance&...

# Touches
https://stats.nba.com/stats/leaguedashptstats?PtMeasureType=Possessions&...

# Paint touches
https://stats.nba.com/stats/leaguedashptstats?PtMeasureType=PaintTouch&...

# Drives
https://stats.nba.com/stats/leaguedashptstats?PtMeasureType=Drives&...
```

**Headers required:** Same as existing NBA.com scrapers (stats_nba_headers)

### Step 2: Raw Processor

Create `data_processors/raw/nbacom/nbac_player_tracking_processor.py`

**Output table:** `nba_raw.nbac_player_tracking`

### Step 3: Analytics Integration

Add tracking features to `upcoming_player_game_context`:
- `avg_touches_last_5`
- `avg_paint_touches_last_5`
- `avg_drives_last_5`
- `contested_shot_pct`

### Step 4: ML Feature Engineering

Add to Phase 4 precompute for ML models:
- `touches_per_minute`
- `paint_touch_rate`
- `drive_frequency`
- `shot_quality_index` (uncontested % weighted)

## API Endpoints Reference

```python
# Base URL
BASE = "https://stats.nba.com/stats/leaguedashptstats"

# Common parameters
PARAMS = {
    "College": "",
    "Conference": "",
    "Country": "",
    "DateFrom": "",
    "DateTo": "",
    "Division": "",
    "DraftPick": "",
    "DraftYear": "",
    "GameScope": "",
    "Height": "",
    "LastNGames": 0,
    "LeagueID": "00",
    "Location": "",
    "Month": 0,
    "OpponentTeamID": 0,
    "Outcome": "",
    "PORound": 0,
    "PerMode": "PerGame",  # or "Totals"
    "PlayerExperience": "",
    "PlayerOrTeam": "Player",
    "PlayerPosition": "",
    "PtMeasureType": "SpeedDistance",  # Key param - varies by stat type
    "Season": "2025-26",
    "SeasonSegment": "",
    "SeasonType": "Regular Season",
    "StarterBench": "",
    "TeamID": 0,
    "VsConference": "",
    "VsDivision": "",
    "Weight": ""
}

# PtMeasureType options:
# - SpeedDistance (speed, distance)
# - Possessions (touches, time of possession)
# - PaintTouch (paint touches)
# - PostTouch (post touches)
# - ElbowTouch (elbow touches)
# - Drives (drives)
# - Passing (passes made/received)
# - Rebounding (rebound chances)
# - Defense (contested shots)
# - CatchShoot (catch and shoot)
# - PullUpShot (pull up shots)
```

## Effort Estimate

- Step 1: 3-4 hours (scraper with multiple endpoints)
- Step 2: 2-3 hours (processor)
- Step 3: 2-3 hours (analytics integration)
- Step 4: 2-3 hours (ML features)

**Total: ~1.5 days of work**

## Risks

- NBA.com rate limiting (already handle this)
- Season-start lag (tracking data not available until games played)
- Endpoint changes (NBA.com updates APIs occasionally)

## Success Metrics

- New features show correlation with scoring variance
- ML model accuracy improves 0.5-1%
- Better prediction on high-touch vs low-touch players
