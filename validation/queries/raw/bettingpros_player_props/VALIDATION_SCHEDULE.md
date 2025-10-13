# BettingPros Player Props - Validation Schedule

**Purpose**: Automated data quality monitoring during NBA season  
**Season**: 2025-26 (October 2025 - June 2026)  
**Tool**: `validate-bettingpros` CLI  
**Status**: Production Ready

---

## 📅 Overview

This document defines the automated validation schedule for BettingPros player props data during the NBA season. All queries run automatically via Cloud Scheduler + Cloud Run Jobs.

### Coverage Periods

| Period | Dates | Validation Frequency |
|--------|-------|---------------------|
| **Preseason** | Oct 1-21, 2025 | Daily (testing mode) |
| **Regular Season** | Oct 22, 2025 - Apr 13, 2026 | Daily + Weekly |
| **Playoffs** | Apr 19 - Jun 22, 2026 | Daily + Real-time |
| **Offseason** | Jun 23 - Sep 30, 2026 | Monthly |

---

## 🔄 Daily Validations (Every Morning)

### Schedule: 8:00 AM ET (5:00 AM PT)
**Runs After**: Overnight scraper completion (typically 2-3 AM PT)

### Query 1: Yesterday Check
```bash
./scripts/validate-bettingpros yesterday
```

**Purpose**: Verify yesterday's games were captured with complete props data

**Execution Time**: ~10 seconds

**Alert Thresholds**:
- 🔴 **CRITICAL**: No props data at all → Page on-call engineer
- 🔴 **CRITICAL**: Zero high-confidence records (validation_confidence < 0.7) → Page on-call
- 🟡 **WARNING**: <30 props per game average → Slack alert
- 🟡 **WARNING**: <10 active bookmakers → Slack alert
- ⚪ **INFO**: No games scheduled (expected) → Log only

**Success Criteria**:
- ✅ All scheduled games have props data
- ✅ 30-60 props per game (regular season)
- ✅ 15-20 active bookmakers
- ✅ 80%+ high-confidence records
- ✅ Avg confidence ≥ 0.6

**Example Output During Season**:
```
check_date: 2025-11-15
scheduled_games: 12
games_with_props: 12
total_records: 5,432
high_confidence_records: 4,890 (90%)
avg_props_per_game: 452.7
active_bookmakers: 18
status: ✅ Complete
bookmaker_status: ✅ Excellent coverage (18 books)
```

**Failure Actions**:
- **CRITICAL**: Trigger incident response, re-run scraper for missing date
- **WARNING**: Create Jira ticket, investigate next business day
- **INFO**: Log and continue

---

## 📊 Weekly Validations

### Schedule: Monday 9:00 AM ET
**Covers**: Previous 7 days (Monday-Sunday)

### Query 2: Weekly Trend Check
```bash
./scripts/validate-bettingpros week
```

**Purpose**: Monitor data quality trends and detect gradual degradation

**Execution Time**: ~15 seconds

**Alert Thresholds**:
- 🔴 **CRITICAL**: 3+ days with no high-confidence data → Escalate
- 🟡 **WARNING**: Avg confidence < 0.6 across week → Investigate
- 🟡 **WARNING**: Avg bookmakers < 10 across week → Investigate
- 🟡 **WARNING**: 2+ days with <100 records → Review scraper health

**Success Criteria**:
- ✅ All game days have data
- ✅ Consistent bookmaker coverage (15-20 books)
- ✅ Stable record counts (no sudden drops)
- ✅ Weekly avg confidence ≥ 0.6

**Example Output During Season**:
```
DAILY BREAKDOWN:
Date       | Day       | Games | Records | Bookmakers | Status
2025-11-10 | Monday    | 8     | 3,654   | 17         | ✅ Good
2025-11-11 | Tuesday   | 11    | 5,321   | 18         | ✅ Good
2025-11-12 | Wednesday | 12    | 5,892   | 18         | ✅ Good
...

WEEKLY SUMMARY:
dates_with_data: 7
total_records: 35,432
avg_records_per_date: 5,061.7
avg_bookmakers: 17.4
overall_avg_confidence: 0.65
status: ✅ Good week
```

**Failure Actions**:
- **CRITICAL**: Incident review, analyze root cause
- **WARNING**: Schedule team review meeting, investigate patterns

### Query 3: Confidence Score Monitoring
```bash
./scripts/validate-bettingpros confidence
```

**Purpose**: Track validation confidence distribution to detect processing timing issues

**Execution Time**: ~20 seconds

