# NBA Scraper Operational Schedule - MASTER REFERENCE

**Document Purpose**: Canonical source of truth for all NBA scraper scheduling decisions. All schedule changes must be made in this document FIRST, then propagated to implementation.

**Last Updated**: July 31, 2025  
**Current Status**: 17/17 Operational Scrapers Scheduled (100% Coverage)  
**Service URL**: `https://nba-scrapers-756957797294.us-west2.run.app/scrape`  
**Timezone**: America/Los_Angeles (Pacific Time)  
**Region**: us-west2  

---

## Current Operational Schedule

### **Trade Season Schedule (February 1 - August 1)**
*Higher frequency monitoring during active trade period*

#### **Daily Morning Operations (8:00-8:15 AM PT)**
| Time | Scraper Class | Job Name | Cron Schedule | Endpoint | Description |
|------|---------------|----------|---------------|----------|-------------|
| 8:00 AM | GetNbaComPlayerMovement | nba-player-movement | `0 8 * * *` | nbac_player_movement | Complete transaction history |
| 8:00 AM | GetDataNbaSeasonSchedule | nba-season-schedule | `0 8 * * *` | nbac_current_schedule_v2_1 | Comprehensive game scheduling |
| 8:00 AM | GetOddsApiTeamPlayers | nba-odds-team-players | `0 8 * * *` | oddsa_team_players | Sportsbook player perspective |
| 8:10 AM | GetEspnTeamRosterAPI | nba-espn-gsw-roster | `10 8 * * *` | espn_roster_api&team_abbr=GSW | Trade validation (GSW only) |
| 8:15 AM | GetNbaTeamRoster | nba-team-roster | `15 8 * * *` | nbac_roster | All 30 team rosters (basic format) |

#### **Real-Time Business Operations (Every 2 Hours, 8 AM - 8 PM PT)**
| Time | Scraper Class | Job Name | Cron Schedule | Endpoint | Description |
|------|---------------|----------|---------------|----------|-------------|
| :00 | GetOddsApiEvents | nba-odds-events | `0 8-20/2 * * *` | oddsa_events | **CRITICAL**: Foundation for prop betting |
| :00 | GetNbaComPlayerList | nba-player-list | `0 */2 * * *` | nbac_player_list | **CRITICAL**: Player-to-team mapping |
| :00 | GetNbaComInjuryReport | nba-injury-report | `0 */2 * * *` | nbac_injury_report | **CRITICAL**: Player availability |
| :05 | BdlActivePlayersScraper | nba-bdl-active-players | `5 */2 * * *` | bdl_active_players | Player validation (5-6 API requests) |
| :30 | GetOddsApiCurrentEventOdds | nba-odds-props | `30 8-20/2 * * *` | oddsa_player_props | **CRITICAL**: Core business revenue |

**Times**: 8:00/8:30, 10:00/10:30, 12:00/12:30, 14:00/14:30, 16:00/16:30, 18:00/18:30, 20:00/20:30

#### **Game Day Evening Operations (6 PM, 9 PM, 11 PM PT)**
| Time | Scraper Class | Job Name | Cron Schedule | Endpoint | Description |
|------|---------------|----------|---------------|----------|-------------|
| 6,9,11 PM | GetEspnScoreboard | nba-espn-scoreboard | `0 18,21,23 * * *` | espn_scoreboard_api | Game scores and status |
| 6,9,11 PM | GetNbaComScoreboardV2 | nba-nbacom-scoreboard | `0 18,21,23 * * *` | nbac_scoreboard_v2 | Official NBA scores with quarter data |

#### **Post-Game Analysis (9:00-9:20 PM PT)**
| Time | Scraper Class | Job Name | Cron Schedule | Endpoint | Description |
|------|---------------|----------|---------------|----------|-------------|
| 9:00 PM | BdlPlayerBoxScoresScraper | nba-bdl-player-boxscores | `0 21 * * *` | bdl_player_box_scores | Individual player statistics |
| 9:05 PM | BdlBoxScoresScraper | nba-bdl-boxscores | `5 21 * * *` | bdl_box_scores | Team stats with embedded players |
| 9:10 PM | GetNbaComPlayerBoxscore | nba-nbacom-player-boxscore | `10 21 * * *` | nbac_player_boxscore | Official player stats with fantasy points |
| 9:15 PM | GetEspnBoxscore | nba-espn-boxscore | `15 21 * * *` | espn_game_boxscore | Alternative boxscore validation |
| 9:20 PM | GetNbaComPlayByPlay | nba-nbacom-playbyplay | `20 21 * * *` | nbac_play_by_play | Detailed play-by-play with coordinates |

