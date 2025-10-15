# NBA Scrapers - Operational Reference

## Document Purpose

This is the **daily operational reference** for NBA data scrapers. Use this document for:
- **Deployment**: Class names and file locations
- **Debugging**: Parameter requirements and output paths  
- **Monitoring**: Schedules and dependencies
- **Troubleshooting**: API limits and common issues

For **strategic guidance** and **business logic**, see the main pipeline implementation document.

---

## GCS Storage Configuration

### **Bucket**: `nba-scraped-data`
All scraped data is stored in the **raw scraped data bucket**: `gs://nba-scraped-data/`

### **Directory Structure**
```
gs://nba-scraped-data/
├── ball-dont-lie/           # Ball Don't Lie API data
├── odds-api/                # Odds API data (business critical)
├── espn/                    # ESPN data
├── nba-com/                 # NBA.com data  
└── big-data-ball/           # Enhanced analytics data
```

---

## Scraper Categories by Business Purpose

### **Overview**
Scrapers are organized by **business function** and **timing requirements** rather than technical data source. This categorization shows **when** and **why** each scraper is used.

### **Timing Definitions**
- **Upcoming**: Real-time data for today's and future games
- **Post-game**: Historical data for completed games (current season)
- **Backfill**: Historical data for past seasons (manual processing)

---

### **Category: Player Intelligence**
- **Timing**: **Upcoming**
- **Purpose**: Player name → team lookup for prop betting analysis
- **Priority**: **🔴 CRITICAL** - Foundation for all prop betting
- **Business Need**: Convert "Jaylen Wells" to "MEM" when processing Odds API props

#### **Scrapers**
- `GetNbaComPlayerList` ⭐ **Primary source**
- `GetNbaComPlayerMovement` - Transaction context  
- `BdlActivePlayersScraper` ⭐ **Third-party validation** (5-6 API requests, aggregated output)
- `GetEspnTeamRosterAPI` - Trade validation

#### **Dependencies**: None (runs first)
#### **Processing Notes**: 
- **Upcoming games**: Use real-time scraped data for current team assignments
- **Historical analysis**: Use game boxscores to determine player's team during specific games

---

### **Category: Live Prop Markets**
- **Timing**: **Upcoming**  
- **Purpose**: Current betting lines for today's games
- **Priority**: **🔴 CORE BUSINESS** - Primary revenue source
- **Business Need**: Collect player prop odds for points betting

#### **Scrapers**
- `GetOddsApiEvents` ⭐ **Must run first**
- `GetOddsApiCurrentEventOdds` ⭐ **Core business data**

#### **Dependencies**: 
- **CRITICAL**: Events must run before Props (provides event IDs)
- **REQUIRES**: Player Intelligence (for team assignments)

#### **Processing Notes**: Sequential dependency - Events → Props → Player lookup integration

---

### **Category: Player Availability**
- **Timing**: **Upcoming** (+ historical context via NBA.com URLs)
- **Purpose**: Determine if player available for prop betting
- **Priority**: **🟡 HIGH** - Affects prop availability and line values
- **Business Need**: Don't offer props on players who are out/questionable

#### **Scrapers**
- `GetNbaComInjuryReport` ⭐ **Official game-specific status**
- `BdlInjuriesScraper` - General injury context

#### **Dependencies**: Player Intelligence (for team context)
#### **Processing Notes**: NBA.com injury reports have historical URLs for backfill capability

---

### **Category: Game Scheduling**
- **Timing**: **Upcoming** (+ backfill capability via date parameters)
- **Purpose**: When games happen, detect postponements and time changes  
- **Priority**: **🟡 HIGH** - Timing affects all downstream processing
- **Business Need**: Know when to collect props, when games start

#### **Scrapers**
- `GetDataNbaSeasonSchedule` ⭐ **Comprehensive official schedule**
- `GetNbaComScheduleCdn` - Fast updates
- `BdlGamesScraper` - Game status validation
- `GetEspnScoreboard` - Score and status updates

