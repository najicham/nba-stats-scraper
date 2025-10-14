# ESPN Boxscore Daily Monitoring Guide

**File:** `validation/queries/raw/espn_boxscore/MONITORING_GUIDE.md`  
**Purpose:** Daily validation workflow for ESPN backup data during NBA season  
**Created:** October 13, 2025  
**Status:** Ready for Season Start

---

## 🎯 Executive Summary

ESPN Boxscore is a **sparse backup data source** used during Early Morning Final Check workflow. Most days will have **NO ESPN data** - this is **NORMAL** and **EXPECTED**.

**Key Monitoring Principle:**
> Monitor for **data quality when ESPN exists**, not for **data completeness**.

---

## 📅 Daily Monitoring Workflow

### Morning Routine (8:00 AM PT)

Run these commands every morning to validate yesterday's backup collection:

```bash
# Quick health check (30 seconds)
./scripts/validate-espn-boxscore yesterday

# If ESPN data exists, run quality checks (1 minute)
./scripts/validate-espn-boxscore quality

# If ESPN data exists AND BDL also has data, cross-validate (2 minutes)
./scripts/validate-espn-boxscore cross-validate
```

**Expected Results:**
- **Most days:** "⚪ NO ESPN DATA (Normal for backup source)" ✅ GOOD
- **Rare days:** ESPN collected data, validate quality

---

## 🚨 Alert Configuration

### ❌ DO NOT Alert On These (Normal Patterns)

```bash
# These are NORMAL - DO NOT create alerts:
- "No ESPN data yesterday"           # Expected most days
- "ESPN coverage below 10%"          # Always low for backup
- "ESPN missing 90% of games"        # Normal for sparse backup
- "No ESPN data for 30 days"         # Normal during off days
```

### ✅ DO Alert On These (Actual Issues)

Create alerts for these conditions:

#### 1. **ESPN Exists But BDL Doesn't** 🔴 CRITICAL
```bash
# Query to detect role reversal
SELECT 
  game_date,
  COUNT(DISTINCT CASE WHEN source = 'ESPN' THEN game_id END) as espn_games,
  COUNT(DISTINCT CASE WHEN source = 'BDL' THEN game_id END) as bdl_games
FROM (
  SELECT game_date, game_id, 'ESPN' as source 
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  UNION ALL
  SELECT game_date, game_id, 'BDL' as source
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
GROUP BY game_date
HAVING espn_games > 0 AND bdl_games = 0;
```

**Alert Severity:** 🔴 CRITICAL  
**Action:** Investigate why BDL (primary source) failed

---

#### 2. **Stats Differ by >5 Points** 🔴 CRITICAL
```bash
# Run this when both ESPN and BDL have same game
./scripts/validate-espn-boxscore stats-compare

# Alert if output shows:
# - Major Points Differences > 0
# - Critical Issues > 0
```

**Alert Severity:** 🔴 CRITICAL  
**Action:** Investigate data accuracy, check NBA.com official stats

---

#### 3. **Team Mismatches** 🔴 CRITICAL
```bash
# Included in cross-validation check
./scripts/validate-espn-boxscore cross-validate

# Alert if: Team Mismatches > 0
```

**Alert Severity:** 🔴 CRITICAL  
**Action:** Data corruption, investigate processor logic

---

#### 4. **NULL Core Stats** ⚠️ WARNING
```bash
# Included in quality check
./scripts/validate-espn-boxscore quality

# Alert if: NULL Points Values > 0
```

**Alert Severity:** ⚠️ WARNING  
**Action:** Processing error, check ESPN scraper/processor

---

## 📊 Weekly Monitoring (Monday Morning)

Run comprehensive checks every Monday:

```bash
# Full validation suite (5 minutes)
./scripts/validate-espn-boxscore all

# Save results to BigQuery for tracking
./scripts/validate-espn-boxscore quality --table=validation.espn_weekly_quality
./scripts/validate-espn-boxscore cross-validate --table=validation.espn_weekly_validation
```

**Review Checklist:**
- [ ] How many games did ESPN collect last week?
- [ ] Any quality issues detected?
- [ ] Any stat discrepancies with BDL?
- [ ] Coverage pattern normal for backup source?