**Alert Thresholds**:
- 🟡 **WARNING**: Recent games (last 7 days) have <80% high-confidence records
- 🟡 **WARNING**: Same-day games showing 0.3 confidence instead of 0.95
- ⚪ **INFO**: Historical games showing expected 0.1 confidence

**Success Criteria**:
- ✅ Recent games: 80%+ with 0.95 confidence
- ✅ No confidence degradation trends
- ✅ Processing timing is correct (same-day = 0.95)

**Example Output During Season**:
```
Date       | Total | High Conf | Med Conf | Low Conf | Avg Conf | Status
2025-11-15 | 5,432 | 4,890     | 542      | 0        | 0.92     | ✅ Good
2025-11-14 | 5,123 | 4,611     | 512      | 0        | 0.91     | ✅ Good
```

**Failure Actions**:
- **WARNING**: Check processor timing, verify processing runs same-day
- **INFO**: Document but no action required

### Query 4: Bookmaker Coverage Analysis
```bash
./scripts/validate-bettingpros bookmakers
```

**Purpose**: Monitor which bookmakers are providing data, detect API outages

**Execution Time**: ~25 seconds

**Alert Thresholds**:
- 🔴 **CRITICAL**: Major bookmaker (DraftKings, FanDuel) missing >3 days → Escalate
- 🟡 **WARNING**: Any bookmaker missing >7 days → Investigate
- 🟡 **WARNING**: Total bookmakers drop below 12 → Review

**Success Criteria**:
- ✅ DraftKings, FanDuel present every day
- ✅ 15-20 total bookmakers active
- ✅ No bookmaker outages >7 days

**Example Output During Season**:
```
BOOKMAKER BREAKDOWN:
Bookmaker     | Records | Days | Players | Last Seen  | Status
DraftKings    | 8,432   | 30   | 245     | 2025-11-15 | ✅ Active
FanDuel       | 8,221   | 30   | 243     | 2025-11-15 | ✅ Active
BetMGM        | 7,891   | 30   | 238     | 2025-11-15 | ✅ Active
Caesars       | 7,654   | 30   | 235     | 2025-11-15 | ✅ Active
```

**Failure Actions**:
- **CRITICAL**: Contact BettingPros support, investigate API issues
- **WARNING**: Monitor and document, review API logs

---

## 🎯 Monthly Validations

### Schedule: 1st of Each Month, 10:00 AM ET

### Query 5: Season Completeness Check
```bash
./scripts/validate-bettingpros completeness
```

**Purpose**: Comprehensive team-by-team validation across all seasons

**Execution Time**: ~45 seconds

**Alert Thresholds**:
- 🔴 **CRITICAL**: Any team with 0 games → Investigate immediately
- 🟡 **WARNING**: Any team <70 games (current season) → Check for gaps
- 🟡 **WARNING**: Avg props/game <30 for any team → Review coverage

**Success Criteria**:
- ✅ Current season: All teams approaching 82 games
- ✅ Previous seasons: All teams have 82+ games
- ✅ All teams: 30-60 props per game average
- ✅ Confidence distribution: 50%+ high confidence (0.95)

**Example Output During Season** (December):
```
DIAGNOSTICS:
total_dates: 150 (current season so far)
avg_confidence: 0.72
unique_books: 20

TEAM STATS (2025-26 Season):
Team | Reg Games | Avg Props | Playoff Games | Status
LAL  | 35        | 245.3     | 0             | ✅
BOS  | 35        | 238.7     | 0             | ✅
GSW  | 34        | 241.2     | 0             | ✅
```

**Failure Actions**:
- **CRITICAL**: Emergency backfill, investigate data pipeline
- **WARNING**: Schedule backfill, review historical gaps

### Query 6: Playoff Completeness (Playoffs Only)
```bash
./scripts/validate-bettingpros playoffs
```

**Schedule**: 
- **Regular Season**: Skip (no playoff games)
- **Playoffs**: Daily during playoffs (Apr 19 - Jun 22)
- **Post-Season**: Run once after Finals completion

**Purpose**: Ensure all playoff games have complete props coverage

**Alert Thresholds**:
- 🔴 **CRITICAL**: Any playoff game with 0 data → Page immediately
- 🔴 **CRITICAL**: Finals game with <400 records → Investigate
- 🟡 **WARNING**: Playoff game <30 records → Review coverage

**Success Criteria**:
- ✅ All playoff games have data
- ✅ Finals games: 700-850 records each
- ✅ Conference Finals: 600-800 records each
- ✅ Earlier rounds: 400-600 records each

