# NBA Scrapers - Operational Reference

## Document Purpose

This is the **daily operational reference** for NBA data scrapers. Use this document for:
- **Deployment**: Class names and file locations
- **Debugging**: Parameter requirements and output paths  
- **Monitoring**: Schedules and dependencies
- **Troubleshooting**: API limits and common issues

For **backfill strategy** and **historical data collection**, see the NBA Workflows Reference document.

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
├── big-data-ball/           # Enhanced analytics data
└── bigdataball/             # BigDataBall play-by-play
```

---

## Scraper Categories by Business Purpose

### **Overview**
Scrapers are organized by **business function** and **timing requirements**. This categorization shows **when** and **why** each scraper is used based on actual operational workflows.

### **Timing Definitions**
- **Real-Time**: Revenue-critical data collected every 2 hours (8 AM - 8 PM PT)
- **Daily Setup**: Foundation data collected every morning (8 AM PT)
- **Post-Game**: Game results collected after completion (8 PM & 11 PM PT)
- **Recovery**: Data recovery and final checks (2 AM & 5 AM PT)

---

### **Category: Live Prop Markets** ⭐ **REVENUE CRITICAL**
- **Timing**: **Real-Time** (Every 2 hours, 8 AM - 8 PM PT)
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

### **Category: Player Intelligence**
- **Timing**: **Daily Setup** + **Real-Time**
- **Purpose**: Player name → team lookup for prop betting analysis
- **Priority**: **🔴 CRITICAL** - Foundation for all prop betting
- **Business Need**: Convert "Jaylen Wells" to "MEM" when processing Odds API props

#### **Scrapers**
- `GetNbaComPlayerList` ⭐ **Primary source** (Morning + Real-Time)
- `GetNbaComPlayerMovement` - Transaction context (Morning only)
- `BdlActivePlayersScraper` ⭐ **Third-party validation** (Morning + Real-Time)

#### **Dependencies**: None (runs first)
#### **Processing Notes**: 
- **Real-time**: Use current data for team assignments
- **Historical**: Use box scores to determine player's team during specific games

---

### **Category: Player Availability**
- **Timing**: **Daily Setup** + **Real-Time**
- **Purpose**: Determine if player available for prop betting
- **Priority**: **🟡 HIGH** - Affects prop availability and line values
- **Business Need**: Don't offer props on players who are out/questionable

#### **Scrapers**
- `GetNbaComInjuryReport` ⭐ **Official game-specific status** (Morning + Real-Time)
- `BdlInjuriesScraper` - **Backup injury data** (Morning + Real-Time)

#### **Dependencies**: Player Intelligence (for team context)
#### **Processing Notes**: Dual-source injury monitoring for data validation

---

### **Category: Game Scheduling**
- **Timing**: **Daily Setup**
- **Purpose**: When games happen, detect postponements and time changes  
- **Priority**: **🟡 HIGH** - Timing affects all downstream processing
- **Business Need**: Know when to collect props, when games start

#### **Scrapers**
- `GetNbaComScheduleApi` ⭐ **Primary schedule source** (Current season + Backfill)
- `GetNbaComScheduleCdn` - **Backup with monitoring** (Compare vs API)
- `BdlStandingsScraper` - League standings context

#### **Dependencies**: None
#### **Processing Notes**: Dual-source monitoring to detect API vs CDN differences

---

### **Category: Game Results**
- **Timing**: **Post-Game** (8 PM & 11 PM PT)
- **Purpose**: Player/team performance for analysis
- **Priority**: **🟢 MEDIUM** - Analytical foundation
- **Business Need**: Game outcome data for performance analysis

#### **Scrapers**
- `GetNbaComScoreboardV2` ⭐ **Official game scores**
- `BdlBoxScoresScraper` ⭐ **Player and team statistics**

#### **Dependencies**: Game Scheduling (for game timing)
#### **Processing Notes**: Dual scheduling (8 PM early games, 11 PM late games)

---

### **Category: Advanced Analytics**
- **Timing**: **Recovery** (2 AM & 5 AM PT)
- **Purpose**: Detailed performance analysis and predictive modeling
- **Priority**: **🔵 LOW** - Enhancement over basic stats
- **Business Need**: Advanced player performance insights

#### **Scrapers**
- `BigDataBallPbpScraper` ⭐ **Enhanced play-by-play** (BigDataBall CSV files)
- `GetNbaComPlayByPlay` - **Official backup play-by-play**
- `GetEspnScoreboard` - **Alternative scoreboard** (Final check only)
- `GetEspnBoxscore` - **Alternative boxscores** (Final check only)

#### **Dependencies**: Game Results (for game context)
#### **Processing Notes**: Multiple recovery windows, ESPN as final backup

---

## Complete Scraper Inventory

### **Total Active Scrapers: 16**
- **Odds API**: 2 scrapers (events, props - revenue critical)
- **NBA.com**: 6 scrapers (schedule, player data, injuries, scoreboards, play-by-play)
- **Ball Don't Lie**: 4 scrapers (active players, injuries, standings, box scores)
- **BigDataBall**: 1 scraper (enhanced play-by-play)
- **ESPN**: 2 scrapers (scoreboard, boxscores - backup only)
- **BigDataBall**: 1 scraper (enhanced play-by-play from CSV files)

---

## Detailed Scraper Reference

### **Odds API (2 Scrapers)** ⭐ **REVENUE CRITICAL**

#### GetOddsApiEvents ⭐ **CRITICAL**
- **File**: `scrapers/oddsapi/oddsa_events.py`
- **Class**: `GetOddsApiEvents`
- **Parameters**: None
- **Output Path**: `/odds-api/events/{date}/{timestamp}.json`
- **Schedule**: Real-Time Business workflow (every 2 hours, 8 AM - 8 PM PT)
- **Purpose**: Current/upcoming NBA games for prop collection
- **API Details**: Single response, ~5-15 events per day
- **Dependencies**: **NONE - MUST RUN FIRST**

#### GetOddsApiCurrentEventOdds ⭐ **CORE BUSINESS**
- **File**: `scrapers/oddsapi/oddsa_player_props.py`
- **Class**: `GetOddsApiCurrentEventOdds`
- **Parameters**: `event_id`
- **Output Path**: `/odds-api/player-props/{date}/event_{id}/{timestamp}.json`
- **Schedule**: Real-Time Business workflow (30 minutes after Events API)
- **Purpose**: Player prop odds for FanDuel + DraftKings
- **API Details**: Response per event, ~20-50 props per game
- **Dependencies**: **REQUIRES GetOddsApiEvents to run first**

### **Odds API Limits**
- **Rate Limit**: 500 requests per month (paid plan)
- **Authentication**: API key via `ODDS_API_KEY` environment variable
- **Critical**: Events API must run before Props API

---

### **NBA.com (6 Scrapers)**

#### GetNbaComPlayerList ⭐ **CRITICAL FOR PLAYER LOOKUP**
- **File**: `scrapers/nbacom/nbac_player_list.py`
- **Class**: `GetNbaComPlayerList`
- **Parameters**: None (current season auto-filtered)
- **Output Path**: `/nba-com/player-list/{date}/{timestamp}.json`
- **Schedule**: Morning Operations + Real-Time Business workflows
- **Purpose**: Official master player database for team assignments
- **API Details**: Single response, ~500 active players, 293KB file
- **Dependencies**: None

#### GetNbaComScheduleApi ⭐ **DUAL PURPOSE**
- **File**: `scrapers/nbacom/nbac_schedule_api.py`
- **Class**: `GetNbaComScheduleApi`
- **Parameters**: `season` (for backfill) or None (for current season)
- **Output Path**: `/nba-com/schedule/{actual_season_nba_format}/{timestamp}.json`
- **Schedule**: Morning Operations workflow (daily at 8 AM PT)
- **Purpose**: Current season schedule + historical backfill capability
- **API Details**: Single response, ~3.3MB file with full season
- **Dependencies**: None

#### GetNbaComScheduleCdn
- **File**: `scrapers/nbacom/nbac_schedule_cdn.py`
- **Class**: `GetNbaComScheduleCdn`
- **Parameters**: None (current season auto-detected)
- **Output Path**: `/nba-com/schedule-cdn/{actual_season_nba_format}/{timestamp}.json`
- **Schedule**: Morning Operations workflow (backup to API version)
- **Purpose**: Compare CDN vs API schedule data for monitoring
- **API Details**: Single response, ~3.3MB file
- **Dependencies**: None

#### GetNbaComInjuryReport ⭐ **CRITICAL FOR PROPS**
- **File**: `scrapers/nbacom/nbac_injury_report.py`
- **Class**: `GetNbaComInjuryReport`
- **Parameters**: `date`, `hour`
- **Output Path**: `/nba-com/injury-report/{date}/{hour}{period}/{timestamp}.json`
- **Schedule**: Morning Operations + Real-Time Business workflows
- **Purpose**: Official NBA injury report with game-specific availability
- **API Details**: JSON format (converted from PDF), ~50-100 players per report
- **Dependencies**: None

#### GetNbaComScoreboardV2
- **File**: `scrapers/nbacom/nbac_scoreboard_v2.py`
- **Class**: `GetNbaComScoreboardV2`
- **Parameters**: `scoreDate`
- **Output Path**: `/nba-com/scoreboard-v2/{date}/{timestamp}.json`
- **Schedule**: Post-Game Collection workflow (8 PM & 11 PM PT)
- **Purpose**: Game scores with quarter-by-quarter data and team stats
- **API Details**: Single response per date
- **Dependencies**: None
- **Warning**: May be deprecated by NBA.com in future

#### GetNbaComPlayByPlay
- **File**: `scrapers/nbacom/nbac_play_by_play.py`
- **Class**: `GetNbaComPlayByPlay`
- **Parameters**: `gameId`
- **Output Path**: `/nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json`
- **Schedule**: Late Night Recovery + Early Morning Final Check workflows
- **Purpose**: Official play-by-play backup to BigDataBall
- **API Details**: ~500-800 events per game, large JSON files
- **Dependencies**: Requires NBA.com game IDs

#### GetNbaComPlayerMovement
- **File**: `scrapers/nbacom/nbac_player_movement.py`
- **Class**: `GetNbaComPlayerMovement`
- **Parameters**: `year`
- **Output Path**: `/nba-com/player-movement/{date}/{timestamp}.json`
- **Schedule**: Morning Operations workflow (daily at 8 AM PT)
- **Purpose**: Complete transaction history (trades, signings, waivers, G-League)
- **API Details**: 8,730+ records back to 2015, large file
- **Dependencies**: None

### **NBA.com API Details**
- **Rate Limit**: No official limit, but be respectful
- **Authentication**: None required for most endpoints
- **Data Format**: Varies (JSON objects, array format, nested structures)
- **Reliability**: Official source, generally very reliable

---

### **Ball Don't Lie API (4 Scrapers)**

#### BdlActivePlayersScraper ⭐ **CRITICAL FOR PLAYER VALIDATION**
- **File**: `scrapers/balldontlie/bdl_active_players.py`
- **Class**: `BdlActivePlayersScraper`
- **Parameters**: None
- **Output Path**: `/ball-dont-lie/active-players/{date}/{timestamp}.json`
- **Schedule**: Morning Operations + Real-Time Business workflows
- **Purpose**: Cross-validate NBA.com player data, detect team assignment discrepancies
- **API Details**: **Paginated, 5-6 requests required**, ~100 players per page, ~500 total active players
- **Dependencies**: None (independent validation source)
- **Special Notes**: Single Cloud Run instance handles all pagination, aggregated into one output file

#### BdlInjuriesScraper
- **File**: `scrapers/balldontlie/bdl_injuries.py`
- **Class**: `BdlInjuriesScraper`
- **Parameters**: None
- **Output Path**: `/ball-dont-lie/injuries/{date}/{timestamp}.json`
- **Schedule**: Morning Operations + Real-Time Business workflows (backup to NBA.com)
- **Purpose**: Alternative injury status source for data validation
- **API Details**: Single response, all injured players
- **Dependencies**: None

#### BdlStandingsScraper
- **File**: `scrapers/balldontlie/bdl_standings.py`
- **Class**: `BdlStandingsScraper`
- **Parameters**: None
- **Output Path**: `/ball-dont-lie/standings/{date}/{timestamp}.json`
- **Schedule**: Morning Operations workflow (daily at 8 AM PT)
- **Purpose**: Current league standings for context
- **API Details**: Single response, all team standings
- **Dependencies**: None

#### BdlBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_box_scores.py`
- **Class**: `BdlBoxScoresScraper`
- **Parameters**: `date`
- **Output Path**: `/ball-dont-lie/boxscores/{date}/{timestamp}.json`
- **Schedule**: Post-Game Collection + Late Night Recovery + Early Morning Final Check workflows
- **Purpose**: Team boxscores with embedded player stats
- **API Details**: Single response with all games for date
- **Dependencies**: None

