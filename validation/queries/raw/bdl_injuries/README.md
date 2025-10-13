# BDL Injuries Validation Queries

## Overview

Ball Don't Lie (BDL) Injuries is a **daily snapshot** data source that shows **current active injuries** across the NBA. Unlike historical tables, this data:

- ✅ Updates daily during NBA season (October - June)
- ✅ Shows who's injured RIGHT NOW (not historical)
- ✅ No data expected during off-season (July - September)
- ✅ Small dataset: ~20-60 injuries per day typical

## Data Characteristics

**Expected During Season:**
- **20-60 injuries** per day
- **15-25 teams** represented (most teams have some injuries)
- **1.0 confidence scores** (excellent BDL parsing)
- **95-100% return date parsing** success

**Expected During Off-Season:**
- Zero or minimal data (scraper may not run)
- This is NORMAL - no alerts needed

## Validation Queries

### Daily Operations (Run Every Morning)

#### 1. `daily_check_yesterday.sql`
**Purpose:** Verify yesterday's scraper ran successfully  
**Schedule:** Run at 9 AM daily during season  
**Alerts:** Status != "✅ Complete" or "⚪ Off-season"

**What it checks:**
- Did scraper run yesterday?
- Reasonable injury count? (10+ during season)
- Good team coverage? (10+ teams)
- Confidence scores healthy? (0.9+)

**Usage:**
```bash
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

#### 2. `weekly_check_last_7_days.sql`
**Purpose:** Trend monitoring and pattern detection  
**Schedule:** Run weekly or when investigating issues  
**Alerts:** Missing days or declining quality

**What it checks:**
- Complete 7-day coverage
- Consistent injury counts
- Stable confidence scores
- Day-by-day comparison

**Usage:**
```bash
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql
```

### Data Quality Monitoring

#### 3. `confidence_score_monitoring.sql`
**Purpose:** Track parsing quality over time  
**Schedule:** Run weekly  
**Alerts:** Confidence drops below 0.9

**What it checks:**
- Daily confidence trends
- Return date parsing success
- 7-day rolling averages
- Quality degradation detection

**Usage:**
```bash
bq query --use_legacy_sql=false < confidence_score_monitoring.sql
```

#### 4. `data_quality_check.sql`
**Purpose:** Comprehensive quality validation  
**Schedule:** Run weekly or monthly  
**Alerts:** Review section summaries

**What it checks:**
- Overall statistics (last 30 days)
- Team coverage (all 30 teams represented?)
- Injury status distribution
- Reason category breakdown
- Data quality flags

**Usage:**
```bash
bq query --use_legacy_sql=false < data_quality_check.sql
```

### Real-Time Monitoring

#### 5. `realtime_scraper_check.sql`
**Purpose:** Check if today's scraper has run  
**Schedule:** Run anytime during the day  
**Alerts:** No data after 10 AM during season

**What it checks:**
- Has today's scraper run?
- How recent is the data?
- Comparison with yesterday
- Time-based recommendations

**Usage:**
```bash
bq query --use_legacy_sql=false < realtime_scraper_check.sql
```

## Alert Thresholds

### 🔴 CRITICAL - Immediate Action Required
- Season active but NO injury data
- Injury count < 10 during season
- Confidence score < 0.6

### 🟡 ERROR - Investigate Soon
- Confidence score < 0.8
- Team coverage < 10 teams
- Data > 6 hours old during season

### ⚠️  WARNING - Monitor
- Confidence below 7-day average
- Low return date parsing (< 80%)
- More flags than usual

### ✅ COMPLETE - All Good
- 10+ injuries during season
- 10+ teams represented
- Confidence ≥ 0.9
- Data < 2 hours old

## Typical Daily Workflow

**Morning Routine (9 AM):**
```bash
# 1. Check yesterday's scrape
bq query --use_legacy_sql=false < daily_check_yesterday.sql

# 2. If issues found, check real-time status
bq query --use_legacy_sql=false < realtime_scraper_check.sql
```

**Weekly Review (Monday):**
```bash
# 3. Check 7-day trends
bq query --use_legacy_sql=false < weekly_check_last_7_days.sql

# 4. Review confidence scores
bq query --use_legacy_sql=false < confidence_score_monitoring.sql

# 5. Comprehensive quality check
bq query --use_legacy_sql=false < data_quality_check.sql
```

## Troubleshooting

### No Data Today
1. Check if season is active (Oct-Jun)
2. Verify scraper is scheduled
3. Check GCS for raw files
4. Review scraper logs

### Low Injury Count
- May be legitimate (healthy league)
- Check if all teams represented
- Compare with NBA.com injury report

### Low Confidence Scores
- API format may have changed
- Check data_quality_flags field
- Review parser logic

### Missing Teams
- Some teams may have zero injuries (normal)
- Over 30 days, expect 29-30 teams

## Data Source Information

**Table:** `nba-props-platform.nba_raw.bdl_injuries`  
**Partition:** `scrape_date` (REQUIRED in all queries)  
**Processor:** BdlInjuriesProcessor  
**Update Frequency:** Daily during season (8 AM PT)  
**Data Type:** Current state snapshot (not historical)

## Season Schedule

**Active Season:** October - June  
**Off-Season:** July - September  
**Expected Data:** Only during active season  
**Alert Suppression:** Auto-suppresses off-season alerts

## Related Tables

- `nba_raw.nbac_injury_report` - NBA.com official injuries (for cross-validation)
- `nba_raw.bdl_active_players_current` - Current player rosters
- `nba_raw.odds_api_player_points_props` - Props risk assessment

## Notes

- **Sparse data is NORMAL** - Not every day has injuries
- **Off-season expects zero data** - Don't alert July-September
- **Small dataset** - This is a lightweight current-state table
- **No historical backfill** - BDL only provides current injuries
- **Start validation when season begins** - Early October 2025

---

**Last Updated:** October 13, 2025  
**Status:** Ready for NBA Season Start  
**Pattern:** Time-Series (Daily Snapshots)
