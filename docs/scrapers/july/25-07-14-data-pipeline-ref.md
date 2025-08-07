# NBA Data Pipeline - Scraper Reference

## Directory Structure Overview

All scraped data is stored in Google Cloud Storage using the following structure:

```
/raw-data/
  /{data-source}/
    /{data-type}/
      /{date}/
        /{parameter-directory}/  # Only for scrapers with specific parameters
          {timestamp}.json
```

## File Naming Conventions

- **Date directories**: `YYYY-MM-DD` format in Eastern Time
- **Timestamps**: `YYYYMMDD_HHMMSS` format in UTC
- **Parameter directories**: `{param-type}_{value}` (e.g., `game_401234567`, `team_LAL`, `event_12345`)

## Scraper Inventory

### Ball Don't Lie API

#### BdlGamesScraper
- **File**: `scrapers/balldontlie/bdl_games.py`
- **Class**: `BdlGamesScraper`
- **Parameters**: start_date, end_date
- **Output Path**: `/raw-data/ball-dont-lie/games/{date}/{timestamp}.json`
- **Description**: Retrieves games for specified date range

#### BdlPlayerBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_player_box_scores.py`
- **Class**: `BdlPlayerBoxScoresScraper`
- **Parameters**: start_date, end_date OR game_id
- **Output Path**: 
  - By date: `/raw-data/ball-dont-lie/player-box-scores/{date}/{timestamp}.json`
  - By game: `/raw-data/ball-dont-lie/player-box-scores/{date}/game_{id}/{timestamp}.json`
- **Description**: Player statistics for games

#### BdlBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_box_scores.py`
- **Class**: `BdlBoxScoresScraper`
- **Parameters**: date
- **Output Path**: `/raw-data/ball-dont-lie/boxscores/{date}/{timestamp}.json`
- **Description**: Team boxscores for specified date

#### BdlInjuriesScraper
- **File**: `scrapers/balldontlie/bdl_injuries.py`
- **Class**: `BdlInjuriesScraper`
- **Parameters**: None
- **Output Path**: `/raw-data/ball-dont-lie/injuries/{date}/{timestamp}.json`
- **Description**: Current player injury status

### Odds API

#### GetOddsApiHistoricalEvents
- **File**: `scrapers/oddsapi/oddsa_events_his.py`
- **Class**: `GetOddsApiHistoricalEvents`
- **Parameters**: date
- **Output Path**: `/raw-data/odds-api/events-history/{date}/{timestamp}.json`
- **Description**: Historical events for backfill purposes

#### GetOddsApiHistoricalEventOdds
- **File**: `scrapers/oddsapi/oddsa_player_props_his.py`
- **Class**: `GetOddsApiHistoricalEventOdds`
- **Parameters**: event_id
- **Output Path**: `/raw-data/odds-api/player-props-history/{date}/event_{id}/{timestamp}.json`
- **Description**: Historical player props for specific events

#### GetOddsApiEvents
- **File**: `scrapers/oddsapi/oddsa_events.py`
- **Class**: `GetOddsApiEvents`
- **Parameters**: None
- **Output Path**: `/raw-data/odds-api/events/{date}/{timestamp}.json`
- **Description**: Current/upcoming events and game IDs

#### GetOddsApiCurrentEventOdds
- **File**: `scrapers/oddsapi/oddsa_player_props.py`
- **Class**: `GetOddsApiCurrentEventOdds`
- **Parameters**: event_id
- **Output Path**: `/raw-data/odds-api/player-props/{date}/event_{id}/{timestamp}.json`
- **Description**: Current player prop odds for specific events

#### GetOddsApiTeamPlayers
- **File**: `scrapers/oddsapi/oddsa_team_players.py`
- **Class**: `GetOddsApiTeamPlayers`
- **Parameters**: None
- **Output Path**: `/raw-data/odds-api/players/{date}/{timestamp}.json`
- **Description**: Players currently on teams