### **Ball Don't Lie API Limits**
- **Rate Limit**: 600 requests per minute
- **Authentication**: Bearer token via `BDL_API_KEY` environment variable
- **Pagination**: 100 items per page (Active Players endpoint requires 5-6 requests)

---

### **BigDataBall (1 Scraper)**

#### BigDataBallPbpScraper
- **File**: `scrapers/bigdataball/bigdataball_pbp.py`
- **Class**: `BigDataBallPbpScraper`
- **Parameters**: `game_id`
- **Output Path**: `/big-data-ball/{nba_season}/{date}/game_{game_id}/{filename}.csv`
- **Schedule**: Late Night Recovery + Early Morning Final Check workflows
- **Purpose**: Enhanced play-by-play with lineup tracking and advanced coordinates
- **API Details**: Google Drive CSV files, 40+ fields per event, ~500-800 events per game
- **Dependencies**: Games must be completed, requires Google Drive API access
- **Special**: Requires Google Drive API and service account authentication

---

### **ESPN (2 Scrapers)** - **BACKUP ONLY**

#### GetEspnScoreboard
- **File**: `scrapers/espn/espn_scoreboard_api.py`
- **Class**: `GetEspnScoreboard`
- **Parameters**: `game_date`
- **Output Path**: `/espn/scoreboard/{date}/{timestamp}.json`
- **Schedule**: Early Morning Final Check workflow only (5 AM PT)
- **Purpose**: Alternative scoreboard data as final backup
- **API Details**: Single response with all games for date
- **Dependencies**: None

