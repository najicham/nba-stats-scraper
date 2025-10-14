# File: validation/queries/raw/nbac_play_by_play/DAILY_MONITORING_SCHEDULE.md
# NBA.com Play-by-Play - Daily Monitoring Schedule

## Purpose

This document defines when and how to run validation queries during the NBA season to ensure play-by-play data quality and completeness.

## When This Applies

**Active Monitoring Period**: October - June (NBA Season)  
**Frequency**: Daily during season, weekly during offseason  
**Owner**: Data Engineering Team  
**Alert Channel**: #data-quality-alerts (Slack)  

---

## Daily Monitoring Workflow

### ⏰ Morning Routine (9:00 AM ET)

Run after overnight scraper workflows complete (Late Night Recovery + Early Morning Final Check).

```bash
# 1. Quick health check - Did yesterday's games process?
./scripts/validate-nbac-pbp yesterday

# 2. Check for any missing games from yesterday
./scripts/validate-nbac-pbp missing | head -20

# Expected Result:
# - Yesterday: All games processed (✅ Complete)
# - Missing: Only shows older missing games, not yesterday
```

**What to Look For**:
- ✅ **Good**: "✅ Complete" status, all scheduled games = processed games
- ⚠️ **Warning**: Processed < scheduled (some games missing)
- 🔴 **Critical**: 0 games processed when games were scheduled

**Action Items**:
- ✅ No action needed - continue to weekly checks
- ⚠️ Investigate missing games, check scraper logs
- 🔴 Immediate escalation, scraper likely failed

---

### 📊 Weekly Deep Dive (Monday 10:00 AM ET)

Run comprehensive validation across the past week.

```bash
# 1. Weekly trend analysis
./scripts/validate-nbac-pbp week

# 2. Game-level completeness
./scripts/validate-nbac-pbp games

# 3. Event type distribution
./scripts/validate-nbac-pbp events

# 4. Player coverage validation
./scripts/validate-nbac-pbp players | head -50

# 5. Score integrity check
./scripts/validate-nbac-pbp scores
```

**What to Look For**:

**Week Trends**:
- Consistent 10-15 games per day (weekdays/weekends)
- Average 500-550 events per game
- Average 17-18 players per game

**Game Completeness**:
- All status checks showing "✅ Good"
- Event counts 450-600 range
- Player counts 15-20 range
- Overtime games properly detected (5+ periods)

**Event Distribution**:
- All core event types present (2pt, 3pt, foul, rebound)
- Shot percentages 35-50% (league average)
- No event types completely missing

**Player Coverage**:
- Most players have ✅ Good coverage
- Bench players may show ⚪ Low events (normal)
- DNP players won't appear (expected)

**Score Integrity**:
- Final scores match box scores
- No critical score decreases within periods
- Score jumps are reasonable (not >10 points)

---

## Data Quality Issues to Monitor

### 🔴 Critical Issues (Immediate Action)

**No Data Collected**:
```bash
./scripts/validate-nbac-pbp yesterday
# Shows: "🔴 CRITICAL: No play-by-play data"
```
**Action**: Check scraper status, verify workflows ran, escalate to engineering

**Score Mismatches**:
```bash
./scripts/validate-nbac-pbp scores
# Shows: "🔴 CRITICAL: Final scores do not match box scores"
```
**Action**: Investigate specific game, check source data, may need reprocessing

**Missing Games During Season**:
```bash
./scripts/validate-nbac-pbp missing | head -10
# Shows yesterday's games
```
**Action**: Check scraper logs, verify NBA.com API availability, rerun scraper

---

### ⚠️ Warning Issues (Monitor and Log)

**Low Event Counts**:
```bash
./scripts/validate-nbac-pbp games
# Shows: "⚠️ WARNING: Low event count (<450)"
```
**Action**: Review game details, may be shortened game or data issue

**Low Player Coverage**:
```bash
./scripts/validate-nbac-pbp games
# Shows: "⚠️ WARNING: Low player count (<16)"
```
**Action**: Acceptable if injury-heavy game, investigate if pattern persists

**Score Anomalies**:
```bash
./scripts/validate-nbac-pbp scores
# Shows: "⚠️ Home score jumped >3" or "🔴 Home score decreased"
```
**Action**: Review event sequence, may indicate period transition or data corruption

**Shot Percentage Issues**:
```bash
./scripts/validate-nbac-pbp events
# Shows: shot_pct = 0.0 or 100.0
```
**Action**: Processor bug with shot_made field, investigate data transformation

---

## Known Data Quality Issues (October 2025)

### Issue 1: Shot Made Detection Not Working

**Symptom**: All shots show 0.0% made (shot_pct = 0.0)  
**Cause**: Processor not correctly parsing shot_made from NBA.com data  
**Impact**: Cannot track shooting percentages  
**Status**: Known bug, needs processor fix  
**Workaround**: Use box scores for shooting stats  

