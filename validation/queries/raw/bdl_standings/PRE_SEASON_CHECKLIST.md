# BDL Standings Validation - Pre-Season Checklist

**Season:** 2025-26 NBA Season  
**Season Start:** Tuesday, October 22, 2025  
**Checklist Deadline:** Monday, October 20, 2025

---

## ☑️ 1. Update Date Ranges

### **find_missing_dates.sql** (CRITICAL)

```bash
vim validation/queries/raw/bdl_standings/find_missing_dates.sql
```

**Update lines 23-24:**
```sql
'2025-10-22',  -- Season start (Tuesday, Oct 22, 2025)
'2026-06-20'   -- Season end (estimated playoffs end)
```

**Update line 68:**
```sql
WHERE date_recorded BETWEEN '2025-10-22' AND '2026-06-20'
```

**Verify the change:**
```bash
grep -n "2025-10-22\|2026-06-20" validation/queries/raw/bdl_standings/find_missing_dates.sql
```

---

## ☑️ 2. Test All Validation Queries

```bash
cd ~/code/nba-stats-scraper

# Test each query individually
./scripts/validate-bdl-standings daily
./scripts/validate-bdl-standings weekly  
./scripts/validate-bdl-standings coverage
./scripts/validate-bdl-standings conference
./scripts/validate-bdl-standings quality
./scripts/validate-bdl-standings missing

# Or run all at once
./scripts/validate-bdl-standings all
```

**Expected Results:**
- ✅ All queries execute without errors
- ⚪ Daily/Weekly show "No data (offseason - normal)" or "MISSING" (expected before season)
- ✅ Conference/Quality show last season's data
- ✅ Missing shows no dates (or dates from last season, not this season)

---

## ☑️ 3. Verify Scraper Configuration

```bash
# Check scraper is ready
gcloud run jobs describe bdl-standings-scraper --region=us-central1

# Verify schedule (should run daily at 8 AM PT)
gcloud scheduler jobs describe bdl-standings-scraper-daily --location=us-central1
```

**Expected:**
- Job exists and is active
- Schedule: `0 8 * * *` (8 AM PT daily)
- Season dates configured correctly

---

## ☑️ 4. Verify Processor Configuration

```bash
# Check processor is ready
gcloud run jobs describe bdl-standings-processor --region=us-central1

# Test processor can connect to database
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.bdl_standings\` LIMIT 1"
```

**Expected:**
- Processor job exists
- Database connection works
- Table schema is correct

---

## ☑️ 5. Verify GCS Bucket Permissions

```bash
# Check bucket exists and is accessible
gsutil ls gs://nba-props-data/ball-dont-lie/standings/

# Verify write permissions
gsutil cp /tmp/test.txt gs://nba-props-data/ball-dont-lie/standings/test.txt
gsutil rm gs://nba-props-data/ball-dont-lie/standings/test.txt
```

**Expected:**
- Bucket accessible
- Can write and delete files
- Folder structure exists

---

## ☑️ 6. Set Up Monitoring & Alerts

### **Option A: Cloud Scheduler Validation Job**

```bash
# Create daily validation job (if not exists)
gcloud scheduler jobs create http bdl-standings-daily-validation \
  --location=us-central1 \
  --schedule="0 9 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://YOUR_VALIDATION_SERVICE_URL/validate/bdl-standings/daily" \
  --http-method=POST
```

### **Option B: Manual Monitoring**

Set up calendar reminders:
- **Daily:** 9:00 AM PT - Run daily validation
- **Monday:** 9:30 AM PT - Run weekly validation suite
- **First Monday:** 10:00 AM PT - Run coverage check

---

## ☑️ 7. Set Up Alert Channels

### **Slack Notifications** (Recommended)

