# NBA Data Pipeline - Primary vs Backup Strategy & Database Design

## Strategic Overview

This document defines which scrapers are **primary sources** vs **backups**, how backup data should be handled, and what fields actually need database storage vs remaining in raw files.

## Core Principles

### **Data Strategy Goals**
- **Minimize database costs** by storing only business-critical data
- **Ensure reliability** with backup sources for critical data
- **Optimize performance** by avoiding redundant processing
- **Maintain flexibility** for future analytics needs

### **Backup Strategy Options**
1. **Same Table Priority**: Primary data wins, backups fill gaps
2. **Separate Backup Tables**: Keep primary and backup data isolated  
3. **GCS-Only Backups**: Only promote to DB when primary fails
4. **Hybrid Approach**: Different strategies by data type

---

## Data Source Classification & Strategy

### **CORE BUSINESS DATA (Always Process → Database)**

#### **Betting Pipeline (CRITICAL - No Backups)**
| **Scraper** | **Status** | **Database Strategy** | **Rationale** |
|-------------|------------|----------------------|---------------|
| `GetOddsApiEvents` | **PRIMARY** | Always → `betting_events` | **BUSINESS CRITICAL** - No alternatives |
| `GetOddsApiCurrentEventOdds` | **PRIMARY** | Always → `player_props` | **CORE REVENUE** - Must be 100% reliable |
| `GetOddsApiHistoricalEvents` | **BACKFILL** | Always → `betting_events` | Historical analysis |
| `GetOddsApiHistoricalEventOdds` | **BACKFILL** | Always → `player_props` | Historical patterns |

**Strategy**: **No backup strategy needed** - Odds API is the only source for betting data

---

### **REFERENCE DATA (Smart Backup Strategy)**

#### **Player Reference (Hybrid Strategy)**
| **Scraper** | **Status** | **Database Strategy** | **Backup Strategy** |
|-------------|------------|----------------------|-------------------|
| `GetNbaComPlayerList` | **PRIMARY** | Always → `players` table | **GCS-Only Backups** |
| `GetEspnTeamRosterAPI` | **BACKUP** | GCS Only → DB when primary fails | Rich biographical data |
| `GetNbaTeamRoster` | **BACKUP** | GCS Only → DB when primary fails | Basic official data |

**Strategy**: **GCS-Only Backups** - NBA.com is authoritative, others for enrichment

#### **Team Reference (Single Source)**
| **Scraper** | **Status** | **Database Strategy** | **Rationale** |
|-------------|------------|----------------------|---------------|
| `Teams` | **DERIVED** | From games data → `teams` table | Built from game sources |

**Strategy**: **No dedicated scraper** - Derive from game data across sources

---

### **GAME DATA (Priority-Based Strategy)**

#### **Games & Schedules (Primary + Smart Backups)**
| **Scraper** | **Status** | **Database Strategy** | **Backup Strategy** |
|-------------|------------|----------------------|-------------------|
| `BdlGamesScraper` | **PRIMARY** | Always → `games` table | **Same Table Priority** |
| `GetDataNbaSeasonSchedule` | **BACKUP** | GCS Only → Fill gaps in `games` | Comprehensive official data |
| `GetNbaComScheduleCdn` | **BACKUP** | GCS Only → Fill gaps in `games` | Fast updates |
| `GetEspnScoreboard` | **VALIDATION** | GCS Only → Validation/alerts | Score verification |
| `GetNbaComScoreboardV2` | **ENHANCEMENT** | GCS Only → Manual promotion | Unique quarter data |

**Strategy**: **Same Table Priority** with **GCS-Only Backups**
- Ball Don't Lie → Primary ingestion
- NBA.com sources → Fill missing games only
- ESPN → Validation and alerts for discrepancies

---

### **PLAYER PERFORMANCE (Primary + Validation)**

#### **Player Statistics (Primary + Quality Backup)**
| **Scraper** | **Status** | **Database Strategy** | **Backup Strategy** |
|-------------|------------|----------------------|-------------------|
| `BdlPlayerBoxScoresScraper` | **PRIMARY** | Always → `player_boxscores` | **Same Table Priority** |
| `GetNbaComPlayerBoxscore` | **BACKUP** | GCS Only → Fill gaps | Official validation |
| `GetEspnBoxscore` | **VALIDATION** | GCS Only → Manual check | Format differences |

**Strategy**: **Same Table Priority** - Ball Don't Lie primary, NBA.com fills gaps

#### **Team Statistics (Primary Only)**
| **Scraper** | **Status** | **Database Strategy** | **Rationale** |
|-------------|------------|----------------------|---------------|
| `BdlBoxScoresScraper` | **PRIMARY** | Always → `team_boxscores` | Embedded in player data |

