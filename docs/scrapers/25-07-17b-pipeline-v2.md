# NBA Data Pipeline - Complete Scraper Reference & Implementation Guide

## Overview

This document provides the complete reference for the NBA prop betting data pipeline, covering **22 active scrapers** across **5 data sources**. The pipeline collects betting lines, player statistics, game data, and injury reports to support prop betting analysis and predictive modeling.

## Directory Structure & File Naming

All scraped data follows a consistent structure in Google Cloud Storage:

```
/raw-data/
  /{data-source}/
    /{data-type}/
      /{date}/                    # YYYY-MM-DD format (Eastern Time)
        /{parameter-directory}/   # Only for scrapers with specific parameters
          {timestamp}.json        # YYYYMMDD_HHMMSS format (UTC)
```

### **Design Principles**
- **Date partitioning** for optimal query performance
- **Parameter isolation** in subdirectories for easy processing
- **Timestamp tracking** for reprocessing and debugging
- **Consistent naming** across all data sources

---

## Complete Scraper Inventory (22 Active Scrapers)

### Ball Don't Lie API (4 Scrapers)

#### BdlGamesScraper
- **File**: `scrapers/balldontlie/bdl_games.py`
- **Class**: `BdlGamesScraper`
- **Parameters**: start_date, end_date
- **Output Path**: `/raw-data/ball-dont-lie/games/{date}/{timestamp}.json`
- **Description**: NBA games for specified date range with team info and scores
- **Business Value**: Foundation for game linking across all sources

#### BdlPlayerBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_player_box_scores.py`
- **Class**: `BdlPlayerBoxScoresScraper`
- **Parameters**: start_date, end_date OR game_id
- **Output Path**: 
  - By date: `/raw-data/ball-dont-lie/player-box-scores/{date}/{timestamp}.json`
  - By game: `/raw-data/ball-dont-lie/player-box-scores/{date}/game_{id}/{timestamp}.json`
- **Description**: Individual player statistics for games
- **Business Value**: Historical performance data for prop predictions

#### BdlBoxScoresScraper
- **File**: `scrapers/balldontlie/bdl_box_scores.py`
- **Class**: `BdlBoxScoresScraper`
- **Parameters**: date
- **Output Path**: `/raw-data/ball-dont-lie/boxscores/{date}/{timestamp}.json`
- **Description**: Team boxscores with embedded player stats for specified date
- **Business Value**: Complete game view with both teams' performance

#### BdlInjuriesScraper
- **File**: `scrapers/balldontlie/bdl_injuries.py`
- **Class**: `BdlInjuriesScraper`
- **Parameters**: None
- **Output Path**: `/raw-data/ball-dont-lie/injuries/{date}/{timestamp}.json`
- **Description**: Current player injury status across the league
- **Business Value**: General injury awareness for prop analysis

---

### Odds API (4 Scrapers) - CORE BUSINESS DATA

#### GetOddsApiEvents
- **File**: `scrapers/oddsapi/oddsa_events.py`
- **Class**: `GetOddsApiEvents`
- **Parameters**: None
- **Output Path**: `/raw-data/odds-api/events/{date}/{timestamp}.json`
- **Description**: Current/upcoming events and game IDs for prop collection
- **Business Value**: **CRITICAL** - Provides event IDs required for prop betting
- **Dependencies**: Must run before GetOddsApiCurrentEventOdds

#### GetOddsApiCurrentEventOdds
- **File**: `scrapers/oddsapi/oddsa_player_props.py`
- **Class**: `GetOddsApiCurrentEventOdds`
- **Parameters**: event_id
- **Output Path**: `/raw-data/odds-api/player-props/{date}/event_{id}/{timestamp}.json`
- **Description**: Current player prop odds for specific events (FanDuel + DraftKings)
- **Business Value**: **PRIMARY BUSINESS DATA** - The actual betting lines for analysis
- **Dependencies**: Requires event IDs from GetOddsApiEvents

#### GetOddsApiHistoricalEvents
- **File**: `scrapers/oddsapi/oddsa_events_his.py`
- **Class**: `GetOddsApiHistoricalEvents`
- **Parameters**: date
- **Output Path**: `/raw-data/odds-api/events-history/{date}/{timestamp}.json`
- **Description**: Historical events for backfill and historical analysis
- **Business Value**: Enables historical prop betting analysis