**Example Output During Playoffs**:
```
GAME DETAILS:
Date       | Matchup      | Records | Players | Status
2025-06-15 | BOS @ DEN    | 820     | 19      | ✅ Complete
2025-06-13 | BOS @ DEN    | 816     | 18      | ✅ Complete

SEASON SUMMARY:
2024-25 Playoffs: 92 games, 100% coverage, ✅ Complete
```

**Failure Actions**:
- **CRITICAL**: Immediate rescrape, high business priority
- **WARNING**: Schedule backfill within 24 hours

---

## 🚨 Real-Time Monitoring (Playoffs Only)

### Query 7: Missing Games Check
```bash
./scripts/validate-bettingpros missing
```

**Schedule**: 
- **Regular Season**: Weekly (included in Monday checks)
- **Playoffs**: Daily (2 hours after last game tipoff)

**Purpose**: Identify specific dates with missing data requiring immediate action

**Alert Thresholds**:
- 🔴 **CRITICAL**: Today's games missing → Page immediately
- 🔴 **CRITICAL**: Playoff game missing → Page immediately
- 🟡 **WARNING**: Any regular season game missing → Next-day backfill

**Success Criteria**:
- ✅ Empty result (no missing dates)
- ✅ All games captured within 2 hours of completion

**Example Output** (Problem State):
```
Date       | Games | Matchups         | Status
2025-04-20 | 3     | BOS@MIA, LAL@DEN | 🔴 CRITICAL: NO PROPS DATA
```

**Failure Actions**:
- **CRITICAL**: Immediate rescrape, investigate scraper failure
- **WARNING**: Add to backfill queue, run next morning

---

## 🔧 Implementation: Cloud Scheduler Jobs

### Job 1: Daily Morning Validation
```yaml
name: bettingpros-daily-validation
schedule: "0 8 * * *"  # 8 AM ET daily
timezone: America/New_York
target:
  type: cloud_run_job
  job_name: bettingpros-validation-runner
  args:
    - "yesterday"
  env:
    - name: ALERT_CHANNEL
      value: "slack-nba-data-alerts"
    - name: ALERT_THRESHOLD
      value: "CRITICAL,WARNING"
```

### Job 2: Weekly Monitoring
```yaml
name: bettingpros-weekly-validation
schedule: "0 9 * * 1"  # 9 AM ET every Monday
timezone: America/New_York
target:
  type: cloud_run_job
  job_name: bettingpros-validation-runner
  args:
    - "week"
    - "confidence"
    - "bookmakers"
  env:
    - name: ALERT_CHANNEL
      value: "slack-nba-data-alerts"
    - name: ALERT_THRESHOLD
      value: "WARNING"
```

### Job 3: Monthly Completeness
```yaml
name: bettingpros-monthly-validation
schedule: "0 10 1 * *"  # 10 AM ET on 1st of month
timezone: America/New_York
target:
  type: cloud_run_job
  job_name: bettingpros-validation-runner
  args:
    - "completeness"
  env:
    - name: ALERT_CHANNEL
      value: "slack-nba-data-reports"
    - name: ALERT_THRESHOLD
      value: "WARNING"
```

### Job 4: Playoff Real-Time (Conditional)
```yaml
name: bettingpros-playoff-validation
schedule: "0 */6 * * *"  # Every 6 hours during playoffs
timezone: America/New_York
enabled: false  # Enable manually when playoffs start
target:
  type: cloud_run_job
  job_name: bettingpros-validation-runner
  args:
    - "playoffs"
    - "missing"
  env:
    - name: ALERT_CHANNEL
      value: "slack-nba-playoffs"
    - name: ALERT_THRESHOLD
      value: "CRITICAL"
```

---

## 📊 Alert Routing

### Slack Channels

**#nba-data-alerts** (Immediate Response Required)
- 🔴 CRITICAL alerts only
- Yesterday check failures
- Playoff game missing data
- On-call engineer tagged

**#nba-data-warnings** (Next Business Day)
- 🟡 WARNING alerts
- Low coverage warnings
- Bookmaker outages
- Reviewed during daily standup

**#nba-data-reports** (Informational)
- ⚪ INFO messages
- Weekly summaries
- Monthly completeness reports
- No action required

### PagerDuty Integration (CRITICAL Only)

**Trigger Conditions**:
1. Yesterday check: Zero props data for scheduled games
2. Playoff game: Missing data 2+ hours after completion
3. Critical bookmaker outage: DraftKings or FanDuel missing 3+ days