**Strategy**: **Single Source** - Team stats embedded in Ball Don't Lie data

---

### **INJURY DATA (Dual Primary Strategy)**

#### **Player Availability (Both Primary)**
| **Scraper** | **Status** | **Database Strategy** | **Rationale** |
|-------------|------------|----------------------|---------------|
| `GetNbaComInjuryReport` | **PRIMARY** | Always → `game_injury_reports` | **CRITICAL FOR PROPS** |
| `BdlInjuriesScraper` | **PRIMARY** | Always → `player_injuries` | General injury tracking |

**Strategy**: **Dual Primary** - Different purposes, both needed
- NBA.com → Game-specific availability (props)
- Ball Don't Lie → General injury status (context)

---

### **ADVANCED ANALYTICS (GCS-Only Strategy)**

#### **Detailed Event Data (Manual Promotion)**
| **Scraper** | **Status** | **Database Strategy** | **Rationale** |
|-------------|------------|----------------------|---------------|
| `GetNbaComPlayByPlay` | **ANALYTICS** | **GCS Only** → Manual promotion | Massive data, specialized use |
| `Big Data Ball` | **ANALYTICS** | **GCS Only** → Manual promotion | Enhanced analytics only |
| `GetNbaComPlayerMovement` | **REFERENCE** | **GCS Only** → Manual queries | Historical context only |

**Strategy**: **GCS-Only** - Keep raw files, promote selectively for specific analysis

---

## Database Field Strategy

### **Core Principle: Store Business Logic, Not Formatting**

#### **ALWAYS Store (Business Critical)**
- **Cross-reference IDs** - For linking across sources
- **Core statistics** - Points, rebounds, assists (prop betting)
- **Game context** - Date, teams, status, scores
- **Player identification** - Names, teams, positions
- **Betting data** - All odds, lines, player names
- **Injury status** - Availability and reasons
- **Timestamps** - For data freshness tracking

#### **NEVER Store (Formatting/Metadata)**
- **Display formatting** - "6' 6\"" (store as inches)
- **URL slugs** - "jaylen-brown" (generate from names)
- **Full descriptions** - Long text descriptions
- **Broadcast details** - TV networks and schedules
- **Color codes** - Team colors and branding
- **Rich metadata** - College, draft details (unless needed)

### **Field-by-Field Analysis**

#### **Player Data (Store Essential Only)**
```sql
-- STORE (Business Critical)
player_id, first_name, last_name, team_abbr, position, jersey_number
height_inches, weight_lbs, draft_year

-- DON'T STORE (Keep in Raw Files)
player_slug, full_url, college, country, draft_round, draft_number
```

#### **Game Data (Store Core Game Logic)**
```sql
-- STORE (Business Critical)  
game_id, game_date, home_team_abbr, away_team_abbr, home_score, away_score
status, start_time, arena_name, is_neutral

-- DON'T STORE (Keep in Raw Files)
broadcast_details, game_code, arena_state, detailed_venue_info
```

#### **Player Stats (Store Performance Only)**
```sql
-- STORE (Business Critical)
game_id, player_id, minutes_decimal, pts, reb, ast, stl, blk, 
fgm, fga, fg3m, fg3a, ftm, fta, plus_minus

-- DON'T STORE (Keep in Raw Files)
fantasy_points, video_available, matchup_string, detailed_shooting_zones
```

#### **Betting Data (Store Everything)**
```sql
-- STORE (ALL - Business Critical)
event_id, player_name, bet_type, line_value, odds_decimal, 
bookmaker_key, market_key, last_update

-- Rationale: All betting data is business-critical
```

---

## Implementation Strategy by Data Type

### **Phase 1: Core Business Pipeline**

#### **Week 1: Betting Data (No Backups)**
```python
# Events Processor - Primary Only
def process_odds_events():
    # Always process to betting_events table
    # No backup strategy - single source
    
# Props Processor - Primary Only  
def process_player_props():
    # Always process to player_props table
    # No backup strategy - single source
```

#### **Week 2: Reference Data (GCS Backups)**
```python
# Players Processor - Primary + GCS Backups
def process_players():
    # Primary: NBA.com Player List → players table
    # Backup: Keep ESPN/NBA rosters in GCS only
    # Promote backups only when primary fails
```

### **Phase 2: Performance Data**

#### **Week 3: Game Data (Priority Strategy)**
```python
# Games Processor - Primary + Same Table Backups
def process_games():
    # Primary: Ball Don't Lie → games table
    # Backup: NBA.com schedule → fill gaps in same table
    # Mark data_source for tracking
```