#### GetEspnBoxscore
- **File**: `scrapers/espn/espn_game_boxscore.py`
- **Class**: `GetEspnBoxscore`
- **Parameters**: `game_id`
- **Output Path**: `/espn/boxscores/{date}/game_{id}/{timestamp}.json`
- **Schedule**: Early Morning Final Check workflow only (5 AM PT)
- **Purpose**: Alternative boxscore data as final backup
- **API Details**: One request per completed game
- **Dependencies**: Requires ESPN game IDs from scoreboard

### **ESPN API Details**
- **Rate Limit**: No official limit, reasonable usage recommended
- **Authentication**: None required
- **Data Format**: Consistent JSON responses
- **Usage**: Backup data source only, not primary operational data

---

## Operational Schedules

### **Morning Operations** (Daily at 8 AM PT)
- `GetNbaComPlayerMovement` (1 request)
- `GetNbaComScheduleApi` (1 request) + `GetNbaComScheduleCdn` (1 request)
- `GetNbaComPlayerList` (1 request)
- `GetNbaComInjuryReport` (1 request) + `BdlInjuriesScraper` (1 request)
- `BdlStandingsScraper` (1 request)
- `BdlActivePlayersScraper` (5-6 requests)
- **Total**: ~12-13 requests

### **Real-Time Business** (Every 2 hours, 8 AM - 8 PM PT)
- `GetOddsApiEvents` (1 request) → `GetOddsApiCurrentEventOdds` (varies by events)
- `GetNbaComPlayerList` (1 request)
- `GetNbaComInjuryReport` (1 request) + `BdlInjuriesScraper` (1 request)
- `BdlActivePlayersScraper` (5-6 requests)
- **Total per cycle**: ~9-10 requests × 7 cycles = ~63-70 requests