### ESPN

#### GetEspnTeamRosterAPI
- **File**: `scrapers/espn/espn_roster_api.py`
- **Backup File**: `scrapers/espn/espn_roster.py`
- **Class**: `GetEspnTeamRosterAPI`
- **Backup Class**: `GetEspnTeamRoster`
- **Parameters**: team_abbreviation
- **Output Path**: `/raw-data/espn/rosters/{date}/team_{abbrev}/{timestamp}.json`
- **Description**: Team roster information

#### GetEspnScoreboard
- **File**: `scrapers/espn/espn_scoreboard_api.py`
- **Class**: `GetEspnScoreboard`
- **Parameters**: game_date
- **Output Path**: `/raw-data/espn/scoreboard/{date}/{timestamp}.json`
- **Description**: Scoreboard with games and scores

#### GetEspnBoxscore
- **File**: `scrapers/espn/espn_game_boxscore.py`
- **Class**: `GetEspnBoxscore`
- **Parameters**: game_id
- **Output Path**: `/raw-data/espn/boxscores/{date}/game_{id}/{timestamp}.json`
- **Description**: Detailed game boxscore

### NBA.com

#### GetDataNbaSeasonSchedule
- **File**: `scrapers/nbacom/nbac_current_schedule_v2_1.py`
- **Class**: `GetDataNbaSeasonSchedule`
- **Parameters**: None
- **Output Path**: `/raw-data/nba-com/schedule/{date}/{timestamp}.json`
- **Description**: Current season schedule (updated daily)

#### GetNbaComInjuryReport
- **File**: `scrapers/nbacom/nbac_injury_report.py`
- **Class**: `GetNbaComInjuryReport`
- **Parameters**: date, hour
- **Output Path**: `/raw-data/nba-com/injury-report/{date}/report_{date}_{hour}/{timestamp}.json`
- **Description**: Official NBA injury report (PDF format)

#### GetNbaPlayByPlayRawBackup
- **File**: `scrapers/nbacom/nbac_play_by_play.py`
- **Class**: `GetNbaPlayByPlayRawBackup`
- **Parameters**: game_id
- **Output Path**: `/raw-data/nba-com/play-by-play/{date}/game_{id}/{timestamp}.json`
- **Description**: Game play-by-play data

#### GetNbaComPlayerBoxscore
- **File**: `scrapers/nbacom/nbac_player_boxscore.py`
- **Class**: `GetNbaComPlayerBoxscore`
- **Parameters**: game_date
- **Output Path**: `/raw-data/nba-com/player-boxscores/{date}/{timestamp}.json`
- **Description**: All player stats for games on specified date

#### GetNbaTeamRoster
- **File**: `scrapers/nbacom/nbac_roster.py`
- **Class**: `GetNbaTeamRoster`
- **Parameters**: team_abbreviation
- **Output Path**: `/raw-data/nba-com/rosters/{date}/team_{abbrev}/{timestamp}.json`
- **Description**: Current team roster

#### GetNbaComPlayerList
- **File**: `scrapers/nbacom/nbac_player_list.py`
- **Class**: `GetNbaComPlayerList`
- **Parameters**: None (possibly current_players_only)
- **Output Path**: `/raw-data/nba-com/player-list/{date}/{timestamp}.json`
- **Description**: Complete NBA player database

### Big Data Ball

#### Play-by-Play Data
- **Source**: Google Drive (service account access)
- **Delivery**: 2 hours after game completion
- **File Format**: `[YYYY-MM-DD]-{game_id}-{away_team}@{home_team}.csv`
- **Example**: `[2021-10-19]-0022100001-BKN@MIL.csv`
- **Output Path**: `/raw-data/big-data-ball/play-by-play/{date}/game_{id}/{timestamp}.csv`
- **Description**: Enhanced play-by-play data
- **Note**: Requires automated transfer from Google Drive

