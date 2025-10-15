# NBA Data Pipeline - Comprehensive Implementation Reference

## Executive Summary

This document captures the complete analysis of the NBA prop betting data pipeline, documenting **20+ scrapers** across **4 data sources** and providing the architectural foundation for a comprehensive betting analytics system.

### **Core Business Objective**
Build a website with NBA player prop betting data, historical performance analysis, and predictive forecasting for **player points prop bets** (initially), with plans to expand to other prop types.

### **Key Achievement**
Successfully documented and designed schemas for a complete data pipeline that:
- **Collects prop betting lines** from multiple sportsbooks
- **Cross-references players** across 4+ different ID systems  
- **Links betting events** to actual NBA games and player statistics
- **Tracks historical performance** for predictive modeling
- **Supports real-time updates** throughout the season

---

## Data Source Overview

### **1. Ball Don't Lie API (4 Scrapers)**
**Purpose**: Core NBA game and player statistics
**Strengths**: Comprehensive historical data, reliable game/player IDs
**Coverage**: Games, player boxscores, team boxscores, injuries

### **2. Odds API (4 Scrapers)** 
**Purpose**: Betting lines and prop odds (CORE BUSINESS DATA)
**Strengths**: Real-time prop odds, multiple sportsbooks
**Coverage**: Events, current props, historical events, historical props
**Critical Dependency**: Events → Props (must run in sequence)

### **3. ESPN (3 Scrapers)**
**Purpose**: Rich player data and game coverage
**Strengths**: Detailed rosters, comprehensive boxscores
**Coverage**: Team rosters, scoreboard, game boxscores

### **4. NBA.com (10+ Scrapers)**
**Purpose**: Official NBA data with maximum detail
**Strengths**: Official status, comprehensive coverage, multiple data types
**Coverage**: Schedule, rosters, players, boxscores, injuries, play-by-play, transactions

### **5. Big Data Ball (1 Scraper)**
**Purpose**: Enhanced analytics data
**Strengths**: Advanced play-by-play with lineup tracking
**Coverage**: Enhanced play-by-play (2-hour delay post-game)

---

## Critical Data Relationships

### **Player Cross-Reference System**
**Challenge**: Each API uses different player identification systems
**Solution**: Master player table with cross-reference mapping

| **Source** | **ID Format** | **Example** | **Name Format** | **Usage** |
|------------|---------------|-------------|-----------------|-----------|
| **Ball Don't Lie** | Integer | `38017703` | `first_name` + `last_name` | Stats & Games |
| **ESPN** | String | `"3917376"` | `name` (full name) | Rosters & Details |
| **NBA.com** | Integer | `1630173` | `PLAYER_FIRST_NAME` + `PLAYER_LAST_NAME` | Official Data |
| **Odds API** | Name String | `"Jaylen Wells"` | `description` field | Prop Betting |

**Cross-Reference Strategy**: 
- Primary matching: `name + team + jersey_number`
- Secondary matching: Name variations array
- Confidence scoring for match quality

### **Game Linking System**
**Challenge**: Different game ID formats across sources
**Solution**: Master games table linking all sources

| **Source** | **ID Format** | **Example** | **Usage** |
|------------|---------------|-------------|-----------|
| **Ball Don't Lie** | Integer | `15908525` | Stats & Results |
| **ESPN** | String | `"401585183"` | Scores & Schedules |
| **NBA.com** | String | `"0022400500"` | Official Data |
| **Odds API** | Hash String | `"242c77a8d5890e18..."` | Betting Events |

**Linking Strategy**:
- Match by: `game_date + team_abbreviations + start_time`
- Handle time zone differences
- Account for postponements and rescheduling

### **Team Standardization**
**Solution**: Standardized team abbreviations as primary keys
**Mapping Examples**:
- Ball Don't Lie: `"LAL"` → NBA.com: `"LAL"` → Odds API: `"Los Angeles Lakers"`
- Consistent `team_abbr` used throughout entire system

