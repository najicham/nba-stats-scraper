# BDL Standings - Daily Validation Operations Guide

**Version:** 1.0  
**Last Updated:** 2025-10-14  
**Season:** 2025-26 NBA Season

---

## 📅 Daily Schedule (During Season)

### **Every Morning - 9:00 AM PT**

After the overnight scraper runs complete, execute the daily validation check:

```bash
cd ~/code/nba-stats-scraper
./scripts/validate-bdl-standings daily
```

#### **Expected Output (Healthy System):**
```
+------------+------------+-------------+------------+------------+------------------+
| check_date | team_count | conferences | east_teams | west_teams | avg_games_played |
+------------+------------+-------------+------------+------------+------------------+
| 2025-10-13 |         30 |           2 |         15 |         15 |             X.X  |
+------------+------------+-------------+------------+------------+------------------+
Status: ✅ Complete
Recommendation: No action needed - data looks good!
```

#### **Alert Conditions:**
- 🔴 **CRITICAL:** Status shows "No data during NBA season" 
  - **ACTION:** Check scraper logs immediately
  - Verify GCS bucket for missing files
  - Re-run scraper for yesterday's date
  
- ⚠️ **WARNING:** Team count ≠ 30 or conference imbalance
  - **ACTION:** Check processor logs
  - Verify team abbreviation mapping
  - Re-run processor if needed

---

## 📅 Weekly Schedule (During Season)

### **Every Monday - 9:30 AM PT**

After daily check passes, run weekly validation suite:

```bash
# 1. Review past week's coverage
./scripts/validate-bdl-standings weekly

# 2. Validate conference rankings
./scripts/validate-bdl-standings conference

# 3. Check data quality
./scripts/validate-bdl-standings quality
```

#### **Expected Results:**

**Weekly Check:**
- 7/7 days with data
- Coverage: 100%
- All days showing "✅ Complete"

**Conference Check:**
- Both conferences: "✅ Valid"
- 15 teams per conference
- Rankings 1-15, no gaps/duplicates

**Quality Check:**
- Overall quality: >95%
- No CRITICAL issues
- Minor home/road discrepancies acceptable (<5%)

#### **Alert Conditions:**

**Weekly Check:**
- Missing days: Identify and backfill
- Incomplete days: Re-run scraper/processor

**Conference Check:**
- Conference imbalance: Check team mappings
- Ranking gaps/duplicates: Verify BDL API data

**Quality Check:**
- CRITICAL issues: Investigate data source
- <90% quality: Review processor logic

---

## 📅 Monthly Schedule (During Season)

### **First Monday of Each Month - 10:00 AM PT**

Run comprehensive season coverage check:

```bash
./scripts/validate-bdl-standings coverage
```

#### **Expected Output:**
- Previous month: >95% coverage
- Current month: Daily coverage starting
- Status: "✅ Excellent" or "✅ Good"

#### **Alert Conditions:**
- <90% coverage: Run `missing` query to identify gaps
- Poor data quality: Review monthly patterns
- Missing weeks: Systematic scraper issue

---

## 🚨 Incident Response

### **Missing Data (CRITICAL)**

1. **Confirm Issue:**
   ```bash
   ./scripts/validate-bdl-standings daily
   ```

2. **Identify Missing Dates:**
   ```bash
   ./scripts/validate-bdl-standings missing
   ```

3. **Check Scraper Logs:**
   ```bash
   # Check Cloud Run job logs
   gcloud run jobs executions list --job=bdl-standings-scraper --limit=10
   ```

4. **Check GCS Bucket:**
   ```bash
   # Verify files exist
   gsutil ls gs://nba-props-data/ball-dont-lie/standings/2024-25/$(date -d yesterday +%Y-%m-%d)/
   ```

5. **Remediation:**
   ```bash
   # Re-run scraper for specific date (if needed)
   gcloud run jobs execute bdl-standings-scraper \
     --args="--date=2025-10-13" \
     --wait
   
   # Re-run processor
   gcloud run jobs execute bdl-standings-processor \
     --args="--date=2025-10-13" \
     --wait
   ```

6. **Verify Fix:**
   ```bash
   ./scripts/validate-bdl-standings daily
   ```

---

### **Data Quality Issues (WARNING)**

1. **Identify Affected Teams:**
   ```bash
   ./scripts/validate-bdl-standings quality
   ```

2. **Check for Patterns:**
   - Multiple teams: BDL API issue
   - Single team: Team-specific data problem
   - Calculation errors: Processor bug

