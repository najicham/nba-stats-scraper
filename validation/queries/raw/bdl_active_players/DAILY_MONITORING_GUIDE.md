# BDL Active Players - Daily Monitoring Guide

**File:** `validation/queries/raw/bdl_active_players/DAILY_MONITORING_GUIDE.md`

Daily workflows and alert procedures for monitoring BDL Active Players data quality.

## Morning Routine (5 minutes)

### Step 1: Run Daily Check (2 minutes)

```bash
validate-bdl-active-players daily
```

**What to look for:**
- ✅ **All systems operational** = Good, no action needed
- 🟡 **WARNING** = Review but not urgent
- 🔴 **CRITICAL** = Immediate action required

### Step 2: Review Status (1 minute)

Check these key metrics:

| Metric | Expected | Alert If |
|--------|----------|----------|
| Last Update | < 48 hours | > 96 hours |
| Teams | 30 of 30 | != 30 |
| Total Players | 550-600 | < 500 or > 650 |
| Validation Rate | 55-65% | < 45% |
| Missing from NBA.com | 20-30% | > 40% |
| Team Mismatches | 10-20% | > 30% |

### Step 3: Take Action (2 minutes if needed)

**If all green (✅):**
- No action needed
- Continue to next task

**If warning (🟡):**
- Make note
- Monitor tomorrow
- Review if persists 2+ days

**If critical (🔴):**
- Follow troubleshooting guide below
- Alert team if needed
- Document issue

## Deep Dive Workflows

### Workflow 1: Data Not Updating (Last Update > 96 hours)

**Symptoms:**
- 🔴 CRITICAL: Not updating
- Last update > 4 days ago

**Investigation:**
```bash
# 1. Check data freshness
validate-bdl-active-players daily

# 2. Check current record count
bq query --use_legacy_sql=false "
SELECT 
  MAX(last_seen_date) as last_update,
  MAX(processed_at) as last_processed,
  COUNT(*) as total_records
FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
"
```

**Resolution steps:**
1. Check scraper logs: `ball_dont_lie/bdl_active_players.py`
2. Verify scraper is scheduled to run
3. Check GCS bucket for recent files
4. Check processor Pub/Sub subscription
5. Manually trigger scraper if needed
6. Monitor for next update

---

### Workflow 2: Low Validation Rate (< 45%)

**Symptoms:**
- 🔴 Low validation rate
- < 45% of players validated

**Investigation:**
```bash
# 1. Check validation status distribution
validate-bdl-active-players validation-status

# 2. See detailed breakdown
validate-bdl-active-players cross-validate
```

**Common causes:**
- NBA.com player list is stale (check `nbac_player_list_current`)
- BDL scraper picked up many new G-League assignments
- Recent roster changes league-wide

**Resolution steps:**
1. Run `validate-player-list daily` to check NBA.com freshness
2. If NBA.com stale, trigger that scraper
3. Review `missing_nba_com` players - are they G-League?
4. If many `data_quality_issue`, investigate those specifically
5. Expected to normalize within 24-48 hours

---

### Workflow 3: High Missing Rate (> 40% missing from NBA.com)

**Symptoms:**
- 🔴 Too many missing from NBA.com
- > 40% of players not in NBA.com

**Investigation:**
```bash
# 1. Run missing players analysis
validate-bdl-active-players missing-players

# 2. Cross-check with NBA.com
validate-player-list daily
```

**Common causes:**
- NBA.com scraper failed or delayed
- Unusual number of G-League assignments
- BDL picked up players NBA.com doesn't track

**Resolution steps:**
1. Check NBA.com scraper status
2. Review teams with most missing players
3. Identify if G-League vs truly missing
4. Trigger NBA.com scraper if stale
5. Monitor for 24-48 hours to normalize

---

### Workflow 4: High Team Mismatch Rate (> 30%)

**Symptoms:**
- 🔴 Excessive mismatches
- > 30% of players have different teams

