# BigDataBall Play-by-Play - Daily Monitoring Guide

**FILE:** `validation/queries/raw/bigdataball_pbp/DAILY_MONITORING_GUIDE.md`

**Purpose:** Guide for daily validation when 2025-26 NBA season starts  
**Audience:** Data team, DevOps, Analysts  
**Frequency:** Daily during NBA season (October - June)

---

## 📋 Quick Start

### Daily Morning Routine (9 AM - After Processor Runs)

```bash
cd ~/code/nba-stats-scraper

# 1. Quick health check (30 seconds)
./scripts/validate-bigdataball daily

# 2. If issues found, investigate (5-10 minutes)
./scripts/validate-bigdataball missing
./scripts/validate-bigdataball quality

# 3. Review weekly trends (Mondays only - 2 minutes)
./scripts/validate-bigdataball weekly
```

**Expected Time:** 30 seconds/day (30 minutes if issues found)

---

## 🎯 Daily Validation Workflow

### Step 1: Yesterday's Games Check

**Query:** `daily_check_yesterday.sql`  
**Command:** `./scripts/validate-bigdataball daily`  
**When:** Every morning at 9 AM (after overnight processing)

#### What It Checks:
- ✅ Did yesterday's games get collected?
- ✅ Are event counts in normal range (400-600)?
- ✅ Is shot coordinate coverage acceptable (>70%)?
- ✅ Are lineups complete (5 home + 5 away players)?

#### Expected Output:

**✅ Good Day (All Clear):**
```json
{
  "check_date": "2025-10-23",
  "scheduled_games": 12,
  "games_with_data": 12,
  "avg_events_per_game": 467.3,
  "min_events_per_game": 423,
  "pct_shots_with_coords": 82.5,
  "status": "✅ Complete"
}
```

**⚠️ Warning (Investigate):**
```json
{
  "check_date": "2025-10-23",
  "scheduled_games": 12,
  "games_with_data": 11,
  "min_events_per_game": 361,
  "status": "⚠️ WARNING: 1 games missing"
}
```

**❌ Critical (Immediate Action):**
```json
{
  "check_date": "2025-10-23",
  "scheduled_games": 12,
  "games_with_data": 0,
  "status": "❌ CRITICAL: No play-by-play data"
}
```

---

### Step 2: Status Interpretation

| Status | Meaning | Action Required | Priority |
|--------|---------|-----------------|----------|
| ✅ Complete | All games collected, good quality | None - log success | ✅ Normal |
| ✅ No games scheduled | Off day (no NBA games) | None - expected | ⚪ Normal |
| ⏳ PROCESSING | Games completed <4 hours ago | Wait - BigDataBall 2hr delay | ⚪ Normal |
| ⚠️ WARNING | 1-3 games missing or low quality | Investigate specific games | ⚠️ Medium |
| ❌ CRITICAL | No data or >3 games missing | Check scraper/processor immediately | 🔴 High |

---

### Step 3: Troubleshooting by Status

#### Status: "⚠️ WARNING: Low event count"

**Meaning:** One or more games have 380-400 events (lower than usual 450-500).

**Investigation:**
```bash
# Find which games have low events
./scripts/validate-bigdataball quality

# Check specific game
bq query --use_legacy_sql=false "
SELECT game_id, COUNT(*) as events
FROM \`nba-props-platform.nba_raw.bigdataball_play_by_play\`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY game_id
ORDER BY events
"
```

**Common Causes:**
- Short game (blowout, team quit early)
- Overtime (can increase events to 550+)
- BigDataBall partial data release

**Action:**
- If >380 events: Accept (borderline normal)
- If <380 events: Investigate or flag for review
- If <350 events: Re-scrape specific game

---

#### Status: "⚠️ WARNING: Poor coordinate coverage"

**Meaning:** Shot coordinates <70% (shots missing X/Y positions).

**Investigation:**
```bash
# Check coordinate coverage by game
bq query --use_legacy_sql=false "
SELECT 
  game_id,
  COUNT(CASE WHEN event_type = 'shot' THEN 1 END) as shots,
  COUNT(CASE WHEN original_x IS NOT NULL THEN 1 END) as coords,
  ROUND(100.0 * COUNT(CASE WHEN original_x IS NOT NULL THEN 1 END) / 
        NULLIF(COUNT(CASE WHEN event_type = 'shot' THEN 1 END), 0), 1) as pct
FROM \`nba-props-platform.nba_raw.bigdataball_play_by_play\`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY game_id
ORDER BY pct
"
```