#### **Dependencies**: None
#### **Processing Notes**: Multiple endpoints provide redundancy for schedule reliability

---

### **Category: Game Results**
- **Timing**: **Post-game** (current season) + **Backfill** (historical)
- **Purpose**: Player/team performance for prop predictions and analysis
- **Priority**: **🟢 MEDIUM** - Analytical foundation for modeling
- **Business Need**: Historical performance context for prop value assessment

#### **Scrapers**
- `BdlPlayerBoxScoresScraper` ⭐ **Primary player stats**
- `BdlBoxScoresScraper` - Team stats with embedded players
- `GetNbaComPlayerBoxscore` - Official stats with additional metrics
- `GetEspnBoxscore` - Alternative source validation

#### **Dependencies**: Game Scheduling (for game IDs and timing)
#### **Processing Notes**: Available after games complete, used for both current analysis and historical backfill

---

### **Category: Advanced Analytics**
- **Timing**: **Post-game** (2+ hour delay) + **Backfill**
- **Purpose**: Detailed performance analysis and predictive modeling
- **Priority**: **🔵 LOW** - Enhancement over basic stats
- **Business Need**: Advanced player performance insights for sophisticated prop analysis

#### **Scrapers**
- `Big Data Ball Play by Play` ⭐ **Enhanced analytics with lineups**
- `GetNbaComPlayByPlay` - Official detailed event data

#### **Dependencies**: Game Results (for game context)
#### **Processing Notes**: Big Data Ball has 2-hour delay, requires Google Drive API access

---

### **Category: Historical Props**
- **Timing**: **Backfill** (manual trigger for 2021-22 season back)
- **Purpose**: Historical betting line analysis and pattern research
- **Priority**: **🟣 ANALYTICAL** - Research and modeling only
- **Business Need**: Understand historical prop line movements and market patterns

#### **Scrapers**
- `GetOddsApiHistoricalEvents` - Historical game events
- `GetOddsApiHistoricalEventOdds` - Historical prop lines

#### **Dependencies**: Manual execution, requires historical event IDs
#### **Processing Notes**: Used for research and model training, not daily operations

---

### **Category Processing Priority**

#### **Real-Time Operations (Every 2-4 Hours)**
1. **Player Intelligence** → 2. **Live Prop Markets** → 3. **Player Availability** → 4. **Game Scheduling**

#### **Post-Game Processing (After Games Complete)**
5. **Game Results** → 6. **Advanced Analytics**

#### **Research & Analysis (Manual/Batch)**
7. **Historical Props** (as needed for modeling)

### **Business Impact Summary**

| **Category** | **Business Impact** | **Failure Effect** |
|--------------|-------------------|-------------------|
| **Player Intelligence** | Props can't be processed | Business stops |
| **Live Prop Markets** | No revenue data | Revenue loss |
| **Player Availability** | Bad prop offerings | Customer dissatisfaction |
| **Game Scheduling** | Timing issues | Missed opportunities |
| **Game Results** | No performance context | Reduced analysis quality |
| **Advanced Analytics** | Limited modeling | Research limitations |
| **Historical Props** | No historical patterns | Modeling gaps |

---

## Complete Scraper Inventory

### **Total Active Scrapers: 23**
- **Ball Don't Lie**: 5 scrapers (games, player stats, team stats, injuries, active players)
- **Odds API**: 5 scrapers (events, props, historical data, team players)
- **ESPN**: 3 scrapers (rosters, scoreboard, boxscores)
- **NBA.com**: 9 scrapers (schedule, rosters, players, injuries, analytics)
- **Big Data Ball**: 1 scraper (enhanced play-by-play)

---

## Ball Don't Lie API (5 Scrapers)

