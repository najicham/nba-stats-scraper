# NBA.com Player List - Daily Monitoring Guide

**File:** `validation/queries/raw/nbac_player_list/DAILY_MONITORING_GUIDE.md`

**Purpose:** Production monitoring for NBA.com Player List during the NBA season  
**Season Start:** October 22, 2025  
**Monitoring Hours:** Daily at 9:00 AM Pacific (after scraper/processor complete)

---

## Quick Start

```bash
# Every morning at 9 AM Pacific
cd ~/code/nba-stats-scraper
./scripts/validate-player-list daily
```

**Expected Result:**
```
✅ All systems operational
```

**Alert Thresholds:**
- 🔴 Last update > 36 hours → CRITICAL
- 🔴 Teams ≠ 30 → CRITICAL
- 🟡 Last update 24-36 hours → WARNING
- 🟡 Active players < 390 or > 550 → WARNING

---

## Daily Monitoring Schedule

### Morning Check (9:00 AM PT) - MANDATORY

**Command:**
```bash
./scripts/validate-player-list daily
```

**What it checks:**
1. ✅ Data updated in last 24 hours
2. ✅ All 30 teams present
3. ✅ Active player count: 390-550 (normal range)
4. ✅ No NULL team assignments
5. ✅ Current season year correct

**Time Required:** 30 seconds

**Response Required:**
- ✅ Green status → No action needed
- 🟡 Yellow status → Investigate within 2 hours
- 🔴 Red status → Immediate action required

---

### Weekly Deep Check (Monday 9:00 AM PT)

**Command:**
```bash
./scripts/validate-player-list all
```

**What it checks:**
1. Data freshness (same as daily)
2. Team completeness and balance
3. Data quality (duplicates, NULLs, invalid data)
4. Cross-validation with Ball Don't Lie
5. Player distribution analysis

**Time Required:** 2-3 minutes

**When to Run:**
- Every Monday morning
- After major trade deadline (Feb 8, 2026)
- After roster cuts (preseason → regular season)
- When investigating daily check warnings

---

## Alert Response Playbook

### 🔴 CRITICAL: Last Update > 36 Hours

**Symptom:**
```
Last Update: 2025-10-15  2 days ago  🔴 CRITICAL: Not updating
```

**Root Causes:**
1. Scraper not running
2. Processor failed
3. GCS permissions issue
4. BigQuery write failure

**Investigation Steps:**
```bash
# 1. Check if scraper ran
gsutil ls gs://nba-scraped-data/nba-com/player-list/$(date -u +%Y-%m-%d)/ | tail -5

# 2. Check processor logs
gcloud run jobs executions list --job=nbac-player-list-processor --region=us-west2 --limit=5

# 3. Check for recent errors
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=nbac-player-list-processor" --limit=20 --format=json
```

**Resolution:**
- If scraper missing: Trigger manual run
- If processor failed: Check logs and re-run
- If GCS issue: Verify bucket permissions
- If BigQuery issue: Check table access

**After Fix:**
```bash
# Verify data updated
./scripts/validate-player-list daily
```

---

### 🔴 CRITICAL: Missing Teams

**Symptom:**
```
Teams: 28 of 30  🔴 CRITICAL: Missing teams
```

**Root Causes:**
1. Scraper didn't collect all teams
2. Team abbreviation mapping issue
3. Partial processor failure
4. Data corruption

**Investigation Steps:**
```bash
# Which teams are missing?
./scripts/validate-player-list teams

# Check raw scraped data
gsutil cat gs://nba-scraped-data/nba-com/player-list/$(date -u +%Y-%m-%d)/$(date -u +%Y-%m-%d)*.json | jq '.data | length'

# Verify all 30 teams in source
gsutil cat gs://nba-scraped-data/nba-com/player-list/$(date -u +%Y-%m-%d)/$(date -u +%Y-%m-%d)*.json | jq '[.data[].team_abbr] | unique | length'
```

**Resolution:**
- If missing from scraper: Re-run scraper
- If mapping issue: Fix NBATeamMapper
- If processor issue: Re-process file
- If data corruption: Investigate and restore

---

### 🔴 CRITICAL: Duplicate player_lookup

**Symptom:**
```
Duplicate player_lookup: 5  🔴 CRITICAL: Primary key violation
```

**Root Causes:**
1. Processor deduplication logic broken
2. Multiple processor runs without cleanup
3. Name normalization bug

**Investigation Steps:**
```bash
# Find duplicates
./scripts/validate-player-list quality

# Get specific duplicate players
bq query --use_legacy_sql=false "
SELECT player_lookup, COUNT(*) as count, STRING_AGG(team_abbr) as teams
FROM \`nba-props-platform.nba_raw.nbac_player_list_current\`
WHERE season_year >= 2024
GROUP BY player_lookup
HAVING COUNT(*) > 1
ORDER BY count DESC
"
```