**Investigation:**
```bash
# 1. Run team mismatch analysis
validate-bdl-active-players team-mismatches

# 2. Check for recent trades
# Look at common team pairs - indicates trades
```

**Common causes:**
- Trade deadline activity (expected spike)
- One source updated, other hasn't yet
- Systematic team mapping issue

**Resolution steps:**
1. Review trade deadline dates - expected spike then
2. Check common team pairs - indicates recent trades
3. Verify both BDL and NBA.com scrapers running
4. If no recent trades, investigate team mapping logic
5. Monitor for 24-48 hours - should resolve as sources sync

---

### Workflow 5: Missing Teams (< 30 teams)

**Symptoms:**
- 🔴 CRITICAL: Missing teams
- < 30 teams found

**Investigation:**
```bash
# 1. Run player count check
validate-bdl-active-players count

# 2. Find which teams are missing
bq query --use_legacy_sql=false "
SELECT DISTINCT team_abbr, team_full_name, COUNT(*) as player_count
FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
GROUP BY team_abbr, team_full_name
ORDER BY team_abbr
"
```

**Resolution steps:**
1. Identify which team(s) are missing
2. Check if scraper filtered them out
3. Check source data from BDL API
4. Check for team abbreviation changes (rare)
5. Manually verify team still exists (relocation/name change)
6. Critical issue - escalate if not resolved quickly

---

### Workflow 6: Duplicate Players Found

**Symptoms:**
- 🔴 CRITICAL: Primary key violation
- Duplicate player_lookup or bdl_player_id

**Investigation:**
```bash
# 1. Run data quality check
validate-bdl-active-players quality

# 2. Find the duplicates
bq query --use_legacy_sql=false "
SELECT 
  player_lookup,
  COUNT(*) as dup_count,
  STRING_AGG(player_full_name) as names,
  STRING_AGG(team_abbr) as teams
FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
GROUP BY player_lookup
HAVING COUNT(*) > 1
"
```

**Resolution steps:**
1. Identify which player(s) are duplicated
2. Check source data from scraper
3. Investigate name normalization logic
4. Check if same player on multiple teams (should not happen)
5. **CRITICAL:** Fix immediately - data integrity issue
6. May need to re-run processor with fixed logic

---

## Weekly Review (10 minutes)

### Monday Morning (Start of Week)

```bash
# 1. Run complete validation suite
validate-bdl-active-players all

# 2. Review week-over-week trends
# Compare with last week's results

# 3. Export for tracking
validate-bdl-active-players validation-status --csv > weekly_$(date +%Y%m%d).csv
```

**What to review:**
- Overall validation rate trends
- Team mismatch trends (spikes = trade activity)
- Missing player trends
- Any persistent warnings

### Friday Afternoon (End of Week)

```bash
# Quick health check before weekend
validate-bdl-active-players daily
```

**Before leaving for weekend:**
- Ensure no critical alerts
- Note any warnings for Monday follow-up
- Check scraper schedule for weekend runs

---

## Alert Thresholds & Response Times

### 🔴 CRITICAL - Immediate Action (within 1 hour)

| Alert | Threshold | Action |
|-------|-----------|--------|
| Data not updating | > 96 hours | Check scraper/processor |
| Missing teams | < 30 teams | Investigate immediately |
| Duplicate players | > 0 duplicates | Fix data integrity |
| Player count | < 500 or > 650 | Investigate scraper |
| Very old data | > 7 days | Critical system issue |

### 🟡 WARNING - Review Soon (within 24 hours)

| Alert | Threshold | Action |
|-------|-----------|--------|
| Stale data | 48-96 hours | Monitor, check scraper |
| Low validation | 45-55% | Cross-check NBA.com |
| High missing | 40-50% | Review missing players |
| High mismatches | 30-40% | Check for trades |
| Team roster | < 13 or > 20 players | Verify team data |

### ✅ HEALTHY - No Action Needed