## Processing Guidelines

### Finding Latest Files
```python
# Get latest file for a specific scraper
latest_file = sorted(list_files(f"/raw-data/{source}/{type}/{date}/"))[-1]

# Get latest file for specific parameter
latest_game_file = sorted(list_files(f"/raw-data/{source}/{type}/{date}/game_{id}/"))[-1]
```

### Processing Patterns
- **Multi-item responses**: Single file contains all items (games, boxscores, etc.)
- **Parameter-specific**: Each parameter gets its own subdirectory
- **Date-based processing**: Processors can iterate through all sources for a given date
- **Parallel processing**: Different games/events can be processed independently

## Workflow Integration

### Pub/Sub Messages
Scrapers will publish completion messages containing:
- Scraper class name
- Success/failure status  
- Output file path(s)
- Timestamp
- Parameters used

### Dependencies
- **Events before Props**: Odds API events must run before player props
- **Schedule before Games**: NBA.com schedule should run before game-specific scrapers
- **No other strict dependencies**: Most scrapers can run in parallel

## Operational Schedule

### Morning (8-10 AM ET)
**Current Data Updates**
- **Rosters** (ESPN, NBA.com): Multiple runs to catch trades/transactions
  - *Note*: Current rosters only - use game boxscores for historical backfill
- **Injuries** (Ball Don't Lie, NBA.com): Multiple runs for latest injury status
  - *Note*: Use game logs for historical injury data
- **Schedule** (NBA.com, Ball Don't Lie): Check for game rescheduling
- **Odds Events** (Odds API): Get upcoming games for prop bet collection

### Afternoon (12-4 PM ET)  
**Pre-Game Preparation**
- **Odds Events** (Odds API): Final check for game events
- **Player Props** (Odds API): Collect prop odds using event IDs from events API
- **Schedule Updates**: Continue monitoring for last-minute changes

### Game Time (Variable)
**Live Monitoring**
- **Injuries**: Hourly checks on game days for updated status
- **Schedule**: Monitor for postponements or changes

### Evening/Post-Game
**Game Results**
- **Game Boxscores** (Ball Don't Lie, ESPN, NBA.com): Completed games
- **Player Boxscores** (Ball Don't Lie, NBA.com): Final player statistics
- **Scoreboard Updates** (ESPN): Final scores and results

### Night/Early Morning
**Enhanced Data**
- **Play-by-Play** (Big Data Ball): Check for completed game data (available 2 hours post-game)
- **Odds Props** (Odds API): Check for next day's games if available

### Backfill Operations
**Historical Data** (As Needed)
- **Odds Events Historical** (Odds API): Event data for past dates
- **Odds Props Historical** (Odds API): Historical prop odds by event ID
- **Historical Analysis**: Use game boxscores instead of current rosters/injuries

### Dependencies & Flow
1. **Odds API Events → Player Props**: Events must run first to get event IDs
2. **Schedule Updates → Game-Specific Scrapers**: Schedule provides game IDs
3. **Current vs Historical**: Rosters/injuries are current-only; use game data for historical analysis

## Error Handling

### Failed Scrapers
- Pub/Sub message includes failure status
- Processors should handle missing files gracefully
- Retry logic at workflow level

### Data Quality
- Timestamp allows tracking of data freshness
- Multiple runs per day enable comparison and validation
- Backup scrapers available for critical data sources (ESPN rosters)

## Design Notes

### Team Abbreviations
- Prefer team abbreviations over full team names throughout the system
- Consistent with BigDataBall format: `BKN@MIL` vs `Brooklyn@Milwaukee`
- Applies to directory naming: `team_LAL` vs `team_lakers`

### Historical vs Current Data
- **Current-only APIs**: Rosters, injuries, player lists (today's data only)
- **Historical backfill**: Use game boxscores and logs to determine historical rosters/injuries
- **Scheduling**: Current season schedule updated daily; historical games from completed boxscores