#### **Week 4: Player Stats (Priority Strategy)**
```python
# Boxscores Processor - Primary + Gap Filling
def process_player_boxscores():
    # Primary: Ball Don't Lie → player_boxscores table
    # Backup: NBA.com → fill missing games only
    # Validation: ESPN → alerts for discrepancies
```

### **Phase 3: Injury Data (Dual Primary)**

#### **Week 5: Injury Processing (Both Primary)**
```python
# Injuries Processor - Dual Primary Strategy
def process_injuries():
    # Primary 1: NBA.com → game_injury_reports table
    # Primary 2: Ball Don't Lie → player_injuries table
    # Different purposes, both always processed
```

---

## Backup Data Management

### **GCS-Only Backup Strategy**

#### **File Organization**
```
/raw-data/
  /primary/           # Always processed to DB
    /odds-api/
    /ball-dont-lie/
  /backup/            # GCS only, manual promotion
    /nba-com/
    /espn/
  /analytics/         # GCS only, specialized use
    /play-by-play/
    /big-data-ball/
```

#### **Promotion Scripts**
```python
# Manual promotion from GCS to DB when needed
def promote_backup_data(data_type, date_range, reason):
    """
    Manually promote backup data to database
    Used when primary source fails or for historical backfill
    """
    # Log promotion reason and scope
    # Process backup files to appropriate tables
    # Mark as backup source in metadata
```

### **Monitoring & Alerting**

#### **Primary Source Health**
```python
# Alert when primary sources fail
primary_health_checks = {
    'odds_api_events': 'CRITICAL - Business stops',
    'odds_api_props': 'CRITICAL - Revenue impact', 
    'bdl_games': 'HIGH - Switch to NBA.com backup',
    'bdl_player_stats': 'MEDIUM - Fill gaps from NBA.com',
    'nba_injury_reports': 'HIGH - Switch to Ball Don't Lie'
}
```

#### **Backup Promotion Triggers**
- **Automatic**: Primary source fails for >2 hours
- **Manual**: Data quality issues or historical backfill
- **Scheduled**: Validation runs comparing primary vs backup

---

## Cost-Benefit Analysis

### **Database Storage Savings**

#### **Estimated Storage Reduction**
| **Data Type** | **Full Storage** | **Optimized Storage** | **Savings** |
|---------------|------------------|----------------------|-------------|
| **Player Metadata** | 100% (all fields) | 30% (core only) | **70% reduction** |
| **Game Details** | 100% (all fields) | 40% (core only) | **60% reduction** |
| **Advanced Analytics** | 100% (in DB) | 0% (GCS only) | **100% reduction** |
| **Backup Sources** | 100% (duplicate) | 10% (gaps only) | **90% reduction** |

#### **BigQuery Cost Impact**
- **Primary tables**: ~2GB/day (business critical data)
- **Backup promotion**: ~200MB/day (gap filling only)
- **Raw file storage**: ~10GB/day (much cheaper in GCS)
- **Total savings**: ~80% reduction in BigQuery costs

### **Operational Benefits**
- **Faster queries**: Less data in analytical tables
- **Simpler processors**: Focus on business logic
- **Better reliability**: Clear primary/backup hierarchy
- **Easier debugging**: Clean data lineage tracking

---

## Implementation Recommendations

### **Recommended Approach: Hybrid Strategy**

#### **Core Business Data → Database**
- **Betting pipeline**: All data (single source)
- **Player stats**: Primary + gap filling
- **Game data**: Primary + gap filling  
- **Injury reports**: Dual primary (different purposes)

#### **Supporting Data → GCS + Manual Promotion**
- **Reference data**: Primary to DB, backups to GCS
- **Advanced analytics**: GCS only, promote for specific analysis
- **Historical backfill**: GCS storage, batch promotion

#### **Field Strategy → Store Business Logic Only**
- **Essential fields**: Cross-references, core stats, business data
- **Skip formatting**: Display strings, metadata, rich descriptions
- **Raw files**: Keep everything for future flexibility

### **Next Steps**

1. **Define primary sources** for each data type
2. **Implement core business pipeline** (betting data)
3. **Build backup promotion scripts** for manual intervention
4. **Set up monitoring** for primary source health
5. **Create field mapping** for optimized database storage

### **Success Metrics**
- **Data availability**: 99.9% for primary sources
- **Storage costs**: 80% reduction vs storing everything
- **Query performance**: <2 second response for prop analysis
- **Backup usage**: <5% of total data volume from backups

---

## Conclusion

This hybrid strategy maximizes **reliability** while minimizing **costs**:

- **Business-critical data** gets primary + backup sources
- **Supporting data** uses cost-effective GCS storage  
- **Database contains only** business logic and core analytics
- **Raw files preserve** all data for future flexibility

**Key Principle**: Store what you need for daily operations, keep everything else accessible but not expensive.