**Resolution:**
- **CRITICAL:** This breaks primary key integrity
- Stop processor immediately
- Fix deduplication logic
- Clear table and reprocess
- Verify fix before resuming

---

### 🟡 WARNING: Stale Data (24-36 hours)

**Symptom:**
```
Last Update: 2025-10-15  1 day ago  ⚠️ Stale (check scraper)
```

**Root Causes:**
1. Scraper delayed
2. Processor queue backed up
3. Off day (no games = no trigger)
4. Manual pause

**Investigation Steps:**
```bash
# Check if yesterday had games
bq query --use_legacy_sql=false "
SELECT COUNT(*) as games
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
"

# If no games, this is expected
# If games exist, check scraper
```

**Resolution:**
- If no games: Expected, monitor tomorrow
- If games exist: Investigate scraper/processor
- If weekend: Check if scheduled
- If holidays: Verify schedule

---

### 🟡 WARNING: Unusual Player Count

**Symptom:**
```
Active Players: 620  ⚠️ WARNING: High player count
```

**Root Causes:**
1. Two-way contracts included
2. Hardship exceptions active
3. Preseason roster sizes
4. Data quality issue

**Investigation Steps:**
```bash
# Check player distribution
./scripts/validate-player-list teams

# See which teams have extra players
bq query --use_legacy_sql=false "
SELECT team_abbr, COUNT(*) as players
FROM \`nba-props-platform.nba_raw.nbac_player_list_current\`
WHERE season_year >= 2024 AND is_active = TRUE
GROUP BY team_abbr
ORDER BY players DESC
LIMIT 10
"
```

**Resolution:**
- If preseason: Normal, monitor for roster cuts
- If hardship: Verify against NBA.com announcements
- If data issue: Investigate player_lookup duplicates
- If unexplained: Cross-check with Ball Don't Lie

---

## Monitoring Metrics

### Key Performance Indicators (KPIs)

**Data Freshness:**
- Target: < 12 hours
- Warning: 24 hours
- Critical: 36 hours

**Data Completeness:**
- Target: 30/30 teams, 100%
- Critical: < 30 teams

**Data Quality:**
- Target: 0 duplicates, 0 critical NULLs
- Critical: > 0 duplicates

**Cross-Validation:**
- Target: 60-70% overlap with BDL
- Warning: < 50% overlap

### Historical Tracking

**Weekly Metrics to Track:**
```bash
# Export weekly
./scripts/validate-player-list daily --table nba_processing.player_list_weekly_$(date +%Y%m%d)
```

**Track over time:**
- Average update lag (hours)
- Player count trends
- Team roster size variance
- Data quality issues per week

---

## Automated Monitoring Setup

### Option 1: Cron Job (Recommended)

```bash
# Edit crontab
crontab -e

# Add daily check at 9 AM Pacific (5 PM UTC)
0 17 * * * cd /path/to/nba-stats-scraper && ./scripts/validate-player-list daily >> /var/log/player_list_daily.log 2>&1

# Add weekly check on Mondays at 9 AM Pacific
0 17 * * 1 cd /path/to/nba-stats-scraper && ./scripts/validate-player-list all >> /var/log/player_list_weekly.log 2>&1
```

**Alert Setup:**
```bash
# Create alert script
cat > scripts/alert-on-failure.sh << 'EOF'
#!/bin/bash
OUTPUT=$(./scripts/validate-player-list daily)
if echo "$OUTPUT" | grep -q "🔴"; then
    echo "$OUTPUT" | mail -s "CRITICAL: Player List Validation Failed" your-email@example.com
fi
EOF

chmod +x scripts/alert-on-failure.sh

# Update crontab to use alert script
0 17 * * * cd /path/to/nba-stats-scraper && ./scripts/alert-on-failure.sh
```

---

### Option 2: Cloud Scheduler + Cloud Functions

```yaml
# cloud-scheduler-config.yaml
name: player-list-daily-validation
schedule: "0 17 * * *"  # 9 AM Pacific daily
timeZone: America/Los_Angeles
target:
  httpTarget:
    uri: https://YOUR-CLOUD-FUNCTION-URL
    httpMethod: POST
```

---

### Option 3: GitHub Actions

```yaml
# .github/workflows/player-list-validation.yml
name: Daily Player List Validation

on:
  schedule:
    - cron: '0 17 * * *'  # 9 AM Pacific (5 PM UTC)
  workflow_dispatch:

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v1
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      
      - name: Run validation
        run: ./scripts/validate-player-list daily
      
      - name: Alert on failure
        if: failure()
        uses: actions/github-script@v6
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: 'CRITICAL: Player List Validation Failed',
              body: 'Daily validation check failed. Check workflow logs.'
            })
```

---

## Special Monitoring Periods

### Preseason (October 1-21)
**Frequency:** Weekly  
**Expected:** Larger rosters (18-21 per team)  
**Monitor:** Roster cuts before season opener