**Common Causes:**
- BigDataBall data quality issue (their side)
- CSV parsing error in processor
- Specific arena/camera issues

**Action:**
- If 50-70%: Accept but document
- If <50%: Contact BigDataBall or flag for manual review
- Check if specific arena/team pattern

---

#### Status: "⚠️ WARNING: X games missing"

**Meaning:** 1-3 games from yesterday not in database.

**Investigation:**
```bash
# Find which games are missing
./scripts/validate-bigdataball missing | grep $(date -d yesterday +%Y-%m-%d)

# Check if files in GCS
gsutil ls gs://nba-scraped-data/big-data-ball/2024-25/$(date -d yesterday +%Y-%m-%d)/
```

**Common Causes:**
- BigDataBall delayed release (wait 2-4 hours)
- Scraper failed for specific game
- Processor failed to process file
- GCS upload failure

**Action:**
1. **Wait 2 hours** (BigDataBall delay)
2. **Check scraper logs:** `grep "$(date -d yesterday +%Y-%m-%d)" ~/logs/bigdataball_scraper.log`
3. **Check processor logs:** `grep "$(date -d yesterday +%Y-%m-%d)" ~/logs/bigdataball_processor.log`
4. **Re-run scraper** for specific date if files not in GCS
5. **Re-run processor** if files exist but not in BigQuery

---

#### Status: "❌ CRITICAL: No play-by-play data"

**Meaning:** Zero games from yesterday in database.

**Investigation:**
```bash
# 1. Verify games were actually played
bq query --use_legacy_sql=false "
SELECT COUNT(*) as scheduled
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
"

# 2. Check scraper logs
tail -100 ~/logs/bigdataball_scraper.log

# 3. Check processor logs  
tail -100 ~/logs/bigdataball_processor.log

# 4. Check GCS for files
gsutil ls gs://nba-scraped-data/big-data-ball/2024-25/$(date -d yesterday +%Y-%m-%d)/
```

**Common Causes:**
- Scraper didn't run (cron failure, server issue)
- BigDataBall site down
- Processor crash
- BigQuery connection failure

**Action:**
1. **URGENT:** Notify team immediately
2. **Check scraper status:** Is it running? Any errors?
3. **Check BigDataBall site:** Is it accessible?
4. **Manual scraper run:** `python scrapers/bigdataball/bigdataball_pbp.py --date $(date -d yesterday +%Y-%m-%d)`
5. **Manual processor run:** Process yesterday's files
6. **Verify after fix:** Re-run daily check

---

## 📅 Weekly Monitoring (Mondays)

### Step 4: Weekly Trend Analysis

**Query:** `weekly_check_last_7_days.sql`  
**Command:** `./scripts/validate-bigdataball weekly`  
**When:** Monday mornings (review past week)

#### What It Shows:
- Daily game coverage for past 7 days
- Event count trends
- Day-of-week patterns
- Coordinate coverage trends

#### Expected Output:

```
| game_date  | day_of_week | scheduled | games_data | avg_events | status      |
|------------|-------------|-----------|------------|------------|-------------|
| 2025-10-27 | Sunday      | 10        | 10         | 465.2      | ✅ Complete |
| 2025-10-26 | Saturday    | 10        | 10         | 471.3      | ✅ Complete |
| 2025-10-25 | Friday      | 8         | 8          | 458.7      | ✅ Complete |
| 2025-10-24 | Thursday    | 6         | 6          | 462.1      | ✅ Complete |
| 2025-10-23 | Wednesday   | 8         | 7          | 449.8      | ⚠️ Incomplete |
| 2025-10-22 | Tuesday     | 12        | 12         | 473.5      | ✅ Complete |
| 2025-10-21 | Monday      | 0         | 0          | 0          | ⚪ No games |
```

#### What to Look For:

**✅ Healthy Pattern:**
- Most days: "✅ Complete"
- Event counts: 450-480 range
- Weekend games: Slightly higher attendance (more events)

**⚠️ Warning Signs:**
- Multiple "⚠️ Incomplete" days
- Consistent low event counts (<430)
- Specific day-of-week pattern (e.g., all Wednesdays missing)

**🔴 Red Flags:**
- Multiple "❌ Missing all" days
- Event counts declining over time
- Coordinate coverage dropping

---

## 🔔 Alert Thresholds & Escalation

### Automated Alerting Setup