### BdlGamesScraper
- **File**: `scrapers/balldontlie/bdl_games.py`
- **Class**: `BdlGamesScraper`
- **Parameters**: `start_date`, `end_date`
- **Output Path**: `/ball-dont-lie/games/{date}/{timestamp}.json`
- **Schedule**: Daily at 8 AM, 12 PM, 6 PM ET
- **Purpose**: NBA games with scores and team info
- **API Details**: No pagination, ~15 games per response
- **Dependencies**: None

### BdlPlayerBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_player_box_scores.py`
- **Class**: `BdlPlayerBoxScoresScraper`
- **Parameters**: `start_date`, `end_date` OR `game_id`
- **Output Path**: 
  - By date: `/ball-dont-lie/player-box-scores/{date}/{timestamp}.json`
  - By game: `/ball-dont-lie/player-box-scores/{date}/game_{id}/{timestamp}.json`
- **Schedule**: Daily at 9 PM ET (after games complete)
- **Purpose**: Individual player statistics for completed games
- **API Details**: Paginated, ~25 players per response
- **Dependencies**: None

### BdlBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_box_scores.py`
- **Class**: `BdlBoxScoresScraper`
- **Parameters**: `date`
- **Output Path**: `/ball-dont-lie/boxscores/{date}/{timestamp}.json`
- **Schedule**: Daily at 9 PM ET (after games complete)
- **Purpose**: Team boxscores with embedded player stats
- **API Details**: Single response with all games for date
- **Dependencies**: None

### BdlActivePlayersScraper ⭐ **CRITICAL FOR PLAYER VALIDATION**
- **File**: `scrapers/balldontlie/bdl_active_players.py`
- **Class**: `BdlActivePlayersScraper`
- **Parameters**: None
- **Output Path**: `/ball-dont-lie/active-players/{date}/{timestamp}.json`
- **Schedule**: Daily for validation, every 4-6 hours during trade season
- **Purpose**: Cross-validate NBA.com player data, detect team assignment discrepancies
- **API Details**: **Paginated, 5-6 requests required**, ~100 players per page, ~500 total active players
- **Dependencies**: None (independent validation source)
- **Special Notes**: Single Cloud Run instance handles all pagination, aggregated into one output file

### BdlInjuriesScraper
- **File**: `scrapers/balldontlie/bdl_injuries.py`
- **Class**: `BdlInjuriesScraper`
- **Parameters**: None
- **Output Path**: `/ball-dont-lie/injuries/{date}/{timestamp}.json`
- **Schedule**: Every 2-4 hours, 8 AM - 8 PM ET
- **Purpose**: Current league-wide injury status
- **API Details**: Single response, all injured players
- **Dependencies**: None

### **Ball Don't Lie API Limits**
- **Rate Limit**: 600 requests per minute
- **Authentication**: Bearer token via `BDL_API_KEY` environment variable
- **Pagination**: 100 items per page (Active Players endpoint requires 5-6 requests)

---

## Odds API (5 Scrapers)

### GetOddsApiEvents ⭐ **CRITICAL**
- **File**: `scrapers/oddsapi/oddsa_events.py`
- **Class**: `GetOddsApiEvents`
- **Parameters**: None
- **Output Path**: `/odds-api/events/{date}/{timestamp}.json`
- **Schedule**: Every 2-4 hours, 8 AM - 8 PM ET
- **Purpose**: Current/upcoming NBA games for prop collection
- **API Details**: Single response, ~5-15 events per day
- **Dependencies**: **NONE - MUST RUN FIRST**

### GetOddsApiCurrentEventOdds ⭐ **CORE BUSINESS**
- **File**: `scrapers/oddsapi/oddsa_player_props.py`
- **Class**: `GetOddsApiCurrentEventOdds`
- **Parameters**: `event_id`
- **Output Path**: `/odds-api/player-props/{date}/event_{id}/{timestamp}.json`
- **Schedule**: 30 minutes after Events API, then every 2-4 hours
- **Purpose**: Player prop odds for FanDuel + DraftKings
- **API Details**: Response per event, ~20-50 props per game
- **Dependencies**: **REQUIRES GetOddsApiEvents to run first**

