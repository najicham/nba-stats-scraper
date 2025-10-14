# BDL Injuries - Daily Operations Guide

**Start Date:** When NBA season begins (October 22, 2025)  
**Frequency:** Every day during season (Oct-Jun)  
**Time:** 9:00 AM PT (after scraper completes at 8 AM PT)  
**Duration:** 2-5 minutes per day

---

## 📋 Daily Morning Checklist

### ⏰ 9:00 AM PT - Automated Check

Your cron job runs automatically:
```bash
# This runs automatically via cron
/path/to/scripts/daily-bdl-injuries-validation.sh
```

**No action needed unless you receive an alert.**

---

### 🚨 If You Receive an Alert

#### Alert: 🔴 CRITICAL - No Data

**What it means:** Yesterday's scraper didn't run or processor failed

**What to do:**

```bash
# 1. Check if data exists in GCS
gsutil ls gs://nba-scraped-data/ball-dont-lie/injuries/$(date -d yesterday +%Y-%m-%d)/

# 2. If GCS file exists, check processor
gcloud run jobs executions list \
  --job=bdl-injuries-processor \
  --region=us-west2 \
  --limit=5

# 3. Check processor logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=bdl-injuries-processor" \
  --limit=20 \
  --format=json

# 4. Manually trigger processor if needed
gcloud run jobs execute bdl-injuries-processor-backfill \
  --region=us-west2 \
  --args="--start-date=$(date -d yesterday +%Y-%m-%d),--end-date=$(date -d yesterday +%Y-%m-%d)"

# 5. Verify fix
./scripts/validate-bdl-injuries daily
```

**Expected resolution time:** 15-30 minutes

---

#### Alert: 🟡 ERROR - Low Count

**What it means:** Data exists but very few injuries (< 10)

**What to do:**

```bash
# 1. Check actual count
bq query --use_legacy_sql=false "
SELECT COUNT(*) as injuries, COUNT(DISTINCT team_abbr) as teams
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
"

# 2. Compare with NBA.com injuries
bq query --use_legacy_sql=false "
SELECT 
  'BDL' as source, 
  COUNT(DISTINCT player_lookup) as injured_players
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)

UNION ALL

SELECT 
  'NBA.com' as source,
  COUNT(DISTINCT player_lookup) as injured_players
FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
WHERE report_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
"

# 3. If NBA.com also low → legitimate (healthy league)
# 4. If NBA.com high → BDL API issue, investigate
```

**Decision:** If both sources low (< 15), accept as legitimate. Otherwise investigate.

---

#### Alert: ⚠️ WARNING - Low Confidence

**What it means:** Parsing quality dropped below 0.9

**What to do:**

```bash
# 1. Check which records have low confidence
bq query --use_legacy_sql=false "
SELECT 
  player_full_name,
  team_abbr,
  parsing_confidence,
  data_quality_flags,
  injury_description
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND parsing_confidence < 0.9
ORDER BY parsing_confidence
LIMIT 20;
"

# 2. Review data quality flags
bq query --use_legacy_sql=false "
SELECT 
  data_quality_flags,
  COUNT(*) as count
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND data_quality_flags IS NOT NULL
GROUP BY data_quality_flags;
"

# 3. Check if BDL API format changed
# Review raw JSON file in GCS
gsutil cat gs://nba-scraped-data/ball-dont-lie/injuries/$(date -d yesterday +%Y-%m-%d)/*.json | head -100
```

**Decision:** If widespread (> 10 records), BDL API may have changed. Escalate to processor team.

---

## 📊 Manual Verification (Optional)

If you want to manually verify (not required):

```bash
# Quick check - run the daily validation
./scripts/validate-bdl-injuries daily

# Expected output during season:
# ✅ Complete: Good coverage
# 10-60 injuries
# 10-25 teams
# Confidence: 1.0
```

---

## 🗓️ Weekly Review (Every Monday)

### 10:00 AM PT - Weekly Check

```bash
# Automated script runs
/path/to/scripts/weekly-bdl-injuries-review.sh

# Generates report at:
# reports/bdl_injuries/weekly_review_YYYYMMDD.txt
```

**Manual review steps:**