### Regular Season (October 22 - April 13)
**Frequency:** Daily at 9 AM  
**Expected:** 13-17 players per team  
**Monitor:** Trades, injuries, signings

### Trade Deadline Week (February 3-8, 2026)
**Frequency:** 3x daily (9 AM, 3 PM, 9 PM)  
**Expected:** Rapid roster changes  
**Monitor:** Team mismatches with BDL, player movements

### Playoffs (April 14 - June 18)
**Frequency:** Daily at 9 AM  
**Expected:** Stable rosters (16 teams)  
**Monitor:** Hardship exceptions, injuries

### Offseason (June 19 - September 30)
**Frequency:** Weekly  
**Expected:** Major roster turnover  
**Monitor:** Free agency, draft picks, trades

---

## Escalation Path

### Level 1: Automated Alert (0-5 minutes)
- Cron job detects failure
- Alert sent via email/Slack
- Ticket created in tracking system

### Level 2: On-Call Engineer (5-30 minutes)
- Investigate root cause using playbook
- Check scraper/processor logs
- Attempt automatic remediation

### Level 3: Data Team (30 minutes - 2 hours)
- Manual investigation if automation fails
- Check data source (NBA.com)
- Coordinate with infrastructure team

### Level 4: Engineering Lead (2+ hours)
- Major system failure
- Coordinate cross-team response
- Implement hotfix if needed

---

## Communication Templates

### Daily Check - All Green
```
✅ Player List Validation: PASSED
Date: 2025-10-22
Last Update: 2025-10-22 (5 hours ago)
Teams: 30/30
Active Players: 456
Status: All systems operational
```

### Daily Check - Warning
```
⚠️ Player List Validation: WARNING
Date: 2025-10-22
Issue: Data last updated 28 hours ago
Impact: Low - data is stale but complete
Action: Monitoring - investigating scraper schedule
ETA: Next update expected by 12 PM
```

### Daily Check - Critical
```
🔴 Player List Validation: CRITICAL
Date: 2025-10-22
Issue: Missing 2 teams (GSW, LAL)
Impact: High - incomplete data affecting prop generation
Action: Emergency - manual scraper triggered
ETA: Resolution within 1 hour
Ticket: #12345
```

---

## Season Preparation Checklist

### Before Season Starts (by October 21, 2025)

- [ ] Verify scraper scheduled for daily runs
- [ ] Test processor handles roster cuts
- [ ] Confirm alert system configured
- [ ] Set up monitoring dashboard
- [ ] Document on-call rotation
- [ ] Test escalation procedures
- [ ] Verify CLI tool working
- [ ] Baseline "normal" metrics established
- [ ] Cross-validation with BDL tested
- [ ] Backup/recovery procedures documented

### Season Opener Day (October 22, 2025)

- [ ] Run morning validation (6 AM, 9 AM, 12 PM)
- [ ] Verify rosters reflect cuts from preseason
- [ ] Check player counts normalized (13-17 per team)
- [ ] Confirm BDL cross-validation working
- [ ] Monitor for any scraper issues
- [ ] Document any anomalies

### First Week of Season (October 22-28)

- [ ] Daily validation at 9 AM
- [ ] Monitor for early season trades
- [ ] Track data freshness metrics
- [ ] Verify alert system triggering correctly
- [ ] Review and adjust thresholds if needed
- [ ] Document any false positives

---

## Continuous Improvement

### Monthly Review
- Analyze failure patterns
- Adjust alert thresholds
- Update playbooks based on new issues
- Review escalation effectiveness

### Quarterly Review
- Update documentation
- Refine automation
- Train new team members
- Review KPI targets

---

## Contact Information

**Primary:** Data Engineering Team  
**On-Call:** [Rotation Schedule]  
**Escalation:** Engineering Lead  
**Documentation:** This guide + README.md

---

## Quick Reference Commands

```bash
# Daily check
./scripts/validate-player-list daily

# Full validation
./scripts/validate-player-list all

# Specific checks
./scripts/validate-player-list freshness
./scripts/validate-player-list teams
./scripts/validate-player-list quality
./scripts/validate-player-list bdl-comparison

# Export results
./scripts/validate-player-list daily --csv > daily_check.csv
./scripts/validate-player-list all --table nba_processing.player_list_validation_$(date +%Y%m%d)

# Check scraper ran today
gsutil ls gs://nba-scraped-data/nba-com/player-list/$(date -u +%Y-%m-%d)/

# Check processor logs
gcloud run jobs executions list --job=nbac-player-list-processor --region=us-west2 --limit=5

# Manual processor trigger
gcloud run jobs execute nbac-player-list-processor --region=us-west2
```

---

**Last Updated:** October 13, 2025  
**Next Review:** October 22, 2025 (season opener)  
**Version:** 1.0