### GetOddsApiHistoricalEvents
- **File**: `scrapers/oddsapi/oddsa_events_his.py`
- **Class**: `GetOddsApiHistoricalEvents`
- **Parameters**: `date`
- **Output Path**: `/odds-api/events-history/{date}/{timestamp}.json`
- **Schedule**: As needed for backfill
- **Purpose**: Historical events for analysis
- **API Details**: Single response per date
- **Dependencies**: None

### GetOddsApiHistoricalEventOdds
- **File**: `scrapers/oddsapi/oddsa_player_props_his.py`
- **Class**: `GetOddsApiHistoricalEventOdds`
- **Parameters**: `event_id`
- **Output Path**: `/odds-api/player-props-history/{date}/event_{id}/{timestamp}.json`
- **Schedule**: As needed for backfill
- **Purpose**: Historical prop odds by event
- **API Details**: Response per event
- **Dependencies**: Requires historical event IDs

### GetOddsApiTeamPlayers
- **File**: `scrapers/oddsapi/oddsa_team_players.py`
- **Class**: `GetOddsApiTeamPlayers`
- **Parameters**: None
- **Output Path**: `/odds-api/players/{date}/{timestamp}.json`
- **Schedule**: Daily at 8 AM ET
- **Purpose**: Players currently on teams (sportsbook perspective)
- **API Details**: Single response, all active players
- **Dependencies**: None

### **Odds API Limits**
- **Rate Limit**: 500 requests per month (paid plan)
- **Authentication**: API key via `ODDS_API_KEY` environment variable
- **Critical**: Events API must run before Props API

---

## ESPN (3 Scrapers)

### GetEspnTeamRosterAPI
- **File**: `scrapers/espn/espn_roster_api.py`
- **Backup File**: `scrapers/espn/espn_roster.py` (GetEspnTeamRoster)
- **Class**: `GetEspnTeamRosterAPI`
- **Parameters**: `team_abbr`
- **Output Path**: `/espn/rosters/{date}/{team_abbr}/{timestamp}.json`
- **Schedule**: Daily at 8 AM ET (all 30 teams)
- **Purpose**: Detailed team rosters for trade validation
- **API Details**: One request per team, ~15 players per team
- **Dependencies**: None

### GetEspnScoreboard
- **File**: `scrapers/espn/espn_scoreboard_api.py`
- **Class**: `GetEspnScoreboard`
- **Parameters**: `game_date`
- **Output Path**: `/espn/scoreboard/{date}/{timestamp}.json`
- **Schedule**: Daily at 6 PM, 9 PM, 11 PM ET
- **Purpose**: Game scores and status validation
- **API Details**: Single response with all games for date
- **Dependencies**: None

### GetEspnBoxscore
- **File**: `scrapers/espn/espn_game_boxscore.py`
- **Class**: `GetEspnBoxscore`
- **Parameters**: `game_id`
- **Output Path**: `/espn/boxscores/{date}/game_{id}/{timestamp}.json`
- **Schedule**: After games complete (triggered by scoreboard)
- **Purpose**: Detailed game boxscore with player stats
- **API Details**: One request per completed game
- **Dependencies**: Requires ESPN game IDs from scoreboard

### **ESPN API Details**
- **Rate Limit**: No official limit, reasonable usage recommended
- **Authentication**: None required
- **Data Format**: Consistent JSON responses

---

## NBA.com (9 Scrapers)

### GetNbaComPlayerList ⭐ **CRITICAL FOR PLAYER LOOKUP**
- **File**: `scrapers/nbacom/nbac_player_list.py`
- **Class**: `GetNbaComPlayerList`
- **Parameters**: None (current season auto-filtered)
- **Output Path**: `/nba-com/player-list/{date}/{timestamp}.json`
- **Schedule**: Every 2-4 hours, 8 AM - 8 PM ET
- **Purpose**: Official master player database for team assignments
- **API Details**: Single response, ~500 active players, 293KB file
- **Dependencies**: None