**Escalation Path**:
1. On-call data engineer (immediate)
2. Data team lead (after 30 minutes)
3. Engineering manager (after 1 hour)

---

## 📈 Success Metrics

### Daily KPIs
- **Completeness**: 99%+ of games have props data
- **Timeliness**: Data available within 2 hours of scraper run
- **Quality**: 80%+ high-confidence records
- **Coverage**: 15-20 bookmakers active

### Weekly KPIs
- **Reliability**: Zero CRITICAL alerts
- **Consistency**: <3 WARNING alerts per week
- **Bookmaker Health**: All major books present daily

### Monthly KPIs
- **Season Progress**: All teams trending toward 82 games
- **Data Quality**: Confidence scores stable/improving
- **Backfill Rate**: <5 dates requiring manual backfill per month

---

## 🔄 Seasonal Workflow

### October (Season Start)
**Week 1-3**: Preseason monitoring
- [ ] Run `yesterday` check daily (testing mode)
- [ ] Review scraper performance
- [ ] Tune alert thresholds if needed
- [ ] Verify bookmaker coverage

**Week 4**: Regular season begins (Oct 22)
- [ ] Enable all daily validations
- [ ] Activate PagerDuty integration
- [ ] Baseline first week metrics
- [ ] Document any early issues

### November - April (Regular Season)
**Routine Operations**:
- [x] Daily `yesterday` check @ 8 AM ET
- [x] Weekly monitoring @ 9 AM ET Mondays
- [x] Monthly completeness @ 10 AM ET on 1st
- [x] Respond to alerts per escalation matrix

**Monthly Review**:
- Review cumulative missing dates
- Plan backfill windows
- Analyze bookmaker trends
- Update thresholds if needed

### April - June (Playoffs)
**Enhanced Monitoring**:
- [x] Enable `playoffs` validation (every 6 hours)
- [x] Enable `missing` check (daily)
- [x] Reduce CRITICAL alert threshold
- [x] Monitor Finals games in real-time

**Post-Playoffs**:
- [ ] Run final `playoffs` completeness check
- [ ] Document season coverage statistics
- [ ] Archive validation results
- [ ] Prepare offseason report

### July - September (Offseason)
**Reduced Schedule**:
- Monthly completeness check only
- No daily/weekly validations
- Review and improve queries
- Plan next season enhancements

---

## 📋 Validation Checklist (Season Start)

### Pre-Season Setup (1 week before Oct 22)
- [ ] Test all 7 validation queries manually
- [ ] Verify Cloud Scheduler jobs configured
- [ ] Confirm Slack channels exist and accessible
- [ ] Test PagerDuty alert routing
- [ ] Update alert thresholds based on previous season
- [ ] Document on-call rotation
- [ ] Train team on escalation procedures

### Week 1 of Season
- [ ] Verify `yesterday` runs successfully daily
- [ ] Confirm alerts reach correct channels
- [ ] Review first week metrics
- [ ] Adjust thresholds if too noisy/quiet
- [ ] Document any unexpected patterns

### Ongoing (Monthly)
- [ ] Review missed alerts or false positives
- [ ] Update alert thresholds based on patterns
- [ ] Backfill any accumulated gaps
- [ ] Report metrics to stakeholders

---

## 🛠️ Troubleshooting

### Alert Fatigue
**Problem**: Too many WARNING alerts

**Solutions**:
1. Increase thresholds slightly (e.g., 25 → 20 props/game)
2. Add grace period for non-critical issues
3. Batch weekly warnings into single summary

### Missed Critical Alerts
**Problem**: CRITICAL issue not detected

**Solutions**:
1. Lower CRITICAL thresholds
2. Add redundant validation checks
3. Increase monitoring frequency during high-risk periods

### Processing Delays
**Problem**: Validations run before data ready

**Solutions**:
1. Delay schedule (e.g., 8 AM → 9 AM)
2. Add retry logic with exponential backoff
3. Check scraper completion before validation

---

## 📞 Support Contacts

**Data Engineering Team**: #nba-data-engineering  
**On-Call Rotation**: PagerDuty schedule "NBA-Data-Oncall"  
**Business Stakeholders**: #nba-props-business  
**BettingPros API Support**: support@bettingpros.com

---

**Document Owner**: NBA Props Data Team  
**Last Updated**: October 13, 2025  
**Next Review**: October 22, 2025 (Season Start)  
**Status**: ✅ Production Ready - Awaiting Season Start
