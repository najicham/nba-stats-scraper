# NBA Scrapers - GCS Output Path Reference

## Base Configuration
- **Bucket**: `nba-scraped-data`
- **Base Path**: `gs://nba-scraped-data/`

## Ball Don't Lie API Scrapers (5 total)

### 1. BdlGamesScraper
- **File**: `scrapers/balldontlie/bdl_games.py`
- **Class**: `BdlGamesScraper`
- **Output Path**: `/ball-dont-lie/games/{date}/{timestamp}.json`

### 2. BdlPlayerBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_player_box_scores.py`
- **Class**: `BdlPlayerBoxScoresScraper`
- **Output Paths**: 
  - By date: `/ball-dont-lie/player-box-scores/{date}/{timestamp}.json`
  - By game: `/ball-dont-lie/player-box-scores/{date}/game_{id}/{timestamp}.json`

### 3. BdlBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_box_scores.py`
- **Class**: `BdlBoxScoresScraper`
- **Output Path**: `/ball-dont-lie/boxscores/{date}/{timestamp}.json`

### 4. BdlActivePlayersScraper ⭐ **CRITICAL**
- **File**: `scrapers/balldontlie/bdl_active_players.py`
- **Class**: `BdlActivePlayersScraper`
- **Output Path**: `/ball-dont-lie/active-players/{date}/{timestamp}.json`

### 5. BdlInjuriesScraper
- **File**: `scrapers/balldontlie/bdl_injuries.py`
- **Class**: `BdlInjuriesScraper`
- **Output Path**: `/ball-dont-lie/injuries/{date}/{timestamp}.json`

---

## Odds API Scrapers (5 total)

### 1. GetOddsApiEvents ⭐ **CRITICAL**
- **File**: `scrapers/oddsapi/oddsa_events.py`
- **Class**: `GetOddsApiEvents`
- **Output Path**: `/odds-api/events/{date}/{timestamp}.json`

### 2. GetOddsApiCurrentEventOdds ⭐ **CORE BUSINESS**
- **File**: `scrapers/oddsapi/oddsa_player_props.py`
- **Class**: `GetOddsApiCurrentEventOdds`
- **Output Path**: `/odds-api/player-props/{date}/event_{id}/{timestamp}.json`

### 3. GetOddsApiHistoricalEvents
- **File**: `scrapers/oddsapi/oddsa_events_his.py`
- **Class**: `GetOddsApiHistoricalEvents`
- **Output Path**: `/odds-api/events-history/{date}/{timestamp}.json`

### 4. GetOddsApiHistoricalEventOdds
- **File**: `scrapers/oddsapi/oddsa_player_props_his.py`
- **Class**: `GetOddsApiHistoricalEventOdds`
- **Output Path**: `/odds-api/player-props-history/{date}/event_{id}/{timestamp}.json`

### 5. GetOddsApiTeamPlayers
- **File**: `scrapers/oddsapi/oddsa_team_players.py`
- **Class**: `GetOddsApiTeamPlayers`
- **Output Path**: `/odds-api/players/{date}/{timestamp}.json`

---

## ESPN Scrapers (3 total)

### 1. GetEspnTeamRosterAPI
- **File**: `scrapers/espn/espn_roster_api.py`
- **Backup File**: `scrapers/espn/espn_roster.py` (GetEspnTeamRoster)
- **Class**: `GetEspnTeamRosterAPI`
- **Output Path**: `/espn/rosters/{date}/team_{abbrev}/{timestamp}.json`

### 2. GetEspnScoreboard
- **File**: `scrapers/espn/espn_scoreboard_api.py`
- **Class**: `GetEspnScoreboard`
- **Output Path**: `/espn/scoreboard/{date}/{timestamp}.json`

### 3. GetEspnBoxscore
- **File**: `scrapers/espn/espn_game_boxscore.py`
- **Class**: `GetEspnBoxscore`
- **Output Path**: `/espn/boxscores/{date}/game_{id}/{timestamp}.json`

---

## NBA.com Scrapers (9 total)

### 1. GetNbaComPlayerList ⭐ **CRITICAL**
- **File**: `scrapers/nbacom/nbac_player_list.py`
- **Class**: `GetNbaComPlayerList`
- **Output Path**: `/nba-com/player-list/{date}/{timestamp}.json`

### 2. GetDataNbaSeasonSchedule
- **File**: `scrapers/nbacom/nbac_current_schedule_v2_1.py`
- **Class**: `GetDataNbaSeasonSchedule`
- **Output Path**: `/nba-com/schedule/{date}/{timestamp}.json`

### 3. GetNbaComScheduleCdn
- **File**: `scrapers/nbacom/nbac_schedule_cdn.py`
- **Class**: `GetNbaComScheduleCdn`
- **Output Path**: `/nba-com/schedule-cdn/{date}/{timestamp}.json`

