# validate-schedule CLI Tool Guide

**Quick Reference for NBA.com Schedule Data Validation**

---

## 🚀 Installation

```bash
cd ~/code/nba-stats-scraper

# Make the script executable
chmod +x scripts/validate-schedule

# Optional: Create alias for easier access
echo "alias validate-schedule='~/code/nba-stats-scraper/scripts/validate-schedule'" >> ~/.bashrc
source ~/.bashrc
```

**Verify installation:**
```bash
validate-schedule help
```

---

## 📖 Quick Start

### See What's Available
```bash
validate-schedule help      # Show full help
validate-schedule list      # List all queries
```

### Run Your First Check
```bash
# Check yesterday's games (daily morning routine)
validate-schedule yesterday

# Full season completeness check
validate-schedule completeness
```

---

## 🎯 Common Workflows

### Morning Routine (During Season)
```bash
# Check if yesterday's games are in schedule
validate-schedule yesterday

# Check how far ahead we have schedule data
validate-schedule horizon
```

**Expected Output:**
```
✅ Complete          - Yesterday's games present
✅ GOOD: 3+ weeks    - Healthy schedule horizon
🟡 WARNING           - Less than 2 weeks ahead
❌ CRITICAL          - No future games or yesterday missing
```

---

### After Schedule Updates
```bash
# 1. Full completeness check
validate-schedule completeness

# 2. Check team balance
validate-schedule balance

# 3. Validate enhanced fields
validate-schedule fields
```

---

### Weekly Health Check
```bash
# Run on Monday mornings
validate-schedule completeness
validate-schedule balance
validate-schedule fields
```

---

### Investigating Anomalies
```bash
# If completeness shows missing games
validate-schedule missing

# If team balance shows issues
validate-schedule gaps

# During/after playoffs
validate-schedule playoffs
```

---

## 📋 All Commands

### Historical Validation

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `completeness` | `complete`, `full`, `season` | Full season check (all seasons) | After updates, weekly |
| `missing` | `regular` | Find regular season gaps | When completeness shows issues |
| `playoffs` | `playoff` | Verify playoff structure | After playoffs, during updates |
| `balance` | `teams` | Check team game count balance | Weekly, investigating anomalies |
| `gaps` | `schedule-gaps` | Detect suspicious gaps (7+ days) | When investigating missing data |

### Daily Monitoring

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `yesterday` | `daily`, `freshness` | Check yesterday's games | Every morning 9 AM |
| `horizon` | `future`, `ahead` | How far ahead we have data | Daily, after schedule updates |

### Data Quality

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `fields` | `enhanced`, `quality` | Validate 18 analytical fields | Weekly, after processor updates |

---

## 💾 Saving Results

### Save to CSV
```bash
validate-schedule completeness --csv
validate-schedule yesterday --csv
```

**Output:** `validation_season_completeness_check_20251012_143022.csv`

### Save to BigQuery Table
```bash
validate-schedule completeness --table
```

**Output:** `nba-props-platform:validation.schedule_season_completeness_check_20251012`

---

## 📊 Understanding Output

### Season Completeness Check

```
row_type    | season  | team | regular_season | playoffs | total | notes
DIAGNOSTICS | 6706    | ...  | 0              | 0        | 0     | All should be 0
TEAM        | 2024-25 | LAL  | 82             | 16       | 98    |
TEAM        | 2024-25 | LAC  | 79             | 0        | 79    | ⚠️ Missing regular season games
```

**What to Look For:**
- ✅ **DIAGNOSTICS row**: All values should be 0 (no data quality issues)
- ✅ **regular_season**: Should be ~82 for all teams (80-84 acceptable)
- ✅ **playoffs**: Varies by team (4-28 games depending on playoff run)
- ⚠️ **Notes column**: Shows teams with missing games

---

### Yesterday Check

```
Date       | Games Found | Status
2025-10-11 | 12          | ✅ Complete
```

**Status Values:**
- `✅ Complete` - All good, no action needed
- `✅ No games scheduled (expected)` - Off day or All-Star break
- `❌ CRITICAL: Expected games but found none` - **Data missing - investigate now**
- `🟡 WARNING: Games found but missing enhanced fields` - **Data quality issue**

---

### Team Balance Check

```
team | total_games | games_diff | status
LAL  | 82          | +0.2       | ✅ Normal
LAC  | 76          | -6.0       | 🔴 CRITICAL: >5 games from average
```

**What to Look For:**
- All teams should be within ~2-3 games of league average
- Large deviations (>5 games) indicate missing data
- Home/away split should be roughly equal (~41/41)

---

### Schedule Horizon

```
Furthest Game | 2025-11-15 | 34 days ahead | ✅ GOOD: 3+ weeks ahead
```

**Status Values:**
- `✅ GOOD: 3+ weeks ahead` - Healthy
- `✅ OK: 2-3 weeks ahead` - Acceptable
- `🟡 WARNING: Less than 2 weeks ahead` - **Schedule updates needed**
- `🔴 CRITICAL: Less than 1 week ahead` - **Urgent update required**

