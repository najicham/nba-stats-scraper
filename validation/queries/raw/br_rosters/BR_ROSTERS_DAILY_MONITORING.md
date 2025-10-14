# Basketball Reference Rosters - Daily Monitoring Guide

**Purpose:** Monitor Basketball Reference roster data quality during the 2025-26 NBA season  
**When to Use:** October 2025 - June 2026 (NBA season)  
**Frequency:** Daily checks + weekly reviews  

---

## Quick Reference

| Check Type | Frequency | Query | Alert Threshold | Expected Time |
|------------|-----------|-------|-----------------|---------------|
| Yesterday's Changes | Daily 9 AM | `daily_check_yesterday.sql` | new_players > 5 | <2 seconds |
| Weekly Trend | Monday 9 AM | `weekly_check_last_7_days.sql` | Multiple days no scraper | <3 seconds |
| Scraper Health | As needed | `realtime_scraper_check.sql` | days_since_scrape > 2 | <2 seconds |
| Data Quality | Monthly | `data_quality_check.sql` | Any new nulls | <5 seconds |
| Completeness | End of season | `season_completeness_check.sql` | Missing teams | <10 seconds |

---

## Daily Monitoring Workflow

### Morning Routine (9:00 AM PT)

**Step 1: Check Yesterday's Roster Updates**

```bash
cd ~/code/nba-stats-scraper
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/daily_check_yesterday.sql
```

**What to Look For:**

✅ **Normal Results:**
```
status = "✅ No roster changes"      → Most common (no trades/signings)
status = "✅ Normal changes"         → 1-5 new players (expected)
status = "⚪ No scraper run"         → Offseason or scraper didn't run
```

⚠️ **Investigate:**
```
status = "⚠️ Multiple changes"       → >5 new players
  → Review the new player list below the summary
  → Cross-check with ESPN/NBA.com for trades
  → Normal during trade deadline (Feb 8), but unusual other times
```

**Example Normal Output:**
```
check_date  | season  | teams_updated | players_updated | new_players | status
2025-10-23  | 2024-25 | 30            | 655            | 2           | ✅ Normal changes

NEW_PLAYER rows:
2025-10-23  | NEW_PLAYER | 0 | 0 | 0 | LAL: Christian Wood (C)
2025-10-23  | NEW_PLAYER | 0 | 0 | 0 | BOS: Dalano Banton (G)
```

**Action Items:**
- If status = "⚪ No scraper run" during season → Check scraper logs
- If status = "⚠️ Multiple changes" → Verify trades on ESPN.com
- Log any new players for prop betting impact analysis

---

### Weekly Review (Monday 9:00 AM PT)

**Step 2: Review Last Week's Activity**

```bash
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/weekly_check_last_7_days.sql
```

**What to Look For:**

✅ **Healthy Pattern:**
```
Most days: status = "✅ No changes"
Occasional: status = "✅ Normal changes"
Scraper runs: 7/7 days during season
```

⚠️ **Problem Patterns:**
```
Multiple days: status = "⚠️ Multiple changes"
  → Trade deadline period (Feb 6-8) = EXPECTED
  → Other times = Investigate unusual activity

Multiple days: status = "⚪ No scraper run"
  → During season = CRITICAL (scraper failed)
  → During offseason = EXPECTED (scraper paused)
```

**Example Healthy Output:**
```
check_date | day_of_week | teams_updated | players_updated | new_players | changes | status
2025-10-20 | Monday      | 30            | 655            | 0           |         | ✅ No changes
2025-10-21 | Tuesday     | 30            | 656            | 1           | LAL:... | ✅ Normal changes
2025-10-22 | Wednesday   | 30            | 656            | 0           |         | ✅ No changes
...
```

**Action Items:**
- Scraper down 2+ days → Restart scraper and backfill missing days
- Trade spike → Document for prop betting team (player availability changes)
- No activity for 7 days during season → Verify Basketball Reference website accessibility

---

### As-Needed: Scraper Health Check

**Step 3: Check Scraper Freshness (When Investigating Issues)**

```bash
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/realtime_scraper_check.sql
```

**What to Look For:**

✅ **Healthy Scraper (During Season):**
```
status = "✅ Scraper ran today"           → Perfect
status = "✅ Scraper healthy (yesterday)" → Acceptable
days_since_scrape = 0 or 1
```

⚠️ **Warning (During Season):**
```
status = "⚠️ Scraper stale (check logs)"
days_since_scrape = 2-7
  → Action: Check Cloud Scheduler execution history
  → Verify scraper logs in Cloud Run
```