---

## 🔍 Investigation Workflows

### When ESPN Data Appears (Rare Event)

**Step 1: Verify It's Intentional**
```bash
# Check if Early Morning Final Check workflow ran
# (This is the only workflow that triggers ESPN collection)

# Look for workflow logs indicating backup validation needed
```

**Step 2: Quality Check**
```bash
./scripts/validate-espn-boxscore quality
```

**Expected:** All ✅ passes, 20-30 players per game

---

**Step 3: Cross-Validate with BDL**
```bash
./scripts/validate-espn-boxscore cross-validate
```

**Expected:**
- **Ideal:** Both Sources = X games (can validate)
- **Normal:** BDL Only = most games, ESPN Only = few games
- **Problem:** ESPN Only with no BDL = investigate

---

### When Stats Don't Match

**Step 1: Get Detailed Comparison**

Edit `validation/queries/raw/espn_boxscore/cross_validate_with_bdl.sql`:

Uncomment the "DETAILED DISCREPANCIES" section at the bottom:
```sql
/*
SELECT 
  game_date,
  game_id,
  player_lookup,
  espn_name,
  bdl_name,
  espn_points,
  bdl_points,
  points_diff,
  ...
FROM player_stat_comparison
WHERE points_diff > 0 
   OR rebounds_diff > 0 
   OR assists_diff > 0 
   OR team_mismatch
ORDER BY points_diff DESC;
*/
```

Remove `/*` and `*/` to enable, then run:
```bash
bq query --use_legacy_sql=false < validation/queries/raw/espn_boxscore/cross_validate_with_bdl.sql
```

---

**Step 2: Compare Against NBA.com Official Stats**

```sql
-- Get NBA.com gamebook stats for comparison
SELECT 
  player_full_name,
  points,
  rebounds,
  assists,
  'NBA.com Official' as source
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_id = 'PROBLEMATIC_GAME_ID'
  AND player_status = 'active'
ORDER BY points DESC;
```

---

**Step 3: Document Findings**

Create incident report:
```
Date: YYYY-MM-DD
Game: HOME vs AWAY (game_id)
Issue: ESPN vs BDL stat discrepancy

Players Affected:
- Player Name: ESPN X pts, BDL Y pts, NBA.com Z pts

Root Cause: [TBD after investigation]
Resolution: [Action taken]
```

---

## 📈 Metrics to Track

### Monthly Report Queries

**1. ESPN Collection Frequency**
```sql
-- How often does ESPN backup collect data?
SELECT 
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(DISTINCT game_date) as dates_with_espn,
  COUNT(DISTINCT game_id) as games_collected
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
GROUP BY month
ORDER BY month DESC;
```

**Expected:** 0-10 games per month (sparse backup)

---

**2. Data Quality Trends**
```sql
-- Track quality metrics over time
SELECT 
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(DISTINCT game_id) as games,
  AVG(player_count) as avg_players,
  SUM(CASE WHEN null_points > 0 THEN 1 ELSE 0 END) as games_with_nulls
FROM (
  SELECT 
    game_date,
    game_id,
    COUNT(*) as player_count,
    COUNT(CASE WHEN points IS NULL THEN 1 END) as null_points
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
  GROUP BY game_date, game_id
)
GROUP BY week
ORDER BY week DESC;
```

**Expected:** Avg 20-30 players, 0 games with nulls

---

**3. ESPN vs BDL Overlap**
```sql
-- How often do we get both sources?
SELECT 
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(DISTINCT game_id) as overlapping_games,
  AVG(stat_accuracy) as avg_accuracy
FROM (
  SELECT 
    e.game_date,
    e.game_id,
    AVG(CASE WHEN e.points = b.points THEN 1.0 ELSE 0.0 END) as stat_accuracy
  FROM `nba-props-platform.nba_raw.espn_boxscores` e
  JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON e.game_date = b.game_date
    AND e.game_id = b.game_id
    AND e.player_lookup = b.player_lookup
  WHERE e.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
  GROUP BY e.game_date, e.game_id
)
GROUP BY month
ORDER BY month DESC;
```

**Expected:** Low overlap (0-5 games/month), >95% accuracy when overlap exists

---

## 🎓 Understanding ESPN's Role