### **Post-Game Collection** (8 PM & 11 PM PT)
- `GetNbaComScoreboardV2` (1 request)
- `BdlBoxScoresScraper` (1 request)
- **Total per cycle**: 2 requests × 2 cycles = 4 requests

### **Late Night Recovery** (2 AM PT)
- `BigDataBallPbpScraper` (varies by games)
- `GetNbaComPlayByPlay` (varies by games)
- `BdlBoxScoresScraper` (1 request)
- **Total**: Variable based on games

### **Early Morning Final Check** (5 AM PT)
- `BigDataBallPbpScraper` (varies by games)
- `GetNbaComPlayByPlay` (varies by games)
- `BdlBoxScoresScraper` (1 request)
- `GetEspnScoreboard` (1 request) → `GetEspnBoxscore` (varies by games)
- **Total**: Variable based on games

### **Daily Total API Requests**
- **Regular Day**: ~80-85 requests
- **Game Day**: ~100-120 requests (including variable game-based scrapers)

---

## Critical Dependencies

### **Revenue Critical (Business Stops on Failure)**
1. `GetOddsApiEvents` → `GetOddsApiCurrentEventOdds` (Real-Time Business workflow)

### **Data Dependencies (Backup Available)**
2. `GetEspnScoreboard` → `GetEspnBoxscore` (Early Morning Final Check workflow)