❌ **Critical (During Season):**
```
status = "❌ CRITICAL: Scraper down during season"
days_since_scrape > 7
  → Action: IMMEDIATE - Restart scraper
  → Backfill missing dates
  → Alert engineering team
```

✅ **Expected (During Offseason):**
```
status = "⚪ Offseason - scraper idle (expected)"
days_since_scrape > 7 (June-September)
  → No action needed - normal behavior
```

**Example Output:**
```
check_date | check_timestamp      | season  | most_recent_scrape | days_since | status
2025-10-23 | 2025-10-23 09:15:00  | 2024-25 | 2025-10-23        | 0          | ✅ Scraper ran today
```

**Action Items:**
- days_since_scrape > 2 during season → Investigate immediately
- days_since_scrape > 7 during season → CRITICAL - restart and backfill

---

## Monthly Data Quality Checks

### Data Quality Validation (1st Monday of Month)

```bash
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/data_quality_check.sql
```

**What to Monitor:**

**Critical Fields (Must Always Be 0 Nulls):**
```
COMPLETENESS row:
- null_season_year = 0
- null_team_abbrev = 0
- null_full_name = 0
- null_player_lookup = 0
- null_last_name = 0
- null_position = 0
```

**Date Tracking (Must Always Be 0 Nulls):**
```
DATE_TRACKING row:
- null_first_seen = 0
- null_last_scraped = 0
```

**Name Normalization (Must Always Be 0):**
```
NAME_QUALITY row:
- bad_normalized = 0
- bad_lookup = 0
- lookup_has_spaces = 0
- lookup_mixed_case = 0
```

**Position Distribution (Should Be Reasonable):**
```
POSITION rows:
- SG: ~600-700 occurrences (most common)
- SF: ~500-550
- PG, PF, C: ~450-500 each
```

**⚠️ Alert Triggers:**
- ANY critical field has nulls > 0 → Data quality issue
- bad_lookup > 0 → Name normalization broken
- Position counts drastically different from historical → Investigate

**Action Items:**
- If ANY nulls appear in critical fields → Check processor logs
- If name normalization fails → Review processor code changes
- Document monthly metrics for trend analysis

---

## End-of-Season Validation

### Complete Season Review (June 2026)

```bash
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/season_completeness_check.sql
```

**Final Checklist:**

✅ **Season 2025-26 Should Show:**
```
SEASON_SUMMARY row:
- Teams = 30
- Status = "✅ Complete"
- Unique players = 550-650 (varies by trade activity)
- Avg per team = 19-24
- Multi-team players = 70-100 (trades)
```

✅ **All 30 Teams Present:**
```
TEAM rows: Should have 30 entries for 2025-26
Each team: 15-33 players (typical range)
```

⚠️ **Alert Triggers:**
```
- Teams < 30 → Run find_missing_teams.sql
- Any team with < 13 players → Incomplete data
- Any team with > 33 players → Review for data quality
- Status != "✅ Complete" → Missing games
```

**Action Items:**
- Missing teams → Backfill from Basketball Reference
- Document final season statistics
- Archive for historical reference

---

## Alert Escalation

### Severity Levels

**🟢 INFO (Log Only):**
- 1-2 new players in daily check
- Scraper 1 day old
- Normal trade activity

**🟡 WARNING (Investigate Same Day):**
- 3-5 new players in daily check
- Scraper 2-3 days stale
- Unusual but not critical

**🔴 CRITICAL (Immediate Action):**
- >5 new players (outside trade deadline)
- Scraper >7 days stale during season
- ANY nulls in critical fields
- Missing entire team-season

### Contact Information

**For Scraper Issues:**
- Check: Cloud Scheduler → `br-season-roster-scraper`
- Logs: Cloud Run → `br-rosters-processor-backfill`
- Manual run: `python -m scrapers.basketball_reference.br_season_roster --season 2025`

**For Data Quality Issues:**
- Check: BigQuery table `nba_raw.br_rosters_current`
- Processor: `processors/basketball_reference/br_rosters_processor.py`
- Schema: Review processor documentation

---

## Automation Setup

### Cron Schedule (Production)

