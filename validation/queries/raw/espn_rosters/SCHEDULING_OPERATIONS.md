# ESPN Team Rosters - Scheduling & Operations Guide

**File: validation/queries/raw/espn_rosters/SCHEDULING_OPERATIONS.md**

**Purpose:** Comprehensive guide for running ESPN roster validation queries on a schedule during NBA season

**Last Updated:** October 13, 2025  
**Status:** Production Ready - Awaiting Season Start

---

## 📅 Daily Schedule Overview

ESPN roster validation runs **every day during NBA season** to ensure data collection is working properly as a backup to NBA.com Player List.

### Timeline

```
8:00 AM PT  - ESPN Scraper runs (espn_team_roster.py)
8:30 AM PT  - Processor runs (EspnTeamRosterProcessor)
9:00 AM PT  - Data available in BigQuery
10:00 AM PT - Validation queries run ← YOU ARE HERE
```

---

## 🔄 Query Execution Schedule

### Priority 1: Critical Daily Queries (Run Every Day)

#### 1. Daily Freshness Check
**Query:** `daily_freshness_check.sql`  
**Schedule:** Every day at **10:00 AM PT**  
**Purpose:** Verify yesterday's roster data was collected  
**Alert On:** Status != "✅ Complete"

```bash
# Run command
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/daily_freshness_check.sql

# Expected output (successful day)
# status: "✅ Complete: All 30 teams with roster data"
# teams_with_data: 30
# unique_players: 500-650

# Alert conditions
# 🔴 CRITICAL: teams_with_data = 0
# 🟡 WARNING: teams_with_data < 30
# ⚠️  WARNING: unique_players < 450
```

**What to check if alert fires:**
1. Did scraper run? Check GCS: `gs://nba-scraped-data/espn/rosters/YYYY-MM-DD/`
2. Did processor run? Check Cloud Run logs: `espn-team-roster-processor-backfill`
3. Are there errors in processor logs?

---

#### 2. Team Coverage Check
**Query:** `team_coverage_check.sql`  
**Schedule:** Every day at **10:05 AM PT** (5 minutes after freshness check)  
**Purpose:** Verify all 30 teams have roster data  
**Alert On:** Any team with status != "✅ Normal"

```bash
# Run command
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/team_coverage_check.sql

# Expected output
# Teams Found: 30/30 ✅ Complete
# All teams: player_count between 15-23

# Alert conditions
# 🔴 CRITICAL: player_count < 15 for any team
# 🟡 WARNING: player_count > 23 for any team
```

**What to check if alert fires:**
1. Team with <15 players: Check for mass injuries or data collection issue
2. Team with >23 players: Training camp invites (normal in preseason)
3. Missing teams: Check scraper logs for that specific team

---

### Priority 2: Weekly Validation Queries (Run Weekly)

#### 3. Cross-Validation with NBA.com
**Query:** `cross_validate_with_nbac.sql`  
**Schedule:** Every **Monday at 10:00 AM PT**  
**Purpose:** Compare ESPN rosters with NBA.com (primary source)  
**Alert On:** Match rate < 80%

```bash
# Run command
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/cross_validate_with_nbac.sql

# Expected output
# Perfect Matches: 83-85%
# Team Mismatches: <5%
# Only in ESPN / Only in NBA.com: ~7-8% each (suffix normalization)

# Alert conditions
# 🔴 CRITICAL: match rate < 70%
# 🟡 WARNING: match rate < 80%
# ⚠️  REVIEW: team_mismatch count > 10 (possible trades)
```

**What to check if alert fires:**
1. Large drop in match rate: Compare timestamps of ESPN vs NBA.com data
2. Many team mismatches: Check NBA.com Player Movement table for recent trades
3. New players appearing: Recent signings or call-ups

**Known Issue:** Players with Jr./II/III suffixes may appear in both "ESPN only" and "NBA.com only" lists. This is expected due to different name normalization approaches.

---

### Priority 3: Ad-Hoc Analysis (Run As Needed)

#### 4. Player Count Distribution
**Query:** `player_count_distribution.sql`  
**Schedule:** As needed (not automated)  
**Purpose:** Understand roster size patterns  
**Use When:** Investigating unusual team player counts

```bash
# Run command
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/player_count_distribution.sql

# Typical results
# 18-21 players: 80-90% of teams (normal)
# 17 players: 3-7% of teams (minimal roster)
# 22-23 players: 7-13% of teams (training camp, two-way contracts)
```