### Data Collection Trigger

ESPN Boxscore collection is triggered **ONLY** during:

1. **Early Morning Final Check** workflow failures
2. Manual backup validation scenarios
3. Data quality investigation requests

**This means:**
- ✅ Most days = no ESPN data = **NORMAL**
- ✅ ESPN appears sporadically = **EXPECTED**
- ⚠️ ESPN appears regularly = **UNUSUAL** (investigate workflow)

---

### Backup Data Philosophy

```
Primary Sources (Always Running):
├── Ball Don't Lie      → Comprehensive, real-time
└── NBA.com Gamebooks   → Official, authoritative

Backup Sources (Triggered Only):
└── ESPN Boxscores      → Validation checkpoint
    ↑
    Only runs when primary sources need validation
```

**Monitoring Focus:**
- **Primary sources:** Monitor for completeness (all games expected)
- **Backup sources:** Monitor for quality (accuracy when it exists)

---

## 🔧 Automated Monitoring Setup

### Cron Job (Daily Check)

```bash
# /etc/cron.d/espn-boxscore-validation
# Run at 8 AM PT every day during NBA season (Oct-June)

0 8 * 10-12,1-6 * /path/to/scripts/validate-espn-boxscore yesterday >> /var/log/espn-validation.log 2>&1
```

---

### BigQuery Scheduled Query

Create a scheduled query to track metrics:

```sql
-- Name: ESPN Boxscore Daily Metrics
-- Schedule: Every day at 9 AM PT
-- Destination: validation.espn_daily_metrics

INSERT INTO `nba-props-platform.validation.espn_daily_metrics`
SELECT 
  CURRENT_DATE() as check_date,
  CURRENT_TIMESTAMP() as check_time,
  
  -- Yesterday's data
  (SELECT COUNT(DISTINCT game_id) 
   FROM `nba-props-platform.nba_raw.espn_boxscores` 
   WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as espn_games,
  
  (SELECT COUNT(DISTINCT game_id)
   FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
   WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as bdl_games,
  
  -- Last 7 days
  (SELECT COUNT(DISTINCT game_date)
   FROM `nba-props-platform.nba_raw.espn_boxscores`
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) as espn_dates_last_7d,
  
  -- Quality metrics
  (SELECT COUNT(*)
   FROM `nba-props-platform.nba_raw.espn_boxscores`
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
     AND points IS NULL) as null_points_last_7d;
```

---

### Alert Queries (Cloud Monitoring)

Create these as Cloud Monitoring alerts:

**Alert 1: ESPN Without BDL (Critical)**
```sql
SELECT 
  COUNT(*) as problem_count
FROM (
  SELECT game_date, game_id FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  EXCEPT DISTINCT
  SELECT game_date, game_id FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
HAVING problem_count > 0;
```

**Alert Condition:** `problem_count > 0`  
**Severity:** Critical  
**Notification:** Slack + Email

---

**Alert 2: NULL Core Stats (Warning)**
```sql
SELECT 
  COUNT(*) as null_count
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND points IS NULL;
```

**Alert Condition:** `null_count > 0`  
**Severity:** Warning  
**Notification:** Slack

---

## 📋 Seasonal Checklist

### Season Start (October)

- [ ] Review and update this monitoring guide
- [ ] Test all validation queries with current season data
- [ ] Verify CLI tool works (`validate-espn-boxscore help`)
- [ ] Set up cron jobs for daily validation
- [ ] Configure Cloud Monitoring alerts
- [ ] Create BigQuery scheduled queries
- [ ] Brief team on ESPN's sparse nature (avoid false alarms)

---

### Mid-Season Review (January)

- [ ] Review monthly metrics (collection frequency, quality)
- [ ] Check for any unexpected patterns
- [ ] Verify alert configuration working correctly
- [ ] Update monitoring guide if needed
- [ ] Review ESPN vs BDL overlap and accuracy

---

### Season End (June)

- [ ] Generate final season report
- [ ] Document any issues encountered
- [ ] Archive validation logs
- [ ] Update monitoring guide with lessons learned
- [ ] Disable daily cron jobs (resume in October)

---

## 📞 Troubleshooting

### "Why is ESPN collecting data today?"