### **Regular Season Schedule (August 1 - February 1)**  
*Reduced frequency monitoring during stable roster period*

#### **Changes from Trade Season**
- **Real-Time Operations**: Change from every 2 hours to every 4 hours
  - GetNbaComPlayerList: `0 */4 * * *` (instead of `0 */2 * * *`)
  - GetNbaComInjuryReport: `0 */4 * * *` (instead of `0 */2 * * *`)  
  - BdlActivePlayersScraper: `5 */4 * * *` (instead of `5 */2 * * *`)
- **All other schedules remain identical**

---

## Business Rules & Dependencies

### **Critical Dependencies**
1. **Events → Props Dependency**: 
   - `nba-odds-events` MUST complete before `nba-odds-props` runs
   - 30-minute timing window: Events at :00, Props at :30
   - **Business Impact**: Props API will fail without valid event IDs

2. **Player Intelligence Requirement**:
   - `nba-player-list` required for prop processing
   - Maps player names to team abbreviations
   - **Business Impact**: Cannot process prop bets without player-team mapping

3. **Sequential Post-Game Processing**:
   - 5-minute stagger prevents resource conflicts
   - Allows each scraper to complete before next starts

### **API Rate Limits**
| API | Limit | Current Usage | Monitor |
|-----|-------|---------------|---------|
| Ball Don't Lie | 600 requests/minute | ~15-20/day | ✅ Under limit |
| Odds API | 500 requests/month | ~60-80/month | ✅ Under limit |
| NBA.com | No official limit | ~40-50/day | Monitor for blocking |
| ESPN | No official limit | ~25-30/day | Monitor for blocking |

### **Resource Management**
- **Cloud Run Timeout**: 5 minutes per scraper
- **Memory**: 512MB standard, 1GB for large files
- **Concurrency**: Max 3 instances per scraper
- **Retry Policy**: 3 attempts with exponential backoff

---

## Monitoring & Validation

### **Health Check Command**
```bash
./bin/monitoring/nba_monitor_scheduler.sh
```

### **Expected Healthy Output**
```
📈 Coverage: 100% - COMPLETE OPERATIONAL COVERAGE
🔗 Business Dependencies
✅ Events → Props: Both scheduled
✅ Player Intelligence: Available
```

### **Critical Alert Conditions**
- Coverage < 100%
- Events → Props dependency broken
- Any critical scraper (Events, Props, Player List, Injury Report) missing
- API rate limit violations

### **Daily Monitoring Schedule**
- **8:30 AM PT**: Verify morning scrapers completed
- **11:30 PM PT**: Full system health check
- **Weekly**: Complete operational review

---

## Scraper Categories

### **🔴 Critical Scrapers (4) - Business Stopping if Missing**
1. **GetOddsApiEvents** - Foundation for all prop betting
2. **GetOddsApiCurrentEventOdds** - Core business revenue source  
3. **GetNbaComPlayerList** - Official player-to-team mapping
4. **GetNbaComInjuryReport** - Player availability for props

### **🟡 High Priority Scrapers (4) - Important Support Functions**
5. **GetDataNbaSeasonSchedule** - Comprehensive game scheduling
6. **GetOddsApiTeamPlayers** - Sportsbook player perspective
7. **BdlActivePlayersScraper** - Player validation (5-6 API requests)
8. **GetEspnTeamRosterAPI** - Trade validation (GSW only for now)

### **🔵 Additional Operational Scrapers (9) - Enhanced Data Collection**
9. **GetNbaComPlayerMovement** - Complete transaction history
10. **GetNbaTeamRoster** - All 30 team rosters (basic format)
11. **GetEspnScoreboard** - Game scores and status validation
12. **GetNbaComScoreboardV2** - Official NBA scores with quarter data
13. **BdlPlayerBoxScoresScraper** - Individual player statistics
14. **BdlBoxScoresScraper** - Team stats with embedded players
15. **GetNbaComPlayerBoxscore** - Official player stats with fantasy points
16. **GetEspnBoxscore** - Alternative boxscore validation  
17. **GetNbaComPlayByPlay** - Detailed play-by-play with coordinates

