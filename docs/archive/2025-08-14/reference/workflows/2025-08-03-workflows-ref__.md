# NBA Workflows Reference

**Purpose:** Complete reference for all NBA data collection workflows - operational and backfill  
**Status:** Production ready - 16 operational scrapers + 4 backfill scrapers planned

---

## **Morning Operations** 
**Schedule:** Daily at 8 AM PT  
**Total Scrapers:** 8

| Endpoint | Class Name (in workflow) | ✅/❌ Status | Notes |
|----------|-------------------------|-------------|-------|
| `nbac_player_movement` | `GetNbaComPlayerMovement` | ✅ | User confirmed working |
| `nbac_schedule_api` | `GetNbaComScheduleApi` | ✅ | **PRIMARY - Current season schedule** |
| `nbac_schedule_cdn` | `GetNbaComScheduleCdn` | ✅ | **BACKUP - Monitor differences** |
| `nbac_player_list` | `GetNbaComPlayerList` | ✅ | Confirmed |
| `nbac_injury_report` | `GetNbaComInjuryReport` | ✅ | **PRIMARY - Official NBA injury report** |
| `bdl_injuries` | `BdlInjuriesScraper` | ✅ | **BACKUP - Ball Don't Lie injury data** |
| `bdl_standings` | `BdlStandingsScraper` | ✅ | User confirmed active |
| `bdl_active_players` | `BdlActivePlayersScraper` | ✅ | Confirmed |

**Removed Scrapers:**
- `nbac_roster` - **Redundant:** `nbac_player_list` provides player-to-team mapping
- `espn_roster_api` - **Redundant:** `nbac_player_list` covers this, could be backup in future
- `pbp_enhanced_pbp` - **Not reliable:** Not guaranteed to work, prefer NBA.com if needed

---

## **Real-Time Business**
**Schedule:** Every 2 hours, 8 AM - 8 PM PT  
**Total Scrapers:** 6

| Endpoint | Class Name (in workflow) | ✅/❌ Status | Notes |
|----------|-------------------------|-------------|-------|
| `oddsa_events` | `GetOddsApiEvents` | ✅ | **CRITICAL - Revenue** |
| `oddsa_player_props` | `GetOddsApiCurrentEventOdds` | ✅ | **CRITICAL - Revenue (depends on events)** |
| `nbac_player_list` | `GetNbaComPlayerList` | ✅ | Confirmed |
| `nbac_injury_report` | `GetNbaComInjuryReport` | ✅ | **PRIMARY - Official NBA injury report** |
| `bdl_injuries` | `BdlInjuriesScraper` | ✅ | **BACKUP - Ball Don't Lie injury data** |
| `bdl_active_players` | `BdlActivePlayersScraper` | ✅ | Confirmed |

**Dependencies:** `oddsa_events` → `oddsa_player_props` (sequential, critical)

---

## **Post-Game Collection**
**Schedule:** 8 PM PT & 11 PM PT (2 schedulers, same workflow)  
**Total Scrapers:** 2

| Endpoint | Class Name (in workflow) | ✅/❌ Status | Notes |
|----------|-------------------------|-------------|-------|
| `nbac_scoreboard_v2` | `GetNbaComScoreboardV2` | ✅ | User confirmed working (may be deprecated by NBA.com) |
| `bdl_box_scores` | `BdlBoxScoresScraper` | ✅ | User confirmed active |

**Removed Scrapers:**
- `bdl_live_box_scores` - **Not needed:** Not collecting live stats currently
- `bdl_player_averages` - **Wrong timing:** Don't need averages now, maybe future morning workflow
- `espn_scoreboard_api` - **Wrong timing:** Only use ESPN as backup in morning scrape
- `espn_game_boxscore` - **Wrong timing:** Only use ESPN as backup in morning scrape
- `bdl_player_box_scores` - **Redundant:** Data included in bdl_box_scores
- `bdl_game_adv_stats` - **Need study:** Removing until further analysis

---

## **Late Night Recovery**
**Schedule:** Daily at 2 AM PT  
**Total Scrapers:** 3

