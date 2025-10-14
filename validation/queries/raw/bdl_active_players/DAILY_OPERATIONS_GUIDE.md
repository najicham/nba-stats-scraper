# BDL Active Players - Daily Operations Guide

**File:** `validation/queries/raw/bdl_active_players/DAILY_OPERATIONS_GUIDE.md`

**Purpose:** Operational playbook for using BDL Active Players validation in production during NBA season

**Last Updated:** October 14, 2025

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Daily Schedule & Pipeline](#daily-schedule)
3. [Morning Validation Workflow](#morning-workflow)
4. [Alert Response Procedures](#alert-response)
5. [Automation Setup](#automation)
6. [Integration with Data Pipeline](#pipeline-integration)
7. [Season-Specific Considerations](#season-considerations)
8. [Troubleshooting Common Issues](#troubleshooting)
9. [Escalation Procedures](#escalation)

---

## 🎯 Overview {#overview}

### Purpose

This guide describes how to integrate BDL Active Players validation into your daily operations when scrapers and processors run automatically during the NBA season.

### Daily Operations Goals

1. **Ensure data freshness** - Validate scrapers ran successfully
2. **Verify data quality** - Check for duplicates, missing teams, validation issues
3. **Monitor validation rates** - Track G-League assignments and trade timing
4. **Quick issue detection** - Catch problems before they impact props
5. **Minimal time investment** - 5-10 minutes daily monitoring

### When to Use This Guide

- **Regular Season:** October - April (daily operations)
- **Playoffs:** April - June (increased monitoring)
- **Off-Season:** June - September (reduced frequency)
- **Preseason:** September - October (resume daily checks)

---

## ⏰ Daily Schedule & Pipeline {#daily-schedule}

### Typical Daily Pipeline (During Season)

```
TIME              | COMPONENT                    | ACTION
------------------|------------------------------|----------------------------------
12:00 AM - 2:00 AM | Games finish                | Last games of night complete
2:00 AM - 3:00 AM  | BDL API updates             | Ball Don't Lie updates rosters
3:00 AM - 4:00 AM  | Scraper runs                | bdl_active_players scraper
4:00 AM - 5:00 AM  | Processor runs              | BdlActivePlayersProcessor
5:00 AM - 6:00 AM  | Data available              | BigQuery table updated
8:00 AM - 9:00 AM  | ✅ VALIDATION RUNS          | Morning validation check
9:00 AM - 10:00 AM | Review & action             | Human review of alerts
```

### Validation Integration Points

**Point 1: Post-Processor (Automated)**
- **When:** Immediately after processor completes (5-6 AM)
- **What:** Automated validation check
- **Action:** Send alerts if critical issues

**Point 2: Morning Review (Manual)**
- **When:** 8-9 AM (before market opens)
- **What:** Human review of validation results
- **Action:** Investigate warnings, confirm no blockers

**Point 3: Pre-Props (Automated)**
- **When:** Before props generation runs
- **What:** Gate check for data quality
- **Action:** Block props generation if critical issues

---

## 🌅 Morning Validation Workflow {#morning-workflow}

### Step 1: Quick Health Check (2 minutes)

**Run the daily command:**
```bash
cd ~/code/nba-stats-scraper
./scripts/validate-bdl-active-players daily
```

**What you're looking for:**

| Metric | Expected | Alert If |
|--------|----------|----------|
| Last Update | Today or yesterday | > 48 hours old |
| Teams | 30 of 30 | != 30 |
| Total Players | 550-600 | < 500 or > 650 |
| Validation Rate | 55-65% | < 45% |
| Missing from NBA.com | 20-30% | > 40% |
| Team Mismatches | 10-20% | > 30% |

**Expected output:**
```
✅ All systems operational
```

**Action:**
- ✅ Green status → Proceed to Step 2
- 🟡 Yellow warnings → Note for investigation later
- 🔴 Red critical → Stop and troubleshoot immediately

---

### Step 2: Validation Status Check (1 minute)

**Only run if Step 1 shows warnings:**
```bash
./scripts/validate-bdl-active-players validation-status
```

**What you're checking:**
- Distribution of validation statuses
- Any spike in `data_quality_issue` (should be <5%)
- Validation rate trends

**Action:**
- Document any unusual patterns
- Compare to previous day (is it getting better/worse?)

---

### Step 3: Player Count Verification (1 minute)

**Run weekly or when issues detected:**
```bash
./scripts/validate-bdl-active-players count
```

**What you're checking:**
- Teams with unusual player counts (<13 or >20)
- Which teams have outliers
- Overall data volume

**Action:**
- Teams with high counts (>20) → Recent signings, normal early season
- Teams with low counts (<13) → Injuries, trades, investigate

---

### Step 4: Data Quality Audit (1 minute)

**Run daily:**
```bash
./scripts/validate-bdl-active-players quality
```

**Critical checks (must be 0):**
- Duplicate player_lookup
- Duplicate bdl_player_id
- NULL required fields
- Invalid validation_status

**Action:**
- Any duplicates → **CRITICAL** → Investigate immediately
- NULLs in required fields → **CRITICAL** → Check processor logs
- All pass → Document and proceed

---

### Step 5: Document Status (1 minute)

**Log the results:**
```bash
# Save daily check to log file
./scripts/validate-bdl-active-players daily >> logs/bdl_validation_$(date +%Y%m%d).log 2>&1

# Or export to BigQuery for tracking
./scripts/validate-bdl-active-players daily --table nba_processing.bdl_validation_daily_$(date +%Y%m%d)
```

**Action:**
- Keep last 30 days of logs
- Weekly review of trends
- Monthly summary report

---

## 🚨 Alert Response Procedures {#alert-response}

### Critical Alerts (🔴 Immediate Action Required)

#### Alert: "Data not updating" (> 48 hours old)

**Impact:** High - Props will be based on stale player data

**Response (within 30 minutes):**
1. Check scraper status:
   ```bash
   # Check last scraper run
   gsutil ls -l gs://nba-props-platform-raw-data/ball_dont_lie/active_players/ | tail -10
   
   # Check scraper logs
   gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=bdl-active-players-scraper" --limit 50 --format json
   ```

2. Check processor status:
   ```bash
   # Check processor logs
   gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=bdl-active-players-processor" --limit 50 --format json
   ```

3. If scraper failed:
   - Check BDL API status
   - Check GCP quotas/billing
   - Manually trigger scraper

4. If processor failed:
   - Check Pub/Sub subscription
   - Check processor logs for errors
   - Manually trigger processor

5. Verify fix:
   ```bash
   ./scripts/validate-bdl-active-players daily
   ```

**Escalation:** If not resolved in 1 hour, escalate to engineering team

---

#### Alert: "Missing teams" (< 30 teams)

**Impact:** Critical - Missing entire team's player data

**Response (within 15 minutes):**
1. Identify missing team:
   ```bash
   ./scripts/validate-bdl-active-players count
   ```

2. Check if team abbreviation changed (rare)

3. Check BDL API directly:
   ```bash
   curl "https://api.balldontlie.io/v1/players?per_page=100" | jq '.data[] | select(.team.abbreviation=="MIA")' | head -20
   ```

4. If team present in API but missing in table:
   - Check processor team mapping
   - Check for filter logic excluding team

5. Verify fix:
   ```bash
   ./scripts/validate-bdl-active-players count
   ```

**Escalation:** Immediate - this is a critical data integrity issue

---

#### Alert: "Duplicate player_lookup"

**Impact:** Critical - Primary key violation, data corruption

**Response (within 15 minutes):**
1. Identify duplicates:
   ```bash
   bq query --use_legacy_sql=false "
   SELECT 
     player_lookup,
     COUNT(*) as dup_count,
     STRING_AGG(player_full_name) as names,
     STRING_AGG(CAST(bdl_player_id AS STRING)) as bdl_ids
   FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
   GROUP BY player_lookup
   HAVING COUNT(*) > 1
   "
   ```

2. Determine if true duplicates or different players:
   - Different BDL IDs = Different players with same name (expected)
   - Same BDL ID = Data corruption (critical)

3. If different players with same name:
   - Document in known issues
   - Update name normalization logic if needed
   - Add differentiator (middle name, suffix)

4. If data corruption:
   - Re-run processor
   - Check name normalization logic
   - Verify source data

**Escalation:** Immediate if data corruption, document if name collision

---

### Warning Alerts (🟡 Review Within 24 Hours)

#### Alert: "Low validation rate" (< 55%)

**Impact:** Medium - May indicate NBA.com data is stale

**Response:**
1. Check NBA.com player list freshness:
   ```bash
   ./scripts/validate-player-list daily
   ```

2. If NBA.com is stale:
   - Trigger NBA.com scraper
   - Re-run BDL processor after NBA.com updates

3. If BDL has unusual players:
   ```bash
   ./scripts/validate-bdl-active-players missing-players
   ```
   - Review list of missing players
   - Verify they are G-League/two-way (expected)

4. Document findings and monitor trend

---

#### Alert: "High team mismatch rate" (> 25%)

**Impact:** Medium - May indicate trade deadline activity or timing issues

**Response:**
1. Check if it's trade deadline period (February):
   - If yes → Expected, document and monitor
   - If no → Investigate timing

2. Analyze mismatches:
   ```bash
   ./scripts/validate-bdl-active-players team-mismatches
   ```

3. Review trade news:
   - Check ESPN/NBA.com for recent trades
   - Verify mismatches align with known trades

4. If timing issue:
   - Check when BDL scraper last ran
   - Check when NBA.com scraper last ran
   - May need to wait 24-48 hours for sync

---

## 🤖 Automation Setup {#automation}

### Option 1: Cron Job (Recommended for Development)

**Setup:**
```bash
# Edit crontab
crontab -e

# Add daily validation (runs at 8 AM)
0 8 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-bdl-active-players daily >> ~/logs/bdl_validation_$(date +\%Y\%m\%d).log 2>&1

# Add weekly full validation (runs Sunday at 7 AM)
0 7 * * 0 cd ~/code/nba-stats-scraper && ./scripts/validate-bdl-active-players all >> ~/logs/bdl_validation_weekly_$(date +\%Y\%m\%d).log 2>&1
```

**Alerts:**
```bash
# Add alerting wrapper
# File: ~/scripts/validate-bdl-with-alerts.sh

#!/bin/bash
RESULT=$(cd ~/code/nba-stats-scraper && ./scripts/validate-bdl-active-players daily)

# Check for critical alerts
if echo "$RESULT" | grep -q "🔴 CRITICAL"; then
    # Send email alert
    echo "$RESULT" | mail -s "🔴 BDL Validation CRITICAL" ops-team@yourcompany.com
    
    # Or Slack webhook
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"🔴 BDL Active Players Validation CRITICAL\n\`\`\`$RESULT\`\`\`\"}" \
        $SLACK_WEBHOOK_URL
fi

echo "$RESULT"
```

---

### Option 2: Cloud Scheduler (Recommended for Production)

**Setup:**
```bash
# Create Cloud Scheduler job for daily validation
gcloud scheduler jobs create http bdl-validation-daily \
  --schedule="0 8 * * *" \
  --uri="https://YOUR-REGION-YOUR-PROJECT.cloudfunctions.net/bdl-validation-function" \
  --http-method=POST \
  --time-zone="America/Los_Angeles" \
  --description="Daily BDL Active Players validation check"

# Create Cloud Scheduler job for weekly validation
gcloud scheduler jobs create http bdl-validation-weekly \
  --schedule="0 7 * * 0" \
  --uri="https://YOUR-REGION-YOUR-PROJECT.cloudfunctions.net/bdl-validation-function" \
  --http-method=POST \
  --message-body='{"validation_type":"full"}' \
  --time-zone="America/Los_Angeles" \
  --description="Weekly BDL Active Players full validation"
```

**Cloud Function (Python):**
```python
# File: cloud_functions/bdl_validation/main.py

import subprocess
import requests
import os
from google.cloud import bigquery

def validate_bdl_active_players(request):
    """Cloud Function to run BDL validation and send alerts."""
    
    # Run validation
    result = subprocess.run(
        ['./scripts/validate-bdl-active-players', 'daily'],
        cwd='/workspace',
        capture_output=True,
        text=True
    )
    
    output = result.stdout
    
    # Check for critical alerts
    if '🔴 CRITICAL' in output:
        # Send Slack alert
        slack_webhook = os.environ.get('SLACK_WEBHOOK_URL')
        if slack_webhook:
            requests.post(slack_webhook, json={
                'text': f'🔴 BDL Active Players Validation CRITICAL\n```{output}```'
            })
        
        # Log to BigQuery
        client = bigquery.Client()
        table_id = 'nba-props-platform.nba_processing.validation_alerts'
        rows = [{
            'timestamp': datetime.utcnow().isoformat(),
            'validation_type': 'bdl_active_players',
            'status': 'CRITICAL',
            'details': output
        }]
        client.insert_rows_json(table_id, rows)
    
    return {'status': 'success', 'output': output}
```

---

### Option 3: Integrated with Processor (Real-time)

**Setup:** Add validation to the processor pipeline

```python
# File: data_processors/raw/bdl_active_players_processor.py
# Add to the load_data() method

def load_data(self, rows: List[Dict], **kwargs) -> Dict:
    # ... existing code ...
    
    # After successful load, run validation
    if not errors:
        self._run_validation_checks()
    
    return {'rows_processed': len(rows), 'errors': errors}

def _run_validation_checks(self):
    """Run quick validation checks after processing."""
    try:
        # Run daily check query
        query = """
        SELECT 
            COUNT(*) as total_players,
            COUNT(DISTINCT team_abbr) as total_teams,
            COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) as validated,
            MAX(processed_at) as last_processed
        FROM `nba-props-platform.nba_raw.bdl_active_players_current`
        """
        result = self.bq_client.query(query).result()
        row = next(result)
        
        # Check critical conditions
        if row.total_teams != 30:
            notify_error(
                title="Missing Teams in BDL Data",
                message=f"Only {row.total_teams} of 30 teams found",
                details={'total_players': row.total_players}
            )
        
        if row.total_players < 500:
            notify_warning(
                title="Low Player Count",
                message=f"Only {row.total_players} players found (expected 550-600)",
                details={'total_teams': row.total_teams}
            )
        
        validation_rate = (row.validated / row.total_players) * 100
        if validation_rate < 45:
            notify_warning(
                title="Low Validation Rate",
                message=f"Only {validation_rate:.1f}% validation rate",
                details={'validated': row.validated, 'total': row.total_players}
            )
            
    except Exception as e:
        logging.warning(f"Validation checks failed: {e}")
```

---

## 🔗 Integration with Data Pipeline {#pipeline-integration}

### Pipeline Flow with Validation

```
┌─────────────────┐
│  BDL API        │
│  (Data Source)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Scraper        │ ──► Save to GCS
│  (bdl_active)   │     (JSON files)
└────────┬────────┘
         │
         ▼ (Pub/Sub trigger)
┌─────────────────┐
│  Processor      │
│  (Transform +   │ ──► Load to BigQuery
│   Validate)     │     (nba_raw.bdl_active_players_current)
└────────┬────────┘
         │
         ▼ (Post-process)
┌─────────────────┐
│  ✅ VALIDATION  │
│  (This System)  │ ──► Alerts & Logs
└────────┬────────┘
         │
         ▼ (Gate check)
┌─────────────────┐
│  Props          │
│  Generation     │ ──► Only if validation passes
└─────────────────┘
```

### Gate Check Implementation

**Before props generation, verify data quality:**

```python
# File: props_generation/player_points_props.py

def generate_props(game_date: str):
    """Generate player props, but only if data passes validation."""
    
    # Gate check: Validate BDL data quality
    if not _validate_bdl_data_quality():
        logging.error("BDL validation failed - blocking props generation")
        notify_error(
            title="Props Generation Blocked",
            message="BDL Active Players validation failed critical checks",
            details={'game_date': game_date}
        )
        return {'status': 'blocked', 'reason': 'validation_failed'}
    
    # Proceed with props generation
    # ... rest of code ...

def _validate_bdl_data_quality() -> bool:
    """Quick validation check before props generation."""
    client = bigquery.Client()
    
    query = """
    SELECT 
        MAX(last_seen_date) as last_update,
        COUNT(DISTINCT team_abbr) as total_teams,
        COUNT(*) as total_players,
        COUNT(CASE WHEN player_lookup IS NULL THEN 1 END) as null_lookups
    FROM `nba-props-platform.nba_raw.bdl_active_players_current`
    """
    
    result = client.query(query).result()
    row = next(result)
    
    # Critical checks
    checks = {
        'data_fresh': (datetime.now().date() - row.last_update).days <= 2,
        'all_teams': row.total_teams == 30,
        'reasonable_count': 500 <= row.total_players <= 650,
        'no_nulls': row.null_lookups == 0
    }
    
    # Log results
    logging.info(f"BDL validation checks: {checks}")
    
    # Return True only if all critical checks pass
    return all(checks.values())
```

---

## 🏀 Season-Specific Considerations {#season-considerations}

### Pre-Season (September - October)

**Validation Adjustments:**
- Higher roster turnover expected (>30% team mismatches normal)
- More two-way contracts (>35% missing from NBA.com normal)
- Daily validation important as rosters stabilize

**Actions:**
- Document roster changes daily
- Compare to previous season's final rosters
- Identify new players to watch

---

### Regular Season (October - April)

**Validation Expectations:**
- Most stable validation rates
- Expected ranges apply normally
- Focus on daily consistency

**Key Dates:**
- **October 15-25:** Opening week - high roster activity
- **December 15:** Trades eligible - watch for mismatches
- **February (Trade Deadline):** Expect 25-40% team mismatches
- **February 18-20:** All-Star Break - lower activity

**Actions:**
- Daily validation routine
- Weekly trend analysis
- Document trade deadline impacts

---

### Playoffs (April - June)

**Validation Adjustments:**
- Smaller player pool (only playoff teams)
- Expected player count: 200-250
- Team count: 16 → gradually decreasing

**Actions:**
- Adjust alert thresholds for lower counts
- Focus on playoff team validation
- Monitor eliminated teams (players may not update)

---

### Off-Season (June - September)

**Validation Frequency:**
- Reduce to 2-3 times per week
- Focus on major events (draft, free agency)

**Key Dates:**
- **June 26-27:** NBA Draft - new players added
- **July 1:** Free Agency - high roster movement
- **July-August:** Summer League - two-way signings

**Actions:**
- Weekly validation sufficient
- Monitor for off-season moves
- Prepare for pre-season ramp-up

---

## 🔧 Troubleshooting Common Issues {#troubleshooting}

### Issue: Validation Shows "Very Old Data" but Scraper Ran

**Symptoms:**
- Scraper logs show successful run
- GCS has recent files
- BigQuery table shows old processed_at

**Diagnosis:**
```bash
# Check if processor actually ran
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=bdl-active-players-processor" --limit 10

# Check Pub/Sub subscription
gcloud pubsub subscriptions list --filter="name:bdl-active-players"
```

**Common Causes:**
1. Processor not triggered (Pub/Sub issue)
2. Processor failed silently
3. Processor running but not committing to BigQuery

**Resolution:**
1. Check Pub/Sub subscription backlog
2. Manually trigger processor
3. Review processor logs for errors

---

### Issue: High Team Mismatch Rate Outside Trade Deadline

**Symptoms:**
- >30% team mismatches
- Not near trade deadline

**Diagnosis:**
```bash
# Check if BDL and NBA.com ran at different times
./scripts/validate-bdl-active-players daily
./scripts/validate-player-list daily

# Compare last update times
```

**Common Causes:**
1. NBA.com scraper delayed
2. BDL API had stale data
3. Timing difference in scraper schedules

**Resolution:**
1. Check scraper schedules align
2. Re-run both scrapers
3. Wait 24 hours for sync

---

### Issue: Duplicate Player Error (Same Person, Not Name Collision)

**Symptoms:**
- Same player_lookup AND same bdl_player_id
- True duplicate

**Diagnosis:**
```bash
# Find the duplicate
bq query --use_legacy_sql=false "
SELECT * 
FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
WHERE player_lookup IN (
  SELECT player_lookup 
  FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
  GROUP BY player_lookup 
  HAVING COUNT(*) > 1
)
ORDER BY player_lookup, processed_at
"
```

**Common Causes:**
1. Processor ran twice without clearing table
2. MERGE_UPDATE logic failed
3. Race condition in processing

**Resolution:**
1. Check processor logs for double-run
2. Manually clear and re-run processor
3. Fix MERGE_UPDATE logic if needed

---

## 📞 Escalation Procedures {#escalation}

### Tier 1: Self-Service (You can fix)

**Issues:**
- Data 24-48 hours old
- Minor validation rate fluctuations
- Expected G-League/trade mismatches

**Response Time:** 1-2 hours

**Actions:**
- Re-run scrapers manually
- Document issue
- Monitor for resolution

---

### Tier 2: Engineering Support (Need help)

**Issues:**
- Data >48 hours old and scraper fails
- Missing teams
- Persistent duplicates

**Response Time:** 4 hours during business hours

**Contact:**
- Engineering team lead
- On-call engineer
- Post in #data-engineering Slack

**Information to Provide:**
- Validation output
- Scraper/processor logs
- Timeline of issue

---

### Tier 3: Critical Escalation (Business impact)

**Issues:**
- Props generation blocked
- Data corruption
- Complete system failure

**Response Time:** Immediate

**Contact:**
- Page on-call engineer
- Alert engineering manager
- Post in #incidents Slack

**Information to Provide:**
- Business impact (props affected?)
- Timeline of issue
- All relevant logs
- Validation output

---

## 📊 Weekly and Monthly Reviews

### Weekly Review (Monday Morning, 15 minutes)

**Run complete validation:**
```bash
./scripts/validate-bdl-active-players all
```

**Review:**
1. Validation rate trends (up/down?)
2. Team mismatch patterns (trades?)
3. G-League assignment trends
4. Any persistent issues

**Document:**
- Weekly summary report
- Notable changes
- Action items for next week

---

### Monthly Review (First Monday, 30 minutes)

**Export data for analysis:**
```bash
# Export last 30 days of validation
./scripts/validate-bdl-active-players validation-status --csv > monthly_validation_$(date +%Y%m).csv

# Query historical trends
bq query --use_legacy_sql=false "
SELECT 
  DATE_TRUNC(processed_at, WEEK) as week,
  AVG(CASE WHEN has_validation_issues = FALSE THEN 100 ELSE 0 END) as avg_validation_rate,
  COUNT(DISTINCT team_abbr) as teams,
  COUNT(*) as total_players
FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
WHERE processed_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY week
ORDER BY week
"
```

**Review:**
1. Month-over-month trends
2. Impact of trades/signings
3. Validation system performance
4. Alert accuracy (false positives?)

**Actions:**
- Update alert thresholds if needed
- Document seasonal patterns
- Plan for next month

---

## 🎯 Success Metrics

### Daily Success Criteria

- ✅ Validation completes in <5 minutes
- ✅ No critical alerts (🔴)
- ✅ Data updated within 24 hours
- ✅ All 30 teams present
- ✅ 55-65% validation rate

### Weekly Success Criteria

- ✅ Validation trends stable
- ✅ No recurring issues
- ✅ All alerts investigated
- ✅ Documentation updated

### Monthly Success Criteria

- ✅ >95% daily validation success rate
- ✅ <1 hour average issue resolution time
- ✅ Zero props blocked by validation failures
- ✅ Complete audit trail maintained

---

## 📝 Checklist for Season Start

### One Week Before Season

- [ ] Test all validation queries
- [ ] Set up automation (cron or Cloud Scheduler)
- [ ] Configure alerting (email/Slack)
- [ ] Document alert contacts
- [ ] Review alert thresholds
- [ ] Test escalation procedures

### First Week of Season

- [ ] Run validation daily
- [ ] Monitor closely for issues
- [ ] Document any unexpected patterns
- [ ] Adjust thresholds if needed
- [ ] Confirm automation working

### Ongoing (Every Week)

- [ ] Monday: Weekly review
- [ ] Daily: Quick health check
- [ ] Document significant events
- [ ] Update runbook as needed

---

## 🆘 Quick Reference Card

**Print this and keep at your desk:**

```
═══════════════════════════════════════════════════════════
  BDL ACTIVE PLAYERS - DAILY VALIDATION QUICK REFERENCE
═══════════════════════════════════════════════════════════

MORNING ROUTINE (5 minutes):
1. cd ~/code/nba-stats-scraper
2. ./scripts/validate-bdl-active-players daily
3. Check for 🔴 CRITICAL alerts
4. Document and proceed

EXPECTED VALUES:
✅ Last update: <48 hours
✅ Teams: 30 of 30
✅ Players: 550-600
✅ Validation rate: 55-65%
✅ Missing NBA.com: 20-30%
✅ Team mismatches: 10-20%

CRITICAL ALERTS (🔴 - Take immediate action):
- Data >48 hours old → Check scraper/processor
- Teams != 30 → Check for missing teams
- Duplicates > 0 → Check for data corruption

WARNING ALERTS (🟡 - Review within 24 hours):
- Validation rate <55% → Check NBA.com freshness
- Team mismatches >25% → Check for trades

ESCALATION:
Tier 1 (1-2 hrs): Self-service
Tier 2 (4 hrs): Engineering support
Tier 3 (Immediate): Page on-call

COMMANDS:
Daily check:          ./scripts/validate-bdl-active-players daily
Full validation:      ./scripts/validate-bdl-active-players all
Deep dive:            ./scripts/validate-bdl-active-players [command]
Export CSV:           ./scripts/validate-bdl-active-players daily --csv

═══════════════════════════════════════════════════════════
```

---

## Last Updated
October 14, 2025

## Document Owner
Data Engineering Team

## Review Schedule
- Monthly during season
- Quarterly during off-season
- After any major system changes