3. **Investigate Source:**
   ```bash
   # Check raw data in GCS
   gsutil cat gs://nba-props-data/ball-dont-lie/standings/2024-25/$(date -d yesterday +%Y-%m-%d)/*.json
   ```

4. **Remediation:**
   - If BDL API issue: Wait for fix or contact BDL support
   - If processor issue: Fix code and re-run
   - If transient: Re-scrape specific date

---

### **Conference Ranking Issues**

1. **Review Ranking Details:**
   ```bash
   ./scripts/validate-bdl-standings conference
   ```

2. **Common Causes:**
   - Ties in records (normal - teams may have same rank)
   - API tiebreaker logic differs from NBA official
   - Missing/incorrect win percentage

3. **Validation:**
   - Check NBA.com official standings
   - Compare with BDL API response
   - Document expected discrepancies

---

## 📊 Export and Reporting

### **CSV Export (for analysis)**
```bash
# Export missing dates for backfill planning
./scripts/validate-bdl-standings missing --csv > missing_dates.csv

# Export weekly summary for reporting
./scripts/validate-bdl-standings weekly --csv > weekly_report.csv
```

### **JSON Export (for automation)**
```bash
# Export quality check results
./scripts/validate-bdl-standings quality --json > quality_report.json
```

---

## 🔧 Automation Setup

### **Cloud Scheduler - Daily Validation**

Create a Cloud Scheduler job to run daily validation and alert on failures:

```bash
# Create validation Cloud Run job (runs validation and sends alerts)
gcloud scheduler jobs create http bdl-standings-daily-validation \
  --location=us-central1 \
  --schedule="0 9 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://YOUR_VALIDATION_SERVICE_URL/validate/bdl-standings/daily" \
  --http-method=POST \
  --description="Daily BDL standings validation at 9 AM PT"
```

### **Slack/Email Alerts**

Configure alerts to notify on validation failures:
- Daily check status ≠ "✅ Complete" during season
- Missing data detected
- Data quality <95%
- Conference ranking issues

---

## 📝 Pre-Season Checklist

**Before 2025-26 Season Starts (October 2025):**

- [ ] Update `find_missing_dates.sql` date range (lines 23-24):
  ```sql
  '2025-10-22',  -- Season start
  '2026-06-20'   -- Season end
  ```

- [ ] Test all validation queries:
  ```bash
  ./scripts/validate-bdl-standings all
  ```

- [ ] Verify scraper schedule is active

- [ ] Set up Cloud Scheduler for daily validation

- [ ] Configure alert channels (Slack/Email)

- [ ] Review and update expected metrics if needed

---

## 📈 Success Metrics (During Season)

### **Daily:**
- ✅ 100% of days with data (30 teams each)
- ✅ Zero CRITICAL alerts
- ⏱️ Validation runs complete in <30 seconds

### **Weekly:**
- ✅ 7/7 days coverage
- ✅ Data quality >95%
- ✅ All conference rankings valid

### **Monthly:**
- ✅ >95% season coverage
- ✅ <5 backfill operations
- ✅ No systematic issues

---

## 🔗 Quick Reference

### **Common Commands:**
```bash
# Daily routine (9 AM)
./scripts/validate-bdl-standings daily

# Weekly routine (Monday 9:30 AM)
./scripts/validate-bdl-standings weekly
./scripts/validate-bdl-standings conference
./scripts/validate-bdl-standings quality

# Monthly routine (First Monday)
./scripts/validate-bdl-standings coverage

# Troubleshooting
./scripts/validate-bdl-standings missing
./scripts/validate-bdl-standings all
```

### **File Locations:**
- **Queries:** `validation/queries/raw/bdl_standings/`
- **CLI Tool:** `scripts/validate-bdl-standings`
- **Documentation:** `validation/queries/raw/bdl_standings/README.md`

### **Related Systems:**
- **Scraper:** `data_scrapers/balldontlie/bdl_standings_scraper.py`
- **Processor:** `data_processors/raw/balldontlie/bdl_standings_processor.py`
- **Database:** `nba-props-platform.nba_raw.bdl_standings`

---

## 🆘 Support

**For Issues:**
1. Check this guide first
2. Review scraper/processor logs
3. Check GCS bucket for raw data
4. Verify BDL API status
5. Document incident and resolution

**Documentation:**
- Full validation guide: `validation/queries/raw/bdl_standings/README.md`
- Processor docs: `NBA Processors Reference Documentation`
- Master validation guide: `NBA_DATA_VALIDATION_MASTER_GUIDE.md`

---

**Remember:** Validation is your early warning system. Run it daily, respond to alerts quickly, and maintain >95% data quality throughout the season!