```bash
# Configure Slack webhook for alerts
# Add to your alerting service or Cloud Function
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

### **Email Alerts**

Configure Cloud Monitoring alerts for:
- Scraper job failures
- Processor job failures
- Validation check failures

---

## ☑️ 8. Document Expected Behavior

Review and confirm understanding:

**During Regular Season (Oct-Apr):**
- ✅ Daily scraper runs at 8 AM PT
- ✅ Daily validation runs at 9 AM PT
- ✅ Expected: 30 teams, 15 East/15 West, every day
- 🔴 Alert if: Missing data, wrong team count

**During Playoffs (Apr-Jun):**
- ✅ Scraper continues daily
- ✅ Validation continues daily
- ⚠️ Standings update less frequently (games less frequent)

**During Offseason (Jul-Sep):**
- ⚪ Scraper may return no new data (normal)
- ⚪ Final standings frozen
- ✅ No alerts for missing data

---

## ☑️ 9. Create Runbook

Save this information where team can access:

```bash
# Create operations directory if not exists
mkdir -p docs/operations

# Copy guide to operations docs
cp validation/queries/raw/bdl_standings/README.md \
   docs/operations/bdl-standings-validation-guide.md
```

Document:
- Daily validation procedure
- Alert response steps
- Escalation contacts
- Known issues and workarounds

---

## ☑️ 10. Test End-to-End on Opening Day

**Tuesday, October 22, 2025 - Opening Day Test:**

**Morning (8:00-9:00 AM PT):**
```bash
# Check scraper ran
gcloud run jobs executions list --job=bdl-standings-scraper --limit=1

# Check GCS for new files
gsutil ls gs://nba-props-data/ball-dont-lie/standings/2025-26/2025-10-22/
```

**Morning (9:00 AM PT):**
```bash
# Run validation
./scripts/validate-bdl-standings daily
```

**Expected First Day Results:**
```
Status: ✅ Complete
Team count: 30
East teams: 15
West teams: 15
Avg games played: 0.0-1.0 (opening day)
```

**If Problems:**
1. Check scraper logs
2. Verify BDL API is returning data
3. Re-run scraper manually if needed
4. Contact BDL support if API issues

---

## ☑️ 11. Week 1 Monitoring Plan

**Days 1-7 (Oct 22-28):**
- ✅ Run daily validation every morning
- ✅ Document any issues
- ✅ Verify coverage reaches 7/7 by end of week
- ✅ Run weekly suite on Monday, Oct 28

**Success Criteria:**
- 7/7 days with complete data
- No critical issues
- Team comfortable with validation process

---

## ☑️ 12. Backup and Recovery Plan

### **Before Season:**
```bash
# Backup current validation queries
tar -czf bdl-standings-validation-backup-$(date +%Y%m%d).tar.gz \
  validation/queries/raw/bdl_standings/ \
  scripts/validate-bdl-standings
```

### **During Season:**
```bash
# Weekly backup of validation results
mkdir -p validation/results/bdl_standings/
./scripts/validate-bdl-standings weekly --csv > \
  validation/results/bdl_standings/weekly-$(date +%Y%m%d).csv
```

---

## 📋 Final Checklist Summary

- [ ] Updated date ranges in `find_missing_dates.sql`
- [ ] Tested all 6 validation queries
- [ ] Verified scraper configuration and schedule
- [ ] Verified processor configuration
- [ ] Verified GCS bucket permissions
- [ ] Set up monitoring (Cloud Scheduler or calendar)
- [ ] Configured alert channels (Slack/Email)
- [ ] Documented expected behavior
- [ ] Created/updated runbook
- [ ] Planned opening day test
- [ ] Planned week 1 monitoring
- [ ] Created backup and recovery plan

---

## ✅ Sign-Off

**Completed By:** ___________________  
**Date:** ___________________  
**Ready for Season:** [ ] Yes [ ] No  
**Notes:** _________________________

---

**After completing this checklist, you're ready for the 2025-26 NBA season!**

**First validation run:** Tuesday, October 22, 2025 at 9:00 AM PT
