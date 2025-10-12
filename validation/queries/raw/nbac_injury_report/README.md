# NBA.com Injury Report Validation Queries

Validation queries for hourly injury report data from NBA.com.

---

## 🎯 Overview

These queries validate the **most critical data source** for props risk management - NBA injury reports. Unlike game-based data, injury reports are:

- **Hourly snapshots** (24 per day, but 60-70% empty is normal)
- **Peak hours critical** (5 PM and 8 PM ET have most data)
- **Game-day focused** (off days with sparse reports are expected)
- **Status-tracking** (intraday changes indicate late scratches)

---

## 📁 Query Files

### Historical Validation

#### 1. `hourly_snapshot_completeness.sql`
**Purpose:** Detect scraper failures by checking hourly snapshot coverage

**Key Metrics:**
- Hourly snapshots per day (expect 5-10 during season)
- Player counts per day (expect 40-70 during season)
- Peak hour presence (5 PM, 8 PM)
- Game day vs off day distinction

**Severity Levels:**
- 🔴 **CRITICAL**: Game day with 0-2 snapshots (scraper failure)
- 🟡 **ERROR**: Game day missing peak hours
- ⚠️ **WARNING**: Moderate coverage (3-4 snapshots)
- ⚪ **EXPECTED**: Off day with 0-3 snapshots

**When to Run:** Daily, after backfills, investigating scraper issues

---

#### 2. `player_coverage_trends.sql`
**Purpose:** Track player count trends to detect data quality degradation

**Key Metrics:**
- Daily unique player counts
- 7-day and 30-day rolling averages
- Game day vs off day context
- Injury status breakdown

**Alert Conditions:**
- 50%+ drop on game day (critical anomaly)
- 30%+ drop on game day (warning)
- Sustained downward trend

**When to Run:** Weekly (Monday), investigating quality issues

---

#### 3. `confidence_score_monitoring.sql`
**Purpose:** Monitor PDF parsing quality via confidence scores

**Key Metrics:**
- Average confidence per day
- Distribution (low, medium, high confidence)
- Percentage below 0.7 threshold
- Rolling 7-day average

**Alert Conditions:**
- Average confidence <0.6 (critical)
- Average confidence <0.7 (error)
- >20% records below 0.7 (warning)

**When to Run:** Weekly, investigating parsing issues

---

### Game Day Monitoring

#### 4. `game_day_coverage_check.sql`
**Purpose:** Cross-validate with schedule - ensure reports on all game days

**Key Metrics:**
- Game dates from schedule
- Hourly snapshot coverage per game day
- Peak hour presence
- Player counts

**Alert Conditions:**
- Game day with 0 reports (CRITICAL - high revenue risk)
- Game day with <3 snapshots (CRITICAL)
- Missing both peak hours (ERROR)

**When to Run:** Daily, weekly health checks, after backfills

**Business Impact:** Missing injury reports on game days = props offered on unavailable players = customer complaints + refunds

---

#### 5. `peak_hour_validation.sql`
**Purpose:** Validate critical 5 PM and 8 PM ET reports on game days

**Key Metrics:**
- Player counts at 5 PM (hour 17)
- Player counts at 8 PM (hour 20)
- Game dates from schedule

**Alert Conditions:**
- Both peak hours missing (CRITICAL)
- One peak hour missing (ERROR)
- Low player counts (<20)

**When to Run:** Daily (during season), investigating missing data

**Why Critical:** Peak hours have most comprehensive injury data. Missing both = operating blind for props decisions.

---

### Business Intelligence

#### 6. `status_change_detection.sql`
**Purpose:** Track intraday status changes (late scratches, game-time decisions)

**Key Metrics:**
- Status changes within same day
- Time of first vs last status
- Impact level categorization

**Impact Levels:**
- 🔴 **HIGH**: Availability changed (out ↔ available)
- 🟡 **MEDIUM**: Uncertainty changed (questionable ↔ probable)
- ⚪ **LOW**: Expected progression (doubtful → out)

**When to Run:** Daily after games (11 PM), investigating specific players

**Business Use:** Identify late scratches for props risk management and post-game analysis

---

### Daily Monitoring

#### 7. `daily_check_yesterday.sql`
**Purpose:** Automated morning check for yesterday's injury reports

**Key Metrics:**
- Games scheduled yesterday
- Hourly snapshots captured
- Peak hour presence
- Overall status

**Status Values:**
- `✅ Complete: Game day` - All systems operational
- `⚪ Expected: Off day` - Normal sparse reports
- `🔴 CRITICAL: Game day - NO injury reports` - **IMMEDIATE ACTION**
- `🟡 ERROR: Missing peak hours` - **INVESTIGATE**

**When to Run:** Every morning at 9 AM (automated via cron)

**Automation:**
```bash
# Add to crontab
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-injuries yesterday
```

---

## 🚀 Quick Start

### Using CLI Tool (Recommended)
```bash
# Make executable
chmod +x scripts/validate-injuries

# Morning routine
validate-injuries yesterday

# Full health check
validate-injuries completeness

# Find late scratches
validate-injuries changes
```

