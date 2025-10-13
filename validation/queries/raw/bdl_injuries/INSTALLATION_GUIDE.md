# BDL Injuries Validation - Installation Guide

## Quick Start

BDL Injuries validation is designed for **daily monitoring during NBA season**. Since this is a current-state snapshot table (not historical), there's no backfill validation needed.

### ✅ You're Ready When:
- NBA season has started (October 2025+)
- BDL injuries scraper is scheduled to run daily
- Data is being collected to `nba_raw.bdl_injuries`

---

## Installation Steps

### 1. Verify Files Are In Place

Check that all validation files exist:

```bash
ls -la validation/queries/raw/bdl_injuries/
```

You should see:
- ✅ `daily_check_yesterday.sql`
- ✅ `weekly_check_last_7_days.sql`
- ✅ `confidence_score_monitoring.sql`
- ✅ `data_quality_check.sql`
- ✅ `realtime_scraper_check.sql`
- ✅ `README.md`
- ✅ `INSTALLATION_GUIDE.md` (this file)

### 2. Set Up CLI Tool

Make the validation script executable:

```bash
chmod +x scripts/validate-bdl-injuries
```

Test the CLI tool:

```bash
./scripts/validate-bdl-injuries help
```

### 3. Verify BigQuery Access

Test that you can query the table:

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as record_count
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
LIMIT 1;
"
```

---

## First Time Validation (When Season Starts)

### Day 1: After First Scraper Run

Once the scraper has run for the first time:

```bash
# Check that data exists
./scripts/validate-bdl-injuries realtime

# Verify quality
./scripts/validate-bdl-injuries quality
```

Expected results:
- ✅ 20-60 injury records
- ✅ 15-25 teams represented
- ✅ 1.0 confidence scores

### Day 2: Set Up Daily Checks

After second day of scraping:

```bash
# Morning routine
./scripts/validate-bdl-injuries daily
```

Expected results:
- ✅ Yesterday shows "Complete" status
- ✅ Injury count in reasonable range
- ✅ Good team coverage

### Week 1: Enable Trend Monitoring

After first week of data:

```bash
# Weekly review
./scripts/validate-bdl-injuries weekly
./scripts/validate-bdl-injuries confidence
```

Expected results:
- ✅ 7 days of data
- ✅ Consistent quality across days
- ✅ Stable confidence scores

---

## Daily Operations Setup

### Automated Morning Checks

Add to your daily workflow or cron job:

```bash
#!/bin/bash
# File: scripts/daily-validation.sh

# BDL Injuries morning check (9 AM)
echo "Checking BDL Injuries..."
./scripts/validate-bdl-injuries daily

# Alert if not complete
if [ $? -ne 0 ]; then
    echo "ALERT: BDL Injuries validation failed!"
    # Add your alerting logic here (Slack, email, etc.)
fi
```

### Schedule with Cron

```bash
# Edit crontab
crontab -e

# Add daily check at 9 AM
0 9 * * * /path/to/nba-stats-scraper/scripts/daily-validation.sh
```

---

## Validation Thresholds

Configure alerts based on these thresholds:

### 🔴 CRITICAL - Page Immediately
```bash
# No data during season
# Injury count < 10
# Confidence < 0.6
```

### 🟡 ERROR - Alert to Channel
```bash
# Confidence < 0.8
# Team coverage < 10
# Data > 6 hours old
```

### ⚠️  WARNING - Log for Review
```bash
# Confidence below trend
# Low return date parsing
# Increased quality flags
```

---

## Testing Before Season

If you want to test before the season starts:

### Option 1: Use Existing Test Data

Your processor ran in August 2025, so you have test data:

```bash
# Check what data exists
bq query --use_legacy_sql=false "
SELECT 
  scrape_date,
  COUNT(*) as injuries,
  COUNT(DISTINCT team_abbr) as teams
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
GROUP BY scrape_date
ORDER BY scrape_date DESC;
"

# Test queries on this data
./scripts/validate-bdl-injuries daily
```

### Option 2: Wait for Season

- Queries will auto-suppress off-season alerts
- "⚪ Expected: Off-season" status is normal
- Start validation when season begins

---

## Weekly Review Checklist

Every Monday during season:

```bash
# 1. Check yesterday was successful
./scripts/validate-bdl-injuries daily

# 2. Review weekly trends
./scripts/validate-bdl-injuries weekly

# 3. Monitor parsing quality
./scripts/validate-bdl-injuries confidence

# 4. Comprehensive quality check
./scripts/validate-bdl-injuries quality
```

Save a report:

```bash
# Generate weekly report
./scripts/validate-bdl-injuries all > reports/bdl_injuries_$(date +%Y%m%d).txt
```

---

## Troubleshooting

### "No data found" Errors

**Cause:** Season hasn't started or scraper hasn't run  
**Solution:** Check if season is active (Oct-Jun) and verify scraper schedule

### Low Injury Counts

**Cause:** May be legitimate (healthy league) or scraper issue  
**Solution:** 
1. Check if all teams represented
2. Compare with NBA.com injury report
3. Verify scraper logs

### Confidence Score Drops

**Cause:** BDL API format changed  
**Solution:**
1. Check `data_quality_flags` field
2. Review parser logic
3. Update processor if needed

### Missing Teams

**Cause:** Some teams may have zero injuries (normal)  
**Solution:** Over 30 days, expect 29-30 teams total

---

## Integration with Other Systems

### Slack Notifications

```bash
# Add to daily check script
RESULT=$(./scripts/validate-bdl-injuries daily)

if echo "$RESULT" | grep -q "CRITICAL\|ERROR"; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"BDL Injuries Alert: $RESULT\"}" \
        YOUR_SLACK_WEBHOOK_URL
fi
```

### BigQuery Validation Tables

Save daily results for tracking:

```bash
# Save daily check to table
./scripts/validate-bdl-injuries daily \
    --table bdl_injuries_daily_$(date +%Y%m%d)

# Query historical validation results
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_validation.bdl_injuries_daily_*\`
WHERE _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY))
ORDER BY _TABLE_SUFFIX DESC;
"
```

---

## Season Timeline

### Pre-Season (September)
- ✅ Verify files installed
- ✅ Test CLI tool works
- ✅ Set up automation
- ⚪ No data validation needed

### Season Start (October)
- ✅ First scraper run
- ✅ Daily checks begin
- ✅ Monitor initial quality
- ✅ Establish baselines

### Regular Season (Oct-Apr)
- ✅ Daily validation
- ✅ Weekly reviews
- ✅ Quality monitoring
- ✅ Trend analysis

### Playoffs (Apr-Jun)
- ✅ Continue daily checks
- ✅ Expect 20-30 injuries
- ✅ Fewer teams represented (normal)

### Off-Season (Jul-Sep)
- ⚪ Validation paused
- ⚪ No alerts expected
- ✅ Review season performance

---

## Success Metrics

Your validation is working well when:

✅ **Daily checks pass** with "Complete" status  
✅ **Weekly trends** show consistent coverage  
✅ **Confidence scores** stay at 1.0  
✅ **Quality checks** show minimal flags  
✅ **Real-time status** shows fresh data  

---

## Support

**Questions?**
- Check `README.md` for query details
- Review example queries in other validation folders
- Consult NBA Data Validation Master Guide

**Found an Issue?**
- Check query logic
- Verify date ranges
- Compare with reference implementations

---

**Status:** Ready for NBA Season Start  
**Last Updated:** October 13, 2025  
**Next Review:** When season begins (October 2025)