### 4. GetNbaComScoreboardV2
- **File**: `scrapers/nbacom/nbac_scoreboard_v2.py`
- **Class**: `GetNbaComScoreboardV2`
- **Output Path**: `/nba-com/scoreboard-v2/{date}/{timestamp}.json`

### 5. GetNbaComInjuryReport ⭐ **CRITICAL**
- **File**: `scrapers/nbacom/nbac_injury_report.py`
- **Class**: `GetNbaComInjuryReport`
- **Output Path**: `/nba-com/injury-report/{date}/report_{date}_{hour}/{timestamp}.json`

### 6. GetNbaComPlayByPlay
- **File**: `scrapers/nbacom/nbac_play_by_play.py`
- **Class**: `GetNbaComPlayByPlay`
- **Output Path**: `/nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json`

### 7. GetNbaComPlayerBoxscore
- **File**: `scrapers/nbacom/nbac_player_boxscore.py`
- **Class**: `GetNbaComPlayerBoxscore`
- **Output Path**: `/nba-com/player-boxscores/{date}/{timestamp}.json`

### 8. GetNbaTeamRoster
- **File**: `scrapers/nbacom/nbac_roster.py`
- **Class**: `GetNbaTeamRoster`
- **Output Path**: `/nba-com/rosters/{date}/team_{abbrev}/{timestamp}.json`

### 9. GetNbaComPlayerMovement
- **File**: `scrapers/nbacom/nbac_player_movement.py`
- **Class**: `GetNbaComPlayerMovement`
- **Output Path**: `/nba-com/player-movement/{date}/{timestamp}.json`

---

## Big Data Ball Scrapers (1 total)

### 1. Enhanced Play-by-Play Data
- **Source**: Google Drive service account access
- **File Format**: CSV files
- **Output Path**: `/big-data-ball/play-by-play/{date}/game_{id}/{timestamp}.csv`

---

## Path Pattern Analysis

### Common Variables Used:
- `{date}` - Date in YYYY-MM-DD format
- `{timestamp}` - Timestamp for file versioning
- `{id}` or `{gameId}` - Game identifier
- `{abbrev}` - Team abbreviation (3 letters)
- `{hour}` - Hour for injury report tracking

### Path Structure Patterns:

#### Simple Date-Based:
```
/{source}/{type}/{date}/{timestamp}.{format}
```
**Examples:**
- `/ball-dont-lie/games/{date}/{timestamp}.json`
- `/espn/scoreboard/{date}/{timestamp}.json`

#### Game-Specific:
```
/{source}/{type}/{date}/game_{id}/{timestamp}.{format}
```
**Examples:**
- `/espn/boxscores/{date}/game_{id}/{timestamp}.json`
- `/nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json`

#### Team-Specific:
```
/{source}/{type}/{date}/team_{abbrev}/{timestamp}.{format}
```
**Examples:**
- `/espn/rosters/{date}/team_{abbrev}/{timestamp}.json`
- `/nba-com/rosters/{date}/team_{abbrev}/{timestamp}.json`

#### Event-Specific (Odds API):
```
/{source}/{type}/{date}/event_{id}/{timestamp}.{format}
```
**Examples:**
- `/odds-api/player-props/{date}/event_{id}/{timestamp}.json`
- `/odds-api/player-props-history/{date}/event_{id}/{timestamp}.json`

#### Special Formats:
- **Injury Report**: `/nba-com/injury-report/{date}/report_{date}_{hour}/{timestamp}.json`
- **Historical**: `-history` suffix for historical data endpoints

---

## Environment Variables for Exporters

```python
# Common GCS configuration
GCS_BUCKET_RAW = "nba-scraped-data"
GCS_BASE_PATH = "gs://nba-scraped-data/"

# Path construction examples:
def get_bdl_games_path(date, timestamp):
    return f"ball-dont-lie/games/{date}/{timestamp}.json"

def get_odds_events_path(date, timestamp):
    return f"odds-api/events/{date}/{timestamp}.json"

def get_player_props_path(date, event_id, timestamp):
    return f"odds-api/player-props/{date}/event_{event_id}/{timestamp}.json"
```

---

## Key Notes for Exporter Updates:

1. **Consistent Naming**: All paths use lowercase with hyphens for separation
2. **Date Format**: Use YYYY-MM-DD format for `{date}` variable
3. **File Extensions**: JSON for most data, CSV for Big Data Ball
4. **Timestamp**: Include for versioning and avoiding overwrites
5. **Subdirectories**: Use appropriate subdirs for games, teams, events
6. **Critical Scrapers**: Pay special attention to paths marked with ⭐