#### GetOddsApiHistoricalEventOdds
- **File**: `scrapers/oddsapi/oddsa_player_props_his.py`
- **Class**: `GetOddsApiHistoricalEventOdds`
- **Parameters**: event_id
- **Output Path**: `/raw-data/odds-api/player-props-history/{date}/event_{id}/{timestamp}.json`
- **Description**: Historical player props for specific events
- **Business Value**: Historical line tracking and pattern analysis

#### GetOddsApiTeamPlayers (Supplementary)
- **File**: `scrapers/oddsapi/oddsa_team_players.py`
- **Class**: `GetOddsApiTeamPlayers`
- **Parameters**: None
- **Output Path**: `/raw-data/odds-api/players/{date}/{timestamp}.json`
- **Description**: Players currently on teams according to sportsbooks

---

### ESPN (3 Scrapers)

#### GetEspnTeamRosterAPI
- **File**: `scrapers/espn/espn_roster_api.py`
- **Backup File**: `scrapers/espn/espn_roster.py` (GetEspnTeamRoster)
- **Class**: `GetEspnTeamRosterAPI`
- **Parameters**: team_abbreviation
- **Output Path**: `/raw-data/espn/rosters/{date}/team_{abbrev}/{timestamp}.json`
- **Description**: Detailed team roster with player biographical data
- **Business Value**: Rich player information for cross-referencing

#### GetEspnScoreboard
- **File**: `scrapers/espn/espn_scoreboard_api.py`
- **Class**: `GetEspnScoreboard`
- **Parameters**: game_date
- **Output Path**: `/raw-data/espn/scoreboard/{date}/{timestamp}.json`
- **Description**: Game scoreboard with final scores and status
- **Business Value**: Game results and status validation

#### GetEspnBoxscore
- **File**: `scrapers/espn/espn_game_boxscore.py`
- **Class**: `GetEspnBoxscore`
- **Parameters**: game_id
- **Output Path**: `/raw-data/espn/boxscores/{date}/game_{id}/{timestamp}.json`
- **Description**: Detailed game boxscore with player statistics
- **Business Value**: Alternative source for player performance validation

---

### NBA.com (10 Scrapers) - Official Data

#### GetDataNbaSeasonSchedule (Comprehensive)
- **File**: `scrapers/nbacom/nbac_current_schedule_v2_1.py`
- **Class**: `GetDataNbaSeasonSchedule`
- **Parameters**: None
- **Output Path**: `/raw-data/nba-com/schedule/{date}/{timestamp}.json`
- **Description**: Complete season schedule with detailed broadcast and venue info (17MB)
- **Business Value**: Comprehensive official schedule with rich metadata

#### GetNbaComScheduleCdn (Fast/Light)
- **File**: `scrapers/nbacom/nbac_schedule_cdn.py`
- **Class**: `GetNbaComScheduleCdn`
- **Parameters**: None
- **Output Path**: `/raw-data/nba-com/schedule-cdn/{date}/{timestamp}.json`
- **Description**: Current season schedule from CDN (faster, lighter version)
- **Business Value**: Quick schedule updates for daily processing

#### GetNbaComScoreboardV2
- **File**: `scrapers/nbacom/nbac_scoreboard_v2.py`
- **Class**: `GetNbaComScoreboardV2`
- **Parameters**: scoreDate
- **Output Path**: `/raw-data/nba-com/scoreboard-v2/{date}/{timestamp}.json`
- **Description**: Game scores with quarter-by-quarter breakdown and team stats
- **Business Value**: Detailed game flow analysis with quarter performance

#### GetNbaComInjuryReport
- **File**: `scrapers/nbacom/nbac_injury_report.py`
- **Class**: `GetNbaComInjuryReport`
- **Parameters**: date, hour
- **Output Path**: `/raw-data/nba-com/injury-report/{date}/report_{date}_{hour}/{timestamp}.json`
- **Description**: Official NBA injury report with game-specific availability
- **Business Value**: **CRITICAL FOR PROPS** - Official pre-game player availability

#### GetNbaComPlayByPlay
- **File**: `scrapers/nbacom/nbac_play_by_play.py`
- **Class**: `GetNbaComPlayByPlay` (formerly GetNbaPlayByPlayRawBackup)
- **Parameters**: gameId
- **Output Path**: `/raw-data/nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json`
- **Description**: Detailed game play-by-play with precise timing and coordinates
- **Business Value**: Advanced analytics for shot patterns and game flow