### GetDataNbaSeasonSchedule
- **File**: `scrapers/nbacom/nbac_current_schedule_v2_1.py`
- **Class**: `GetDataNbaSeasonSchedule`
- **Parameters**: None
- **Output Path**: `/nba-com/schedule/{date}/{timestamp}.json`
- **Schedule**: Daily at 8 AM ET
- **Purpose**: Comprehensive season schedule with detailed metadata
- **API Details**: Single response, 17MB file with full season
- **Dependencies**: None

### GetNbaComScheduleCdn
- **File**: `scrapers/nbacom/nbac_schedule_cdn.py`
- **Class**: `GetNbaComScheduleCdn`
- **Parameters**: None
- **Output Path**: `/nba-com/schedule-cdn/{date}/{timestamp}.json`
- **Schedule**: Every 4 hours during game days
- **Purpose**: Fast/light version of schedule for quick updates
- **API Details**: Single response, smaller file size
- **Dependencies**: None

### GetNbaComScoreboardV2
- **File**: `scrapers/nbacom/nbac_scoreboard_v2.py`
- **Class**: `GetNbaComScoreboardV2`
- **Parameters**: `scoreDate`
- **Output Path**: `/nba-com/scoreboard-v2/{date}/{timestamp}.json`
- **Schedule**: Daily at 6 PM, 9 PM, 11 PM ET
- **Purpose**: Game scores with quarter-by-quarter data and team stats
- **API Details**: Single response per date
- **Dependencies**: None

### GetNbaComInjuryReport ⭐ **CRITICAL FOR PROPS**
- **File**: `scrapers/nbacom/nbac_injury_report.py`
- **Class**: `GetNbaComInjuryReport`
- **Parameters**: `date`, `hour`
- **Output Path**: `/nba-com/injury-report/{date}/{hour}{period}/{timestamp}.json`
- **Schedule**: Every hour on game days, daily otherwise
- **Purpose**: Official NBA injury report with game-specific availability
- **API Details**: JSON format (converted from PDF), ~50-100 players per report
- **Dependencies**: None

### GetNbaComPlayByPlay
- **File**: `scrapers/nbacom/nbac_play_by_play.py`
- **Class**: `GetNbaComPlayByPlay`
- **Parameters**: `gameId`
- **Output Path**: `/nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json`
- **Schedule**: After games complete
- **Purpose**: Detailed play-by-play with coordinates and timing
- **API Details**: ~500-800 events per game, large JSON files
- **Dependencies**: Requires NBA.com game IDs

### GetNbaComPlayerBoxscore
- **File**: `scrapers/nbacom/nbac_player_boxscore.py`
- **Class**: `GetNbaComPlayerBoxscore`
- **Parameters**: `game_date`
- **Output Path**: `/nba-com/player-boxscores/{date}/{timestamp}.json`
- **Schedule**: Daily at 9 PM ET (after games complete)
- **Purpose**: Official player stats with fantasy points and additional metrics
- **API Details**: Array format mapped to headers, all players for date
- **Dependencies**: None

### GetNbaTeamRoster
- **File**: `scrapers/nbacom/nbac_roster.py`
- **Class**: `GetNbaTeamRoster`
- **Parameters**: `team_abbr`
- **Output Path**: `/nba-com/rosters/{date}/{team_abbr}/{timestamp}.json`
- **Schedule**: Daily at 8 AM ET (all 30 teams)
- **Purpose**: Official current team roster (basic format)
- **API Details**: One request per team, ~15-18 players per team
- **Dependencies**: None

### GetNbaComPlayerMovement
- **File**: `scrapers/nbacom/nbac_player_movement.py`
- **Class**: `GetNbaComPlayerMovement`
- **Parameters**: `year`
- **Output Path**: `/nba-com/player-movement/{date}/{timestamp}.json`
- **Schedule**: Daily at 8 AM ET
- **Purpose**: Complete transaction history (trades, signings, waivers, G-League)
- **API Details**: 8,730+ records back to 2015, large file
- **Dependencies**: None