### **All Other Scrapers**
- Independent execution (system continues on individual failures)
- Multiple backup sources available
- Recovery opportunities across multiple workflows

---

## Backup & Monitoring Strategy

### **Dual-Source Data Collection**
- **Schedules**: NBA.com API (primary) vs CDN (backup/monitoring)
- **Injuries**: NBA.com official (primary) vs Ball Don't Lie (backup)
- **Play-by-Play**: BigDataBall enhanced (primary) vs NBA.com official (backup)
- **Players**: NBA.com official (primary) vs Ball Don't Lie (validation)

### **Recovery Workflows**
- **Late Night Recovery** (2 AM PT): Core game data + enhanced analytics
- **Early Morning Final Check** (5 AM PT): Final attempt + ESPN backups
- **Multiple Opportunities**: Data collection spread across multiple time windows

### **Success Metrics**
- **Scraper Success Rate**: >95% for all scrapers
- **Data Freshness**: <2 hours for critical data
- **Player Lookup Accuracy**: >95% match rate
- **API Usage**: Within rate limits
- **Dual-Source Validation**: <5% discrepancy between primary/backup sources

---

## Troubleshooting Guide

### **Revenue Critical Failures**
- **Odds API Events Down**: Alert immediately, check API status, manual collection if needed
- **Odds API Props Down**: Verify Events API success, check event IDs, restart Props collection

### **Data Quality Issues**
- **Schedule Discrepancies**: Compare NBA.com API vs CDN, validate game counts
- **Injury Report Mismatches**: Cross-reference NBA.com vs Ball Don't Lie data
- **Player Lookup Failures**: Check both NBA.com and Ball Don't Lie player databases

### **Authentication/Rate Limit Issues**
- **Ball Don't Lie**: Check `BDL_API_KEY`, monitor 600/minute limit, note Active Players uses 5-6 requests
- **Odds API**: Monitor monthly quota (500 requests), prioritize revenue-critical endpoints
- **BigDataBall**: Verify Google Drive service account access, check file availability

### **Emergency Procedures**
- **Primary Source Down**: Workflows automatically attempt backup sources
- **Complete Workflow Failure**: Data recovery available in subsequent workflow windows
- **Critical Business Impact**: Manual intervention protocols for revenue-affecting failures

---

## File and URL References

### **Repository Structure**
```
scrapers/
├── oddsapi/              # Odds API scrapers (revenue critical)
├── nbacom/               # NBA.com scrapers (official data)
├── balldontlie/          # Ball Don't Lie scrapers (validation/backup)
├── bigdataball/          # BigDataBall integration (enhanced analytics)
├── espn/                 # ESPN scrapers (backup only)
└── utils/                # Shared utilities
```

### **Cloud Run Service**: `nba-scrapers-756957797294.us-west2.run.app`

---

## Quick Reference Summary

### **Most Critical Scrapers**
1. `GetOddsApiEvents` - Foundation for all prop betting
2. `GetOddsApiCurrentEventOdds` - Core business revenue
3. `GetNbaComPlayerList` - Player team assignments
4. `GetNbaComInjuryReport` - Player availability for props

### **Daily Operations**
- **Morning Setup**: 8 scrapers, ~12-13 API requests
- **Real-Time Business**: 6 scrapers, 7 cycles, ~63-70 API requests
- **Post-Game**: 2 scrapers, 2 cycles, 4 API requests
- **Recovery**: Variable scrapers based on games

### **Backup Strategy**
- **Dual-source monitoring** for schedules, injuries, and player data
- **Multiple recovery windows** for game data collection
- **ESPN as final backup** for scoreboard/boxscore data

This operational reference provides all practical details needed for day-to-day scraper management, deployment, and troubleshooting based on actual production workflows.