| Endpoint | Class Name (in workflow) | ✅/❌ Status | Notes |
|----------|-------------------------|-------------|-------|
| `bigdataball_pbp` | `BigDataBallPbpScraper` | ✅ | **PRIMARY - Enhanced play-by-play** |
| `nbac_play_by_play` | `GetNbaComPlayByPlay` | ✅ | **BACKUP - NBA.com play-by-play** |
| `bdl_box_scores` | `BdlBoxScoresScraper` | ✅ | User confirmed active |

**Removed Scrapers:**
- `pbp_enhanced_pbp` - **Not reliable:** Not guaranteed to work, not using
- `bdl_player_averages` - **Future use:** Remove for now, maybe use in future
- `nbac_injury_report` - **Wrong timing:** Don't need 2 AM injury report
- `nbac_player_movement` - **Wrong timing:** Don't need 2 AM player movement check
- `bdl_player_box_scores` - **Redundant:** Data included in bdl_box_scores
- `bdl_game_adv_stats` - **Need study:** Removing until further analysis

---

## **Early Morning Final Check**
**Schedule:** Daily at 5 AM PT  
**Total Scrapers:** 5

| Endpoint | Class Name (in workflow) | ✅/❌ Status | Notes |
|----------|-------------------------|-------------|-------|
| `bigdataball_pbp` | `BigDataBallPbpScraper` | ✅ | **PRIMARY - Enhanced play-by-play final attempt** |
| `nbac_play_by_play` | `GetNbaComPlayByPlay` | ✅ | **BACKUP - NBA.com play-by-play** |
| `bdl_box_scores` | `BdlBoxScoresScraper` | ✅ | User confirmed active |
| `espn_scoreboard_api` | `GetEspnScoreboard` | ✅ | **Backup data source** |
| `espn_game_boxscore` | `GetEspnBoxscore` | ✅ | **Backup data source** |

**Dependencies:** `espn_scoreboard_api` → `espn_game_boxscore` (sequential)

**Removed Scrapers:**
- `pbp_enhanced_pbp` - **Not reliable:** Not guaranteed to work, not using
- `bdl_player_box_scores` - **Redundant:** Data included in bdl_box_scores
- `bdl_game_adv_stats` - **Need study:** Removing until further analysis

---

## **BACKFILL WORKFLOWS**

### **Completed Backfill**

#### **NBA Historical Schedules** ✅ **COMPLETE**
**Workflow:** `collect-nba-historical-schedules.yaml`  
**Status:** Successfully completed  
**Total Scrapers:** 1

| Endpoint | Class Name | ✅/❌ Status | Notes |
|----------|------------|-------------|-------|
| `nbac_schedule_api` | `GetNbaComScheduleApi` | ✅ | **Seasons 2021-2024 collected** |

**Results:**
- ✅ **4 seasons collected:** 2021-22, 2022-23, 2023-24, 2024-25
- ✅ **5,583 total games** across all seasons
- ✅ **Season-based storage:** `gs://nba-scraped-data/nba-com/schedule/{season}/`

---

### **Planned Backfill Workflows**

#### **NBA Historical Box Scores** 📋 **PLANNED**
**Purpose:** Player performance data for all historical games  
**Input:** Game IDs from completed schedule collection  
**Total Scrapers:** 2

| Endpoint | Class Name | ✅/❌ Status | Notes |
|----------|------------|-------------|-------|
| `bdl_box_scores` | `BdlBoxScoresScraper` | ✅ | **PRIMARY - Ball Don't Lie data** |
| `nbac_player_boxscore` | `GetNbaComPlayerBoxscore` | ✅ | **BACKUP - Official NBA.com stats** |

**Scope:** ~140,000 player performances (5,583 games × ~25 players)

#### **NBA Historical Props Data** 📋 **PLANNED**
**Purpose:** Historical betting lines for model training  
**Total Scrapers:** 2

| Endpoint | Class Name | ✅/❌ Status | Notes |
|----------|------------|-------------|-------|
| `oddsa_events_his` | `GetOddsApiHistoricalEvents` | ✅ | **Historical game events** |
| `oddsa_player_props_his` | `GetOddsApiHistoricalEventOdds` | ✅ | **Historical prop lines** |

**Constraints:** Limited data retention, API costs