---

### Enhanced Field Quality

```
field               | null_count | percentage | status
is_primetime        | 0          | 0.0%       | ✅
has_national_tv     | 0          | 0.0%       | ✅
primary_network     | 145        | 2.2%       | 🟡
```

**What to Look For:**
- Critical fields (is_primetime, has_national_tv) should have 0% NULL
- Network fields may have ~10-20% NULL (local games without network data)
- Special events (Christmas, MLK Day) should have reasonable counts

---

### Missing Games Analysis

```
=== TEAM ANALYSIS ===
Team | Total Games | Games Diff | Status
LAC  | 76          | -6.0       | 🔴 CRITICAL: >5 games from average

=== DAILY GAPS ===
2025-11-15 | Friday  | 2 games | 5 days since last | 🟡 Longer gap
```

**Action Steps:**
1. Review daily gaps to identify missing date ranges
2. Check if gaps are expected (All-Star break, unusual scheduling)
3. If unexpected, check schedule scraper/processor logs

---

### Playoff Verification

```
=== PLAYOFF STRUCTURE ===
First Round     | Teams: 16 (expected 16) | Games: 80 | Per team: 4-7 games | ✅ Structure OK

=== TEAM PLAYOFF RUNS ===
LAL | Lakers        | First Round → Conference Semis → Conference Finals → NBA Finals | 26 games | 🏆 Finals participant
BOS | Celtics       | First Round → Conference Semis → Conference Finals | 19 games | 🏀 Conference Finals
LAC | Clippers      | First Round | 7 games | 📉 First Round exit
```