### **NBA.com API Details**
- **Rate Limit**: No official limit, but be respectful
- **Authentication**: None required for most endpoints
- **Data Format**: Varies (JSON objects, array format, nested structures)
- **Reliability**: Official source, generally very reliable

---

## Big Data Ball (1 Scraper)

### Enhanced Play-by-Play Data
- **Source**: Google Drive service account access
- **File Format**: CSV files
- **Naming**: `[YYYY-MM-DD]-{game_id}-{away_team}@{home_team}.csv`
- **Example**: `[2021-10-19]-0022100001-BKN@MIL.csv`
- **Output Path**: `/big-data-ball/play-by-play/{date}/game_{id}/{timestamp}.csv`
- **Schedule**: Check for new files 2 hours after game completion
- **Purpose**: Enhanced play-by-play with lineup tracking and advanced coordinates
- **API Details**: 40+ fields per event, ~500-800 events per game
- **Dependencies**: Games must be completed
- **Special**: Requires Google Drive API and service account authentication

---

## Operational Schedules

### **Trade Season Schedule (February - July)**

#### **Every 2 Hours (8 AM - 8 PM ET)**
- `GetNbaComPlayerList` (1 request)
- `BdlActivePlayersScraper` (5-6 requests)
- `GetOddsApiEvents` (1 request) → `GetOddsApiCurrentEventOdds` (varies by events)

#### **Daily at 8 AM ET**
- `GetNbaComPlayerMovement` (1 request)
- `GetEspnTeamRosterAPI` (30 requests - all teams)
- `GetNbaTeamRoster` (30 requests - all teams)
- `GetOddsApiTeamPlayers` (1 request)

#### **Game Day Additional**
- `GetNbaComInjuryReport` (hourly on game days)
- `GetEspnScoreboard` + `GetNbaComScoreboardV2` (6 PM, 9 PM, 11 PM)
- Post-game boxscores and play-by-play

### **Regular Season Schedule (August - January)**

#### **Every 4 Hours (8 AM - 8 PM ET)**
- `GetNbaComPlayerList` (1 request)
- `BdlActivePlayersScraper` (5-6 requests)
- `GetOddsApiEvents` (1 request) → `GetOddsApiCurrentEventOdds` (varies by events)

#### **Daily at 8 AM ET**
- All supporting scrapers (same as trade season)

---

## Critical Dependencies

### **Must Run in Order**
1. `GetOddsApiEvents` **→** `GetOddsApiCurrentEventOdds`
   - **Why**: Props API requires event IDs from Events API
   - **Failure Impact**: No prop data collection possible

### **Recommended Order**
1. `GetNbaComPlayerList` (foundation for player lookup)
2. `BdlActivePlayersScraper` (validation for player lookup - note: 5-6 API requests)
3. `GetOddsApiEvents` (foundation for props)
4. `GetOddsApiCurrentEventOdds` (core business data)
5. All other scrapers (parallel execution possible)

---

## Cloud Run Configuration

### **Standard Scraper Settings**
```yaml
# Default Cloud Run configuration for most scrapers
memory: 512Mi
cpu: 1
timeout: 300s  # 5 minutes
max_instances: 3
environment_variables:
  - BDL_API_KEY: "from Secret Manager"
  - ODDS_API_KEY: "from Secret Manager"
  - GCS_BUCKET_RAW: "nba-scraped-data"
```

### **Heavy Scrapers (Special Configuration)**
```yaml
# For large data scrapers (NBA.com schedule, player movement, play-by-play)
memory: 1Gi
cpu: 2
timeout: 600s  # 10 minutes
max_instances: 1  # Prevent duplicate processing
```

### **Critical Business Scrapers (Enhanced Monitoring)**
```yaml
# For Odds API scrapers (business critical)
memory: 512Mi
cpu: 1
timeout: 180s  # Shorter timeout for faster failure detection
max_instances: 2
retry_attempts: 3
alert_on_failure: true
```