```bash
# Add to crontab
crontab -e

# Daily check (9 AM PT = 5 PM UTC)
0 17 * * * cd ~/code/nba-stats-scraper && bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/daily_check_yesterday.sql > /tmp/br_rosters_daily.log 2>&1

# Weekly review (Monday 9 AM PT = 5 PM UTC)
0 17 * * 1 cd ~/code/nba-stats-scraper && bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/weekly_check_last_7_days.sql > /tmp/br_rosters_weekly.log 2>&1

# Monthly quality check (1st of month, 9 AM PT)
0 17 1 * * cd ~/code/nba-stats-scraper && bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/data_quality_check.sql > /tmp/br_rosters_quality.log 2>&1
```

### Email Alerts (Optional)

```bash
# Daily check with email on issues
0 17 * * * cd ~/code/nba-stats-scraper && \
  RESULT=$(bq query --use_legacy_sql=false --format=csv < validation/queries/raw/br_rosters/daily_check_yesterday.sql | grep -c "⚠️\|❌") && \
  if [ $RESULT -gt 0 ]; then \
    bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/daily_check_yesterday.sql | \
    mail -s "BR Rosters Alert: Issues Found" your-email@example.com; \
  fi
```

### Slack Integration (Optional)

```python
# Add to monitoring/slack_alerts.py
def check_br_rosters_daily():
    """Run daily BR roster check and alert on Slack if issues found"""
    result = run_bq_query("validation/queries/raw/br_rosters/daily_check_yesterday.sql")
    
    if "⚠️" in result or "❌" in result:
        send_slack_alert(
            channel="#data-alerts",
            message=f"⚠️ BR Rosters: Issues detected in daily check\n```{result}```"
        )
```

---

## Seasonal Preparation

### Before Season Starts (September 2025)

**Step 1: Update Season Configuration**

Update `current_season` CTE in these files:
- `daily_check_yesterday.sql`
- `weekly_check_last_7_days.sql`
- `realtime_scraper_check.sql`

```sql
-- Change from:
SELECT 2024 as season_year, '2024-25' as season_display

-- To:
SELECT 2025 as season_year, '2025-26' as season_display
```

**Step 2: Add New Season to Completeness Check**

Update `season_completeness_check.sql`:

```sql
CASE
  WHEN game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
  WHEN game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
  WHEN game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
  WHEN game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
  WHEN game_date BETWEEN '2025-10-21' AND '2026-06-20' THEN '2025-26'  -- ADD THIS
END as season
```

**Step 3: Test Scraper**

```bash
# Test scraper on first preseason game
python -m scrapers.basketball_reference.br_season_roster --season 2025 --teams LAL

# Verify data loaded
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_raw.br_rosters_current\`
WHERE season_year = 2025
LIMIT 5
"
```

**Step 4: Enable Daily Monitoring**

```bash
# Verify cron jobs are active
crontab -l | grep br_rosters

# Test daily check manually
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/daily_check_yesterday.sql
```

---

## Trade Deadline Period (February 6-8, 2026)

**Special Considerations:**

During the 3-day trade deadline window, expect:
- **10-30 new players per day** (NORMAL)
- **Multiple roster updates per team** (NORMAL)
- **Increased scraper frequency** (may need hourly scraping)

**Monitoring Adjustments:**

```bash
# Increase check frequency to every 2 hours
0 */2 * * * cd ~/code/nba-stats-scraper && \
  bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/realtime_scraper_check.sql
```

**Daily Summary:**

```bash
# End-of-day trade deadline summary (11 PM PT)
0 6 * * * cd ~/code/nba-stats-scraper && \
  bq query --use_legacy_sql=false "
  SELECT 
    last_scraped_date,
    COUNT(DISTINCT player_full_name) as players_added_today,
    STRING_AGG(CONCAT(team_abbrev, ': ', player_full_name), ', ' ORDER BY team_abbrev) as new_players
  FROM \`nba-props-platform.nba_raw.br_rosters_current\`
  WHERE first_seen_date = CURRENT_DATE() - 1
    AND season_year = 2025
  GROUP BY last_scraped_date
  " | mail -s "Trade Deadline Summary" your-email@example.com
```

---

## Common Issues & Solutions

### Issue 1: Scraper Not Running

**Symptoms:**
- `realtime_scraper_check.sql` shows days_since_scrape > 2
- `daily_check_yesterday.sql` shows "⚪ No scraper run"

**Diagnosis:**
```bash
# Check Cloud Scheduler
gcloud scheduler jobs describe br-season-roster-scraper --location=us-west2

# Check recent runs
gcloud scheduler jobs executions list br-season-roster-scraper --location=us-west2 --limit=5
```

**Solution:**
```bash
# Manual trigger
gcloud scheduler jobs run br-season-roster-scraper --location=us-west2

# Or run scraper directly
python -m scrapers.basketball_reference.br_season_roster --season 2025
```