**Removed from Backfill:**
- `bdl_player_averages` - **No date filters:** Need to study options more, not season 1 priority
- `bdl_active_players` - **No date filters:** Current active only, not good for historical backfill

---

## **SUMMARY ANALYSIS**

### **Operational Workflows**
**Total Unique Scrapers:** 16 (daily operations)

### **Backfill Workflows** 
**Completed:** 1 scraper (NBA schedules - ✅ 5,583 games collected)  
**Planned:** 4 scrapers (box scores, historical props)

### **Issues Found:**

#### **1. All Scrapers Confirmed Working:**
- `nbac_scoreboard_v2`: ✅ Confirmed working (but may be deprecated by NBA.com in future)
- `nbac_player_movement`: ✅ Confirmed working

#### **2. Technology Switch:**
- **BigDataBall PBP**: Added to Late Night Recovery and Early Morning Final Check workflows
- **PbpStats**: Removed from all workflows (not reliable/not using)

### **Critical Dependencies:**
1. **Revenue Critical:** `oddsa_events` → `oddsa_player_props` (Real-Time Business)
2. **Data Chain:** `espn_scoreboard_api` → `espn_game_boxscore` (Post-Game, Early Morning)

### **Workflow Optimization Results:**

#### **Operational Workflows:**
- **Morning Operations**: Increased from 6 to 8 scrapers (added schedule backup + injury backup)
- **Real-Time Business**: Increased from 5 to 6 scrapers (added injury backup) - revenue critical
- **Post-Game Collection**: Reduced from 8 to 2 scrapers (removed redundant/unnecessary scrapers)
- **Late Night Recovery**: Reduced from 7 to 3 scrapers (focused on core recovery + BDB + backup)
- **Early Morning Final Check**: Reduced from 7 to 5 scrapers (final attempt + backups) - **5 AM PT**

#### **Backfill Workflows:**
- **Historical Schedules**: ✅ **Complete** - 1 scraper, 4 seasons, 5,583 games
- **Historical Box Scores**: 📋 **Planned** - 2 scrapers, ~140k player performances
- **Historical Props**: 📋 **Planned** - 2 scrapers, betting line history

### **Key Changes Made:**
1. **Added backup scrapers** - Schedule CDN backup, NBA.com play-by-play backup, Ball Don't Lie injury backup
2. **Removed redundant scrapers** - bdl_player_box_scores (data in bdl_box_scores)
3. **Removed under-study scrapers** - bdl_game_adv_stats (need more analysis)
4. **Optimized timing** - Removed unnecessary 2 AM injury/movement checks
5. **Streamlined post-game collection** - Focused on core data only, ESPN backups in morning
6. **Earlier final check** - Moved from 6 AM to 5 AM PT for better business day prep
7. **Maintained critical paths** - Kept all revenue-critical Odds API workflows intact
8. **Simplified backfill** - Removed date-filter incompatible scrapers

### **Recommended Actions:**

#### **Operational Workflows:**
1. **Update operational workflows** to match this optimized scraper list
2. **Update operational doc** to reflect 16 active workflow scrapers  
3. **Deploy backup monitoring** - Schedule CDN vs API, NBA.com vs BigDataBall play-by-play, NBA.com vs BDL injuries
4. **Monitor NBA.com scoreboard v2** for potential deprecation

#### **Backfill Workflows:**
5. **Create planned backfill workflows** for box scores and historical props
6. **Focus on core data sources** - Ball Don't Lie primary, NBA.com backup
7. **Plan backfill execution timeline** - Phase 2 (box scores) ready for implementation

---

## **Questions for Review:**

### **Operational Workflows:**
1. **Comprehensive backup strategy looks good - ready for deployment?**
2. **Should the operational doc reflect these 16 active scrapers as the new source of truth?**
3. **Are the backup monitoring strategies (Schedule CDN, NBA.com play-by-play, BDL injuries) sufficient?**

### **Backfill Workflows:**
4. **Should I help create the simplified backfill workflow files (box scores + props only)?**
5. **Do you need more details about Box Score vs Player Boxscore scraper differences?**
6. **Should backfill scrapers be included in the main operational doc or separate backfill doc?**