### Running Queries Directly
```bash
# Run specific query
bq query --use_legacy_sql=false < hourly_snapshot_completeness.sql

# Save to CSV
bq query --use_legacy_sql=false --format=csv < peak_hour_validation.sql > results.csv

# Save to BigQuery table
bq query --use_legacy_sql=false \
  --destination_table=nba-props-platform:validation.injury_peaks_20251012 \
  < peak_hour_validation.sql
```

---

## 📊 Understanding Results

### Normal Patterns

#### Active Season (October - June)
```
Game Days:
- 5-10 hourly snapshots per day
- 40-70 unique players
- Both peak hours (5 PM, 8 PM) present

Off Days:
- 0-3 hourly snapshots
- 0-15 unique players
- Peak hours may be missing (NORMAL)
```

#### Off-Season (July - September)
```
All Days:
- 0-3 hourly snapshots per day
- 0-10 unique players
- Sporadic peak hour coverage (NORMAL)
```

### Critical vs Normal

#### 🔴 CRITICAL (Immediate Action)
```sql
-- Game day with NO reports
game_date: 2025-10-11 (12 games scheduled)
hourly_snapshots: 0
status: CRITICAL - scraper failure

-- Game day with very few snapshots
game_date: 2025-10-11 (12 games scheduled)
hourly_snapshots: 2
status: CRITICAL - incomplete scraper run
```

#### ⚪ NORMAL (No Action)
```sql
-- Off day with no reports
game_date: 2025-10-09 (0 games scheduled)
hourly_snapshots: 0
status: EXPECTED - off day

-- Off day with sparse reports
game_date: 2025-10-09 (0 games scheduled)
hourly_snapshots: 2
status: EXPECTED - off day sparse reports
```

---

## 🔑 Key Differences from Odds Validation

| Aspect | Odds Data | Injury Data |
|--------|-----------|-------------|
| **Granularity** | Game-based (1 snapshot) | Hourly (24 snapshots) |
| **Empty Normal?** | ❌ No - empty = failure | ✅ Yes - 60-70% empty |
| **Critical Times** | Pre-game (2hrs before) | Peak hours (5 PM, 8 PM) |
| **Validation Focus** | Game completeness | Game day coverage |
| **Expected Records** | 8 rows per game | 40-70 players per peak hour |
| **Off-Day Behavior** | No data expected | Sparse data is normal |

---

## 📅 Recommended Schedule

### Daily
- **9 AM:** Run `daily_check_yesterday.sql` (automated)
- **11 PM:** Run `status_change_detection.sql` (find late scratches)

### Weekly
- **Monday:** Run all historical queries (completeness, trends, confidence)
- **Friday:** Run game day validation (gameday, peaks)

### Monthly
- **First Monday:** Full health check + save results to BigQuery tables

### After Backfills
- Run all queries to verify data integrity

---

## 🚨 Alert Priorities

### P0 - CRITICAL (Immediate Response)
- Game day with 0 injury reports
- Game day with both peak hours missing
- 50%+ player count drop on game day

**Impact:** High revenue risk - props may be offered on unavailable players

---

### P1 - ERROR (Same Day Response)
- Game day with <3 hourly snapshots
- Game day missing one peak hour
- Confidence scores <0.7

**Impact:** Incomplete data - may miss injury updates

---

### P2 - WARNING (Weekly Review)
- 30%+ player count drop on game day
- Low confidence scores (0.7-0.8)
- Moderate snapshot coverage (3-4 per day)

**Impact:** Data quality issues - investigate patterns

---

### P3 - INFO (Monthly Review)
- Status changes for business intelligence
- Long-term trends in player coverage
- Historical confidence score patterns

**Impact:** Business optimization - not operational issues

---

## 💡 Pro Tips

### 1. Season Awareness
Adjust expectations based on season:
```sql
-- Add to queries as needed
CASE 
  WHEN EXTRACT(MONTH FROM report_date) BETWEEN 7 AND 9 THEN 'off-season'
  WHEN EXTRACT(MONTH FROM report_date) BETWEEN 10 AND 6 THEN 'active-season'
END as season_phase
```

### 2. Peak Hour Focus
When investigating issues, always check peak hours first:
```bash
validate-injuries peaks
```
These hours (5 PM, 8 PM ET) have most comprehensive data.

### 3. Cross-Validation
Combine with schedule validation:
```bash
validate-injuries gameday
# Then drill down on specific dates
```

### 4. Trend Analysis
Save weekly results to track patterns:
```bash
validate-injuries trends --table
# Creates timestamped table for historical tracking
```

---

## 🔗 Related Resources

- **CLI Tool:** `scripts/validate-injuries`
- **Quick Start Guide:** `scripts/VALIDATE_INJURIES_CLI.md`
- **Processor Reference:** See "NBA.com Injury Report" in processor docs
- **Base Validator:** `validation/base_validator.py`

---

## 📞 Support

**Questions or Issues?**
- Check CLI guide: `validate-injuries help`
- Review processor docs for data structure
- Test queries with recent dates first
- Adjust date ranges in queries as needed

---

**Last Updated:** October 12, 2025  
**Query Count:** 7  
**Status:** Production Ready  
**Critical Priority:** P0 (Revenue Protecting)