---

### Issue 2: Missing Teams After Scraper Run

**Symptoms:**
- `daily_check_yesterday.sql` shows teams_updated < 30
- `find_missing_teams.sql` returns results

**Diagnosis:**
```bash
# Check which teams are missing
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/find_missing_teams.sql
```

**Solution:**
```bash
# Re-scrape specific teams
python -m scrapers.basketball_reference.br_season_roster \
  --season 2025 \
  --teams LAL BOS GSW  # Add missing teams

# Or re-scrape all teams
python -m scrapers.basketball_reference.br_season_roster --season 2025
```

---

### Issue 3: Data Quality Degradation

**Symptoms:**
- `data_quality_check.sql` shows new nulls in critical fields
- Name normalization failures

**Diagnosis:**
```bash
# Find specific problem records
bq query --use_legacy_sql=false "
SELECT *
FROM \`nba-props-platform.nba_raw.br_rosters_current\`
WHERE season_year = 2025
  AND (player_lookup IS NULL OR team_abbrev IS NULL)
LIMIT 10
"
```

**Solution:**
- Review processor logs for errors
- Check if Basketball Reference changed HTML structure
- Update scraper/processor code if needed
- Re-process affected dates

---

### Issue 4: Duplicate Players

**Symptoms:**
- Same player appears multiple times for same team-season
- `season_completeness_check.sql` shows player_count != roster_spots

**Diagnosis:**
```bash
# Find duplicates
bq query --use_legacy_sql=false "
SELECT 
  season_year,
  team_abbrev,
  player_full_name,
  COUNT(*) as occurrences
FROM \`nba-props-platform.nba_raw.br_rosters_current\`
WHERE season_year = 2025
GROUP BY season_year, team_abbrev, player_full_name
HAVING COUNT(*) > 1
"
```

**Solution:**
- Check processor MERGE logic
- Review deduplication strategy
- May need to clean data manually and re-process

---

## Historical Comparison

### Year-over-Year Metrics

Track these metrics each season for comparison:

| Metric | 2021-22 | 2022-23 | 2023-24 | 2024-25 | 2025-26 (Target) |
|--------|---------|---------|---------|---------|------------------|
| Unique Players | 606 | 541 | 572 | 569 | 550-650 |
| Total Roster Spots | 716 | 612 | 657 | 655 | 650-750 |
| Avg Players/Team | 23.9 | 20.4 | 21.9 | 21.8 | 20-24 |
| Multi-Team Players | 97 | 71 | 78 | 82 | 70-100 |
| Largest Team Roster | 30 (MIL) | 26 (LAL) | 33 (MEM) | 30 (PHI) | <35 |

**Use these ranges to validate 2025-26 season data looks reasonable.**

---

## Documentation Updates

### When to Update This Guide

- **Before each season:** Update season numbers and date ranges
- **After major scraper changes:** Update scraper commands
- **After processor changes:** Update query expectations
- **When alert thresholds change:** Document new thresholds

### Version History

- **v1.0 (October 2025):** Initial daily monitoring guide
- **v1.1 (Expected):** Post-trade deadline refinements
- **v2.0 (Expected):** Post-season lessons learned

---

## Success Metrics

### Daily Monitoring Goals

✅ **Zero Data Loss:** Catch missing days within 24 hours  
✅ **Trade Detection:** Identify roster changes within 1 day  
✅ **Data Quality:** Maintain 0 nulls in critical fields  
✅ **Scraper Uptime:** >95% daily success rate during season  

### Season-End Goals

✅ **Complete Coverage:** All 30 teams present  
✅ **Data Quality:** 0 nulls in critical fields all season  
✅ **Timeliness:** No gaps >2 days in roster updates  
✅ **Accuracy:** Cross-validate 100% of trades with NBA.com  

---

## Quick Command Reference

```bash
# Daily morning check
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/daily_check_yesterday.sql

# Weekly Monday review
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/weekly_check_last_7_days.sql

# Check scraper health
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/realtime_scraper_check.sql

# Monthly data quality
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/data_quality_check.sql

# Find missing teams
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/find_missing_teams.sql

# Manual scraper run
python -m scrapers.basketball_reference.br_season_roster --season 2025

# Check specific team
python -m scrapers.basketball_reference.br_season_roster --season 2025 --teams LAL
```

---

**Last Updated:** October 13, 2025  
**Next Review:** Before 2025-26 season starts (September 2025)  
**Maintained By:** Data Engineering Team