```bash
# Add to daily cron job
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-bigdataball daily | grep -q "❌ CRITICAL" && mail -s "BigDataBall CRITICAL Alert" team@example.com
```

### Alert Levels

| Level | Trigger | Notification | Response Time |
|-------|---------|--------------|---------------|
| 🟢 Success | ✅ Complete | Log only | None |
| 🟡 Info | ⏳ Processing | Log only | Check in 2 hours |
| 🟠 Warning | ⚠️ 1-3 games missing | Slack message | 4 hours |
| 🔴 Critical | ❌ No data or >3 missing | Email + Slack + Page | Immediate |

### Escalation Path

**Level 1 (0-2 hours):** Data engineer investigates  
**Level 2 (2-4 hours):** Senior engineer notified  
**Level 3 (4+ hours):** Engineering manager involved  

---

## 📊 Monthly Review (First Monday of Month)

### Step 5: Season Completeness Check

**Query:** `season_completeness_check.sql`  
**Command:** `./scripts/validate-bigdataball season`  
**When:** Monthly (first Monday)

#### What to Check:

```bash
# Run full season check
./scripts/validate-bigdataball season > season_monthly.txt

# Key metrics
grep '"reg_games"' season_monthly.txt | head -10
```

**Expected Results:**
- **Early season (Oct-Nov):** 10-15 games per team
- **Mid season (Dec-Feb):** 40-50 games per team
- **Late season (Mar-Apr):** 70-82 games per team

**Warning Signs:**
- Teams with significantly fewer games than others
- Specific teams consistently missing games
- Wide variance in avg_events_per_game across teams

---

## 🛠️ Common Issues & Solutions

### Issue 1: BigDataBall 2-Hour Delay

**Symptom:** Yesterday's games show "⏳ PROCESSING" at 9 AM.

**Explanation:** BigDataBall releases data ~2 hours after game ends. Late games (10:30 PM ET tip) may not be ready until 2-3 AM.

**Solution:**
```bash
# Check again at 11 AM
./scripts/validate-bigdataball daily

# Or use realtime check
./scripts/validate-bigdataball realtime
```

**When to escalate:** If still missing after 12 hours.

---

### Issue 2: Scraper Didn't Run

**Symptom:** All games missing, scraper logs show no recent activity.

**Check:**
```bash
# Check cron schedule
crontab -l | grep bigdataball

# Check scraper logs
tail -50 ~/logs/bigdataball_scraper.log

# Check last run time
ls -lht ~/logs/bigdataball_scraper.log
```

**Solution:**
```bash
# Manual scraper run for yesterday
python scrapers/bigdataball/bigdataball_pbp.py \
  --date $(date -d yesterday +%Y-%m-%d) \
  --force
```

---

### Issue 3: Processor Failed

**Symptom:** Files in GCS but not in BigQuery.

**Check:**
```bash
# Files exist in GCS?
gsutil ls gs://nba-scraped-data/big-data-ball/2024-25/$(date -d yesterday +%Y-%m-%d)/

# Check processor logs
grep "$(date -d yesterday +%Y-%m-%d)" ~/logs/bigdataball_processor.log | tail -20
```

**Solution:**
```bash
# Re-run processor for specific date
gcloud run jobs execute bigdataball-pbp-processor-backfill \
  --region=us-west2 \
  --args="--start-date,$(date -d yesterday +%Y-%m-%d),--end-date,$(date -d yesterday +%Y-%m-%d)"
```

---

### Issue 4: Single Game Missing

**Symptom:** 11 of 12 games present, 1 missing.

**Investigation:**
```bash
# Find which game
./scripts/validate-bigdataball missing | grep $(date -d yesterday +%Y-%m-%d)

# Check if file in GCS
gsutil ls gs://nba-scraped-data/big-data-ball/2024-25/$(date -d yesterday +%Y-%m-%d)/ | grep [GAME_ID]
```

**Common Causes:**
- BigDataBall didn't release that specific game
- File corrupted during scraping
- Processor failed on that specific CSV

**Solution:**
```bash
# Re-scrape specific game if available on BigDataBall
# Or wait 24 hours and check if BigDataBall releases it later
```

---

### Issue 5: Low Event Count but Game Complete

**Symptom:** Game has 360-390 events (lower than 400-600 normal).

**Is it a problem?**
- **No if:** Game was a blowout (check final score)
- **No if:** Game ended early due to technical issues
- **Yes if:** Event counts consistently low across multiple games