**Check:**
1. Did Early Morning Final Check workflow run?
2. Was there a manual backup validation request?
3. Are there known BDL issues today?

**Normal Reasons:**
- BDL scraper had issues
- Manual data quality investigation
- Backup validation test

---

### "ESPN and BDL stats don't match"

**Investigation Steps:**
1. Run detailed comparison (uncomment SQL section)
2. Check NBA.com official stats
3. Verify both scrapers ran correctly
4. Check processing timestamps
5. Look for data source API changes

**Resolution:**
- If ESPN wrong: Document, use BDL
- If BDL wrong: Use ESPN, investigate BDL issue
- If both wrong: Use NBA.com official, investigate both

---

### "I got 100+ ESPN games this month"

**This is UNUSUAL** - ESPN should be sparse

**Check:**
1. Is backup workflow triggering too often?
2. Is there a systemic BDL failure?
3. Was there manual backfill activity?

**Action:**
- Review workflow logs
- Check BDL health
- Investigate why backup triggering frequently

---

## 📚 Quick Reference

### Essential Commands

```bash
# Daily check (30 seconds)
./scripts/validate-espn-boxscore yesterday

# Quality validation (1 minute)
./scripts/validate-espn-boxscore quality

# Cross-validation (2 minutes)
./scripts/validate-espn-boxscore cross-validate

# Weekly comprehensive (5 minutes)
./scripts/validate-espn-boxscore all
```

---

### Key Files

```
validation/queries/raw/espn_boxscore/
├── README.md                       # Quick-start guide
├── DISCOVERY_FINDINGS.md           # Data characteristics
├── MONITORING_GUIDE.md             # This file
├── data_existence_check.sql        # Basic health check
├── cross_validate_with_bdl.sql     # Compare sources
├── daily_check_yesterday.sql       # Yesterday validation
├── data_quality_checks.sql         # Quality metrics
└── player_stats_comparison.sql     # Detailed comparison
```

---

### Expected Patterns (Quick Reference)

| Scenario | Expected | Status |
|----------|----------|--------|
| No ESPN data yesterday | NORMAL | ✅ |
| ESPN data appears sporadically | NORMAL | ✅ |
| ESPN + BDL both exist | IDEAL | ✅ |
| ESPN exists, BDL doesn't | PROBLEM | 🔴 |
| Stats differ by 1-2 points | ACCEPTABLE | ⚪ |
| Stats differ by >5 points | INVESTIGATE | 🔴 |
| ESPN coverage <10% | NORMAL | ✅ |

---

## 🎯 Success Metrics

**Healthy ESPN Backup Monitoring:**

1. ✅ No false alarms about "missing data"
2. ✅ Quick detection when ESPN exists without BDL
3. ✅ Stat accuracy >95% when overlap exists
4. ✅ Zero NULL core stats (points, rebounds, assists)
5. ✅ Team assignments 100% accurate

**Unhealthy Signs:**

1. ⚠️ Frequent ESPN collection (>20 games/month)
2. 🔴 Stat accuracy <90%
3. 🔴 NULL points values appearing
4. 🔴 Team mismatches detected

---

## 📝 Document Maintenance

**Review Schedule:**
- Before each season starts (September)
- After each season ends (June)
- When validation issues detected

**Update Triggers:**
- New validation queries added
- Alert thresholds adjusted
- Workflow changes affecting ESPN collection
- Processor changes affecting data structure

---

**Last Updated:** October 13, 2025  
**Next Review:** September 2026 (before 2026-27 season)  
**Owner:** Data Engineering Team  
**Status:** Ready for Season Start

---

## 🚀 Quick Start for New Season

When NBA season starts:

```bash
# Day 1: Verify everything works
./scripts/validate-espn-boxscore help
./scripts/validate-espn-boxscore existence
./scripts/validate-espn-boxscore quality

# Day 2+: Daily monitoring
./scripts/validate-espn-boxscore yesterday

# Weekly: Comprehensive check
./scripts/validate-espn-boxscore all

# As needed: Cross-validation
./scripts/validate-espn-boxscore cross-validate
```

**Remember:** ESPN is a sparse backup source. Most days showing "no data" is perfectly normal and expected! 🎯