#### GetNbaComPlayerBoxscore
- **File**: `scrapers/nbacom/nbac_player_boxscore.py`
- **Class**: `GetNbaComPlayerBoxscore`
- **Parameters**: game_date
- **Output Path**: `/raw-data/nba-com/player-boxscores/{date}/{timestamp}.json`
- **Description**: All player stats for games on specified date with fantasy points
- **Business Value**: Official player statistics with additional metrics

#### GetNbaTeamRoster
- **File**: `scrapers/nbacom/nbac_roster.py`
- **Class**: `GetNbaTeamRoster`
- **Parameters**: team_abbreviation
- **Output Path**: `/raw-data/nba-com/rosters/{date}/team_{abbrev}/{timestamp}.json`
- **Description**: Current team roster with basic player information
- **Business Value**: Official current roster status

#### GetNbaComPlayerList
- **File**: `scrapers/nbacom/nbac_player_list.py`
- **Class**: `GetNbaComPlayerList`
- **Parameters**: None (current season filter applied)
- **Output Path**: `/raw-data/nba-com/player-list/{date}/{timestamp}.json`
- **Description**: Complete NBA player database for current season
- **Business Value**: **CRITICAL** - Master player reference for cross-linking

#### GetNbaComPlayerMovement
- **File**: `scrapers/nbacom/nbac_player_movement.py`
- **Class**: `GetNbaComPlayerMovement`
- **Parameters**: year
- **Output Path**: `/raw-data/nba-com/player-movement/{date}/{timestamp}.json`
- **Description**: Complete transaction history (signings, trades, waivers) back to 2015
- **Business Value**: Historical context for roster changes (8,730+ records)

---

### Big Data Ball (1 Scraper) - Enhanced Analytics

#### Enhanced Play-by-Play Data
- **Source**: Google Drive (service account access)
- **Delivery**: 2 hours after game completion
- **File Format**: `[YYYY-MM-DD]-{game_id}-{away_team}@{home_team}.csv`
- **Example**: `[2021-10-19]-0022100001-BKN@MIL.csv`
- **Output Path**: `/raw-data/big-data-ball/play-by-play/{date}/game_{id}/{timestamp}.csv`
- **Description**: Enhanced play-by-play with lineup tracking and advanced coordinates
- **Business Value**: Advanced analytics with 40+ fields including exact lineups

---

## Data Relationships & Cross-Reference Strategy

### **Player Cross-Reference System**
**Challenge**: 4+ different player ID systems across APIs

| **Source** | **ID Format** | **Example** | **Name Format** | **Cross-Reference Strategy** |
|------------|---------------|-------------|-----------------|------------------------------|
| **Ball Don't Lie** | Integer | `38017703` | `first_name` + `last_name` | Primary stats source |
| **ESPN** | String | `"3917376"` | `name` (full name) | Rich biographical data |
| **NBA.com** | Integer | `1630173` | `PLAYER_FIRST_NAME` + `PLAYER_LAST_NAME` | Official master database |
| **Odds API** | Name Only | `"Jaylen Wells"` | `description` field | **CRITICAL** - Must match for props |

**Matching Strategy**:
1. **Primary**: `player_name + team_abbr + jersey_number`
2. **Secondary**: Name variations array (nicknames, abbreviations)
3. **Confidence scoring**: Track match quality for validation
4. **Manual review**: Flag low-confidence matches

### **Game Linking Strategy**
**Challenge**: Different game ID formats across sources

| **Source** | **ID Format** | **Example** | **Linking Strategy** |
|------------|---------------|-------------|----------------------|
| **Ball Don't Lie** | Integer | `15908525` | `game_date + teams + time` |
| **ESPN** | String | `"401585183"` | `game_date + teams + time` |
| **NBA.com** | String | `"0022400500"` | `game_date + teams + time` |
| **Odds API** | Hash String | `"242c77a8d5890e18..."` | `commence_time + team_names` |

### **Team Standardization**
- **Primary Key**: Standardized abbreviations (LAL, NYK, PHI, etc.)
- **Mapping**: Full team names → abbreviations for each source
- **Consistency**: Same abbreviations used across entire system

---

## Daily Operational Schedule

### **Morning Updates (8-10 AM ET)**
**Focus**: Current state data before games

#### **Roster Monitoring** (Multiple runs)
- **ESPN Rosters** (`GetEspnTeamRosterAPI`) - All teams
- **NBA.com Rosters** (`GetNbaTeamRoster`) - All teams
- **Purpose**: Catch overnight trades, signings, releases
- **Frequency**: 2-3 runs during window