---

## 🚨 Alert Thresholds & Actions

### Critical Alerts (Immediate Action Required)

| Condition | Severity | Action | Timeline |
|-----------|----------|--------|----------|
| No data collected | 🔴 CRITICAL | Check scraper/processor immediately | 15 min |
| teams_with_data = 0 | 🔴 CRITICAL | Verify GCS files exist | 15 min |
| Match rate < 70% | 🔴 CRITICAL | Compare data sources, check for corruption | 30 min |
| Team player_count < 15 | 🔴 CRITICAL | Verify against NBA.com, may be data error | 30 min |

### Warning Alerts (Action Within Hours)

| Condition | Severity | Action | Timeline |
|-----------|----------|--------|----------|
| teams_with_data < 30 | 🟡 WARNING | Check missing teams, re-run scraper if needed | 2 hours |
| unique_players < 450 | 🟡 WARNING | Investigate low player counts | 2 hours |
| Match rate < 80% | 🟡 WARNING | Review discrepancies, document if legitimate | 4 hours |
| Team player_count > 23 | 🟡 WARNING | Normal in preseason, verify in regular season | 4 hours |

### Review Alerts (Action Within Day)

| Condition | Severity | Action | Timeline |
|-----------|----------|--------|----------|
| Team mismatches > 10 | ⚠️  REVIEW | Check recent trades, update if needed | 1 day |
| New players in ESPN only | ⚠️  REVIEW | Verify recent signings | 1 day |

---

## 🤖 Automation Setup

### Option 1: Cloud Scheduler + Cloud Functions (Recommended)

Create scheduled Cloud Functions to run queries automatically:

```yaml
# Daily freshness check
name: espn-rosters-daily-freshness
schedule: "0 10 * * *"  # 10 AM daily
timezone: America/Los_Angeles
target: 
  function: run-bq-validation-query
  data:
    query_file: validation/queries/raw/espn_rosters/daily_freshness_check.sql
    alert_channel: slack-nba-data-alerts

# Weekly cross-validation
name: espn-rosters-weekly-validation
schedule: "0 10 * * 1"  # 10 AM Mondays
timezone: America/Los_Angeles
target:
  function: run-bq-validation-query
  data:
    query_file: validation/queries/raw/espn_rosters/cross_validate_with_nbac.sql
    alert_channel: slack-nba-data-alerts
```

### Option 2: Cron Job on VM/Local Machine

Add to crontab:

```bash
# Edit crontab
crontab -e

# Daily freshness check (10 AM PT = 5 PM UTC)
0 17 * * * cd /path/to/nba-stats-scraper && bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/daily_freshness_check.sql >> logs/espn_rosters_validation.log 2>&1

# Weekly cross-validation (Monday 10 AM PT = Monday 5 PM UTC)
0 17 * * 1 cd /path/to/nba-stats-scraper && bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/cross_validate_with_nbac.sql >> logs/espn_rosters_validation_weekly.log 2>&1
```

### Option 3: Manual Execution (Development/Testing)

```bash
#!/bin/bash
# File: scripts/validate_espn_rosters.sh

echo "=== ESPN Rosters Daily Validation ==="
echo "Started: $(date)"

cd /path/to/nba-stats-scraper

echo ""
echo "1. Running daily freshness check..."
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/daily_freshness_check.sql

echo ""
echo "2. Running team coverage check..."
bq query --use_legacy_sql=false < validation/queries/raw/espn_rosters/team_coverage_check.sql

echo ""
echo "Completed: $(date)"
```

---

## 📊 Monitoring Dashboard (Future Enhancement)

Consider creating a dashboard that tracks:

1. **Daily Metrics**
   - Teams collected (target: 30)
   - Players collected (target: 500-650)
   - Collection time (target: <30 min)
   - Data freshness (hours since last update)

2. **Weekly Metrics**
   - Match rate with NBA.com (target: >80%)
   - Team mismatches (target: <10)
   - New player discoveries
   - Data quality score

3. **Historical Trends**
   - Collection success rate over time
   - Average players per team by week
   - Match rate trends
   - Alert frequency

---

## 🔍 Troubleshooting Guide

### Scenario 1: No Data Collected Yesterday

**Symptoms:**
```
status: "🔴 CRITICAL: No roster data collected"
teams_with_data: 0
```