**What to Look For:**
- Each round should have expected team count (16 → 8 → 4 → 2)
- Series should have 4-7 games
- Team playoff runs should make sense (can't skip rounds)

---

### Team Schedule Gaps

```
=== TEAMS WITH SUSPICIOUS GAPS ===
LAC | Clippers | 76 | 3 | 8 days | 🟠 WARNING: Multiple 7+ day gaps

=== SPECIFIC GAPS (7+ DAYS) ===
LAC - Clippers | 2024-11-15 → 2024-11-23 | 8 days | LAC @ DEN | 🟠 Suspicious gap
```

**What to Look For:**
- 7+ day gaps outside All-Star break are unusual
- Multiple 7+ day gaps indicate missing data
- Check if gaps coincide with known breaks

---

## 🔧 Troubleshooting

### "Command not found: validate-schedule"

**Problem:** Alias not set up or script not executable

**Solution:**
```bash
# Make executable
chmod +x ~/code/nba-stats-scraper/scripts/validate-schedule

# Use full path
~/code/nba-stats-scraper/scripts/validate-schedule help

# Or set up alias
echo "alias validate-schedule='~/code/nba-stats-scraper/scripts/validate-schedule'" >> ~/.bashrc
source ~/.bashrc
```

---

### "Query file not found"

**Problem:** Running from wrong directory or queries not created

**Solution:**
```bash
# Verify queries exist
ls -la ~/code/nba-stats-scraper/validation/queries/raw/nbac_schedule/

# Should see:
# season_completeness_check.sql
# find_missing_regular_season_games.sql
# verify_playoff_completeness.sql
# team_balance_check.sql
# team_schedule_gaps.sql
# daily_freshness_check.sql
# schedule_horizon_check.sql
# enhanced_field_quality.sql

# Run list command to verify
validate-schedule list
```

---

### "Cannot query over table without a filter on partition key"

**Problem:** Query missing required partition filter on `game_date`

**Solution:** This shouldn't happen with provided queries (all include partition filters), but if you modify queries:

```sql
-- Always include:
WHERE game_date >= 'YYYY-MM-DD'  -- Required!
```

---

## 📅 Recommended Schedule

### Daily (Automated via Cron)

```bash
# Add to crontab: crontab -e
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-schedule yesterday
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-schedule horizon
```

### Weekly (Manual or Automated)

```bash
# Monday mornings
validate-schedule completeness
validate-schedule balance
validate-schedule fields
```

### Monthly (Manual)

```bash
# First Monday of month - full health check
validate-schedule completeness
validate-schedule missing
validate-schedule balance
validate-schedule gaps
validate-schedule fields
```

### After Schedule Updates (Manual)

```bash
# Run full validation suite
validate-schedule completeness
validate-schedule balance
validate-schedule horizon
validate-schedule fields
```

### During Playoffs (Manual)

```bash
# Playoff-specific checks
validate-schedule playoffs
validate-schedule horizon
```

---

## 🎯 Real-World Examples

### Example 1: Morning Check Shows Missing Games

```bash
$ validate-schedule yesterday

Date       | Games Found | Status
2025-10-11 | 0           | ❌ CRITICAL: Expected games but found none
```

**Actions:**
1. Check schedule scraper logs
2. Verify NBA.com API is accessible
3. Re-run schedule processor for that date
4. Verify again

---

### Example 2: Season Completeness Shows Gaps

```bash
$ validate-schedule completeness

TEAM | 2024-25 | LAC | 76 | 0 | 76 | ⚠️ Missing regular season games

# Investigate:
$ validate-schedule missing

=== TEAM ANALYSIS ===
LAC | 76 games | -6.0 from average | 🔴 CRITICAL

=== DAILY GAPS ===
2024-11-15 | 5 days since last game | 🟡 Longer gap
2024-12-01 | 7 days since last game | 🟠 Suspicious gap
```

**Actions:**
1. Note specific date ranges with gaps
2. Check if gaps are expected (schedule not released, postponements)
3. If unexpected, re-run schedule scraper for those dates
4. Verify with `validate-schedule completeness` again

---

### Example 3: Enhanced Fields Not Populated

```bash
$ validate-schedule fields

field           | null_count | percentage | status
is_primetime    | 145        | 2.2%       | 🔴
primary_network | 3200       | 48%        | 🔴
```

**Actions:**
1. Check schedule processor logs for errors
2. Verify enhanced field extraction logic
3. Re-run processor to populate fields
4. Verify with `validate-schedule fields` again

---

### Example 4: Playoff Structure Validation

```bash
$ validate-schedule playoffs

=== PLAYOFF STRUCTURE ===
First Round | Teams: 14 (expected 16) | ⚠️ Incomplete

=== TEAM PLAYOFF RUNS ===
# Only 14 teams listed, 2 missing
```

**Actions:**
1. Identify which teams are missing
2. Check schedule scraper for playoff games
3. Verify playoff_round field populated correctly
4. Re-run validation

---

## 💡 Pro Tips

### 1. Chain Commands for Complete Report
```bash
# Generate complete validation report
{
  echo "=== Season Completeness ==="
  validate-schedule completeness
  echo ""
  echo "=== Team Balance ==="
  validate-schedule balance
  echo ""
  echo "=== Enhanced Fields ==="
  validate-schedule fields
  echo ""
  echo "=== Schedule Horizon ==="
  validate-schedule horizon
} > schedule_validation_report_$(date +%Y%m%d).txt
```

### 2. Quick Health Check
```bash
# One-liner to check everything is healthy
validate-schedule yesterday && validate-schedule horizon && echo "✅ All systems operational"
```

### 3. Alert on Critical Issues
```bash
# Add to cron job
validate-schedule yesterday | grep -q "CRITICAL" && echo "❌ Schedule validation failed!" | mail -s "Schedule Alert" you@example.com
```

### 4. Compare Schedule Horizon Over Time
```bash
# Save daily horizon checks
validate-schedule horizon --table  # Creates dated table
```

### 5. Monitor Enhanced Field Population
```bash
# Track field quality over time
validate-schedule fields --csv >> field_quality_history.csv
```

---

## 🔗 Related Documentation

- **Query Files:** `validation/queries/raw/nbac_schedule/`
- **Query README:** `validation/queries/raw/nbac_schedule/README.md`
- **Validator Config:** `validation/configs/raw/nbac_schedule.yaml` (to be created)
- **Validator Code:** `validation/validators/raw/nbac_schedule_validator.py` (to be created)
- **Schedule Processor:** `processors/nba_com/nbac_schedule_processor.py`

---

## 📞 Quick Reference Card

```bash
# Daily
validate-schedule yesterday          # Check yesterday
validate-schedule horizon            # Future schedule

# Weekly  
validate-schedule completeness       # Full check
validate-schedule balance            # Team balance
validate-schedule fields             # Data quality

# Investigating Issues
validate-schedule missing            # Find gaps
validate-schedule gaps               # Suspicious gaps
validate-schedule playoffs           # Verify playoffs

# Save Results
validate-schedule [command] --csv    # To CSV
validate-schedule [command] --table  # To BigQuery

# Help
validate-schedule help               # Full help
validate-schedule list               # List queries
```

---

## 🚦 Status Indicators Cheat Sheet

| Symbol | Meaning | Action Required |
|--------|---------|----------------|
| ✅ | All good | None |
| ⚪ | Expected gap (off day) | None |
| 🟡 | Warning - minor issue | Monitor |
| 🟠 | Suspicious - investigate | Investigate soon |
| 🔴 | Critical - data missing | **Fix immediately** |
| ❌ | Error - system failure | **Fix now** |

---

## 📊 Expected Values Reference

### Regular Season
- Games per team: ~82 (80-84 acceptable)
- Home/away split: ~41/41
- Games per day: 10-15 during peak season
- Schedule horizon: 2-4 weeks ahead
- Primetime games: 15-20% of total

### Playoffs
- First round: 16 teams
- Conference semis: 8 teams
- Conference finals: 4 teams
- NBA Finals: 2 teams
- Games per series: 4-7

### Enhanced Fields
- is_primetime: 0% NULL
- has_national_tv: 0% NULL
- primary_network: <20% NULL acceptable
- is_christmas: 5-10 games per season
- is_mlk_day: 8-12 games per season

---

**Last Updated:** October 12, 2025  
**Version:** 1.0  
**Table:** `nba-props-platform.nba_raw.nbac_schedule`