**Action:**
- If isolated case: Accept and document
- If pattern: Investigate processor logic or BigDataBall quality

---

## 📈 Performance Metrics to Track

### Daily Metrics (Track in Spreadsheet or Dashboard)

| Date | Scheduled | Collected | % Complete | Avg Events | Min Events | Coord % | Issues |
|------|-----------|-----------|------------|------------|------------|---------|---------|
| 10/22 | 12 | 12 | 100% | 467 | 423 | 85% | None |
| 10/23 | 10 | 9 | 90% | 458 | 361 | 78% | 1 missing |

**Target Metrics:**
- **Coverage:** >95% daily (11+ of 12 games)
- **Avg Events:** 450-480 per game
- **Min Events:** >380 per game
- **Coordinate Coverage:** >70%

---

## 🔄 Weekly Report Template

```markdown
# BigDataBall Weekly Validation Report
**Week:** Oct 21-27, 2025

## Summary
- **Total Games Scheduled:** 70
- **Total Games Collected:** 68
- **Coverage:** 97.1%
- **Average Events/Game:** 465.3

## Issues This Week
1. Oct 23: 1 game missing (LAL @ GSW) - Resolved: Re-scraped Oct 24
2. Oct 25: Low coord coverage (62%) - Accepted: BigDataBall data issue

## Trends
- ✅ Coverage improving (95% → 97%)
- ✅ Event counts stable (460-470 range)
- ⚠️ Coordinate coverage declining (82% → 75%)

## Action Items
- [ ] Monitor coordinate coverage - contact BigDataBall if drops below 70%
- [ ] Investigate why LAL games occasionally missing
- [x] All missing games backfilled

## Metrics Comparison
| Metric | This Week | Last Week | Change |
|--------|-----------|-----------|--------|
| Coverage | 97.1% | 95.2% | +1.9% ↗️ |
| Avg Events | 465.3 | 462.1 | +3.2 ↗️ |
| Coord % | 75.3% | 81.2% | -5.9% ↘️ |
```

---

## 🎯 Best Practices

### DO:
- ✅ Run daily check every morning at consistent time
- ✅ Investigate warnings within 4 hours
- ✅ Document all issues in tracking log
- ✅ Set up automated alerts for critical failures
- ✅ Review weekly trends every Monday
- ✅ Keep validation queries updated

### DON'T:
- ❌ Ignore warnings (they compound)
- ❌ Wait >24 hours to investigate missing games
- ❌ Assume BigDataBall will auto-fix issues
- ❌ Skip weekly trend review
- ❌ Forget to verify after re-runs

---

## 📞 Support & Resources

**Queries Location:**
```
~/code/nba-stats-scraper/validation/queries/raw/bigdataball_pbp/
```

**CLI Commands:**
- `./scripts/validate-bigdataball daily` - Yesterday's check
- `./scripts/validate-bigdataball weekly` - Last 7 days
- `./scripts/validate-bigdataball missing` - Find missing games
- `./scripts/validate-bigdataball quality` - Quality issues
- `./scripts/validate-bigdataball realtime` - Scraper status

**Documentation:**
- Validation guide: `README.md`
- Backfill plan: `BACKFILL_PLAN.md`
- Discovery findings: `DISCOVERY_FINDINGS.md`

**Logs:**
- Scraper: `~/logs/bigdataball_scraper.log`
- Processor: `~/logs/bigdataball_processor.log`
- Daily checks: `~/logs/bigdataball_daily.log`

---

## ✅ Daily Checklist

**Every Morning (9 AM):**
- [ ] Run `./scripts/validate-bigdataball daily`
- [ ] Review status (✅/⚠️/❌)
- [ ] If warnings, investigate within 4 hours
- [ ] If critical, escalate immediately
- [ ] Log results in tracking spreadsheet

**Every Monday (9 AM):**
- [ ] Run `./scripts/validate-bigdataball weekly`
- [ ] Review 7-day trends
- [ ] Check for patterns (specific days/teams)
- [ ] Update weekly report
- [ ] Plan fixes for recurring issues

**First Monday of Month:**
- [ ] Run `./scripts/validate-bigdataball season`
- [ ] Verify games-per-team on track
- [ ] Review monthly metrics
- [ ] Update team on data health

---

**Last Updated:** October 13, 2025  
**Version:** 1.0  
**Season:** 2025-26 (Ready for Use)  
**Status:** Production Ready
