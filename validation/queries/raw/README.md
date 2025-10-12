# NBA.com Schedule Validation Queries

This directory contains SQL validation queries for the `nba_raw.nbac_schedule` table.

## 📋 Query Overview

| Query | Purpose | Frequency | Output |
|-------|---------|-----------|--------|
| `season_completeness_check.sql` | Overall season validation | Weekly | Teams × seasons with game counts |
| `find_missing_regular_season_games.sql` | Detect regular season gaps | As-needed | Team gaps + daily gaps analysis |
| `verify_playoff_completeness.sql` | Validate playoff structure | Post-playoffs | Playoff rounds + team runs |
| `team_balance_check.sql` | Ensure fair team coverage | Weekly | Teams with unusual game counts |
| `schedule_horizon_check.sql` | Check future schedule data | Daily | How far ahead we have data |
| `enhanced_field_quality.sql` | Validate 18 analytical fields | Weekly | NULL counts + special events |
| `daily_freshness_check.sql` | Verify yesterday's games | Daily | Yesterday + today + tomorrow |

---

## 🎯 Validation Philosophy

These queries follow the **"expected patterns"** approach rather than **"absolute truth"**:

- ✅ **Historical comparison**: Is 2024-25 on pace with 2023-24?
- ✅ **Anomaly detection**: Does one team have way fewer games?
- ✅ **Data quality**: Are enhanced fields populated?
- ✅ **Freshness**: How far ahead is schedule data?
- ❌ **Not checking**: Exact missing game IDs (we don't know the absolute truth)

---

## 🔧 Usage Instructions

### Daily Monitoring (Automated)

Run these queries every morning:

```bash
# 1. Check yesterday's games
bq query --use_legacy_sql=false < daily_freshness_check.sql

# 2. Check schedule horizon
bq query --use_legacy_sql=false < schedule_horizon_check.sql
```

**Alert if:**
- `daily_freshness_check` status = "❌ CRITICAL"
- `schedule_horizon_check` shows <7 days ahead

---

### Weekly Health Check

Run these queries once per week:

```bash
# 1. Season completeness overview
bq query --use_legacy_sql=false < season_completeness_check.sql

# 2. Team balance (anomaly detection)
bq query --use_legacy_sql=false < team_balance_check.sql

# 3. Enhanced field quality
bq query --use_legacy_sql=false < enhanced_field_quality.sql
```

**Review for:**
- Teams with <80 games (regular season)
- Teams >3 games from league average
- Enhanced fields with >10% NULL values

---

### Investigation Queries (As-Needed)

Use when anomalies detected:

```bash
# When season_completeness shows missing games:
bq query --use_legacy_sql=false < find_missing_regular_season_games.sql

# During/after playoffs:
bq query --use_legacy_sql=false < verify_playoff_completeness.sql

# When team balance shows issues:
bq query --use_legacy_sql=false < team_schedule_gaps.sql
```

---

## ⚙️ Customizing Date Ranges

Most queries have date ranges that need updating:

### Season Completeness Check
```sql
-- Line 11-15: Update season date ranges
WHEN game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
```

### Find Missing Regular Season Games
```sql
-- Line 26: Update for season you're checking
WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- Regular season only
```

### Verify Playoff Completeness
```sql
-- Line 23: Update for playoff period
WHERE game_date BETWEEN '2024-04-19' AND '2024-06-20'  -- Playoff period
```

### Team Schedule Gaps
```sql
-- Line 24: Update for regular season
WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- Regular season only
```

---

## 📊 Understanding Results

### ✅ Good Results

**Season Completeness:**
```
TEAM | 2024-25 | LAL | 82 | 16 | 98 |  | ✅
```
- 82 regular season games ✅
- 16 playoff games (Finals run) ✅

**Team Balance:**
```
LAL | Lakers | 41 | 41 | 82 | +0.2 | ✅ Normal
```
- Even home/away split ✅
- Within 1 game of average ✅

**Daily Freshness:**
```
Games Found | 12 | 12 regular + 0 playoff | ✅ Complete
```

---

### 🔴 Problem Results

**Season Completeness:**
```
TEAM | 2024-25 | LAC | 76 | 0 | 76 | ⚠️ Missing regular season games
```
- Only 76/82 games = 6 games missing ❌

**Team Balance:**
```
LAC | Clippers | 38 | 38 | 76 | -6.0 | 🔴 CRITICAL: >5 games from average
```
- 6 games below league average ❌

**Daily Freshness:**
```
Games Found | 0 | 0 regular + 0 playoff | ❌ CRITICAL: Expected games but found none
```
- Expected games yesterday but found none ❌

**Team Schedule Gaps:**
```
LAC | 2024-11-15 → 2024-11-23 | 8 days | LAC @ DEN | 🟠 Suspicious gap
```
- 8-day gap outside All-Star break ❌

---

## 🚨 Critical Checks

### Partition Filter Requirement

⚠️ **CRITICAL**: The `nbac_schedule` table requires partition filters on all queries!

Every query must include:
```sql
WHERE game_date >= 'YYYY-MM-DD'  -- Required!
```

Without this, queries will fail with:
```
Cannot query over table without a filter on partition key 'game_date'
```

---

## 📈 Expected Values

### Regular Season

- **Games per team**: ~82 (can be 80-84 due to makeup games)
- **Home/away split**: ~41/41
- **Games per day**: 10-15 during peak season
- **Days between games**: 1-3 days typical
- **Primetime games**: 15-20% of total

### Playoffs

- **First round**: 16 teams, 4-7 games each
- **Conference semis**: 8 teams, 4-7 games each
- **Conference finals**: 4 teams, 4-7 games each
- **NBA Finals**: 2 teams, 4-7 games
- **Total per team**: 4-28 games depending on run

### Enhanced Fields

- **is_primetime**: Should have 0% NULL
- **has_national_tv**: Should have 0% NULL
- **primary_network**: May have ~10-20% NULL (local games)
- **playoff_round**: Only NULL for non-playoff games
- **is_christmas**: 5-10 games per season
- **is_mlk_day**: 8-12 games per season

---

## 🔍 Investigation Workflow

When validation fails:

1. **Run `daily_freshness_check.sql`**
   - Confirms if yesterday's data missing

2. **Run `season_completeness_check.sql`**
   - Shows which teams affected
   - Regular season vs playoff breakdown

3. **Run team-specific investigation:**
   - `find_missing_regular_season_games.sql` - Daily gaps
   - `team_schedule_gaps.sql` - Specific missing dates
   - `team_balance_check.sql` - Home/away balance

4. **Check data quality:**
   - `enhanced_field_quality.sql` - NULL counts
   - `schedule_horizon_check.sql` - Future data

---

## 💡 Tips

### Using in CLI Validator

These queries are designed to be called by the Python validator:

```python
from validation.validators.raw.nbac_schedule_validator import NbacScheduleValidator

validator = NbacScheduleValidator()
report = validator.validate(
    start_date='2024-10-22',
    end_date='2025-04-13'
)
```

### Manual BigQuery Testing

```bash
# Copy query to clipboard, then:
bq query --use_legacy_sql=false < season_completeness_check.sql > results.txt
```

### Scheduling in Cloud Scheduler

```bash
# Daily freshness check at 9 AM
gcloud scheduler jobs create http schedule-daily-check \
  --schedule="0 9 * * *" \
  --uri="https://validator.example.com/check/nbac_schedule/daily"
```

---

## 📝 Maintenance

### Updating for New Seasons

1. Update season date ranges in `season_completeness_check.sql`
2. Update All-Star break dates in `team_schedule_gaps.sql`
3. Update playoff dates in `verify_playoff_completeness.sql`

### Adding New Enhanced Fields

If new analytical fields added to table:

1. Update `enhanced_field_quality.sql` NULL checks
2. Update expected values documentation
3. Add to validation config YAML

---

## 🎓 Learn More

- **Validation Framework**: See `validation/README.md`
- **Base Validator**: See `validation/base_validator.py`
- **Schedule Processor**: See `processors/nba_com/nbac_schedule_processor.py`
- **Enhanced Fields**: See processor reference doc (18 analytical fields)

---

**Last Updated**: October 12, 2025  
**Queries Version**: 1.0  
**Table**: `nba-props-platform.nba_raw.nbac_schedule`