**Evidence**:
```
+--------------+-----------------------+--------------+----------+
|  event_type  |   event_action_type   | total_events | shot_pct |
+--------------+-----------------------+--------------+----------+
| 3pt          | Jump Shot             |          143 |      0.0 |
| 2pt          | Layup                 |           99 |      0.0 |
| freethrow    | 1 of 2                |           35 |      0.0 |
```

### Issue 2: Score Progression Has Period Transitions

**Symptom**: Scores appear to decrease at period boundaries  
**Cause**: Period start/end events may reset running totals  
**Impact**: False positives in score validation  
**Status**: Expected behavior in some cases  
**Workaround**: Filter SCORE ANOMALIES by period transitions  

**Example**:
```
| SCORE ANOMALIES | 2025-01-15 | 20250115_NYK_PHI | 86 | 1 | 8 | 14 | 🔴 Home score decreased |
```

---

## Monthly Reporting (First Monday of Month)

Generate monthly data quality report:

```bash
# Create monthly report directory
mkdir -p reports/play_by_play/$(date +%Y-%m)

# Export all validation data
./scripts/validate-nbac-pbp games --csv > reports/play_by_play/$(date +%Y-%m)/games.csv
./scripts/validate-nbac-pbp events --csv > reports/play_by_play/$(date +%Y-%m)/events.csv
./scripts/validate-nbac-pbp missing --csv > reports/play_by_play/$(date +%Y-%m)/missing.csv

# Summary metrics
echo "Play-by-Play Quality Report - $(date +%B\ %Y)" > reports/play_by_play/$(date +%Y-%m)/summary.txt
echo "" >> reports/play_by_play/$(date +%Y-%m)/summary.txt
./scripts/validate-nbac-pbp all >> reports/play_by_play/$(date +%Y-%m)/summary.txt
```

**Share with**:
- Data Engineering Team
- Analytics Team
- Product Team (if quality issues impact features)

---

## Automated Monitoring Setup

### Option 1: Cron Job (Recommended)

```bash
# Add to crontab on monitoring server
# Daily check at 9 AM ET (14:00 UTC during EST, 13:00 UTC during EDT)
0 14 * * * cd /path/to/nba-stats-scraper && ./scripts/validate-nbac-pbp yesterday > /var/log/pbp_validation/$(date +\%Y\%m\%d).log 2>&1

# Weekly check every Monday at 10 AM ET
0 15 * * 1 cd /path/to/nba-stats-scraper && ./scripts/validate-nbac-pbp all > /var/log/pbp_validation/weekly_$(date +\%Y\%m\%d).log 2>&1
```

### Option 2: Cloud Scheduler (GCP)

```bash
# Daily check job
gcloud scheduler jobs create http pbp-daily-check \
  --schedule="0 14 * * *" \
  --uri="https://monitoring-endpoint.run.app/validate/pbp/yesterday" \
  --http-method=POST \
  --time-zone="America/New_York"

# Weekly check job
gcloud scheduler jobs create http pbp-weekly-check \
  --schedule="0 15 * * 1" \
  --uri="https://monitoring-endpoint.run.app/validate/pbp/all" \
  --http-method=POST \
  --time-zone="America/New_York"
```

### Option 3: GitHub Actions (CI/CD)

```yaml
# .github/workflows/pbp-validation.yml
name: Play-by-Play Daily Validation
on:
  schedule:
    - cron: '0 14 * * *'  # 9 AM ET during NBA season
  workflow_dispatch:  # Manual trigger

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup gcloud
        uses: google-github-actions/setup-gcloud@v1
      - name: Run validation
        run: |
          ./scripts/validate-nbac-pbp yesterday > validation_results.txt
          cat validation_results.txt
      - name: Alert on failure
        if: failure()
        uses: 8398a7/action-slack@v3
        with:
          status: ${{ job.status }}
          channel: '#data-quality-alerts'
```

---

## Slack Alert Integration

Create a wrapper script for Slack notifications:

```bash
#!/bin/bash
# File: scripts/validate-nbac-pbp-with-alerts

SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Run validation
RESULT=$(./scripts/validate-nbac-pbp yesterday 2>&1)
EXIT_CODE=$?

# Check for critical issues
if echo "$RESULT" | grep -q "🔴 CRITICAL"; then
  # Send Slack alert
  curl -X POST -H 'Content-type: application/json' \
    --data "{
      \"text\":\"🔴 CRITICAL: NBA.com Play-by-Play Validation Failed\",
      \"blocks\":[{
        \"type\":\"section\",
        \"text\":{\"type\":\"mrkdwn\",\"text\":\"*Play-by-Play Validation Alert*\n\`\`\`$RESULT\`\`\`\"}
      }]
    }" \
    $SLACK_WEBHOOK_URL
elif echo "$RESULT" | grep -q "⚠️ WARNING"; then
  # Send warning notification
  curl -X POST -H 'Content-type: application/json' \
    --data "{\"text\":\"⚠️ Play-by-Play validation warnings detected. Check logs.\"}" \
    $SLACK_WEBHOOK_URL
fi

# Output results to console
echo "$RESULT"
exit $EXIT_CODE
```