---

## Monitoring & Alerting

### **Critical Alerts (Business Stopping)**
- `GetOddsApiEvents` failure
- `GetOddsApiCurrentEventOdds` failure  
- `GetNbaComPlayerList` failure during trade season
- Any scraper failure rate >10% in 24 hours

### **High Priority Alerts**
- `GetNbaComInjuryReport` failure on game days
- Player lookup match rate <95%
- API rate limit violations

### **Medium Priority Alerts**
- Individual scraper failures (with successful retries)
- Data quality issues (missing fields, format changes)
- Unusual data patterns

### **Success Metrics**
- **Scraper Success Rate**: >95% for all scrapers
- **Data Freshness**: <2 hours for critical data
- **Player Lookup Accuracy**: >95% match rate
- **API Usage**: Within rate limits

---

## Troubleshooting Guide

### **Common Issues**

#### **Authentication Failures**
- Check `BDL_API_KEY` and `ODDS_API_KEY` in Secret Manager
- Verify service account permissions for NBA.com endpoints
- Confirm Google Drive API access for Big Data Ball

#### **Rate Limit Violations**
- **Ball Don't Lie**: Reduce frequency, check 600/minute limit, note BdlActivePlayersScraper uses 5-6 requests per run
- **Odds API**: Monitor monthly quota (500 requests)
- **NBA.com**: Add delays between requests if blocked

#### **Data Quality Issues**
- Compare data across multiple sources
- Check for API format changes in raw_data JSON field
- Validate player names and team abbreviations
- **BDL Active Players**: Verify pagination completion in aggregated files

#### **Processing Failures**
- Check GCS file paths match expected format
- Verify Pub/Sub message delivery
- Monitor processor Cloud Run logs
- **Multi-request scrapers**: Check for partial completion in aggregated files

### **Emergency Procedures**

#### **Odds API Down (Business Critical)**
1. Alert immediately
2. Check API status page
3. Increase retry frequency when service restored
4. Manual data collection if extended outage

#### **Player Lookup Failures**
1. Check NBA.com Player List scraper status
2. Validate BDL Active Players as backup
3. Use ESPN rosters for emergency validation
4. Alert on unknown players with active props

---

## File and URL References

### **Repository Structure**
```
scrapers/
├── balldontlie/          # Ball Don't Lie scrapers
├── oddsapi/              # Odds API scrapers  
├── espn/                 # ESPN scrapers
├── nbacom/               # NBA.com scrapers
├── bigdataball/          # Big Data Ball integration
└── utils/                # Shared utilities
```

### **GCS Directory Structure**
```
gs://nba-scraped-data/
├── ball-dont-lie/        # BDL data
├── odds-api/             # Odds API data (business critical)
├── espn/                 # ESPN data
├── nba-com/              # NBA.com data  
└── big-data-ball/        # Enhanced analytics data
```

### **Cloud Run Service Names**
- Format: `nba-{source}-{type}-scraper`
- Examples: `nba-odds-events-scraper`, `nba-nbacom-players-scraper`

---

## Quick Reference Summary

### **Most Critical Scrapers**
1. `GetOddsApiEvents` - Foundation for all prop betting
2. `GetOddsApiCurrentEventOdds` - Core business revenue
3. `GetNbaComPlayerList` - Player team assignments
4. `GetNbaComInjuryReport` - Player availability for props

### **Daily API Request Volume**
- **Trade Season**: ~80-85 requests/day (includes BDL Active Players 5-6 requests)
- **Regular Season**: ~60-65 requests/day
- **Peak Game Days**: ~105-110 requests/day

### **Key File Locations**
- **Scrapers**: `/scrapers/{source}/{scraper_name}.py`
- **Raw Data**: `gs://nba-scraped-data/{source}/{type}/{date}/`
- **Configs**: Environment variables in Cloud Run

This operational reference provides all the practical details needed for day-to-day scraper management, deployment, and troubleshooting.