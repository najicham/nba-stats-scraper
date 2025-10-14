# ESPN Scoreboard Validation - Production Operations Guide

**Purpose**: Complete operational procedures for ESPN Scoreboard validation  
**Audience**: Data engineers, on-call rotation, automation scripts  
**Status**: Production Ready  
**Last Updated**: October 13, 2025

---

## 📋 Table of Contents

1. [Daily Operations (NBA Season)](#daily-operations)
2. [Weekly/Monthly Health Checks](#weekly-monthly-checks)
3. [Historical Backfill Validation](#backfill-validation)
4. [Alert Thresholds & Response](#alert-thresholds)
5. [Troubleshooting Workflows](#troubleshooting)
6. [Integration with Existing Systems](#integration)
7. [Success Criteria & Metrics](#success-criteria)

---

## 🏀 Daily Operations (NBA Season) {#daily-operations}

### When NBA Season is Active (October - June)

ESPN Scoreboard runs as part of the **Early Morning Final Check workflow** at **5 AM PT**.

---

### Daily Validation Workflow

#### **6:00 AM PT - Morning Validation Check**

Run immediately after the 5 AM workflow completes.

```bash
# Primary validation
./scripts/validate-espn-scoreboard yesterday

# Expected result: ✅ OK - Backup source (0 games is VALID)
# Action required: ONLY if systematic pattern changes
```

**What to Check**:
- ✅ **0 games = NORMAL** (backup source doesn't collect everything)
- ✅ **Partial coverage = NORMAL** (e.g., 3 of 8 games)
- ⚠️ **Alert only if**: Pattern changes dramatically (e.g., always 0 for 7+ consecutive game days)

**Example Outputs**:

```
Good Scenarios:
- "0 games yesterday" → ✅ OK - Backup source works as designed
- "3 of 8 games collected" → ✅ OK - Partial backup coverage
- "All 12 games collected" → ✅ EXCELLENT - Full backup coverage

Alert Scenarios:
- "0 games for 7 consecutive game days" → ⚠️ Investigate scraper
- "Status: 🔴 CRITICAL" → 🔴 Immediate action required
```

---

#### **Export for Monitoring Dashboard** (Optional)

If you want to track coverage trends over time:

```bash
# Daily - Save to BigQuery for trending
./scripts/validate-espn-scoreboard yesterday --table

# Weekly - Export for analysis
./scripts/validate-espn-scoreboard yesterday --csv

# Result: Creates nba-props-platform:validation.espn_daily_check_yesterday_YYYYMMDD
```

**Dashboard Query**:
```sql
-- Track ESPN backup coverage over time
SELECT 
  check_date,
  espn_collected,
  total_scheduled,
  status
FROM `nba-props-platform.validation.espn_daily_check_yesterday_*`
WHERE check_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY check_date DESC;
```

---

### Post-Game Validation (Optional Enhanced Monitoring)

If you want **same-day validation** after games complete:

#### **11:00 PM PT - Evening Spot Check** (Optional)

After BDL box scores processing completes:

```bash
# Cross-validate scores (if games were collected today)
./scripts/validate-espn-scoreboard cross-bdl

# Expected: All scores match between ESPN and BDL
```

**When to Run**:
- Only on days with NBA games
- After BDL processing completes (~10:30 PM PT)
- Optional - not required daily

---

## 📅 Weekly/Monthly Health Checks {#weekly-monthly-checks}

### Weekly Validation (Every Monday)

Run comprehensive validation to catch patterns missed in daily checks.

#### **Monday 8:00 AM PT - Weekly Review**

```bash
# 1. Coverage analysis (last 7 days)
./scripts/validate-espn-scoreboard coverage

# 2. Data quality check
./scripts/validate-espn-scoreboard quality

# 3. Team mapping validation
./scripts/validate-espn-scoreboard team-mapping
```

**What to Review**:

**Coverage Analysis**:
- ✅ Recent months should show **4-8 games/day** average
- ⚠️ Alert if: < 2 games/day for 7+ consecutive days
- ⚪ Expected: Variation is normal (backup source)

**Data Quality**:
- ✅ Score distribution: 55% in 210-239 range = normal
- ⚠️ Alert if: >10% very low scores (<100)
- ⚠️ Alert if: >5% very high scores (>280)
- ✅ Processing confidence: Always 1.0

**Team Mapping**:
- ✅ Known mappings: GS→GSW, NY→NYK, SA→SAS, NO→NOP, UTAH→UTA, WSH→WAS
- 🔴 Alert if: New unknown codes appear
- ⚪ Expected: CHK (2), SHQ (2), EAST/WEST (1 each) already known

---

### Monthly Deep Validation (First Monday of Month)

```bash
# 1. Three-way cross-validation
./scripts/validate-espn-scoreboard discrepancies

# 2. Cross-validate with NBA.com (CRITICAL)
./scripts/validate-espn-scoreboard cross-nbac

# 3. Cross-validate with BDL (primary source)
./scripts/validate-espn-scoreboard cross-bdl --csv

# 4. Export all for monthly report
./scripts/validate-espn-scoreboard quality --table
```

**Monthly Report Checklist**:

- [ ] ESPN backup coverage rate (% of games collected)
- [ ] Score discrepancies count (should be 0)
- [ ] New team codes discovered (update processor if valid)
- [ ] Data quality trends (score distributions)
- [ ] Cross-validation success rate (should be 100% when overlap exists)

---

## 🔄 Historical Backfill Validation {#backfill-validation}

### If Backfilling Past 4 Seasons (2021-22 through 2024-25)

ESPN has limited historical data because it's a **backup source**. If you backfill:

---

### Pre-Backfill Discovery

**Before starting backfill**, understand what data exists:

```bash
# Discovery: What dates have ESPN data in GCS?
gsutil ls gs://nba-scraped-data/espn/scoreboard/2024-*/

# Expected: Sparse coverage (not every game day)
```

---

### Backfill Execution Plan

#### **Phase 1: Season-by-Season Backfill**

Process one season at a time to validate incrementally:

```bash
# Example: Backfill 2024-25 season
# (Assume processor command exists or manual GCS→BigQuery)

# After backfill completes, validate immediately:
./scripts/validate-espn-scoreboard coverage

# Expected result from coverage query:
# Season 2024: ~1,398 games across ~229 dates
```

**Validation Per Season**:

| Season | Expected Games | Expected Dates | Coverage % | Notes |
|--------|----------------|----------------|------------|-------|
| 2021-22 | ~1,337 | ~215 | Sparse | Backup collection |
| 2022-23 | ~1,390 | ~227 | Sparse | Backup collection |
| 2023-24 | ~1,395 | ~224 | Sparse | Backup collection |
| 2024-25 | ~1,398 | ~229 | Sparse | Backup collection |

---

#### **Phase 2: Cross-Validation After Each Season**

After each season backfill:

```bash
# 1. Verify team mappings
./scripts/validate-espn-scoreboard team-mapping

# Check for new unknown codes by season:
# - 2021-22: Should see standard mappings
# - 2022-23: Possible international game codes (MRC, etc.)
# - 2023-24: Check for All-Star codes (EAST, WEST)
# - 2024-25: Known unknowns (CHK, SHQ)

# 2. Data quality check per season
./scripts/validate-espn-scoreboard quality

# 3. Cross-validate with BDL (primary source)
./scripts/validate-espn-scoreboard cross-bdl
```

---

#### **Phase 3: Complete Historical Validation**

After all 4 seasons backfilled:

```bash
# 1. Run full coverage analysis
./scripts/validate-espn-scoreboard coverage --csv

# Export shows:
# - Total: 5,520 games across 895 dates
# - Average: 6.2 games/day
# - Offseason gaps: 100+ days (NORMAL)

# 2. Three-way cross-validation (90-day lookback)
./scripts/validate-espn-scoreboard discrepancies --csv

# Should show:
# - Perfect matches when overlap exists
# - ESPN sparse coverage = normal
# - No score discrepancies

# 3. Critical validation vs NBA.com
./scripts/validate-espn-scoreboard cross-nbac --csv

# CRITICAL: Any mismatches = data quality issue
```

---

### Backfill Validation Checklist

Complete this checklist after full historical backfill:

**Coverage Validation**:
- [ ] Total games: ~5,520 (within 5% tolerance)
- [ ] Total dates: ~895 (sparse is expected)
- [ ] Average games/day: 5-7 (backup collection)
- [ ] Offseason gaps: 3 gaps of 100+ days (expected)
- [ ] Season distribution: All 4 seasons present

**Team Mapping Validation**:
- [ ] 6 standard mappings working (GS→GSW, NY→NYK, SA→SAS, NO→NOP, UTAH→UTA, WSH→WAS)
- [ ] Unknown codes documented: CHK (2), SHQ (2), EAST (1), WEST (1)
- [ ] All-Star games identified: Feb 2024 (EAST vs WEST)
- [ ] International game codes: MRC, NZL, LEB, etc. (expected)

**Data Quality Validation**:
- [ ] Score distribution: 55% in 210-239 range
- [ ] Very low scores (<100): < 1% of games
- [ ] Very high scores (>280): 1-3% (overtime games)
- [ ] Processing confidence: 100% at 1.0
- [ ] Status mismatches: < 1% of games

**Cross-Validation Results**:
- [ ] ESPN vs BDL: 100% match when overlap exists
- [ ] ESPN vs NBA.com: 100% match (CRITICAL)
- [ ] Three-way: All sources agree
- [ ] Discrepancies: 0 score mismatches

**Documentation**:
- [ ] Missing dates list exported (for reference)
- [ ] Unknown team codes documented (for processor updates)
- [ ] Score outliers reviewed (very low/high games)
- [ ] All validation results archived

---

### Backfill Quality Gates

**Before declaring backfill successful**, verify:

✅ **PASS Criteria**:
- Coverage matches expected sparse pattern (5-7 games/day)
- No score discrepancies vs NBA.com Scoreboard V2
- All known team mappings working
- Score distributions normal (bell curve centered on 210-239)

⚠️ **REVIEW Required If**:
- Coverage suddenly 0 for entire months
- New unknown team codes appear (need processor update)
- Score discrepancies vs NBA.com (CRITICAL)
- > 2% very low scores (< 100)

🔴 **FAIL - Don't Proceed If**:
- ESPN vs NBA.com score mismatches exist
- > 50% of dates missing (worse than expected)
- Processing confidence < 1.0 (data corruption)
- Critical team mapping failures

---

## 🚨 Alert Thresholds & Response {#alert-thresholds}

### Critical Alerts (Immediate Action Required)

#### **🔴 ESPN vs NBA.com Score Mismatch**

```bash
# Detection query
./scripts/validate-espn-scoreboard cross-nbac

# Alert trigger: ANY score differences
```

**Why Critical**: Both are official sources - mismatch = data corruption

**Response Procedure**:
1. Check source files in GCS: `gs://nba-scraped-data/espn/scoreboard/YYYY-MM-DD/`
2. Verify NBA.com Scoreboard V2 data
3. Investigate processor transformation logic
4. Check if team mapping caused issue
5. If ESPN wrong: Document and rely on NBA.com
6. If systematic: Disable ESPN scraper until fixed

**SLA**: Respond within 1 hour, resolve within 4 hours

---

#### **🔴 New Unknown Team Codes**

```bash
# Detection query
./scripts/validate-espn-scoreboard team-mapping

# Alert trigger: Unknown codes appear beyond known set (CHK, SHQ, EAST, WEST)
```

**Why Critical**: Breaks team mapping, affects cross-validation

**Response Procedure**:
1. Identify the game: Check "INVESTIGATE THESE" section
2. Research team code: Check ESPN documentation/source files
3. Determine if valid:
   - If valid NBA team: Update processor team_mapping dict
   - If All-Star/special event: Add to processor filter
   - If international: Document as exhibition game
4. Reprocess affected games
5. Update documentation

**SLA**: Investigate within 4 hours, resolve within 1 business day

---

### Warning Alerts (Review Within 24 Hours)

#### **⚠️ Systematic 0 Games Pattern**

```bash
# Detection: 7+ consecutive game days with 0 ESPN games
```

**Why Warning**: Backup source failure, but not revenue-impacting

**Response Procedure**:
1. Check Early Morning Final Check workflow logs
2. Verify ESPN scraper is running (Cloud Scheduler)
3. Check for ESPN website changes
4. Review recent processor deployments
5. If systematic failure: Create ticket for scraper fix

**SLA**: Review within 24 hours, fix within 1 week

---

#### **⚠️ High Score Outlier Rate**

```bash
# Detection query
./scripts/validate-espn-scoreboard quality

# Alert trigger: >10% very low scores (<100) OR >5% very high (>280)
```

**Why Warning**: May indicate data quality issue

**Response Procedure**:
1. Export outliers for review
2. Check if legitimate (overtime games, data entry errors)
3. Cross-validate against BDL and NBA.com
4. If systematic: Check processor score conversion logic
5. Document findings

**SLA**: Review within 1 week

---

### Informational (Monitor Trends)

#### **⚪ Sparse Coverage Variation**

```bash
# Detection: Coverage rate fluctuates (2-10 games/day)
```

**Why Informational**: Expected for backup source

**Action**: Monitor trends, no immediate action unless systematic change

---

## 🔧 Troubleshooting Workflows {#troubleshooting}

### Scenario 1: Daily Check Shows 0 Games (During Season)

**Context**: NBA season active, games scheduled yesterday, ESPN shows 0 games

**Investigation Steps**:

```bash
# Step 1: Verify games were scheduled
bq query --use_legacy_sql=false "
SELECT COUNT(*) as games
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND is_playoffs = FALSE
  AND is_all_star = FALSE
  AND game_date >= '2024-01-01'
"
# Expected: > 0 (if 0, then truly no games - Off day)

# Step 2: Check if scraper ran
gsutil ls gs://nba-scraped-data/espn/scoreboard/$(date -d yesterday +%Y-%m-%d)/
# Expected: JSON files present

# Step 3: Check processor logs
gcloud logging read "resource.type=cloud_run_job 
  AND resource.labels.job_name=espn-scoreboard-processor-backfill 
  AND timestamp>=yesterday" 
  --limit 50 --format json

# Step 4: Check for processing errors
./scripts/validate-espn-scoreboard yesterday
# Look for error messages or warnings
```

**Resolution Paths**:

- **If no files in GCS**: Scraper didn't run → Check Cloud Scheduler
- **If files exist but not processed**: Processor issue → Check job logs
- **If 7+ days of 0 games**: Systematic → Create P1 ticket
- **If occasional (< 7 days)**: Expected behavior → No action

---

### Scenario 2: Score Discrepancy Detected

**Context**: ESPN vs NBA.com score mismatch found

**Investigation Steps**:

```bash
# Step 1: Identify affected games
./scripts/validate-espn-scoreboard cross-nbac --csv

# Step 2: Get game details
bq query --use_legacy_sql=false "
SELECT 
  e.game_id,
  e.home_team_abbr,
  e.away_team_abbr,
  e.home_team_score as espn_home,
  e.away_team_score as espn_away,
  n.home_score as nbac_home,
  n.away_score as nbac_away
FROM \`nba-props-platform.nba_raw.espn_scoreboard\` e
JOIN \`nba-props-platform.nba_raw.nbac_scoreboard_v2\` n
  ON e.game_id = n.game_id
WHERE e.game_id = 'PROBLEMATIC_GAME_ID'
  AND e.game_date >= '2024-01-01'
  AND n.game_date >= '2024-01-01'
"

# Step 3: Check source file
gsutil cat gs://nba-scraped-data/espn/scoreboard/YYYY-MM-DD/*.json | jq .

# Step 4: Verify against official NBA.com
# Visit: https://www.nba.com/game/[game_id]
```

**Resolution Matrix**:

| ESPN Score | NBA.com Score | BDL Score | Diagnosis | Action |
|------------|---------------|-----------|-----------|---------|
| Wrong | Correct | Correct | ESPN data bad | Document, use NBA.com |
| Correct | Wrong | Correct | NBA.com issue | Report to NBA.com team |
| Correct | Correct | Wrong | BDL issue | Report to BDL team |
| All differ | All differ | All differ | Score changed | Investigate stat correction |

---

### Scenario 3: Unknown Team Code Appears

**Context**: Team mapping validation flags new unknown code

**Investigation Steps**:

```bash
# Step 1: Identify the code
./scripts/validate-espn-scoreboard team-mapping

# Step 2: Find the game
bq query --use_legacy_sql=false "
SELECT game_id, game_date, 
  home_team_espn_abbr, away_team_espn_abbr,
  home_team_name, away_team_name
FROM \`nba-props-platform.nba_raw.espn_scoreboard\`
WHERE home_team_espn_abbr = 'UNKNOWN_CODE'
   OR away_team_espn_abbr = 'UNKNOWN_CODE'
  AND game_date >= '2024-01-01'
ORDER BY game_date DESC
LIMIT 5
"

# Step 3: Check source JSON
gsutil cat gs://nba-scraped-data/espn/scoreboard/YYYY-MM-DD/*.json | \
  jq '.games[] | select(.teams[].abbreviation == "UNKNOWN_CODE")'
```

**Resolution Decision Tree**:

```
Is code a valid NBA team?
├─ YES
│  ├─ New team/relocation? → Update processor mapping
│  └─ ESPN-specific abbreviation? → Add to team_mapping dict
│
├─ NO - Special Event
│  ├─ All-Star Game? → Add to processor filter (is_all_star)
│  ├─ International game? → Document as exhibition
│  └─ Rising Stars/Celebrity? → Add to processor filter
│
└─ UNKNOWN
   └─ Research ESPN documentation → Document findings
```

**Processor Update Example**:

```python
# In espn_scoreboard_processor.py
self.team_mapping = {
    # ... existing mappings ...
    'NEW': 'SEA',  # Example: Seattle expansion team
}
```

---

## 🔗 Integration with Existing Systems {#integration}

### Workflow Integration Points

#### **1. Early Morning Final Check (5 AM PT)**

**Current Workflow**:
```
1. ESPN Scraper runs (5:00 AM)
2. ESPN Processor runs (5:05 AM)
3. [NEW] ESPN Validation runs (6:00 AM)
```

**Integration Point**:
- Add validation step to existing workflow
- Use exit codes for success/failure
- Send results to monitoring dashboard

**Example Cloud Scheduler Job**:
```yaml
name: espn-scoreboard-daily-validation
schedule: "0 6 * * *"  # 6 AM PT daily
timezone: America/Los_Angeles
target:
  type: cloudRun
  job: espn-scoreboard-validator
  args:
    - "yesterday"
    - "--table"  # Save results to BigQuery
```

---

#### **2. Weekly Health Check Automation**

**Automated Weekly Report**:

```bash
#!/bin/bash
# File: scripts/weekly-espn-validation.sh
# Run: Every Monday 8 AM PT

DATE=$(date +%Y-%m-%d)
REPORT_DIR="validation_reports/espn/${DATE}"
mkdir -p ${REPORT_DIR}

# Run all weekly checks
./scripts/validate-espn-scoreboard coverage --csv > ${REPORT_DIR}/coverage.csv
./scripts/validate-espn-scoreboard quality --csv > ${REPORT_DIR}/quality.csv
./scripts/validate-espn-scoreboard team-mapping --csv > ${REPORT_DIR}/teams.csv

# Generate summary
echo "ESPN Scoreboard Weekly Report - ${DATE}" > ${REPORT_DIR}/summary.txt
echo "Coverage: $(wc -l ${REPORT_DIR}/coverage.csv)" >> ${REPORT_DIR}/summary.txt
echo "Quality: $(wc -l ${REPORT_DIR}/quality.csv)" >> ${REPORT_DIR}/summary.txt

# Upload to Cloud Storage
gsutil -m cp -r ${REPORT_DIR} gs://nba-validation-reports/espn/

# Send notification (if configured)
# ./scripts/send-slack-notification.sh "ESPN weekly validation complete"
```

---

#### **3. Dashboard Integration**

**BigQuery Views for Dashboards**:

```sql
-- Daily coverage trend
CREATE OR REPLACE VIEW `nba-props-platform.validation.espn_daily_trend` AS
SELECT 
  check_date,
  CAST(espn_collected AS INT64) as games_collected,
  CAST(total_scheduled AS INT64) as games_scheduled,
  status
FROM `nba-props-platform.validation.espn_daily_check_yesterday_*`
WHERE check_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
ORDER BY check_date DESC;

-- Quality metrics trend
CREATE OR REPLACE VIEW `nba-props-platform.validation.espn_quality_trend` AS
SELECT 
  EXTRACT(DATE FROM processed_at) as report_date,
  COUNT(*) as total_games,
  AVG(processing_confidence) as avg_confidence,
  COUNT(CASE WHEN home_team_score + away_team_score < 150 THEN 1 END) as low_score_games,
  COUNT(CASE WHEN home_team_score + away_team_score > 280 THEN 1 END) as high_score_games
FROM `nba-props-platform.nba_raw.espn_scoreboard`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY report_date
ORDER BY report_date DESC;
```

**Looker Studio / Tableau Integration**:
- Connect to BigQuery validation tables
- Create daily coverage chart
- Show team mapping status over time
- Alert on critical thresholds

---

### Alert Integration

#### **Slack Notifications** (Optional)

```bash
# Example Slack webhook integration
function send_slack_alert() {
  local severity=$1
  local message=$2
  
  curl -X POST ${SLACK_WEBHOOK_URL} \
    -H 'Content-Type: application/json' \
    -d "{
      \"text\": \"ESPN Scoreboard Alert\",
      \"attachments\": [{
        \"color\": \"${severity}\",
        \"text\": \"${message}\",
        \"footer\": \"ESPN Validation System\"
      }]
    }"
}

# Usage in validation script
if [[ $(./scripts/validate-espn-scoreboard cross-nbac | grep "🔴") ]]; then
  send_slack_alert "danger" "CRITICAL: ESPN vs NBA.com score mismatch detected"
fi
```

---

#### **PagerDuty Integration** (For Critical Alerts)

```bash
# Example PagerDuty event
function trigger_pagerduty() {
  local summary=$1
  
  curl -X POST https://events.pagerduty.com/v2/enqueue \
    -H 'Content-Type: application/json' \
    -d "{
      \"routing_key\": \"${PAGERDUTY_INTEGRATION_KEY}\",
      \"event_action\": \"trigger\",
      \"payload\": {
        \"summary\": \"${summary}\",
        \"severity\": \"critical\",
        \"source\": \"ESPN Scoreboard Validation\",
        \"component\": \"espn-scoreboard\"
      }
    }"
}
```

---

## ✅ Success Criteria & Metrics {#success-criteria}

### Operational KPIs

**Daily Operations** (During NBA Season):

| Metric | Target | Alert Threshold | Notes |
|--------|--------|-----------------|-------|
| Validation completion rate | 100% | < 95% | Daily check must run |
| False positive rate | < 5% | > 10% | Alerts that aren't real issues |
| Mean time to detection (MTTD) | < 1 hour | > 4 hours | Time to detect issues |
| Mean time to resolution (MTTR) | < 4 hours | > 24 hours | Time to resolve critical issues |

**Data Quality** (Historical & Ongoing):

| Metric | Target | Alert Threshold | Notes |
|--------|--------|-----------------|-------|
| Score accuracy (vs NBA.com) | 100% | < 100% | Any mismatch = critical |
| Team mapping success | 100% | < 98% | Unknown codes acceptable if documented |
| Processing confidence | 1.0 | < 1.0 | ESPN data reliability |
| Coverage rate | 5-15% | N/A | Backup source - sparse is normal |

**Backfill Validation** (One-time):

| Metric | Target | Pass/Fail | Notes |
|--------|--------|-----------|-------|
| Total games processed | ~5,520 | ± 5% | Within tolerance |
| Score discrepancies | 0 | = 0 | Must be perfect |
| Unknown team codes | ≤ 4 | ≤ 10 | Beyond known set |
| Processing failures | 0 | = 0 | All files must process |

---

### Monthly Report Template

```markdown
# ESPN Scoreboard Validation Report
**Month**: [Month Year]
**Report Date**: [Date]
**Prepared By**: [Name]

## Executive Summary
- Total games processed: [X]
- Validation success rate: [X%]
- Critical issues: [X]
- Action items: [X]

## Coverage Metrics
- Average games/day: [X.X]
- Total dates with data: [X]
- Coverage vs expectation: [X%]

## Data Quality
- Score discrepancies: [X] (Target: 0)
- Processing confidence: [X.XX] (Target: 1.0)
- Very low scores: [X%] (Target: < 1%)
- Very high scores: [X%] (Target: < 3%)

## Team Mapping
- Standard mappings: [✅/❌]
- New unknown codes: [List]
- Action taken: [Description]

## Cross-Validation Results
- ESPN vs NBA.com: [X% match] (Target: 100%)
- ESPN vs BDL: [X% match]
- Discrepancies resolved: [X/X]

## Incidents & Resolutions
1. [Incident description]
   - Detection: [Date/Time]
   - Resolution: [Date/Time]
   - Root cause: [Description]
   - Prevention: [Action taken]

## Recommendations
1. [Recommendation]
2. [Recommendation]
```

---

## 📞 Support & Escalation

### Contact Information

| Role | Responsibility | Contact | Escalation Time |
|------|---------------|---------|-----------------|
| Data Engineer (Primary) | Daily validation, routine issues | On-call rotation | First responder |
| Senior Data Engineer | Critical issues, processor updates | [Contact] | If unresolved > 4 hours |
| Platform Lead | System-wide failures, architecture | [Contact] | If unresolved > 24 hours |

### Escalation Matrix

**Level 1 - Data Engineer** (0-4 hours):
- Daily validation failures
- Minor data quality issues
- Routine unknown team codes
- Weekly report anomalies

**Level 2 - Senior Data Engineer** (4-24 hours):
- Score discrepancies vs NBA.com
- Systematic processing failures
- Major team mapping issues
- Processor bugs

**Level 3 - Platform Lead** (24+ hours):
- Multi-day outages
- Data corruption
- System architecture issues
- Third-party API changes

---

## 📚 Additional Resources

### Documentation Links
- Master Validation Guide: `/docs/NBA_DATA_VALIDATION_MASTER_GUIDE.md`
- Processor Reference: `/docs/NBA_PROCESSORS_REFERENCE.md`
- BigQuery SQL Gotchas: `/docs/VALIDATION_ADVANCED_TOPICS.md`
- ESPN Scoreboard README: `/validation/queries/raw/espn_scoreboard/README.md`

### Query Files Location
```
validation/queries/raw/espn_scoreboard/
├── date_coverage_analysis.sql
├── daily_check_yesterday.sql
├── team_mapping_validation.sql
├── data_quality_check.sql
├── cross_validate_with_bdl.sql
├── cross_validate_with_nbac.sql
├── find_score_discrepancies.sql
└── README.md
```

### CLI Tool
```bash
scripts/validate-espn-scoreboard [command] [options]

# Quick reference
./scripts/validate-espn-scoreboard help
./scripts/validate-espn-scoreboard list
```

---

## 🔄 Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2025-10-13 | 1.0 | Initial operations guide created | Data Engineering |
| | | 7 validation queries operational | |
| | | Backfill procedures documented | |

---

**Last Updated**: October 13, 2025  
**Next Review**: Start of 2025-26 NBA Season  
**Document Owner**: Data Engineering Team  
**Status**: Production Ready - Approved for Operational Use