**Investigation Steps:**
1. Check if scraper ran:
   ```bash
   gsutil ls gs://nba-scraped-data/espn/rosters/$(date -d yesterday +%Y-%m-%d)/
   ```

2. Check scraper logs (if no GCS files):
   ```bash
   # Check Cloud Scheduler logs
   gcloud scheduler jobs describe espn-team-roster-scraper --location=us-west2
   ```

3. Check processor logs (if GCS files exist):
   ```bash
   gcloud run jobs executions list --job=espn-team-roster-processor-backfill --region=us-west2 --limit=5
   ```

**Resolution:**
- If scraper didn't run: Manually trigger scraper
- If processor didn't run: Manually trigger processor with yesterday's date
- If both ran but no data: Check for ESPN API changes or rate limiting

---

### Scenario 2: Missing Teams

**Symptoms:**
```
status: "🟡 WARNING: Only 28/30 teams"
Missing: SAC, POR
```

**Investigation Steps:**
1. Check which teams are missing:
   ```sql
   -- Find missing teams
   WITH all_teams AS (
     SELECT team_abbr FROM UNNEST(['ATL','BKN','BOS','CHA','CHI','CLE','DAL','DEN','DET','GSW','HOU','IND','LAC','LAL','MEM','MIA','MIL','MIN','NOP','NYK','OKC','ORL','PHI','PHX','POR','SAC','SAS','TOR','UTA','WAS']) as team_abbr
   )
   SELECT a.team_abbr as missing_team
   FROM all_teams a
   LEFT JOIN (
     SELECT DISTINCT team_abbr 
     FROM `nba-props-platform.nba_raw.espn_team_rosters`
     WHERE roster_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
   ) e ON a.team_abbr = e.team_abbr
   WHERE e.team_abbr IS NULL;
   ```

2. Check GCS for missing teams:
   ```bash
   gsutil ls gs://nba-scraped-data/espn/rosters/$(date -d yesterday +%Y-%m-%d)/team_*/
   ```

**Resolution:**
- Re-run scraper for missing teams specifically
- Check if ESPN changed team URLs or structure
- Verify team mapping in `shared/utils/nba_team_mapper.py`

---

### Scenario 3: Low Match Rate with NBA.com

**Symptoms:**
```
Perfect Matches: 65.0% (expected: 83-85%)
Team Mismatches: 15% (expected: <5%)
```

**Investigation Steps:**
1. Check data timestamps:
   ```sql
   SELECT 
     'ESPN' as source,
     MAX(roster_date) as latest_date,
     MAX(processed_at) as latest_processing
   FROM `nba-props-platform.nba_raw.espn_team_rosters`
   UNION ALL
   SELECT
     'NBA.com' as source,
     MAX(last_seen_date) as latest_date,
     MAX(processed_at) as latest_processing  
   FROM `nba-props-platform.nba_raw.nbac_player_list_current`;
   ```

2. Check for recent trades:
   ```sql
   SELECT player_full_name, transaction_type, team_abbr, transaction_date
   FROM `nba-props-platform.nba_raw.nbac_player_movement`
   WHERE transaction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   ORDER BY transaction_date DESC;
   ```

