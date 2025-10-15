# NBA Scraper Schedule Management Guide

**Document Purpose**: Comprehensive guide for managing NBA scraper schedules, monitoring operations, and maintaining schedule consistency across the system.

**Last Updated**: July 31, 2025  
**Current Status**: 17/17 Operational Scrapers Scheduled (100% Coverage)

---

## Table of Contents

1. [Current Scraper Schedule](#current-scraper-schedule)
2. [Monitoring Script Usage](#monitoring-script-usage)
3. [Schedule Maintenance Process](#schedule-maintenance-process)
4. [Source of Truth Management](#source-of-truth-management)
5. [Operational Procedures](#operational-procedures)
6. [Troubleshooting](#troubleshooting)

---

## Current Scraper Schedule

### Complete Operational Schedule (17 Scrapers)

#### **Daily Morning Operations (8:00-8:15 AM PT)**
```bash
8:00 AM  - nba-player-movement     (GetNbaComPlayerMovement)
8:00 AM  - nba-season-schedule     (GetDataNbaSeasonSchedule)  
8:00 AM  - nba-odds-team-players   (GetOddsApiTeamPlayers)
8:10 AM  - nba-espn-gsw-roster     (GetEspnTeamRosterAPI)
8:15 AM  - nba-team-roster         (GetNbaTeamRoster)
```

#### **Real-Time Business Operations (Every 2 Hours, 8 AM - 8 PM PT)**
```bash
Every 2 hours: 8,10,12,14,16,18,20
:00 min - nba-odds-events          (GetOddsApiEvents) - MUST RUN FIRST
:00 min - nba-player-list          (GetNbaComPlayerList)
:00 min - nba-injury-report        (GetNbaComInjuryReport)
:05 min - nba-bdl-active-players   (BdlActivePlayersScraper)
:30 min - nba-odds-props           (GetOddsApiCurrentEventOdds) - DEPENDS ON EVENTS
```

#### **Game Day Evening Operations (6 PM, 9 PM, 11 PM PT)**
```bash
6:00 PM, 9:00 PM, 11:00 PM
- nba-espn-scoreboard      (GetEspnScoreboard)
- nba-nbacom-scoreboard    (GetNbaComScoreboardV2)
```

#### **Post-Game Analysis (9:00-9:20 PM PT)**
```bash
9:00 PM  - nba-bdl-player-boxscores    (BdlPlayerBoxScoresScraper)
9:05 PM  - nba-bdl-boxscores           (BdlBoxScoresScraper)
9:10 PM  - nba-nbacom-player-boxscore  (GetNbaComPlayerBoxscore)
9:15 PM  - nba-espn-boxscore           (GetEspnBoxscore)
9:20 PM  - nba-nbacom-playbyplay       (GetNbaComPlayByPlay)
```

### **Critical Dependencies**
- **Events → Props**: `nba-odds-events` MUST complete before `nba-odds-props` runs
- **Player Intelligence**: `nba-player-list` required for prop processing
- **Timing**: Events at :00, Props at :30 (30-minute dependency window)

---

## Monitoring Script Usage

### **Script Location**
```bash
./bin/monitoring/nba_monitor_scheduler.sh
```

### **Core Commands**

#### **1. Check Current Status**
```bash
./bin/monitoring/nba_monitor_scheduler.sh
```
**Output**: Complete analysis of all 17 operational scrapers with current status, coverage percentage, and business readiness.

#### **2. Schedule Missing Scrapers**
```bash
./bin/monitoring/nba_monitor_scheduler.sh schedule-missing
```
**Output**: Automatically schedules any missing scrapers from the operational plan.

#### **3. Help Information**
```bash
./bin/monitoring/nba_monitor_scheduler.sh help
```

### **Key Monitoring Outputs**

#### **Healthy System Status**
```
📈 Coverage: 100% - COMPLETE OPERATIONAL COVERAGE
🔗 Business Dependencies
✅ Events → Props: Both scheduled
✅ Player Intelligence: Available
```

#### **Problem Indicators**
```
📈 Coverage: <100% - PARTIAL/MINIMAL OPERATIONAL COVERAGE
❌ Events → Props: Props scheduled but Events missing - WILL FAIL
❌ Player Intelligence: Missing
```

### **Regular Monitoring Schedule**
- **Daily**: Check status after any schedule changes
- **Weekly**: Verify all 17 scrapers remain scheduled
- **After deployments**: Confirm no schedulers were accidentally deleted
- **Trade season**: Monitor more frequently (higher change rate)

---

## Schedule Maintenance Process

### **When to Update the Schedule**

#### **Business Requirements Change**
- New prop betting markets require additional data
- Different refresh frequencies needed for seasonal changes
- API rate limits require schedule adjustments

#### **Operational Improvements**
- Better dependency timing discovered
- Resource optimization opportunities
- New data sources added

#### **System Changes**
- Cloud Run service updates
- Scraper endpoint modifications
- New scraper classes added

### **How to Update the Schedule**

#### **Step 1: Update Source of Truth**
Update the canonical schedule in `docs/scrapers/operational-schedule.md` (see [Source of Truth Management](#source-of-truth-management))

#### **Step 2: Modify Monitoring Script**
The monitoring script hardcodes scraper definitions. To add/modify scrapers:

**Location**: `bin/monitoring/nba_monitor_scheduler.sh`

**For new scrapers**, add to the appropriate section:

```bash
# In the main() function, add to appropriate category:
echo "18. NewScraperClass (nba-new-scraper)"
status=$(check_job "nba-new-scraper")
if [[ "$status" == "SCHEDULED" ]]; then
    echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Description"
else
    echo -e "   ❌ ${RED}MISSING${NC} - Description"
fi

# In the counting section:
[[ $(check_job "nba-new-scraper") == "SCHEDULED" ]] && ((appropriate_count++))

# In the schedule-missing section:
if [[ $(check_job "nba-new-scraper") == "MISSING" ]]; then
    echo "Scheduling: nba-new-scraper"
    gcloud scheduler jobs create http nba-new-scraper \
        --schedule='CRON_EXPRESSION' \
        --time-zone='America/Los_Angeles' \
        --uri="${SERVICE_URL}?scraper=ENDPOINT_NAME" \
        --http-method=POST \
        --location="$REGION" \
        --description="DESCRIPTION" \
        --quiet
    echo "✅ Scheduled: nba-new-scraper"
    ((scheduled_count++))
fi
```

**For schedule changes**, modify the `--schedule` parameter:
- Use cron format: `'0 8 * * *'` (daily 8 AM)
- Multiple times: `'0 8,12,18 * * *'` (8 AM, 12 PM, 6 PM)
- Every N hours: `'0 */4 * * *'` (every 4 hours)

#### **Step 3: Update Total Count**
If adding/removing scrapers, update the coverage calculation:
```bash
coverage=$(( total_count * 100 / NEW_TOTAL_COUNT ))
```

#### **Step 4: Test Changes**
```bash
# Test script functionality
./bin/monitoring/nba_monitor_scheduler.sh

# If adding new scrapers, test scheduling
./bin/monitoring/nba_monitor_scheduler.sh schedule-missing

# Verify final state
./bin/monitoring/nba_monitor_scheduler.sh
```

#### **Step 5: Delete Old Schedulers** (if removing scrapers)
```bash
# Delete manually if removing scrapers
gcloud scheduler jobs delete OLD_SCRAPER_NAME --location=us-west2 --quiet
```

---

## Source of Truth Management

### **Recommended: Centralized Schedule Document**

#### **Primary Source of Truth Location**
```
docs/scrapers/operational-schedule.md
```

This document should contain:

#### **Master Schedule Definition**
```markdown
# NBA Scraper Operational Schedule - MASTER REFERENCE

## Trade Season Schedule (February - August 1)
### Real-Time Operations (Every 2 Hours, 8 AM - 8 PM PT)
- GetOddsApiEvents: `0 8-20/2 * * *` (nba-odds-events)
- GetOddsApiCurrentEventOdds: `30 8-20/2 * * *` (nba-odds-props)
- GetNbaComPlayerList: `0 */2 * * *` (nba-player-list)
- GetNbaComInjuryReport: `0 */2 * * *` (nba-injury-report)
- BdlActivePlayersScraper: `5 */2 * * *` (nba-bdl-active-players)

### Daily Operations (8 AM PT)
- GetNbaComPlayerMovement: `0 8 * * *` (nba-player-movement)
- GetDataNbaSeasonSchedule: `0 8 * * *` (nba-season-schedule)
- GetOddsApiTeamPlayers: `0 8 * * *` (nba-odds-team-players)
- GetEspnTeamRosterAPI: `10 8 * * *` (nba-espn-gsw-roster)
- GetNbaTeamRoster: `15 8 * * *` (nba-team-roster)

### Game Day Operations (6 PM, 9 PM, 11 PM PT)
- GetEspnScoreboard: `0 18,21,23 * * *` (nba-espn-scoreboard)
- GetNbaComScoreboardV2: `0 18,21,23 * * *` (nba-nbacom-scoreboard)

### Post-Game Analysis (9 PM+ PT)
- BdlPlayerBoxScoresScraper: `0 21 * * *` (nba-bdl-player-boxscores)
- BdlBoxScoresScraper: `5 21 * * *` (nba-bdl-boxscores)
- GetNbaComPlayerBoxscore: `10 21 * * *` (nba-nbacom-player-boxscore)
- GetEspnBoxscore: `15 21 * * *` (nba-espn-boxscore)
- GetNbaComPlayByPlay: `20 21 * * *` (nba-nbacom-playbyplay)

## Regular Season Schedule (August 1 - February)
### Frequency Changes
- Real-time operations: Every 4 hours instead of 2
- All other schedules remain the same

## Business Rules
1. Events API MUST run before Props API (30-minute dependency)
2. Player Intelligence (nba-player-list) required for prop processing
3. All times in America/Los_Angeles timezone
4. Service URL: https://nba-scrapers-756957797294.us-west2.run.app/scrape

## Change Management
- All schedule changes must be updated in this document FIRST
- Then propagated to monitoring script
- Then tested and deployed
- Document change history below

## Change History
- 2025-07-31: Initial complete operational schedule (17 scrapers)
```

### **Secondary Documentation**
- **Monitoring Script**: `bin/monitoring/nba_monitor_scheduler.sh` (implementation)
- **Operational Reference**: `docs/scrapers/operational-reference.md` (detailed scraper info)
- **Architecture Docs**: For context and rationale

### **Version Control Best Practices**
1. **Always update docs first** before changing code
2. **Use descriptive commit messages** for schedule changes
3. **Tag releases** when major schedule changes occur
4. **Document reasoning** for schedule changes in commit messages

### **Schedule Change Workflow**
```
1. Update docs/scrapers/operational-schedule.md
2. Update bin/monitoring/nba_monitor_scheduler.sh  
3. Test changes in development
4. Deploy to production
5. Verify with monitoring script
6. Update change history in documentation
```

---

## Operational Procedures

### **Daily Operations Checklist**

#### **Morning Routine (8:30 AM PT)**
```bash
# Verify morning scrapers completed successfully
gcloud scheduler jobs list --location=us-west2 | grep -E "(player-movement|season-schedule|team-players|roster)"

# Check for any failures
gcloud logging read "resource.type=cloud_scheduler_job AND severity>=ERROR" --limit=10 --freshness=1h
```

#### **Evening Routine (11:30 PM PT)**
```bash
# Verify complete system status
./bin/monitoring/nba_monitor_scheduler.sh

# Should show 100% coverage
# If not, investigate and remediate
```

### **Weekly Operations Review**

#### **Every Monday Morning**
```bash
# Complete system health check
./bin/monitoring/nba_monitor_scheduler.sh

# Review logs for patterns
gcloud logging read "resource.type=cloud_scheduler_job" --limit=50 --freshness=7d

# Verify API usage within limits
# - Ball Don't Lie: <600 requests/day
# - Odds API: <500 requests/month
```

### **Monthly Operations Review**

#### **First Monday of Each Month**
1. **Review schedule effectiveness**
   - Are we collecting the right data at the right frequency?
   - Any API rate limit issues?
   - Any timing conflicts or dependency issues?

2. **Update seasonal schedules**
   - Trade season vs regular season frequency changes
   - Adjust for NBA schedule changes

3. **Documentation maintenance**
   - Update operational-schedule.md if needed
   - Review and update this guide

### **Emergency Procedures**

#### **Scheduler Jobs Accidentally Deleted**
```bash
# Immediately reschedule all missing scrapers
./bin/monitoring/nba_monitor_scheduler.sh schedule-missing

# Verify restoration
./bin/monitoring/nba_monitor_scheduler.sh
```

#### **Critical Business Scrapers Down**
```bash
# Check critical scrapers specifically
gcloud scheduler jobs describe nba-odds-events --location=us-west2
gcloud scheduler jobs describe nba-odds-props --location=us-west2
gcloud scheduler jobs describe nba-player-list --location=us-west2

# If disabled, re-enable immediately
gcloud scheduler jobs resume nba-odds-events --location=us-west2
gcloud scheduler jobs resume nba-odds-props --location=us-west2
gcloud scheduler jobs resume nba-player-list --location=us-west2
```

#### **Mass Scheduler Failure**
```bash
# Check Cloud Scheduler service status
gcloud scheduler locations list

# Re-deploy all schedulers from source of truth
./bin/monitoring/nba_monitor_scheduler.sh schedule-missing
```

---

## Troubleshooting

### **Common Issues**

#### **Script Shows < 100% Coverage**
**Symptoms**: Monitoring script reports missing scrapers
**Resolution**:
```bash
# Identify specific missing scrapers
./bin/monitoring/nba_monitor_scheduler.sh | grep "MISSING"

# Schedule missing ones
./bin/monitoring/nba_monitor_scheduler.sh schedule-missing

# Verify fix
./bin/monitoring/nba_monitor_scheduler.sh
```

#### **Events → Props Dependency Failure**
**Symptoms**: Props API fails because Events API didn't run
**Resolution**:
```bash
# Check Events API status
gcloud scheduler jobs describe nba-odds-events --location=us-west2

# Ensure Events runs at :00 and Props at :30
# Current schedule should show:
# Events: "0 8-20/2 * * *"  
# Props:  "30 8-20/2 * * *"
```

#### **Monitoring Script Syntax Errors**
**Symptoms**: Script fails with "syntax error near unexpected token"
**Resolution**: The script has been debugged and should work. If errors occur:
1. Check for duplicate functions or case statements
2. Verify all `if` statements have matching `fi`
3. Ensure all `case` statements have proper `;;` endings
4. Use the clean version provided in this guide

#### **Wrong Scraper Count in Coverage**
**Symptoms**: Coverage percentage seems wrong
**Resolution**: Verify the total count in the script matches actual operational scrapers:
```bash
# Should be 17 total operational scrapers
coverage=$(( total_count * 100 / 17 ))
```

### **Debugging Commands**

#### **Check Individual Scheduler Status**
```bash
gcloud scheduler jobs describe SCRAPER_NAME --location=us-west2
```

#### **View Recent Scheduler Logs**
```bash
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=SCRAPER_NAME" --limit=10
```

#### **List All Current Schedulers**
```bash
gcloud scheduler jobs list --location=us-west2 --format="table(name,schedule,state)"
```

#### **Test Script Functions**
```bash
# Test just the monitoring without scheduling
./bin/monitoring/nba_monitor_scheduler.sh | head -50

# Test the help function
./bin/monitoring/nba_monitor_scheduler.sh help
```

### **Performance Monitoring**

#### **API Usage Tracking**
- **Ball Don't Lie**: Monitor via dashboard or logs (600/minute limit)
- **Odds API**: Track monthly usage (500/month limit)
- **NBA.com/ESPN**: No official limits, but monitor for blocking

#### **Scheduler Success Rates**
```bash
# Check success rate over last week
gcloud logging read "resource.type=cloud_scheduler_job AND (severity=ERROR OR textPayload:success)" --freshness=7d
```

#### **Data Collection Verification**
- Monitor GCS bucket for expected file creation
- Verify file sizes and timestamps match schedule
- Check for missing data patterns

---

## Conclusion

This schedule management system provides:
- **Centralized source of truth** in documentation
- **Automated monitoring and scheduling** via shell script  
- **Complete operational coverage** of all business-critical scrapers
- **Maintainable process** for schedule changes and updates

**Key Success Factors**:
1. **Always update documentation first** before changing schedules
2. **Test changes thoroughly** before production deployment
3. **Monitor regularly** to catch issues early
4. **Maintain dependencies** (especially Events → Props timing)

**Next Steps**:
1. Set up monitoring alerts for scheduler failures
2. Create automated tests for schedule validation
3. Consider migrating to Infrastructure as Code (Terraform) for scheduler management
4. Implement data quality monitoring downstream

This system now provides enterprise-grade NBA data collection with 100% operational coverage according to your business requirements.