```bash
# 1. Read this week's report
cat reports/bdl_injuries/weekly_review_$(date +%Y%m%d).txt

# 2. Look for patterns:
# - Consistent injury counts (20-60 range)?
# - All confidence scores 1.0?
# - Good team coverage?
# - Any increasing error rates?

# 3. Compare to last week (optional)
diff reports/bdl_injuries/weekly_review_*.txt | tail -50
```

**Expected time:** 5-10 minutes

---

## 📈 What "Normal" Looks Like

### Regular Season (Oct-Apr)

**Healthy Status:**
```
✅ Complete: Good coverage
check_date: 2025-01-15
injuries: 45
unique_players: 45
unique_teams: 22
avg_confidence: 1.0
```

**Typical Ranges:**
- Injuries per day: 20-60
- Teams represented: 15-25 (out of 30)
- Confidence score: 1.0
- Return dates parsed: 95-100%

### Playoffs (Apr-Jun)

**Adjusted Expectations:**
- Injuries per day: 20-30 (fewer teams playing)
- Teams represented: 8-16 (only playoff teams)
- Everything else same as regular season

### Off-Season (Jul-Sep)

**Expected:**
```
⚪ Expected: Off-season - no scraper run
```
- Zero data is normal
- No alerts
- No action needed

---

## 🔧 Common Issues & Solutions

### Issue 1: "No data today" during season

**Cause:** Scraper or processor didn't run

**Fix:**
1. Check GCS for raw file
2. If file exists, rerun processor
3. If no file, check scraper schedule
4. Verify it's not an off-day (rare in NBA)

---

### Issue 2: "Duplicate records"

**Cause:** Processor bug (if not fixed yet)

**Fix:**
```bash
# Check for duplicates
bq query --use_legacy_sql=false "
SELECT 
  scrape_date,
  COUNT(*) as total,
  COUNT(DISTINCT bdl_player_id) as unique_players
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY scrape_date;
"

# If total != unique_players, processor needs fixing
# See: processors/PROCESSOR_FIX_bdl_injuries.md
```

---

### Issue 3: "Low team coverage" (< 10 teams)

**Cause:** Usually legitimate, but verify

**Fix:**
```bash
# Check which teams are represented
bq query --use_legacy_sql=false "
SELECT team_abbr, COUNT(*) as injuries
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY team_abbr
ORDER BY team_abbr;
"

# Compare with previous days
bq query --use_legacy_sql=false "
SELECT 
  scrape_date,
  COUNT(DISTINCT team_abbr) as teams
FROM \`nba-props-platform.nba_raw.bdl_injuries\`
WHERE scrape_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY scrape_date
ORDER BY scrape_date DESC;
"
```

**Decision:** If consistent with recent days, it's legitimate.

---

### Issue 4: "Confidence score dropped"

**Cause:** BDL API format changed

**Fix:**
1. Review data quality flags
2. Check raw JSON structure
3. Update processor parser if needed
4. Create ticket for processor team

---

## 📞 Escalation Guide

### Level 1: Self-Service (2-5 minutes)
- Run daily validation
- Check logs if alert
- Rerun processor if needed

### Level 2: Investigation (15-30 minutes)
- Compare with NBA.com data
- Review GCS files
- Check Cloud Run logs
- Manual data quality queries

### Level 3: Escalation (Beyond 30 minutes)
- **Scraper issues** → Scraper team
- **Processor issues** → Data engineering team
- **API format changes** → Parser team
- **Data quality** → Analytics team

---

## 💾 Log Management

### Daily Logs

Logs stored in: `logs/validation/bdl_injuries_YYYYMMDD.log`

**Retention:**
- Keep last 90 days
- Archive older logs

**Cleanup script:**
```bash
# Run monthly
find logs/validation/bdl_injuries_*.log -mtime +90 -delete
```

### Weekly Reports

Reports stored in: `reports/bdl_injuries/weekly_review_YYYYMMDD.txt`

**Retention:**
- Keep all season (Oct-Jun)
- Archive at season end

**End-of-season archive:**
```bash
# Run in July
tar -czf archive/bdl_injuries_2024-25_season.tar.gz \
  reports/bdl_injuries/weekly_review_2024*.txt \
  reports/bdl_injuries/weekly_review_2025*.txt
```

---

## 📊 Monthly Reporting

### First Monday of Each Month