---

## Validation Query Reference

| Query | Runtime | When to Run | Alert Threshold |
|-------|---------|-------------|-----------------|
| `yesterday` | <10s | Daily 9 AM | 0 processed games = 🔴 |
| `missing` | ~30s | Daily 9 AM, Weekly review | Yesterday in results = 🔴 |
| `games` | ~20s | Weekly Monday | Any 🔴 status = ⚠️ |
| `events` | ~15s | Weekly Monday | Missing core events = ⚠️ |
| `players` | ~45s | Weekly Monday | >10% missing = ⚠️ |
| `scores` | ~30s | Weekly Monday | Score mismatches = 🔴 |
| `week` | ~10s | Weekly Monday | Trend breaks = ⚠️ |
| `all` | ~3 min | Monthly report | N/A (full audit) |

---

## Troubleshooting Common Issues

### "Query requires partition filter"

**Error**: `Cannot query over table without a filter...`  
**Cause**: Missing `WHERE game_date >= 'YYYY-MM-DD'` in query  
**Fix**: All queries include partition filters, this shouldn't happen  
**Action**: Check query file wasn't modified  

### "No data returned"

**Symptom**: All queries return empty results  
**Cause**: No play-by-play data in table for date range  
**Fix**: Expected if scraper hasn't run yet  
**Action**: Verify scraper is scheduled during NBA season  

### "All games showing as missing"

**Symptom**: `missing` query shows hundreds of games  
**Cause**: Scraper not running or historical backfill not done  
**Fix**: Expected current state (only 2 test games exist)  
**Action**: Review BACKFILL_OPPORTUNITY.md for expansion plan  

### "Score anomalies every game"

**Symptom**: Every game shows score decrease warnings  
**Cause**: Period transitions or processor bug  
**Fix**: Review specific event_sequences  
**Action**: May need processor enhancement for period handling  

---

## Seasonal Schedule

### Regular Season (October - April)

**Daily**:
- 9 AM: Run `yesterday` check
- Alert on 🔴 critical issues immediately

**Weekly**:
- Monday 10 AM: Run full validation suite
- Document any ⚠️ warnings for monthly review

**Monthly**:
- First Monday: Generate quality report
- Review with team, prioritize fixes

### Playoffs (April - June)

**Increased Monitoring**:
- Run `yesterday` check twice daily (9 AM, 9 PM)
- Lower tolerance for warnings (playoff games high value)
- Same-day investigation of any issues

### Offseason (July - September)

**Reduced Monitoring**:
- Weekly validation only (Monday 10 AM)
- Focus on backfill opportunities
- Processor improvements and bug fixes

---

## Success Metrics

Track these metrics over the season:

**Coverage**:
- Target: >95% of scheduled games have play-by-play
- Current: 0.04% (2 of 5,400+ games)
- Goal: 95%+ when season starts

**Quality**:
- Target: <5% games with warnings
- Target: 0% games with critical issues
- Target: 100% score matches with box scores

**Timeliness**:
- Target: Yesterday's games available by 9 AM ET
- Target: All games processed within 12 hours of completion

**Completeness**:
- Target: 450-600 events per game
- Target: 15-20 players per game
- Target: All core event types present

---

## Contact Information

**Data Quality Issues**: #data-quality-alerts (Slack)  
**Processor Bugs**: Create issue in GitHub repo  
**Urgent Issues**: Page on-call engineer  
**Questions**: Data Engineering Team lead  

---

## Change Log

**October 13, 2025**:
- Initial monitoring schedule created
- Documented known shot_made detection issue
- Defined daily/weekly/monthly cadences

**Next Review**: When NBA season starts (October 2025)

---

## Quick Reference Commands

```bash
# Daily morning check
./scripts/validate-nbac-pbp yesterday

# Weekly full audit
./scripts/validate-nbac-pbp all

# Generate CSV reports
./scripts/validate-nbac-pbp games --csv > games_$(date +%Y%m%d).csv
./scripts/validate-nbac-pbp missing --csv > missing_$(date +%Y%m%d).csv

# Check specific game
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_raw.nbac_play_by_play\`
WHERE game_date = 'YYYY-MM-DD'
ORDER BY event_sequence
LIMIT 100
"
```

Remember: **Validation catches issues, but quick response prevents revenue impact!**