| Metric | Healthy Range |
|--------|---------------|
| Last update | < 48 hours |
| Teams | 30 |
| Total players | 550-600 |
| Validation rate | 55-65% |
| Missing from NBA.com | 20-30% |
| Team mismatches | 10-20% |
| Players per team | 13-20 |

---

## Monthly Review (30 minutes)

### First Monday of Month

```bash
# 1. Run complete validation
validate-bdl-active-players all

# 2. Review historical trends
bq query --use_legacy_sql=false "
SELECT 
  DATE_TRUNC(processed_at, MONTH) as month,
  AVG(CASE WHEN has_validation_issues = FALSE THEN 1 ELSE 0 END) * 100 as avg_validation_rate
FROM \`nba-props-platform.nba_raw.bdl_active_players_current\`
GROUP BY month
ORDER BY month DESC
LIMIT 6
"
```

**What to review:**
- Validation rate trends over months
- Identify systematic issues
- Review alert frequency
- Update alert thresholds if needed
- Document any pattern changes

---

## Quick Reference: Command Cheat Sheet

```bash
# Daily quick check
validate-bdl-active-players daily

# Detailed checks
validate-bdl-active-players count                  # Player counts
validate-bdl-active-players validation-status      # Validation distribution
validate-bdl-active-players quality               # Data quality
validate-bdl-active-players cross-validate        # vs NBA.com

# Investigation commands
validate-bdl-active-players team-mismatches       # When mismatches > 20%
validate-bdl-active-players missing-players       # When missing > 30%

# Export results
validate-bdl-active-players daily --csv > daily_check.csv
validate-bdl-active-players quality --table nba_processing.bdl_quality_$(date +%Y%m%d)

# Complete suite
validate-bdl-active-players all
```

---

## Escalation Procedures

### When to Alert Team

**Immediate Escalation (within 1 hour):**
- Data not updating > 4 days
- Missing teams
- Duplicate players
- System-wide data corruption

**Same Day Escalation:**
- Persistent warnings > 2 days
- Unusual validation patterns
- Multiple failed queries

**Next Business Day:**
- Minor warnings
- Trend changes
- Questions about data patterns

### Who to Contact

1. **Data Team Lead:** System-wide issues
2. **Scraper Engineer:** Scraper failures
3. **DevOps:** Infrastructure issues
4. **On-Call:** After hours critical issues

---

## Monitoring Best Practices

### Do's ✅
- Run daily check every morning
- Review trends weekly
- Export results for tracking
- Document unusual patterns
- Set up automated alerts
- Keep escalation list updated

### Don'ts ❌
- Don't ignore persistent warnings
- Don't assume issues will self-resolve
- Don't wait for critical alerts
- Don't skip monitoring on weekends
- Don't over-alert (alert fatigue)
- Don't forget to document resolutions

---

## Expected Seasonal Patterns

### Trade Deadline (February)
- **Expect:** High team mismatch rate (20-30%)
- **Why:** Many trades happening
- **Action:** Monitor but not alarming

### Off-Season (June-September)
- **Expect:** Lower validation rate (50-60%)
- **Why:** More roster movement
- **Action:** Normal for off-season

### Season Start (October)
- **Expect:** Higher missing from NBA.com (25-35%)
- **Why:** Roster cuts, G-League assignments
- **Action:** Should normalize by November

### All-Star Break (February)
- **Expect:** Slower update frequency
- **Why:** Fewer games
- **Action:** Expect 48-72 hour gaps

---

## Troubleshooting Quick Guide

| Symptom | Most Likely Cause | Quick Fix |
|---------|------------------|-----------|
| No updates > 4 days | Scraper stopped | Check/restart scraper |
| Missing teams | Scraper filter issue | Check team mapping |
| Low validation rate | NBA.com is stale | Check/restart NBA.com scraper |
| High mismatches | Recent trades | Monitor - should normalize |
| Duplicates | Name normalization bug | Fix and re-process |
| High missing | G-League assignments | Review and confirm |

---

## Last Updated
October 13, 2025