**Generate monthly summary:**
```bash
# Run comprehensive validation
./scripts/validate-bdl-injuries all > reports/bdl_injuries/monthly_$(date +%Y%m).txt

# Review key metrics:
cat reports/bdl_injuries/monthly_$(date +%Y%m).txt | grep -A5 "OVERALL_STATS"
```

**Monthly checklist:**
- [ ] All 30 teams appeared at some point
- [ ] Average confidence still 1.0
- [ ] No systematic failures
- [ ] Alert system working correctly
- [ ] Logs not filling disk

---

## 🎯 Success Metrics

Track these monthly:

| Metric | Target | Current |
|--------|--------|---------|
| Daily validation pass rate | > 99% | ___% |
| Average injuries/day | 20-60 | ___ |
| Average confidence | 1.0 | ___ |
| Return date parsing | > 95% | ___% |
| Alert response time | < 30 min | ___ |
| False positive rate | < 5/month | ___ |

---

## 🔄 Seasonal Transitions

### Start of Season (October)
- [ ] Enable daily automation
- [ ] Monitor first week closely
- [ ] Establish baselines
- [ ] Document any issues

### During Season (Oct-Jun)
- [ ] Daily checks run automatically
- [ ] Weekly reviews on schedule
- [ ] Monthly reports generated
- [ ] Issues resolved promptly

### End of Season (June)
- [ ] Generate season summary
- [ ] Archive reports
- [ ] Document improvements needed
- [ ] Disable alerts for off-season

### Off-Season (Jul-Sep)
- [ ] Validation paused (no alerts)
- [ ] Plan improvements
- [ ] Test processor changes
- [ ] Prepare for next season

---

## 📝 Quick Reference Commands

```bash
# Daily check
./scripts/validate-bdl-injuries daily

# Real-time status
./scripts/validate-bdl-injuries realtime

# Full validation
./scripts/validate-bdl-injuries all

# Check GCS files
gsutil ls gs://nba-scraped-data/ball-dont-lie/injuries/$(date +%Y-%m-%d)/

# Rerun processor
gcloud run jobs execute bdl-injuries-processor-backfill \
  --region=us-west2 \
  --args="--start-date=$(date +%Y-%m-%d),--end-date=$(date +%Y-%m-%d)"

# View logs
cat logs/validation/bdl_injuries_$(date +%Y%m%d).log
```

---

## 🎓 Training for New Team Members

**Day 1: Setup**
- Review this document
- Test CLI tool: `./scripts/validate-bdl-injuries help`
- Run test validation on historical data

**Day 2: Practice**
- Run daily validation manually
- Interpret results
- Practice alert response procedures

**Day 3: Automation**
- Review cron setup
- Test alert system
- Verify log locations

**Ongoing:**
- Shadow experienced team member for 1 week
- Handle alerts with guidance
- Graduate to independent operations

---

## ✅ Pre-Season Readiness Checklist

Before season starts (October):

**Setup Complete:**
- [ ] All validation files in place
- [ ] CLI tool tested and working
- [ ] Automation scripts created
- [ ] Cron jobs scheduled correctly
- [ ] Alert system configured
- [ ] Log directories created
- [ ] Team trained on procedures

**Validation Working:**
- [ ] Daily check query tested
- [ ] Weekly check query tested
- [ ] Quality check query tested
- [ ] Confidence monitoring tested
- [ ] Realtime check tested

**Procedures Documented:**
- [ ] Alert response procedures known
- [ ] Escalation paths defined
- [ ] Log management understood
- [ ] Monthly reporting scheduled

**Ready for Season:** When all boxes checked! ✅

---

**Last Updated:** October 13, 2025  
**Status:** Ready for Season Start  
**Next Review:** After First Week of Season

---

## 💡 Tips for Success

1. **Don't panic on first alert** - Most are minor and fixable in minutes
2. **Trust the system** - Validation catches issues before they impact users
3. **Check trends, not single days** - One bad day doesn't mean systemic failure
4. **Document weird issues** - Helps improve the system
5. **Off-season alerts are expected** - Status will say "⚪ Expected"
6. **Playoffs have different patterns** - Lower team counts are normal
7. **Keep this guide handy** - Print or bookmark for quick reference

**Remember:** This validation system is designed to make your job easier, not harder. Most days will be green checkmarks! ✅