#### **Injury Status** (Multiple runs)
- **Ball Don't Lie Injuries** (`BdlInjuriesScraper`) - League-wide status
- **NBA.com Injury Report** (`GetNbaComInjuryReport`) - Official reports
- **Purpose**: Latest injury designations before games
- **Critical**: Game-specific availability affects prop values

#### **Schedule Monitoring**
- **NBA.com Schedule** (`GetDataNbaSeasonSchedule` or `GetNbaComScheduleCdn`) - Full season
- **Ball Don't Lie Games** (`BdlGamesScraper`) - Today's games
- **Purpose**: Detect postponements, time changes

### **Afternoon Preparation (12-4 PM ET)**
**Focus**: Pre-game setup and betting markets

#### **Critical Betting Pipeline** (SEQUENTIAL DEPENDENCY)
1. **Odds Events** (`GetOddsApiEvents`) - **MUST RUN FIRST**
   - Gets event IDs for current NBA games
   - Required for all prop collection
2. **Player Props** (`GetOddsApiCurrentEventOdds`) - **DEPENDS ON EVENTS**
   - Collects prop odds using event IDs
   - FanDuel + DraftKings lines
   - **Core business data collection**

#### **Game Preparation**
- **Scoreboard Updates** (`GetEspnScoreboard`, `GetNbaComScoreboardV2`)
- **Schedule Confirmations** (Continue monitoring)

### **Game Time (Variable)**
**Focus**: Live monitoring and updates

#### **Real-Time Monitoring**
- **Injury Updates** (Hourly on game days)
  - Late scratches during warmups
  - Lineup changes affect prop availability
- **Schedule Emergencies** (Postponements, delays)

### **Evening Results (6-11 PM ET)**
**Focus**: Game completion and statistics

#### **Game Results Collection**
- **Scoreboard Updates** (`GetEspnScoreboard`, `GetNbaComScoreboardV2`) - Final scores
- **Player Statistics** (`BdlPlayerBoxScoresScraper`, `GetNbaComPlayerBoxscore`) - Individual performance
- **Team Statistics** (`BdlBoxScoresScraper`) - Team-level results

#### **Detailed Game Analysis**
- **Game Boxscores** (`GetEspnBoxscore`) - Per completed game
- **Play-by-Play** (`GetNbaComPlayByPlay`) - Detailed game events

### **Late Night Processing (11 PM-2 AM ET)**
**Focus**: Enhanced data and next-day preparation

#### **Enhanced Analytics**
- **Big Data Ball** - Check for enhanced play-by-play (2-hour delay)
- **Advanced processing** of completed games

#### **Next Day Setup**
- **Early Betting Lines** (`GetOddsApiEvents`, `GetOddsApiCurrentEventOdds`) - If available
- **Tomorrow's preparation** data

---

## Critical Dependencies & Processing Order

### **Hard Dependencies (Must Respect)**
1. **Odds API Events → Player Props**
   - Events provides event IDs
   - Props requires these IDs to function
   - **Business Critical**: Failure blocks all prop collection

2. **Schedule Updates → Game-Specific Scrapers**
   - Schedule provides game IDs
   - Game boxscores need valid game references

### **Soft Dependencies (Preferred Order)**
1. **Reference Data → Performance Data**
   - Teams and players before statistics
   - Enables cross-referencing during processing

2. **Current Data → Historical Data**
   - Process today's data before backfill operations

---

## Processor Architecture & Implementation

### **Core Processing Principles**
- **One processor per data type** for clean separation
- **Independent operation** with pub/sub triggering
- **Idempotency** using file path tracking
- **Graceful degradation** when dependencies missing

### **Priority Processor Implementation**

#### **Phase 1: Reference Foundation**
1. **teams-processor** - Standardize team abbreviations
2. **players-processor** - Build cross-reference system
3. **games-processor** - Link games across sources

#### **Phase 2: Betting Pipeline (BUSINESS CRITICAL)**
1. **events-processor** - Process betting events
2. **props-processor** - **CORE BUSINESS VALUE** - Player prop odds
3. **odds-history-processor** - Track line movements

#### **Phase 3: Performance Integration**
1. **boxscores-processor** - Historical player performance
2. **injuries-processor** - Both general + game-specific injury data

