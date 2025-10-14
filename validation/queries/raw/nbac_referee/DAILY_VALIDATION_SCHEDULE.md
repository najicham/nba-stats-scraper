# NBA.com Referee Assignments - Daily Validation Schedule

**Purpose:** Automated daily validation during NBA season (October - June)  
**Goal:** Catch data issues within 24 hours

---

## Daily Schedule

### 9:00 AM PT - Morning Validation ⭐ PRIMARY CHECK

**What it does:** Verifies yesterday's referee assignments were captured correctly

**Query to run:**
```bash
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

**Expected output:**
```
Status: ✅ Complete
- All scheduled games have referee data
- Each game has 3 officials (regular) or 4 officials (playoffs)
```

**Alert conditions:**
- ✅ Complete → No action needed
- ⚪ No games scheduled → Normal (off day)
- ⚠️ WARNING → Review within 1 hour
- ❌ CRITICAL → Immediate action required

**Automation command:**
```bash
# Add to crontab or Cloud Scheduler
0 9 * * * cd /path/to/nba-stats-scraper && bq query --use_legacy_sql=false < validation/queries/raw/nbac_referee/daily_check_yesterday.sql
```

---

### 3:00 PM PT - Afternoon Check (Optional)

**What it does:** Verifies tomorrow's referee assignments are published

**Query to run:**
```bash
bq query --use_legacy_sql=false < realtime_scraper_check.sql
```

**Expected output:**
```
Tomorrow's games: X
Tomorrow's games with refs: X
Status: ✅ All games have refs
```

**Why it matters:** NBA.com publishes next day's refs by 2-3 PM PT. Catching missing refs early gives time to fix before game day.

**Alert conditions:**
- Before 3 PM: No alert needed
- After 3 PM: If tomorrow has games but no refs → ⚠️ Warning
- After 5 PM: If tomorrow has games but no refs → ❌ Critical

---

## Weekly Review (Monday 10:00 AM PT)

**What it does:** Reviews past week's data collection health

**Queries to run:**
```bash
# 1. Weekly trend
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql

# 2. Data quality check
bq query --use_legacy_sql=false < official_count_validation.sql
```

**Review checklist:**
- [ ] All 7 days have data
- [ ] No games with wrong official counts
- [ ] All status = "✅ Complete"

**If issues found:**
- Document missing dates
- Plan backfill for missing games

---

## Manual Queries (As Needed)

### When to run season completeness:
```bash
# After backfills or monthly
bq query --use_legacy_sql=false < season_completeness_check.sql
```

### When to check playoffs:
```bash
# During/after playoff games (April - June)
bq query --use_legacy_sql=false < verify_playoff_completeness.sql
```

### When to find specific missing games:
```bash
# When season_completeness shows gaps
bq query --use_legacy_sql=false < find_missing_regular_season_games.sql
```

---

## Cloud Scheduler Setup (Production)

### Morning Check Job

```bash
# Create Cloud Scheduler job
gcloud scheduler jobs create http referee-validation-daily \
  --location=us-west2 \
  --schedule="0 9 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="YOUR_CLOUD_RUN_JOB_URL" \
  --http-method=POST \
  --message-body='{"query": "daily_check_yesterday"}'
```

### Afternoon Check Job (Optional)

```bash
gcloud scheduler jobs create http referee-validation-realtime \
  --location=us-west2 \
  --schedule="0 15 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="YOUR_CLOUD_RUN_JOB_URL" \
  --http-method=POST \
  --message-body='{"query": "realtime_scraper_check"}'
```

---

## Alert Integration

### Slack Notifications

**Webhook setup:**
```bash
# Set environment variable
export SLACK_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Send alert when status != Complete
# (Add to your Cloud Run job or cron script)
```

**Message format:**
```
🏀 Referee Validation Alert
Date: 2025-10-12
Status: ⚠️ WARNING
Issue: 3 games missing referee data
Action: Run backfill for yesterday's date
```

### PagerDuty (Critical Only)

Trigger PagerDuty when:
- Status = ❌ CRITICAL (no referee data)
- Any game has 0 officials
- Consecutive failures (2+ days)

---

## Troubleshooting Common Issues

### Issue: Yesterday's games missing

**Fix:**
```bash
# 1. Check what's missing
bq query --use_legacy_sql=false < find_missing_regular_season_games.sql

# 2. Re-run scraper for yesterday
python scripts/scrapers/nba_com/nbac_referee_scraper.py \
  --date $(date -d yesterday +%Y-%m-%d)

# 3. Process data
gcloud run jobs execute nbac-referee-processor-backfill \
  --region=us-west2 \
  --args="--start-date,$(date -d yesterday +%Y-%m-%d),--end-date,$(date -d yesterday +%Y-%m-%d)"

# 4. Validate again
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

### Issue: Wrong official count

**Fix:**
```bash
# 1. Find games with wrong counts
bq query --use_legacy_sql=false < official_count_validation.sql

# 2. Check source data
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_raw.nbac_referee_game_assignments\`
WHERE game_id = 'GAME_ID'
  AND game_date >= '2024-01-01'"

# 3. Delete bad data
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_raw.nbac_referee_game_assignments\`
WHERE game_id = 'GAME_ID'
  AND game_date >= '2024-01-01'"

# 4. Re-scrape and reprocess
```

---

## Seasonal Adjustments

### Regular Season (Oct - Apr)
- **Run:** Daily check at 9 AM
- **Run:** Afternoon check at 3 PM (optional)
- **Expect:** 3 officials per game

### Playoffs (Apr - Jun)
- **Run:** Daily check at 9 AM (CRITICAL)
- **Run:** Afternoon check at 3 PM (CRITICAL)
- **Expect:** 4 officials per game
- **Higher priority:** Playoff games have higher revenue impact

### Offseason (Jul - Sep)
- **Pause:** All automated checks
- **Run manually:** Only for historical validation

---

## Quick Commands Reference

```bash
# Daily morning check (run at 9 AM)
bq query --use_legacy_sql=false < daily_check_yesterday.sql

# Weekly review (run Monday 10 AM)
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql

# Real-time check (run at 3 PM)
bq query --use_legacy_sql=false < realtime_scraper_check.sql

# Full validation (after backfills)
bq query --use_legacy_sql=false < season_completeness_check.sql

# Find missing games (when gaps detected)
bq query --use_legacy_sql=false < find_missing_regular_season_games.sql

# Check official counts (data quality)
bq query --use_legacy_sql=false < official_count_validation.sql

# Verify playoffs (during/after playoffs)
bq query --use_legacy_sql=false < verify_playoff_completeness.sql
```

---

## Success Metrics

**Daily target:**
- ✅ Status = "Complete" every morning
- ✅ 0 games with wrong official count
- ✅ Response time < 2 hours for any issues

**Weekly target:**
- ✅ 7/7 days successful
- ✅ < 2 warning alerts per week
- ✅ 0 critical alerts

**Monthly target:**
- ✅ 95%+ daily success rate
- ✅ All missing games backfilled within 48 hours
- ✅ Complete season coverage maintained

---

## Contact & Escalation

**Primary:** Data Engineering Team  
**Slack:** #nba-data-quality  
**Validation Queries:** `validation/queries/raw/nbac_referee/`

**Escalation:**
1. Check validation output
2. Review missing games query
3. Check scraper logs
4. Manual backfill if needed
5. Escalate if persistent issues

---

**Status:** Ready for production after backfill completion  
**Last Updated:** October 13, 2025