**Resolution:**
- If timing difference: Wait for both sources to sync
- If trade activity: Document as expected, verify both sources updated
- If data quality issue: Compare against third source (Ball Don't Lie)

---

### Scenario 4: Suspiciously Low Player Count

**Symptoms:**
```
Team: POR
player_count: 12
status: "🔴 CRITICAL: Too few players"
```

**Investigation Steps:**
1. Cross-check with NBA.com:
   ```sql
   SELECT COUNT(*) as nbac_player_count
   FROM `nba-props-platform.nba_raw.nbac_player_list_current`
   WHERE team_abbr = 'POR' AND is_active = TRUE;
   ```

2. Check for recent roster moves:
   ```sql
   SELECT * FROM `nba-props-platform.nba_raw.nbac_player_movement`
   WHERE team_abbr = 'POR' 
     AND transaction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
   ORDER BY transaction_date DESC;
   ```

**Resolution:**
- If NBA.com also shows low count: Legitimate (injuries, trades)
- If ESPN only: Partial scrape failure, re-run for this team
- Document if legitimate roster situation

---

## 📅 Season Start Checklist

Before NBA season starts (October 2025):

### Week Before Season

- [ ] Test all 4 validation queries manually
- [ ] Verify partition filters work (roster_date >= '2025-01-01')
- [ ] Set up Cloud Scheduler jobs OR cron jobs
- [ ] Configure Slack/email alerts for critical failures
- [ ] Document on-call procedures for validation alerts
- [ ] Test manual re-run procedures for scraper/processor

### First Day of Season

- [ ] Monitor validation queries closely (run manually if needed)
- [ ] Verify all 30 teams collected
- [ ] Check player counts are reasonable (450-650 total)
- [ ] Cross-validate with NBA.com Player List
- [ ] Document any unexpected issues
- [ ] Adjust alert thresholds if needed

### First Week of Season

- [ ] Review daily validation results
- [ ] Fine-tune alert thresholds based on actual data patterns
- [ ] Document any false positives/negatives
- [ ] Optimize query performance if needed
- [ ] Create dashboard for monitoring (optional)

---

## 🔗 Integration with Existing Workflows

ESPN rosters validation integrates with:

### 1. Morning Operations (8 AM PT)
```
08:00 - ESPN Scraper runs
08:30 - ESPN Processor runs
09:00 - Data available
10:00 - ESPN Rosters validation (THIS)
10:15 - Compare with NBA.com Player List validation
10:30 - Overall roster status report
```

### 2. Other Roster Validations
- **NBA.com Player List** (primary source)
- **Ball Don't Lie Active Players** (secondary validation)
- **Basketball Reference Rosters** (historical context)

Run ESPN validation in sequence after primary sources:
1. NBA.com Player List validation
2. ESPN Rosters validation (backup)
3. Ball Don't Lie validation (cross-check)
4. Generate consolidated roster status report

### 3. Alert Integration
```yaml
# Example Slack alert payload
channel: "#nba-data-alerts"
alert_level: "critical"
source: "ESPN Rosters Validation"
query: "daily_freshness_check"
status: "🔴 CRITICAL: No roster data collected"
details:
  check_date: "2025-10-22"
  teams_with_data: 0
  expected_teams: 30
action_required: "Check scraper logs and GCS bucket"
```

---

## 📝 Query Maintenance

### When to Update Queries

1. **Season Start:** Update partition filter dates
   ```sql
   -- Change from:
   WHERE roster_date >= '2025-01-01'
   
   -- To (for 2025-26 season):
   WHERE roster_date >= '2025-10-01'
   ```

2. **Schema Changes:** If ESPN processor adds/changes fields
   - Review processor code changes
   - Update queries to use new field names
   - Test queries before deploying to production

3. **Business Logic Changes:** If validation rules change
   - Update alert thresholds in queries
   - Document reasons for changes
   - Test new thresholds with historical data

### Query Performance Optimization

Current query performance (as of Oct 2025):
- `daily_freshness_check.sql`: <5 seconds
- `team_coverage_check.sql`: <5 seconds  
- `cross_validate_with_nbac.sql`: ~10 seconds
- `player_count_distribution.sql`: <5 seconds

If performance degrades:
1. Verify partition filters are present
2. Check BigQuery execution plan
3. Consider materializing intermediate results
4. Add clustering if table grows large

---

## 🎯 Success Metrics

Track these KPIs for ESPN rosters validation:

### Daily Metrics
- ✅ Collection success rate (target: >95%)
- ✅ Teams collected (target: 30/30)
- ✅ Player count range (target: 500-650)
- ✅ Validation query execution time (target: <30 sec total)

### Weekly Metrics
- ✅ Match rate with NBA.com (target: >80%)
- ✅ False positive rate (target: <5%)
- ✅ Alert response time (target: <30 min for critical)

### Monthly Metrics
- ✅ Data quality score (composite metric)
- ✅ System uptime (target: >99%)
- ✅ Issue resolution rate (target: 100% within SLA)

---

## 📞 Support & Escalation

### On-Call Responsibilities

**Primary:** NBA Data Engineer
- Monitor validation alerts during business hours
- Investigate and resolve critical alerts within 30 minutes
- Document issues and resolutions

**Secondary:** Platform Team
- Handle off-hours critical alerts
- Escalate to primary if needed
- Ensure system availability

### Escalation Path

1. **Level 1:** Data Engineer (respond within 30 min)
2. **Level 2:** Senior Data Engineer (respond within 1 hour)
3. **Level 3:** Engineering Manager (respond within 2 hours)

---

**Last Updated:** October 13, 2025  
**Next Review:** Start of 2025-26 NBA Season  
**Owner:** NBA Props Platform Data Team
