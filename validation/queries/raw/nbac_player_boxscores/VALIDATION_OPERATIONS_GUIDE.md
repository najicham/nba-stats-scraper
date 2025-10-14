# NBA.com Player Boxscores - Validation Operations Guide

**Purpose:** Step-by-step guide for validating NBA.com player boxscore data during active season and after historical backfills  
**Audience:** Data Engineers, DevOps, Analytics Team  
**Status:** Ready for Season Start  
**Last Updated:** October 13, 2025

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Pre-Season Checklist](#pre-season-checklist)
3. [Season Start: First Games Validation](#season-start)
4. [Daily Operations Workflow](#daily-operations)
5. [Weekly Validation Routine](#weekly-validation)
6. [Historical Backfill Validation](#backfill-validation)
7. [Alert Thresholds & Escalation](#alert-thresholds)
8. [Troubleshooting Guide](#troubleshooting)
9. [Monitoring Dashboard Queries](#monitoring-dashboard)
10. [Seasonal Checkpoints](#seasonal-checkpoints)

---

## 📖 Overview {#overview}

### What is NBA.com Player Boxscores?

**Data Source:** Official NBA.com player statistics (authoritative)  
**Processor:** `NbacPlayerBoxscoreProcessor`  
**Table:** `nba-props-platform.nba_raw.nbac_player_boxscores`  
**Update Frequency:** Post-game (8 PM & 11 PM PT) + Recovery workflows

### Why This Data Matters

**Business Impact:** CRITICAL (HIGH priority)
- Official NBA source of truth for player statistics
- Cross-validation source for Ball Don't Lie accuracy
- Enhanced metrics for advanced analytics (when available)
- Foundation for accurate prop bet settlement

### Validation Philosophy

**Three-Tiered Approach:**
1. **Daily validation** - Ensure yesterday's games captured
2. **Weekly validation** - Cross-validate with BDL, spot patterns
3. **Seasonal validation** - Complete coverage verification

---

## ✅ Pre-Season Checklist {#pre-season-checklist}

**When:** 1 week before NBA season starts (typically mid-October)

### 1. Verify Processor Deployment

```bash
# Check processor is deployed
gcloud run jobs describe nbac-player-boxscore-processor-backfill \
  --region=us-west2 \
  --format="table(name,status)"

# Expected: Job exists and is enabled
```

### 2. Verify Scraper Configuration

```bash
# Check scraper workflow
gcloud workflows describe get-nba-com-player-boxscore \
  --location=us-west2

# Confirm schedule: Post-game collection (8 PM & 11 PM PT)
```

### 3. Test Validation Queries

```bash
# Run all validation queries (should show "No data yet")
cd /path/to/nba-stats-scraper
./scripts/validate-nbac-boxscores all

# Expected: All queries return gracefully with "⚪ No data yet" messages
```

### 4. Set Up Monitoring Alerts

```bash
# Create alert policies in Google Cloud Monitoring
# See "Alert Thresholds" section for specific thresholds
```

### 5. Verify BDL Boxscores Working

```bash
# Ensure comparison source is functional
./scripts/validate-bdl-boxscores daily-check

# Expected: BDL data flowing normally
```

### Pre-Season Checklist Summary

- [ ] Processor deployed and healthy
- [ ] Scraper workflow configured
- [ ] Validation queries tested
- [ ] Monitoring alerts configured
- [ ] BDL comparison source verified
- [ ] Team notified of season start date
- [ ] On-call rotation established

---

## 🏀 Season Start: First Games Validation {#season-start}

**When:** First 3 days of NBA season (typically late October)

### Day 1: Opening Night Validation

**Morning After First Games (9 AM PT)**

#### Step 1: Verify Data Arrived

```bash
# Check if any data exists
bq query --use_legacy_sql=false "
SELECT 
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as games,
  MIN(game_date) as first_game_date
FROM \`nba-props-platform.nba_raw.nbac_player_boxscores\`
WHERE game_date >= CURRENT_DATE() - 7
"

# Expected: Should show opening night games (~2-4 games, ~60-120 records)
```

#### Step 2: Run Daily Check

```bash
./scripts/validate-nbac-boxscores daily-check

# ✅ GOOD: status = "✅ Complete"
# ❌ BAD: status = "❌ CRITICAL: No box score data"
```

**If data missing:**
1. Check scraper logs: Did it run?
2. Check processor logs: Did it process files?
3. Verify GCS files exist: `gs://nba-scraped-data/nba-com/player-boxscores/{date}/`
4. Manually trigger processor if needed

#### Step 3: Cross-Validate with BDL

```bash
./scripts/validate-nbac-boxscores cross-validate-bdl

# Expected: Status should be "✅ Perfect Match" for most players
# Acceptable: A few "🟡 INFO: In NBA.com only" (expected variation)
# CRITICAL: Any "🔴 CRITICAL: Point discrepancy >2"
```

**If discrepancies found:**
- NBA.com is source of truth
- Document discrepancies
- Investigate if pattern emerges
- May indicate BDL data quality issue

#### Step 4: Verify Enhanced Metrics

```bash
./scripts/validate-nbac-boxscores data-quality

# Expected: Most features show "⚪ Not yet available" (normal)
# Check: NBA Player ID completeness should be 100%
# Check: Starter flags should be populated
# Check: Plus/minus should be available
```

### Day 2-3: Establish Baseline

**Goal:** Confirm consistent data collection

#### Run Full Validation Suite

```bash
# Each morning at 9 AM PT
./scripts/validate-nbac-boxscores all

# Save results for baseline comparison
./scripts/validate-nbac-boxscores all > logs/nbac_boxscore_validation_$(date +%Y%m%d).log
```

#### Key Metrics to Establish

| Metric | Expected Baseline |
|--------|-------------------|
| Games per day | 8-15 (varies by schedule) |
| Players per game | 30-35 active players |
| Starters per game | ~10 (5 per team) |
| Match rate vs BDL | 95%+ perfect matches |
| Points discrepancies | <1% of players |
| Processing latency | Within 90 minutes of game end |

#### Baseline Establishment Checklist

- [ ] Day 1 data captured successfully
- [ ] Day 2 data captured successfully  
- [ ] Day 3 data captured successfully
- [ ] BDL comparison shows high match rate
- [ ] No critical point discrepancies
- [ ] Processing latency acceptable
- [ ] Team confident in data quality
- [ ] Ready for daily operations mode

---

## 🔄 Daily Operations Workflow {#daily-operations}

**When:** Every day during NBA season  
**Who:** Data Engineer on duty  
**Duration:** 5-10 minutes

### Morning Validation (9 AM PT)

**Daily routine once season is active:**

#### 1. Quick Health Check (2 minutes)

```bash
# One command to check yesterday
./scripts/validate-nbac-boxscores daily-check
```

**Interpret Results:**

| Status | Meaning | Action |
|--------|---------|--------|
| `✅ No games scheduled` | Off day | ✅ No action needed |
| `✅ Complete` | All good | ✅ No action needed |
| `⚠️ WARNING: X games missing` | Partial data | ⚠️ Investigate (see troubleshooting) |
| `⚠️ WARNING: Low player count` | Data quality issue | ⚠️ Check processor logs |
| `❌ CRITICAL: No box score data` | Complete failure | 🔴 Immediate action required |

#### 2. Review BDL Consistency (1 minute)

**Check the `bdl_consistency` column in daily check output:**

| Status | Meaning | Action |
|--------|---------|--------|
| `✅ Matches BDL` | Both sources agree | ✅ No action |
| `⚠️ Minor discrepancy` | 1-2 game difference | ⚪ Monitor, acceptable |
| `❌ Major discrepancy` | >2 game difference | ⚠️ Investigate both sources |
| `❌ BDL has data, NBA.com missing` | We're behind | 🔴 Check our scraper |

#### 3. Spot Check Recent Games (2 minutes)

```bash
# Verify a specific game from yesterday
bq query --use_legacy_sql=false "
SELECT 
  player_full_name,
  team_abbr,
  minutes,
  points,
  assists,
  total_rebounds,
  starter
FROM \`nba-props-platform.nba_raw.nbac_player_boxscores\`
WHERE game_date = CURRENT_DATE() - 1
  AND game_id = 'YYYYMMDD_AWAY_HOME'  -- Pick a game
ORDER BY points DESC
LIMIT 10
"

# Sanity check: Do stats look reasonable?
```

#### 4. Document Issues (if any)

If validation fails:
```bash
# Save detailed output
./scripts/validate-nbac-boxscores daily-check > logs/issue_$(date +%Y%m%d_%H%M%S).log

# Document in tracking spreadsheet or ticket system
# Include: Date, Status, Games affected, Actions taken
```

### Daily Operations Checklist

**Every Morning:**
- [ ] Run daily-check query
- [ ] Review status (✅/⚠️/❌)
- [ ] Check BDL consistency
- [ ] Spot check one game
- [ ] Document any issues
- [ ] Escalate if critical
- [ ] Update monitoring dashboard

**Time Required:** 5-10 minutes (2 minutes if all green)

---

## 📊 Weekly Validation Routine {#weekly-validation}

**When:** Monday mornings at 9 AM PT  
**Who:** Data Engineering team lead  
**Duration:** 30-45 minutes

### Step 1: Weekly Trends Review (10 minutes)

```bash
# Run weekly check
./scripts/validate-nbac-boxscores weekly-check

# Save output for trending
./scripts/validate-nbac-boxscores weekly-check --csv > reports/weekly_$(date +%Y%m%d).csv
```

**What to Look For:**

#### A. Daily Pattern Analysis
- Are there specific days with issues? (e.g., every Saturday missing)
- Do off-days show correctly as "⚪ No games"?
- Is coverage consistent across the week?

#### B. Data Quality Trends
- Is `avg_players_per_game` stable (~30-35)?
- Is `avg_starters_per_game` stable (~10)?
- Are `min_players_per_game` consistently >= 20?

#### C. BDL Consistency Over Time
- How many days show "✅ Matches BDL"?
- Are discrepancies random or systematic?
- Is one source consistently ahead/behind?

### Step 2: Cross-Validation Deep Dive (15 minutes)

```bash
# Run comprehensive BDL comparison
./scripts/validate-nbac-boxscores cross-validate-bdl --csv > reports/cross_validation_$(date +%Y%m%d).csv
```

**Analyze Results:**

```bash
# Count discrepancy types
cat reports/cross_validation_$(date +%Y%m%d).csv | grep "CRITICAL" | wc -l
cat reports/cross_validation_$(date +%Y%m%d).csv | grep "WARNING" | wc -l
cat reports/cross_validation_$(date +%Y%m%d).csv | grep "Perfect Match" | wc -l

# Calculate match rate
# Target: 95%+ perfect matches
```

**Investigate Critical Discrepancies:**

```sql
-- Find patterns in point discrepancies
SELECT 
  team_abbr,
  COUNT(*) as discrepancy_count,
  AVG(ABS(nbac_points - bdl_points)) as avg_point_diff
FROM (
  -- Run cross_validate_with_bdl.sql results
)
WHERE ABS(nbac_points - bdl_points) > 2
GROUP BY team_abbr
ORDER BY discrepancy_count DESC
```

If patterns emerge (e.g., one team consistently wrong):
- Check for team name mapping issues
- Verify source data quality
- May indicate broader data issue

### Step 3: Enhanced Metrics Check (5 minutes)

```bash
./scripts/validate-nbac-boxscores data-quality
```

**Track Feature Availability:**

| Feature | Week 1 | Week 2 | Week 3 | Target |
|---------|--------|--------|--------|--------|
| True Shooting % | 0% | 0% | 0% | TBD (future) |
| Effective FG % | 0% | 0% | 0% | TBD (future) |
| Plus/Minus | 100% | 100% | 100% | 100% |
| NBA Player IDs | 100% | 100% | 100% | 100% |

**Alert if:**
- NBA Player ID completeness drops below 100%
- Plus/minus availability drops below 95%
- Starter flag data missing

### Step 4: Generate Weekly Report (5 minutes)

**Weekly Report Template:**

```markdown
# NBA.com Player Boxscores - Weekly Validation Report
**Week Ending:** [Date]
**Data Engineer:** [Name]

## Summary
- ✅ Games Processed: X/Y (Z%)
- ✅ BDL Match Rate: X% (target: 95%+)
- ⚠️ Critical Discrepancies: X (target: 0)
- ✅ Average Latency: X minutes (target: <90min)

## Issues This Week
[List any issues, resolutions, ongoing investigations]

## Action Items
- [ ] Item 1
- [ ] Item 2

## Trends Observed
[Note any patterns, improvements, degradations]

## Next Week Focus
[What to monitor closely]
```

### Weekly Validation Checklist

**Every Monday:**
- [ ] Run weekly-check query
- [ ] Analyze daily patterns
- [ ] Run cross-validation
- [ ] Calculate match rate
- [ ] Investigate discrepancies
- [ ] Check enhanced metrics
- [ ] Generate weekly report
- [ ] Share with team
- [ ] Update tracking dashboard

**Time Required:** 30-45 minutes

---

## 🗄️ Historical Backfill Validation {#backfill-validation}

**When:** After completing historical season backfill  
**Who:** Data Engineering team  
**Duration:** 2-3 hours per season

### Before Starting Backfill

#### 1. Verify Backfill Plan

```bash
# Document planned backfill scope
cat > backfill_plan.md << EOF
# NBA.com Player Boxscores Backfill Plan

**Target Seasons:** 2021-22, 2022-23, 2023-24, 2024-25
**Expected Records:** ~165,000 (4 seasons × ~1,230 games × ~35 players)
**Start Date:** [Date]
**Estimated Duration:** 2-3 hours per season
**Processor:** nbac-player-boxscore-processor-backfill

**Season Date Ranges:**
- 2021-22: October 19, 2021 → June 20, 2022
- 2022-23: October 18, 2022 → June 20, 2023
- 2023-24: October 24, 2023 → June 20, 2024
- 2024-25: October 22, 2024 → June 20, 2025

**Success Criteria:**
- [ ] All seasons 100% complete
- [ ] Cross-validation with BDL 95%+ match
- [ ] Zero critical point discrepancies
- [ ] All NBA Player IDs populated
EOF
```

#### 2. Baseline Current State

```bash
# Capture "before" state
./scripts/validate-nbac-boxscores season-completeness > backfill_before.log

# Expected: Shows current season data only
```

### During Backfill (Per Season)

#### Execute Backfill Job

```bash
# Example: Backfill 2023-24 season
gcloud run jobs execute nbac-player-boxscore-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2023-10-24,--end-date,2024-06-20"

# Monitor progress
gcloud run jobs executions list \
  --job=nbac-player-boxscore-processor-backfill \
  --region=us-west2 \
  --limit=1
```

#### Wait for Completion

Expected duration: 90-120 minutes per season

Monitor via:
- Cloud Run Jobs console
- Processor logs
- BigQuery table row counts

#### Immediate Post-Backfill Check

```bash
# Quick verification that data appeared
bq query --use_legacy_sql=false "
SELECT 
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as total_games,
  COUNT(DISTINCT player_lookup) as unique_players,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game
FROM \`nba-props-platform.nba_raw.nbac_player_boxscores\`
WHERE game_date BETWEEN '2023-10-24' AND '2024-06-20'
GROUP BY year
"

# Expected: Should show ~42,000 records, ~1,230 games
```

### After Backfill Complete (Full Validation)

#### 1. Season Completeness Validation (30 minutes)

```bash
# Run comprehensive season check
./scripts/validate-nbac-boxscores season-completeness --csv > backfill_results.csv
```

**Review Output:**

```bash
# Check DIAGNOSTICS row
grep "DIAGNOSTICS" backfill_results.csv

# Expected:
# - null_playoff_flag_games: 0
# - failed_join_games: 0
# - null_team_games: 0
# - null_player_id_count: 0
```

**Check Each Team:**

```bash
# Count teams with full regular season
cat backfill_results.csv | grep "82" | wc -l

# Expected: 120 rows (30 teams × 4 seasons)
# Note: COVID seasons may have <82 games (acceptable)
```

**Generate Summary Report:**

```sql
-- Season-level summary
SELECT 
  season,
  COUNT(DISTINCT team) as teams,
  SUM(CAST(reg_games AS INT64)) / COUNT(DISTINCT team) as avg_games_per_team,
  MIN(CAST(reg_games AS INT64)) as min_games,
  MAX(CAST(reg_games AS INT64)) as max_games
FROM (
  -- Results from season_completeness_check.sql
)
WHERE row_type = 'TEAM'
GROUP BY season
ORDER BY season DESC
```

#### 2. Find Missing Games (15 minutes)

```bash
# Identify any gaps
./scripts/validate-nbac-boxscores missing-games --csv > missing_games.csv

# Expected: Very few or zero missing games
wc -l missing_games.csv

# If missing games found, create backfill task list
```

**Prioritize Missing Games:**

```bash
# Count missing by season
cat missing_games.csv | cut -d',' -f5 | sort | uniq -c

# Recent seasons: Higher priority
# Older seasons: Lower priority (if data doesn't exist)
```

#### 3. Cross-Validation with BDL (45 minutes)

**This is the CRITICAL validation step.**

```bash
# Compare all historical data with BDL
bq query --use_legacy_sql=false --max_rows=1000000 "$(cat validation/queries/raw/nbac_player_boxscores/cross_validate_with_bdl.sql | sed 's/DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)/\"2021-10-19\"/g')" > full_cross_validation.csv

# This will take several minutes for 165k records
```

**Calculate Match Statistics:**

```bash
# Overall match rate
total_players=$(cat full_cross_validation.csv | wc -l)
perfect_matches=$(cat full_cross_validation.csv | grep "Perfect Match" | wc -l)
echo "Match Rate: $(echo "scale=2; $perfect_matches * 100 / $total_players" | bc)%"

# Target: 95%+ match rate

# Critical discrepancies
critical=$(cat full_cross_validation.csv | grep "CRITICAL" | wc -l)
echo "Critical Discrepancies: $critical"

# Target: <1% of total records
```

**Analyze Discrepancy Patterns:**

```sql
-- Pattern analysis query
WITH discrepancies AS (
  SELECT 
    game_date,
    team_abbr,
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as discrepancy_count
  FROM (
    -- cross_validate_with_bdl results
  )
  WHERE status LIKE '%CRITICAL%' OR status LIKE '%WARNING%'
  GROUP BY game_date, team_abbr, year
)
SELECT 
  year,
  team_abbr,
  COUNT(*) as games_with_discrepancies,
  SUM(discrepancy_count) as total_discrepancies
FROM discrepancies
GROUP BY year, team_abbr
HAVING COUNT(*) > 10  -- More than 10 games with issues
ORDER BY total_discrepancies DESC
```

**If match rate < 95%:**
1. Investigate source data quality
2. Check for systematic differences (e.g., overtime games)
3. Verify team name mapping
4. Document known discrepancies
5. Create remediation plan if needed

#### 4. Playoff Validation (20 minutes)

```bash
# Verify playoff completeness
./scripts/validate-nbac-boxscores playoff-completeness
```

**Expected Results:**

| Season | Playoff Teams | Expected Games Range |
|--------|---------------|---------------------|
| 2021-22 | 16 teams | 4-28 games per team |
| 2022-23 | 16 teams | 4-28 games per team |
| 2023-24 | 16 teams | 4-28 games per team |
| 2024-25 | 16 teams | 4-28 games per team |

**All teams should show:** `✅ Complete`

**If missing playoff games:**
- Higher priority than regular season (playoffs = high value)
- Create immediate backfill plan
- Document for scraper improvement

#### 5. Data Quality Assessment (15 minutes)

```bash
# Run quality checks across all history
bq query --use_legacy_sql=false "$(cat validation/queries/raw/nbac_player_boxscores/data_quality_checks.sql | sed 's/DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)/\"2021-10-19\"/g')"
```

**Key Quality Metrics:**

| Check | Target | Acceptable Range |
|-------|--------|------------------|
| NBA Player ID completeness | 100% | 99%+ |
| Starter flag availability | 100% | 95%+ |
| Plus/minus availability | 100% | 90%+ |
| Field goal % calculations | Match 100% | 99%+ |

**If quality issues found:**
- Document patterns (specific dates, teams, games)
- Assess impact on downstream usage
- Create data quality improvement plan
- May require reprocessing some games

### Backfill Validation Report Template

```markdown
# NBA.com Player Boxscores - Backfill Validation Report
**Completed:** [Date]
**Engineer:** [Name]
**Seasons:** 2021-22, 2022-23, 2023-24, 2024-25

## Executive Summary
- ✅ Total Records Loaded: [X] (target: ~165,000)
- ✅ Season Completeness: [X]% (target: 100%)
- ✅ BDL Match Rate: [X]% (target: 95%+)
- ⚠️ Critical Discrepancies: [X] (target: <1%)

## Detailed Results

### Season Completeness
| Season | Teams | Avg Games | Status |
|--------|-------|-----------|--------|
| 2021-22 | 30 | 82 | ✅ Complete |
| 2022-23 | 30 | 82 | ✅ Complete |
| 2023-24 | 30 | 82 | ✅ Complete |
| 2024-25 | 30 | 82 | ✅ Complete |

### Missing Games
- Total: [X] games
- By season: [breakdown]
- Priority: [High/Medium/Low]
- Backfill plan: [Yes/No]

### Cross-Validation with BDL
- Perfect matches: [X]% 
- Minor discrepancies: [X]%
- Critical discrepancies: [X]%
- Patterns identified: [description]

### Data Quality
- NBA Player IDs: [X]% complete
- Starter flags: [X]% populated
- Plus/minus: [X]% available
- Field goal calculations: [X]% accurate

## Issues Identified
1. [Issue 1]
2. [Issue 2]

## Recommendations
1. [Recommendation 1]
2. [Recommendation 2]

## Sign-Off
- [ ] Data Engineer reviewed
- [ ] Analytics team reviewed
- [ ] Production-ready
```

### Historical Backfill Checklist

**Post-Backfill Validation:**
- [ ] Season completeness check passed
- [ ] Missing games identified and documented
- [ ] BDL cross-validation completed (95%+ match)
- [ ] Critical discrepancies investigated
- [ ] Playoff completeness verified
- [ ] Data quality checks passed
- [ ] Validation report generated
- [ ] Team sign-off received
- [ ] Data marked production-ready
- [ ] Monitoring dashboards updated

**Time Required:** 2-3 hours per season validation

---

## 🚨 Alert Thresholds & Escalation {#alert-thresholds}

### Alert Configuration

#### Critical Alerts (Immediate Response)

**Trigger:** Within 15 minutes  
**Escalation:** Page on-call engineer

| Alert | Threshold | Query | Action |
|-------|-----------|-------|--------|
| **No data for scheduled games** | 0 games when >0 expected | `daily-check` | Check scraper & processor immediately |
| **Point discrepancies >2** | Any player with >2 point difference | `cross-validate-bdl` | Investigate source data, may affect props |
| **Multiple games missing** | >3 games missing from yesterday | `daily-check` | Check scraper logs, manual recovery |
| **Complete processing failure** | Processor job failed | Cloud Logging | Restart processor, check for bugs |

#### Warning Alerts (Review Within 4 Hours)

**Trigger:** Business hours  
**Escalation:** Slack notification

| Alert | Threshold | Query | Action |
|-------|-----------|-------|--------|
| **Any point discrepancy** | 1-2 point difference | `cross-validate-bdl` | Document, monitor pattern |
| **Missing games (1-2)** | 1-2 games missing | `daily-check` | Investigate, may self-resolve |
| **Low player count** | <20 players per game | `daily-check` | Check processor logic |
| **Unusual starter count** | <9 or >11 starters/game | `daily-check` | Check starter flag logic |
| **High BDL discrepancy** | >5% mismatch rate weekly | `weekly-check` | Cross-source investigation |

#### Info Alerts (Review Next Business Day)

**Trigger:** Daily summary  
**Escalation:** Email report

| Alert | Threshold | Query | Action |
|-------|-----------|-------|--------|
| **Minor stat discrepancies** | Assists/rebounds differ by 1-2 | `cross-validate-bdl` | Document, normal variation |
| **NBA.com only players** | Players in NBA.com not BDL | `cross-validate-bdl` | Expected, NBA.com more complete |
| **Processing latency** | >90 minutes post-game | Monitoring | Acceptable, note for trending |

### Escalation Matrix

#### Level 1: Data Engineer On-Call
**Handles:** All daily validation, warnings, info alerts  
**Response Time:** 4 business hours  
**Escalate When:** Critical alerts, unable to resolve warnings

#### Level 2: Data Engineering Lead
**Handles:** Critical issues, pattern investigations  
**Response Time:** 1 hour (critical), 4 hours (pattern)  
**Escalate When:** System-wide failures, data integrity concerns

#### Level 3: Engineering Manager
**Handles:** Vendor escalation, process changes  
**Response Time:** 2 hours  
**Escalate When:** NBA.com API issues, architectural problems

### Alert Response Playbook

#### Critical: No Data for Scheduled Games

```bash
# Step 1: Verify games were scheduled
bq query --use_legacy_sql=false "
SELECT COUNT(*) as games 
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = CURRENT_DATE() - 1
"

# If 0 games: False alarm, close alert
# If >0 games: Continue investigation

# Step 2: Check if scraper ran
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=nba-com-player-boxscore-scraper \
  AND timestamp>=TIMESTAMP(CURRENT_DATE())" \
  --limit=50 --format=json

# Step 3: Check if files exist in GCS
gsutil ls gs://nba-scraped-data/nba-com/player-boxscores/$(date -d yesterday +%Y-%m-%d)/

# Step 4: Check if processor ran
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=nbac-player-boxscore-processor-backfill \
  AND timestamp>=TIMESTAMP(CURRENT_DATE())" \
  --limit=50 --format=json

# Step 5: Manual recovery if needed
# See "Troubleshooting Guide" section
```

---

## 🔧 Troubleshooting Guide {#troubleshooting}

### Common Issues & Solutions

#### Issue 1: Missing Yesterday's Games

**Symptoms:**
- Daily check shows missing games
- `status = "⚠️ WARNING: X games missing"`

**Diagnosis:**

```bash
# Check specific missing games
./scripts/validate-nbac-boxscores missing-games

# Check scraper logs
gcloud logging read "resource.labels.job_name=nba-com-player-boxscore-scraper \
  AND timestamp>=TIMESTAMP('$(date -d yesterday +%Y-%m-%d)')" \
  --format=json --limit=100

# Check GCS for files
gsutil ls gs://nba-scraped-data/nba-com/player-boxscores/$(date -d yesterday +%Y-%m-%d)/**/*.json
```

**Solutions:**

1. **Files missing from GCS:** Scraper failed
   ```bash
   # Manually trigger scraper
   gcloud workflows execute get-nba-com-player-boxscore \
     --data='{"date":"2025-10-22"}'
   ```

2. **Files in GCS but not in BigQuery:** Processor failed
   ```bash
   # Manually trigger processor
   gcloud run jobs execute nbac-player-boxscore-processor-backfill \
     --region=us-west2 \
     --args="--start-date,2025-10-22,--end-date,2025-10-22"
   ```

3. **Both ran but data incomplete:** Data quality issue
   - Check processor logs for errors
   - Verify source data quality
   - May need to reprocess

#### Issue 2: Point Discrepancies with BDL

**Symptoms:**
- Cross-validation shows critical discrepancies
- `status = "🔴 CRITICAL: Point discrepancy >2"`

**Diagnosis:**

```sql
-- Check specific discrepancy
SELECT 
  n.player_full_name,
  n.team_abbr,
  n.game_id,
  n.points as nbac_points,
  b.points as bdl_points,
  ABS(n.points - b.points) as diff,
  n.field_goals_made,
  n.three_pointers_made,
  n.free_throws_made
FROM `nba-props-platform.nba_raw.nbac_player_boxscores` n
JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
  ON n.game_id = b.game_id AND n.player_lookup = b.player_lookup
WHERE ABS(n.points - b.points) > 2
  AND n.game_date >= CURRENT_DATE() - 7
```

**Solutions:**

1. **NBA.com is correct (most likely):**
   - Document the discrepancy
   - NBA.com is official source of truth
   - May indicate BDL data quality issue
   - Update BDL if NBA.com is verified correct

2. **Data corruption:**
   - Check source JSON files
   - Verify processor logic
   - Reprocess if needed

3. **Systematic issue:**
   - Check for overtime games (common source of discrepancy)
   - Verify team name mapping
   - Check player name normalization

#### Issue 3: Low Player Count

**Symptoms:**
- Daily check shows `min_players_per_game < 20`
- `status = "⚠️ WARNING: Suspiciously low player count"`

**Diagnosis:**

```sql
-- Find games with low player counts
SELECT 
  game_id,
  game_date,
  COUNT(DISTINCT player_lookup) as players,
  STRING_AGG(DISTINCT team_abbr) as teams
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_id, game_date
HAVING COUNT(DISTINCT player_lookup) < 20
```

**Solutions:**

1. **Partial scrape:** Some players missing
   - Check scraper logs for errors
   - Rerun scraper for affected games
   - Verify source data completeness

2. **Processor error:** Not all players processed
   - Check processor logs
   - Verify JSON parsing logic
   - Reprocess affected games

3. **Legitimate low count:** Rare but possible
   - Verify against official NBA boxscore
   - Document if legitimate

#### Issue 4: Processing Latency

**Symptoms:**
- Data arrives >90 minutes after game ends
- Dashboard shows delayed processing

**Diagnosis:**

```bash
# Check processor execution times
gcloud run jobs executions list \
  --job=nbac-player-boxscore-processor-backfill \
  --region=us-west2 \
  --limit=20

# Check for backlog
gsutil ls -l gs://nba-scraped-data/nba-com/player-boxscores/$(date +%Y-%m-%d)/ | wc -l
```

**Solutions:**

1. **Processor slow:** Resource constraints
   - Check memory/CPU usage
   - May need to increase resources
   - Consider parallel processing

2. **Backlog buildup:** Too many files
   - Increase processor concurrency
   - Add more Cloud Run instances
   - Optimize processing logic

3. **Scraper delay:** Late source data
   - Check NBA.com API response times
   - Verify scraper schedule
   - May be out of our control

### When to Request Help

**Escalate to Data Engineering Lead if:**
- Issue persists >4 hours
- Pattern of failures (3+ consecutive days)
- Critical discrepancies affecting revenue
- Unknown root cause after initial investigation

**Escalate to Engineering Manager if:**
- System-wide failure
- NBA.com API issues
- Process changes needed
- Architectural problems

---

## 📊 Monitoring Dashboard Queries {#monitoring-dashboard}

### Dashboard Setup

Create a Looker Studio (or similar) dashboard with these key metrics:

#### 1. Daily Health Status

```sql
-- Dashboard Tile: Daily Validation Status
SELECT 
  game_date,
  scheduled_games,
  games_with_data,
  CASE
    WHEN scheduled_games = 0 THEN 'No games'
    WHEN games_with_data = scheduled_games THEN 'Complete'
    WHEN games_with_data = 0 THEN 'Critical'
    ELSE 'Incomplete'
  END as status
FROM (
  SELECT 
    s.game_date,
    COUNT(*) as scheduled_games,
    COUNT(DISTINCT b.game_id) as games_with_data
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  LEFT JOIN `nba-props-platform.nba_raw.nbac_player_boxscores` b
    ON s.game_date = b.game_date AND s.game_id = b.game_id
  WHERE s.game_date >= CURRENT_DATE() - 30
  GROUP BY s.game_date
)
ORDER BY game_date DESC
```

#### 2. BDL Match Rate Trend

```sql
-- Dashboard Tile: BDL Consistency (7-day rolling)
SELECT 
  game_date,
  total_players,
  perfect_matches,
  ROUND(100.0 * perfect_matches / total_players, 1) as match_rate_pct
FROM (
  SELECT 
    n.game_date,
    COUNT(*) as total_players,
    COUNT(CASE WHEN ABS(n.points - b.points) = 0 THEN 1 END) as perfect_matches
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores` n
  JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON n.game_id = b.game_id AND n.player_lookup = b.player_lookup
  WHERE n.game_date >= CURRENT_DATE() - 30
  GROUP BY n.game_date
)
ORDER BY game_date DESC
```

#### 3. Processing Latency

```sql
-- Dashboard Tile: Processing Latency
SELECT 
  game_date,
  AVG(TIMESTAMP_DIFF(processed_at, scrape_timestamp, MINUTE)) as avg_latency_minutes,
  MAX(TIMESTAMP_DIFF(processed_at, scrape_timestamp, MINUTE)) as max_latency_minutes
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date >= CURRENT_DATE() - 30
  AND scrape_timestamp IS NOT NULL
  AND processed_at IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC
```

#### 4. Data Quality Score

```sql
-- Dashboard Tile: Daily Data Quality Score (0-100)
SELECT 
  game_date,
  ROUND(
    (nba_id_completeness * 0.4) +  -- 40% weight
    (player_count_quality * 0.3) +  -- 30% weight
    (bdl_match_rate * 0.3),          -- 30% weight
  1) as quality_score
FROM (
  SELECT 
    game_date,
    100.0 * COUNT(CASE WHEN nba_player_id IS NOT NULL THEN 1 END) / COUNT(*) as nba_id_completeness,
    CASE 
      WHEN AVG(players_per_game) BETWEEN 28 AND 37 THEN 100
      WHEN AVG(players_per_game) BETWEEN 25 AND 40 THEN 80
      ELSE 50
    END as player_count_quality,
    -- BDL match rate subquery would go here
    95.0 as bdl_match_rate  -- Placeholder
  FROM (
    SELECT 
      game_date,
      game_id,
      nba_player_id,
      COUNT(*) OVER (PARTITION BY game_id) as players_per_game
    FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
    WHERE game_date >= CURRENT_DATE() - 30
  )
  GROUP BY game_date
)
ORDER BY game_date DESC
```

### Dashboard Layout Recommendation

```
┌─────────────────────────────────────────────────────┐
│  NBA.com Player Boxscores - Data Quality Dashboard  │
├─────────────────────────────────────────────────────┤
│  Last Updated: [timestamp]                          │
│  Status: ✅ Healthy  |  Alerts: 0 Critical, 2 Info  │
└─────────────────────────────────────────────────────┘

┌──────────────┬──────────────┬──────────────┬─────────────┐
│   Games      │   Players    │   BDL Match  │  Latency    │
│   98.5%      │   32.4 avg   │   96.2%      │  45 min     │
│   ✅ Good    │   ✅ Good    │   ✅ Good    │  ✅ Good    │
└──────────────┴──────────────┴──────────────┴─────────────┘

┌─────────────────────────────────────────────────────┐
│  Daily Validation Status (Last 30 Days)             │
│  [Line Chart: Games Scheduled vs Games Processed]   │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  BDL Match Rate Trend (Rolling 7-Day)               │
│  [Line Chart: Match Rate % over time]               │
│  Target: 95%+                                        │
└─────────────────────────────────────────────────────┘

┌──────────────────────┬──────────────────────────────┐
│  Recent Issues       │  Data Quality Score          │
│  [Table: Last 10]    │  [Gauge Chart: 0-100]        │
└──────────────────────┴──────────────────────────────┘
```

---

## 📅 Seasonal Checkpoints {#seasonal-checkpoints}

### Season Start (Late October)

**Week 1:**
- [ ] Daily validation passing
- [ ] BDL comparison working
- [ ] Baseline metrics established
- [ ] Team trained on monitoring

**Week 2:**
- [ ] All alerts configured
- [ ] Dashboard live
- [ ] Weekly reports started
- [ ] No critical issues

**Week 4:**
- [ ] Monthly review complete
- [ ] Process refinements identified
- [ ] Documentation updated

### Mid-Season (January - All-Star Break)

**January:**
- [ ] Review first quarter data quality
- [ ] Assess BDL consistency trends
- [ ] Identify improvement opportunities
- [ ] Plan for All-Star break

**All-Star Break:**
- [ ] Verify 4-7 day gap handled correctly
- [ ] Use downtime for maintenance
- [ ] Review and update procedures
- [ ] Prepare for playoff push

### Playoff Season (April - June)

**Playoff Start:**
- [ ] Verify playoff flag working
- [ ] Increased monitoring (playoffs = high value)
- [ ] Daily validation during playoffs
- [ ] All games critical

**Finals:**
- [ ] Maximum attention to data quality
- [ ] Real-time monitoring
- [ ] Same-day validation
- [ ] Zero tolerance for issues

### Season End (June - October)

**Post-Season:**
- [ ] Final season validation complete
- [ ] Historical backfill if needed
- [ ] Season summary report
- [ ] Lessons learned documented

**Off-Season:**
- [ ] Reduced monitoring (no new data)
- [ ] System maintenance
- [ ] Process improvements
- [ ] Prepare for next season

---

## 📝 Summary Checklists

### Daily Operations (5-10 minutes)
- [ ] Run `daily-check` query
- [ ] Review status and BDL consistency
- [ ] Spot check one recent game
- [ ] Document any issues
- [ ] Escalate if critical

### Weekly Operations (30-45 minutes)
- [ ] Run `weekly-check` query
- [ ] Run `cross-validate-bdl` query
- [ ] Calculate match rate (target: 95%+)
- [ ] Check enhanced metrics availability
- [ ] Generate weekly report
- [ ] Share with team

### Monthly Operations (2-3 hours)
- [ ] Run `season-completeness` query
- [ ] Review all validation trends
- [ ] Identify patterns or issues
- [ ] Update documentation
- [ ] Team retrospective meeting

### After Backfill (2-3 hours per season)
- [ ] Season completeness validation
- [ ] Find and document missing games
- [ ] Full BDL cross-validation
- [ ] Playoff completeness check
- [ ] Data quality assessment
- [ ] Generate validation report
- [ ] Get team sign-off

---

## 🎯 Success Criteria

### Data Completeness
- ✅ 100% of scheduled games captured
- ✅ 95%+ match rate with BDL
- ✅ <1% critical point discrepancies
- ✅ All playoff games complete

### Data Quality
- ✅ 100% NBA Player IDs populated
- ✅ 95%+ starter flags populated
- ✅ 90%+ plus/minus available
- ✅ 30-35 players per game average

### Operational Excellence
- ✅ Daily validation <10 minutes
- ✅ <90 minute processing latency
- ✅ <5% false positive alert rate
- ✅ Zero undetected failures

---

## 📚 Related Documentation

- **Setup Guide:** `validation/queries/raw/nbac_player_boxscores/README.md`
- **Master Validation Guide:** `validation/NBA_DATA_VALIDATION_MASTER_GUIDE.md`
- **Processor Documentation:** `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`
- **BDL Comparison:** `validation/queries/raw/bdl_boxscores/`

---

**Document Owner:** NBA Props Data Engineering Team  
**Last Updated:** October 13, 2025  
**Next Review:** When NBA season starts  
**Feedback:** Update this document as procedures are refined during actual season operations