### **Pub/Sub Message Format**
```json
{
  "file_path": "/raw-data/odds-api/player-props/2025-07-15/event_242c77a8d5890e18/20250715_143000.json",
  "data_source": "odds-api",
  "data_type": "player-props", 
  "scraper_class": "GetOddsApiCurrentEventOdds",
  "status": "success",
  "timestamp": "2025-07-15T14:30:00Z",
  "parameters": {"event_id": "242c77a8d5890e18bab91773ad32fcb5"},
  "file_size": 15420
}
```

---

## Data Quality & Business Logic

### **Critical Business Rules**

#### **Prop Betting Data Flow**
1. **Events API** provides NBA game event IDs
2. **Player Props API** uses event IDs to get betting lines
3. **Game Injury Reports** show official player availability
4. **Historical Boxscores** provide performance context for predictions
5. **Cross-referenced Player Data** enables accurate prop-to-player matching

#### **Player Availability Logic**
- **NBA.com Injury Report**: Game-specific official status
  - "Out" + "Rest" = Load management (different from injury)
  - "Out" + "Injury/Illness" = Actual injury
  - "G League - Two Way" = Player assignment
- **Ball Don't Lie Injuries**: General ongoing injury status
- **Business Impact**: Affects prop availability and line values

### **Data Quality Monitoring**

#### **Critical Metrics**
- **Player Match Rate**: >95% successful cross-references
- **Game Linking Rate**: >98% successful game ID mapping  
- **Prop Coverage**: % of games with available betting lines
- **Data Freshness**: <30 minutes from scrape to processor completion

#### **Alert Conditions**
- **Failed Events API**: Blocks all prop collection
- **Low Player Match Rate**: Impacts prop analysis accuracy
- **Missing Injury Data**: Affects prop betting strategy
- **Stale Data**: Outdated information for real-time decisions

---

## Business Intelligence Opportunities

### **Prop Betting Analysis**
- **Line Movement Tracking**: How odds change leading up to games
- **Injury Impact Analysis**: Quantify how different injury types affect props
- **Historical Performance Correlation**: Player stats vs. prop line accuracy
- **Sportsbook Arbitrage**: FanDuel vs. DraftKings line differences

### **Predictive Modeling Foundation**
- **Player Performance Trends**: Recent game statistical patterns
- **Matchup Analysis**: Historical performance vs. specific opponents
- **Rest Impact**: Load management effects on performance
- **Injury Recovery Patterns**: Performance after return from specific injuries

---

## Implementation Roadmap

### **Week 1-2: Core Foundation**
- Deploy reference processors (teams, players, games)
- Establish cross-reference system
- Validate core data relationships

### **Week 3-4: Betting Pipeline** 
- Deploy events-processor (betting events)
- Deploy props-processor (**PRIMARY BUSINESS VALUE**)
- Implement odds tracking and validation

### **Week 5-6: Performance Integration**
- Deploy boxscores-processor (historical performance)
- Deploy injuries-processor (player availability)
- Build analytics foundation

### **Week 7-8: Advanced Features**
- Enhanced play-by-play processing
- Predictive modeling framework
- Website development and user interface

---

## Success Metrics & KPIs

### **Technical KPIs**
- **Processing Latency**: <30 minutes end-to-end
- **Data Completeness**: >90% complete prop/performance linkages
- **System Uptime**: 99.5% availability during NBA season
- **Error Rate**: <1% processing failures

### **Business KPIs** 
- **Prop Coverage**: Track % of games with complete prop data
- **Prediction Accuracy**: Baseline statistical model performance
- **User Engagement**: Website usage and analysis adoption
- **Revenue Metrics**: Conversion from analysis to betting decisions

---

## Technology Stack & Infrastructure

### **Current Architecture**
- **Google Cloud Platform**: Cloud Run, BigQuery, Cloud Storage, Pub/Sub
- **Python**: Consistent with existing scrapers
- **Data Format**: JSON for most sources, CSV for Big Data Ball

### **Recommended Additions**
- **Monitoring**: Cloud Monitoring + custom dashboards
- **Data Quality**: Automated validation and alerting
- **Caching**: Redis for frequently accessed reference data
- **Analytics**: Jupyter notebooks for model development

---

## Conclusion

This data pipeline provides a comprehensive foundation for NBA prop betting analysis, handling the complexity of multiple data sources while maintaining data quality and enabling real-time updates. The 22 active scrapers provide redundancy and comprehensive coverage across all aspects of NBA gam