---

## Data Collection Architecture

### **Daily Schedule Overview**

#### **Morning (8-10 AM ET): Current State**
- **Rosters** (ESPN, NBA.com): Catch overnight trades/signings
- **Injuries** (Ball Don't Lie, NBA.com): Latest injury designations  
- **Schedule** (NBA.com): Monitor for postponements

#### **Afternoon (12-4 PM ET): Pre-Game Setup**
- **Betting Events** (Odds API): Get game event IDs
- **Player Props** (Odds API): Collect prop odds (DEPENDS ON EVENTS)
- **Schedule Monitoring**: Final game confirmations

#### **Game Time: Live Monitoring**
- **Injury Updates**: Hourly checks for late scratches
- **Schedule Changes**: Emergency postponement handling

#### **Evening (6-11 PM ET): Results Collection**
- **Game Results** (ESPN, Ball Don't Lie, NBA.com): Final scores
- **Player Statistics** (Ball Don't Lie, NBA.com): Individual performance
- **Team Statistics**: Team-level results

#### **Late Night (11 PM-2 AM ET): Enhanced Data**
- **Big Data Ball**: Enhanced play-by-play (2-hour delay)
- **Next Day Prep**: Early betting lines if available

### **Critical Dependencies**
1. **Odds API Events → Player Props**: Must run sequentially
2. **Schedule Updates → Game-Specific Scrapers**: Need game IDs first
3. **Reference Data → Performance Data**: Teams/players before stats

---

## Database Schema Architecture

### **Reference Tables (Foundation)**

#### **games**
- **Purpose**: Master game reference linking all sources
- **Key Fields**: Multiple game IDs, team abbreviations, scores, timing
- **Partitioning**: By game_date
- **Critical**: Links betting events to actual NBA games

#### **teams** 
- **Purpose**: Standardized team reference
- **Key Fields**: team_abbr (primary), multiple source IDs, league organization
- **Usage**: Primary key for all team references

#### **players**
- **Purpose**: Master player database with cross-references
- **Key Fields**: Generated player_id, multiple source IDs, name variations
- **Critical**: Enables player matching across all APIs

#### **venues**
- **Purpose**: Arena and location reference
- **Key Fields**: venue details, home team, capacity, timezone

### **Event Tables (Time-Based)**

#### **player_injuries**
- **Purpose**: General injury status over time
- **Source**: Ball Don't Lie ongoing injury tracking
- **Key Fields**: status, description, dates, severity

#### **game_injury_reports** 
- **Purpose**: Official pre-game availability (CRITICAL FOR PROPS)
- **Source**: NBA.com official injury reports
- **Key Fields**: game-specific status, reason categories (Rest/Injury/Assignment)
- **Business Impact**: Directly affects prop betting strategy

#### **team_rosters**
- **Purpose**: Track roster changes over time
- **Sources**: ESPN (detailed) + NBA.com (current)
- **Key Fields**: roster status, contract type, dates

### **Performance Tables (Statistics)**

#### **player_boxscores**
- **Purpose**: Individual game statistics
- **Sources**: Ball Don't Lie (primary) + NBA.com (enhanced)
- **Key Fields**: All shooting/rebounding/assist stats, minutes, game context
- **Critical**: Historical performance for prop predictions

#### **team_boxscores**
- **Purpose**: Team-level game statistics  
- **Key Fields**: Team stats, pace, ratings, game results

### **Betting Tables (CORE BUSINESS)**

#### **betting_events**
- **Purpose**: Sportsbook events linked to NBA games
- **Source**: Odds API Events
- **Key Fields**: event_id, team mapping, commence_time, status
- **Critical**: Foundation for all prop betting data

#### **player_props**
- **Purpose**: Individual player prop lines and odds (PRIMARY BUSINESS DATA)
- **Source**: Odds API Player Props
- **Key Fields**: market_key, player_name, bet_type, line_value, odds_decimal
- **Sportsbooks**: FanDuel + DraftKings
- **Critical**: The core data for prop betting analysis

#### **odds_history**
- **Purpose**: Track line movements over time
- **Key Fields**: previous/new odds, line changes, timing
- **Business Value**: Understanding market movement patterns

### **Processing Tables (Operational)**

#### **process_tracking**
- **Purpose**: File processing status and idempotency
- **Key Fields**: file_path, status, retry logic, error handling

#### **scraper_runs**
- **Purpose**: Scraper execution history and performance
- **Key Fields**: run details, performance metrics, output files

#### **data_quality_checks**
- **Purpose**: Data validation and quality monitoring
- **Key Fields**: check results, failure rates, affected data

---

## Processor Architecture

### **Processor Design Principles**
- **One processor per data type** for clean separation
- **Independent operation** with pub/sub triggering
- **Idempotency** with duplicate detection
- **Graceful degradation** when dependencies missing

### **Core Processors**

#### **events-processor**
- **Input**: Odds API Events data
- **Output**: betting_events table
- **Logic**: Map team names to abbreviations, link to games
- **Priority**: Must run before props-processor

#### **props-processor** 
- **Input**: Odds API Player Props data  
- **Output**: player_props + odds_history tables
- **Dependencies**: Requires events-processor completion
- **Logic**: Match player names to player IDs, track odds changes
- **Critical**: Core business data processing

#### **games-processor**
- **Input**: Ball Don't Lie Games, ESPN Scoreboard, NBA.com Schedule
- **Output**: games table
- **Logic**: Cross-reference game IDs, standardize team abbreviations

#### **players-processor** 
- **Input**: NBA.com Player List, ESPN Rosters, NBA.com Rosters
- **Output**: players + team_rosters tables
- **Logic**: Cross-reference player IDs, track name variations

#### **boxscores-processor**
- **Input**: Ball Don't Lie + NBA.com Player Boxscores
- **Output**: player_boxscores table
- **Logic**: Cross-reference players and games, standardize stats

#### **injuries-processor**
- **Input**: Ball Don't Lie Injuries + NBA.com Injury Reports
- **Output**: player_injuries + game_injury_reports tables
- **Logic**: Distinguish general vs game-specific injury data

---

## Key Data Insights & Business Logic

### **Prop Betting Critical Data Flow**
1. **Events API** provides game event IDs
2. **Player Props API** uses event IDs to get betting lines
3. **Game Injury Reports** show player availability 
4. **Historical Boxscores** provide performance context
5. **Cross-referenced Player Data** enables accurate matching

### **Player Matching Strategy**
- **Primary**: `player_name + team_abbr + jersey_number`
- **Secondary**: Name variations (nicknames, abbreviations)
- **Confidence scoring**: Track match quality for data validation
- **Manual review**: Flag low-confidence matches for verification

### **Data Quality Considerations**

#### **Odds API Challenges**
- **Player names only** (no IDs) → Requires name matching
- **Team full names** → Must map to abbreviations
- **Real-time updates** → Handle rapid odds changes

#### **Cross-Source Timing Issues**
- **Data freshness** varies by source
- **Injury updates** may lag between sources
- **Game postponements** affect all downstream data

#### **Missing Data Handling**
- **Graceful degradation**: Process available data
- **Backfill strategies**: Fill gaps when dependencies arrive
- **Data completeness tracking**: Monitor missing relationships

### **Business Intelligence Opportunities**

#### **Prop Betting Analysis**
- **Line movement patterns**: Track how odds change before games
- **Player availability impact**: Quantify how injuries affect lines
- **Historical performance correlation**: Player stats vs prop lines
- **Sportsbook comparison**: FanDuel vs DraftKings line differences

#### **Predictive Modeling Foundation**
- **Player performance trends**: Recent game statistical patterns
- **Matchup analysis**: Historical performance vs specific opponents  
- **Injury impact**: How different injury types affect player performance
- **Rest vs play**: Load management impact on prop values

---

## Implementation Priority & Roadmap

### **Phase 1: Core Reference Data (Weeks 1-2)**
1. **Deploy core processors**: teams, players, games
2. **Establish cross-reference system**: Player/game ID mapping
3. **Basic data quality checks**: Validate core relationships

### **Phase 2: Betting Pipeline (Weeks 3-4)** 
1. **Deploy events-processor**: Betting events foundation
2. **Deploy props-processor**: Core business data
3. **Implement odds tracking**: Historical line movement
4. **Build data quality monitoring**: Prop data validation

### **Phase 3: Performance Integration (Weeks 5-6)**
1. **Deploy boxscores-processor**: Historical performance data
2. **Deploy injuries-processor**: Player availability tracking  
3. **Build analytics foundation**: Link performance to prop outcomes

### **Phase 4: Advanced Features (Weeks 7-8)**
1. **Enhanced analytics**: Play-by-play processing
2. **Predictive modeling**: Statistical analysis framework
3. **Website development**: User-facing prop analysis
4. **Real-time updates**: Live injury and line tracking

### **Phase 5: Scale & Optimization (Ongoing)**
1. **Performance optimization**: Query optimization, caching
2. **Additional prop types**: Rebounds, assists, other markets
3. **Advanced modeling**: Machine learning integration
4. **Mobile optimization**: Responsive design

---

## Risk Mitigation & Monitoring

### **Data Source Risks**
- **API rate limits**: Implement proper throttling and retry logic
- **Schema changes**: Monitor for upstream API modifications
- **Data quality degradation**: Automated validation and alerting

### **Business Continuity**
- **Backup data sources**: Multiple sources for critical data
- **Graceful degradation**: System functionality with partial data
- **Error recovery**: Automated retry and manual intervention procedures

### **Performance Monitoring**
- **Processing latency**: Track end-to-end data freshness
- **Data completeness**: Monitor missing cross-references
- **Query performance**: Optimize for user-facing analytics

---

## Technology Stack Recommendations

### **Data Infrastructure**
- **Google Cloud Platform**: Existing choice, good integration
- **BigQuery**: Optimal for analytical workloads and large datasets
- **Cloud Storage**: Raw data files with organized directory structure
- **Cloud Run**: Scalable processor deployment
- **Pub/Sub**: Reliable async processing triggers

### **Processing Framework**
- **Python**: Consistent with existing scrapers
- **Pandas**: Data transformation and analysis
- **SQLAlchemy**: Database ORM for complex queries
- **Apache Beam**: Future consideration for large-scale processing

### **Monitoring & Observability**
- **Cloud Monitoring**: Infrastructure and application metrics
- **Cloud Logging**: Centralized log analysis
- **Custom dashboards**: Business-specific KPIs and data quality

---

## Success Metrics

### **Data Quality KPIs**
- **Player match rate**: >95% successful cross-references
- **Game linking rate**: >98% successful game ID mapping
- **Data freshness**: <30 minutes from scrape to availability
- **Completeness rate**: >90% complete prop/performance linkages

### **Business KPIs**
- **Prop coverage**: Track % of games with available props
- **Historical depth**: Maintain 2+ seasons of performance data
- **Prediction accuracy**: Baseline statistical models for validation
- **User engagement**: Website usage and prop analysis adoption

---

## Conclusion

This comprehensive data pipeline provides the foundation for a sophisticated NBA prop betting analysis system. The architecture handles the complexity of cross-referencing players and games across multiple APIs while maintaining data quality and enabling real-time updates.

The phased implementation approach ensures that core business functionality (prop betting data) is prioritized while building toward advanced analytics capabilities. The system is designed to scale from the initial focus on player points props to a comprehensive sports betting analytics platform.

**Next Steps**: Begin Phase 1 implementation with core reference data processors, followed immediately by the betting pipeline to establish the primary business value proposition.