---

## Change Management Process

### **Schedule Change Workflow**
```
1. Update this document (operational-schedule.md) FIRST
2. Update monitoring script (bin/monitoring/nba_monitor_scheduler.sh)
3. Test changes in development environment
4. Deploy to production via script
5. Verify with monitoring script
6. Update change history in this document
7. Commit changes with descriptive message
```

### **Emergency Procedures**

#### **If Schedulers Are Accidentally Deleted**
```bash
# Immediately restore all missing scrapers
./bin/monitoring/nba_monitor_scheduler.sh schedule-missing

# Verify restoration
./bin/monitoring/nba_monitor_scheduler.sh
```

#### **If Critical Business Scrapers Fail**
```bash
# Re-enable critical scrapers immediately
gcloud scheduler jobs resume nba-odds-events --location=us-west2
gcloud scheduler jobs resume nba-odds-props --location=us-west2  
gcloud scheduler jobs resume nba-player-list --location=us-west2
gcloud scheduler jobs resume nba-injury-report --location=us-west2
```

### **Deployment Commands**
```bash
# Schedule all missing scrapers according to this document
./bin/monitoring/nba_monitor_scheduler.sh schedule-missing

# Verify complete deployment
./bin/monitoring/nba_monitor_scheduler.sh

# Expected result: 17/17 scheduled, 100% coverage
```

---

## Future Expansion Plans

### **Potential Additions**
- **All 30 Teams ESPN Rosters**: Currently only GSW scheduled
- **Historical Props Scrapers**: For research and modeling (manual trigger)
- **Big Data Ball Integration**: Enhanced play-by-play (2-hour delay)
- **Additional Sportsbooks**: Beyond FanDuel/DraftKings

### **Seasonal Adjustments**
- **Playoffs**: May require different frequencies
- **Off-season**: Reduced scheduling needs
- **Draft/Free Agency**: Increased player movement monitoring

### **Performance Optimizations**
- **Smart Scheduling**: Only run game-day scrapers on actual game days
- **Dynamic Frequencies**: Adjust based on trade activity levels
- **Resource Scaling**: Optimize Cloud Run configurations

---

## Change History

### **2025-07-31: Initial Complete Operational Schedule**
- **Status**: 17/17 scrapers scheduled (100% coverage)
- **Achievement**: Complete operational coverage per business requirements
- **Business Impact**: Full prop betting pipeline operational
- **Technical Details**:
  - All critical business scrapers scheduled (Events, Props, Player Intelligence, Injury Report)
  - Complete data validation across multiple sources (BDL, Odds API, NBA.com, ESPN)
  - Proper dependency management (Events → Props timing)
  - Post-game analysis pipeline complete
  - Trade season frequency implemented (every 2 hours vs 4 hours regular season)

### **Template for Future Changes**
```markdown
### **YYYY-MM-DD: Change Description**
- **Status**: X/17 scrapers scheduled (X% coverage)
- **Changes**: 
  - Added: [New scrapers]
  - Modified: [Schedule changes]
  - Removed: [Deprecated scrapers]
- **Business Impact**: [Why this change was made]
- **Technical Details**: [Implementation specifics]
```

---

## Notes

### **Key Success Factors**
1. **Dependencies**: Events → Props timing is critical for business operations
2. **Monitoring**: Regular health checks prevent business disruption
3. **Documentation**: This document drives all scheduling decisions
4. **Testing**: Always test schedule changes before production deployment

### **Contact Information**
- **Primary Maintainer**: [Your name/role]
- **Backup**: [Team member]
- **Emergency Contact**: [On-call information]

### **Related Documents**
- **Implementation**: `bin/monitoring/nba_monitor_scheduler.sh`
- **Detailed Scraper Info**: `docs/scrapers/operational-reference.md`
- **Architecture**: `docs/architecture.md`
- **Troubleshooting**: `docs/troubleshooting.md`

---

**This document is the SINGLE SOURCE OF TRUTH for NBA scraper scheduling. All schedule changes must be made here first, then propagated to implementation.**
