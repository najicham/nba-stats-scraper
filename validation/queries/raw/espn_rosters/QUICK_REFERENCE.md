# ESPN Rosters Validation - Quick Reference Card

**File: validation/queries/raw/espn_rosters/QUICK_REFERENCE.md**

Print or bookmark this page for quick access during season!

---

## 🚀 Daily Commands (Run at 10 AM PT)

```bash
cd ~/code/nba-stats-scraper/validation/queries/raw/espn_rosters

# 1. Daily freshness check (MOST IMPORTANT)
bq query --use_legacy_sql=false < daily_freshness_check.sql

# 2. Team coverage check
bq query --use_legacy_sql=false < team_coverage_check.sql
```

## 📅 Weekly Commands (Run Monday 10 AM PT)

```bash
# Cross-validation with NBA.com
bq query --use_legacy_sql=false < cross_validate_with_nbac.sql
```

---

## ✅ Expected Results (Healthy System)

### Daily Freshness Check
```
✅ Complete: All 30 teams with roster data
teams_with_data: 30
unique_players: 500-650
scrape_time: ✓ 8 AM
```

### Team Coverage Check
```
Teams Found: 30/30 ✅ Complete
Avg: 20.2 | Range: 17-23
All teams: ✅ Normal
```

### Cross-Validation (Weekly)
```
Perfect Matches: 83-85%
Team Mismatches: <5%
Only in ESPN/NBA.com: ~7-8% each (suffix normalization)
```

---

## 🚨 Alert Severity Guide

| Symbol | Severity | Response Time | Action |
|--------|----------|---------------|--------|
| 🔴 | CRITICAL | 15-30 min | Immediate investigation |
| 🟡 | WARNING | 2-4 hours | Review and fix |
| ⚠️ | REVIEW | 1 day | Document and monitor |
| ✅ | OK | N/A | No action needed |

---

## 🔴 Critical Alerts (Act Immediately)

### "No roster data collected"
```bash
# 1. Check if scraper ran
gsutil ls gs://nba-scraped-data/espn/rosters/$(date -d yesterday +%Y-%m-%d)/

# 2. Check processor logs
gcloud run jobs executions list --job=espn-team-roster-processor-backfill --region=us-west2 --limit=5

# 3. Manual re-run if needed
# (Contact on-call engineer)
```

### "Only X/30 teams"
```bash
# Find missing teams
WITH all_teams AS (
  SELECT team_abbr FROM UNNEST(['ATL','BKN','BOS','CHA','CHI','CLE','DAL','DEN','DET','GSW','HOU','IND','LAC','LAL','MEM','MIA','MIL','MIN','NOP','NYK','OKC','ORL','PHI','PHX','POR','SAC','SAS','TOR','UTA','WAS']) as team_abbr
)
SELECT a.team_abbr as missing_team
FROM all_teams a
LEFT JOIN (
  SELECT DISTINCT team_abbr 
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND roster_date >= '2025-01-01'
) e ON a.team_abbr = e.team_abbr
WHERE e.team_abbr IS NULL;
```

### "Match rate < 70%"
```bash
# Check data timestamps
bq query --use_legacy_sql=false "
SELECT 
  'ESPN' as source,
  MAX(roster_date) as latest_date,
  MAX(processed_at) as latest_processing
FROM \`nba-props-platform.nba_raw.espn_team_rosters\`
WHERE roster_date >= '2025-01-01'
UNION ALL
SELECT
  'NBA.com' as source,
  MAX(last_seen_date) as latest_date,
  MAX(processed_at) as latest_processing  
FROM \`nba-props-platform.nba_raw.nbac_player_list_current\`
"
```

---

## 📞 Contacts

**Primary On-Call:** NBA Data Engineer  
**Secondary:** Platform Team  
**Escalation:** Engineering Manager

**Slack Channel:** `#nba-data-alerts`  
**Documentation:** `validation/queries/raw/espn_rosters/README.md`  
**Operations Guide:** `validation/queries/raw/espn_rosters/SCHEDULING_OPERATIONS.md`

---

## 🛠️ Quick Fixes

### Re-run scraper manually
```bash
# Contact on-call engineer or run:
# python scrapers/espn/espn_team_roster.py --date YYYY-MM-DD
```

### Re-run processor manually
```bash
gcloud run jobs execute espn-team-roster-processor-backfill \
  --region=us-west2 \
  --args="^|^--start-date=YYYY-MM-DD|--end-date=YYYY-MM-DD"
```

### Check recent data
```bash
bq query --use_legacy_sql=false "
SELECT 
  roster_date,
  COUNT(DISTINCT team_abbr) as teams,
  COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_raw.espn_team_rosters\`
WHERE roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND roster_date >= '2025-01-01'
GROUP BY roster_date
ORDER BY roster_date DESC
"
```

---

## 📊 Normal Patterns

- **Player Count:** 17-23 per team (most teams ~21)
- **Total Players:** 500-650 league-wide
- **Match Rate:** 83-85% with NBA.com
- **Suffix Mismatches:** ~50 players with Jr./II/III differences (normal!)
- **Scrape Time:** 8 AM PT daily
- **Processing Time:** <30 minutes
- **Query Time:** <30 seconds total

---

**Print Date:** October 13, 2025  
**Valid For:** 2024-25 and 2025-26 NBA Seasons  
**Update When:** Schema changes, business logic changes, or season rollover
