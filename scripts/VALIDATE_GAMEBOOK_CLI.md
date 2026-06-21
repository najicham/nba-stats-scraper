# validate-gamebook CLI Tool Guide

**Quick Reference for NBA.com Gamebook Player Stats Validation**

---

## 🚀 Installation

```bash
cd ~/code/nba-stats-scraper

# Make the script executable
chmod +x scripts/validate-gamebook

# Optional: Create alias for easier access
echo "alias validate-gamebook='~/code/nba-stats-scraper/scripts/validate-gamebook'" >> ~/.bashrc
source ~/.bashrc
```

**Verify installation:**
```bash
validate-gamebook help
```

---

## 📖 Quick Start

### See What's Available
```bash
validate-gamebook help      # Show full help
validate-gamebook list      # List all queries
```

### Run Your First Check
```bash
# Check yesterday's games (daily morning routine)
validate-gamebook yesterday

# Full season completeness check
validate-gamebook completeness

# Check name resolution quality (98.92% target)
validate-gamebook resolution
```

---

## 🎯 Common Workflows

### Morning Routine (During Season)
```bash
# Check if yesterday's games were processed with full stats
validate-gamebook yesterday

# If issues found, check last week's trend
validate-gamebook week
```

**Expected Output:**
```
✅ Complete            - All games processed, resolution rate ≥98%
⚪ No games            - Off day (All-Star break, etc.)
❌ CRITICAL            - No gamebook data (scraper/processor failure)
⚠️ WARNING             - Games missing or incomplete
⚠️ Low resolution      - Name resolution below 98% target
```

---

### After Running Backfills
```bash
# 1. Full completeness check
validate-gamebook completeness

# 2. Find any remaining gaps
validate-gamebook missing

# 3. Check name resolution quality
validate-gamebook resolution

# 4. Validate player status logic
validate-gamebook status
```

---

### Weekly Health Check
```bash
# Run on Monday mornings
validate-gamebook week

# If patterns emerge, investigate specific dates
validate-gamebook missing
```

---

### Name Resolution Monitoring
```bash
# Check resolution system health (target: 98.92%)
validate-gamebook resolution

# If below target, investigate problem cases
validate-gamebook resolution --csv
```

---

### Game Day Monitoring
```bash
# Check scraper/processor is running (run hourly after games)
validate-gamebook today
```

---

## 📋 All Commands

### Historical Validation

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `completeness` | `complete`, `full` | Full season check (4 seasons) | After backfills, quarterly |
| `missing` | `gaps` | Find specific missing games | When completeness shows gaps |
| `resolution` | `names`, `resolve` | Name resolution quality (98.92% target) | Weekly, after backfills |
| `status` | `players` | Player status validation | Monthly, investigating quality |

### Daily Monitoring

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `yesterday` | `daily` | Check yesterday's games | Every morning 9 AM |
| `week` | `weekly`, `7days` | Last 7 days coverage | Weekly (Monday) |
| `today` | `now`, `realtime` | Real-time processor health | Hourly after games end |

---

## 💾 Saving Results

### Save to CSV
```bash
validate-gamebook completeness --csv
validate-gamebook resolution --csv
```

**Output:** `validation_season_completeness_check_20251012_143022.csv`

### Save to BigQuery Table
```bash
validate-gamebook completeness --table
```

**Output:** `nba-props-platform:validation.gamebook_season_completeness_check_20251012`

---

## 📊 Understanding Output

### Season Completeness Check

```
row_type    | season  | team              | games | total_players | active_players | inactive_players | resolved_inactive | resolution_rate | notes
DIAGNOSTICS | 5400    | DIAGNOSTICS       | 0     | 0             | 0              | 26412            | 26180            | 99.1%           | Check: all should be 0...
TEAM        | 2021-22 | Boston Celtics    | 82    | 2756          | 1640           | 820              | 810              | 98.8%           |
TEAM        | 2021-22 | Lakers            | 81    | 2720          | 1620           | 812              | 800              | 98.5%           | ⚠️ Missing games
```

**What to Look For:**
- ✅ **DIAGNOSTICS row**: All diagnostic counts should be 0
- ✅ **Games**: Should be 82 for regular season teams
- ✅ **Total players**: Should be ~2,750 per season (82 games × ~33.5 players)
- ✅ **Resolution rate**: Should be ≥98.5% (target: 98.92%)
- ⚠️ **Notes column**: Shows teams with issues

---

### Name Resolution Quality

```
report_type         | season  | total_inactive | resolved | not_found | multiple_matches | resolution_rate | status
SEASON RESOLUTION   | 2021-22 | 4410          | 4362     | 48        | 0                | 98.92%         | ✅ Excellent
SEASON RESOLUTION   | 2022-23 | 10806         | 10699    | 107       | 0                | 99.01%         | ✅ Excellent
RESOLUTION METHOD   | auto_exact             | 5243     | 99.1%    | 95.3%    |                  |                |
PROBLEM CASES       | 232                    | See detailed list below |          |                  |                |
```

**What to Look For:**
- ✅ **Resolution rate ≥98.5%** = Excellent (target: 98.92%)
- ✅ **Resolution rate ≥98.0%** = Acceptable
- 🔴 **Resolution rate <98.0%** = Below target (investigate)
- 📋 **Problem cases**: Review detailed list for manual fixes

**Status Values:**
- `✅ Excellent` - 98.9%+ resolution rate
- `✅ Good` - 98.5-98.9% resolution rate
- `⚠️ Acceptable` - 98.0-98.5% resolution rate
- `🔴 Below Target` - <98.0% resolution rate

---

### Player Status Validation

```
report_type     | player_status | total  | active_no_points | active_no_minutes | inactive_has_points | dnp_has_points | status
STATUS SUMMARY  | active        | 65200  | 0                | 0                 | 0                   | 0              | ✅ Clean
STATUS SUMMARY  | inactive      | 26412  | 0                | 0                 | 0                   | 0              | ✅ Clean
STATUS SUMMARY  | dnp           | 26580  | 0                | 0                 | 0                   | 2              | ⚠️ Issues detected
```

**Data Quality Rules:**
- ✅ **Active players**: Must have minutes > 0, should have points
- ✅ **Inactive players**: Should have NO stats (all NULL)
- ✅ **DNP players**: Should have NO playing time
- ⚠️ **Issues detected**: Investigate data quality problems

---

### Yesterday Check

```
check_date | scheduled_games | gamebook_games | total_players | active_players | inactive_players | resolution_rate | status
2025-10-11 | 12              | 12             | 405           | 240            | 100              | 98.0%           | ✅ Complete
```

**Status Values:**
- `✅ Complete` - All games processed with good resolution rate
- `⚪ No games scheduled` - Off day
- `❌ CRITICAL: No gamebook data` - **Scraper failed - investigate now**
- `⚠️ WARNING: X games missing` - **Check which games missing**
- `⚠️ WARNING: X games incomplete` - **Games have <25 players**
- `⚠️ WARNING: Low resolution rate` - **Below 98% target**

---

### Missing Games

```
game_date  | home_team       | away_team        | matchup    | status              | player_count
2024-11-30 | Warriors        | Suns             | PHX @ GSW  | COMPLETELY MISSING  | 0
2024-04-02 | 76ers           | Hornets          | CHA @ PHI  | INCOMPLETE DATA     | 18
```

**Action for completely missing games:**
```bash
# Create dates file from output
cat > backfill_dates.txt << EOF
2024-11-30
2024-04-02
EOF

# Run scraper backfill for those specific dates
# (Your scraper command here)
```

**Action for incomplete games:**
- Investigate why game has <25 players
- May need to reprocess that specific game

---

### Weekly Check

```
game_date  | day_of_week | scheduled | gamebook | total_players | avg_players | inactive | resolved | resolution_rate | status
2025-10-11 | Friday      | 12        | 12       | 405          | 33.8        | 100      | 98       | 98.0%          | ✅ Complete
2025-10-10 | Thursday    | 11        | 11       | 370          | 33.6        | 92       | 90       | 97.8%          | ⚠️ Low resolution
2025-10-09 | Wednesday   | 0         | 0        | 0            | 0.0         | 0        | 0        | 0.0%           | ⚪ No games
```

**What to Look For:**
- ✅ **Avg players per game**: Should be 30-35
- ⚠️ **Low player count**: <28 players per game (data quality issue)
- ⚠️ **Low resolution**: <98% resolution rate
- ❌ **Missing all**: Scheduled games but no gamebook data

---

## 🔧 Troubleshooting

### "Command not found: validate-gamebook"

**Problem:** Alias not set up or script not executable

**Solution:**
```bash
# Make executable
chmod +x ~/code/nba-stats-scraper/scripts/validate-gamebook

# Use full path
~/code/nba-stats-scraper/scripts/validate-gamebook help

# Or set up alias
echo "alias validate-gamebook='~/code/nba-stats-scraper/scripts/validate-gamebook'" >> ~/.bashrc
source ~/.bashrc
```

---

### "Query file not found"

**Problem:** Running from wrong directory or queries not created

**Solution:**
```bash
# Verify queries exist
ls -la ~/code/nba-stats-scraper/validation/queries/raw/nbac_gamebook/

# Should see:
# season_completeness_check.sql
# find_missing_regular_season_games.sql
# name_resolution_quality.sql
# player_status_validation.sql
# daily_check_yesterday.sql
# weekly_check_last_7_days.sql
# realtime_scraper_check.sql

# Run list command to verify
validate-gamebook list
```

---

### Resolution Rate Below Target

**Problem:** Name resolution rate drops below 98.5%

**Investigation Steps:**
```bash
# 1. Get detailed problem cases
validate-gamebook resolution --csv

# 2. Check specific games
# Review CSV for patterns:
# - Specific teams having issues?
# - Specific dates with problems?
# - New players not in Basketball Reference cache?

# 3. Check processor logs
# Look for name resolution warnings/errors
```

**Common Causes:**
- G-League call-ups (expected - not in BR roster)
- Trade-pending players (expected - between teams)
- Two-way contract players (expected - may not be in cache)
- Typos in source data (rare - needs manual fix)

---

### Active Players with No Stats

**Problem:** Player marked "active" but has no points/minutes

**Investigation:**
```bash
# Run player status validation
validate-gamebook status --csv

# Review detailed quality issues section
# Check if player actually played (ESPN/BDL cross-check)
```

---

## 📅 Recommended Schedule

### Daily (Automated via Cron)

```bash
# Add to crontab: crontab -e
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-gamebook yesterday
```

### Weekly (Manual or Automated)

```bash
# Monday mornings - full health check
validate-gamebook week
validate-gamebook resolution
```

### Monthly (Manual)

```bash
# First Monday of month - comprehensive validation
validate-gamebook completeness
validate-gamebook status
validate-gamebook resolution --table  # Save snapshot
```

### After Backfills (Manual)

```bash
# Run all four historical checks
validate-gamebook completeness
validate-gamebook missing
validate-gamebook resolution
validate-gamebook status
```

---

## 🎯 Real-World Examples

### Example 1: Morning Check Shows Issues

```bash
$ validate-gamebook yesterday

check_date | scheduled_games | gamebook_games | resolution_rate | status
2025-10-11 | 12              | 10             | 97.8%           | ⚠️ WARNING: 2 games missing

$ validate-gamebook missing
# Identify which games are missing
# Re-run scraper/processor for those games
```

---

### Example 2: Resolution Rate Drop

```bash
$ validate-gamebook resolution

report_type         | season  | total_inactive | resolved | resolution_rate | status
SEASON RESOLUTION   | 2024-25 | 1384          | 1352     | 97.7%          | ⚠️ Acceptable

# Investigate problem cases
$ validate-gamebook resolution --csv

# Review CSV:
# - Check for G-League players (expected failures)
# - Check for recent trades (expected failures)
# - Look for genuine resolution issues
```

---

### Example 3: Weekly Trend Analysis

```bash
$ validate-gamebook week

game_date  | scheduled | gamebook | avg_players | resolution_rate | status
2025-10-11 | 12        | 12       | 33.8        | 98.0%          | ✅ Complete
2025-10-10 | 11        | 11       | 33.6        | 97.8%          | ⚠️ Low resolution
2025-10-09 | 0         | 0        | 0.0         | 0.0%           | ⚪ No games
2025-10-08 | 10        | 10       | 28.2        | 98.5%          | ⚠️ Low player count
```

**Pattern Found:** October 8 had low average player count - investigate that specific date

---

### Example 4: Data Quality Issues

```bash
$ validate-gamebook status

STATUS SUMMARY  | active  | 1240  | 5   | 0   | 0   | 0  | ⚠️ Issues detected

# 5 active players with no points but >5 minutes playing time
# Need to cross-check with ESPN/BDL boxscores
```

---

## 💡 Pro Tips

### 1. Chain Commands for Comprehensive Report
```bash
# Generate complete validation report
{
  echo "=== Season Completeness ==="
  validate-gamebook completeness
  echo ""
  echo "=== Name Resolution Quality ==="
  validate-gamebook resolution
  echo ""
  echo "=== Player Status Validation ==="
  validate-gamebook status
  echo ""
  echo "=== Last Week ==="
  validate-gamebook week
} > validation_report_$(date +%Y%m%d).txt
```

### 2. Monitor Resolution Rate Trends
```bash
# Save monthly snapshots to track resolution quality over time
validate-gamebook resolution --table
```

### 3. Quick Health Check
```bash
# One-liner to verify system health
validate-gamebook yesterday && echo "✅ All systems operational"
```

### 4. Alert on Critical Issues
```bash
# Add to cron job
validate-gamebook yesterday | grep -q "❌" && echo "Critical issue!" | mail -s "Gamebook Alert" you@example.com
```

### 5. Find Games Needing Reprocessing
```bash
# Export missing/incomplete games for bulk reprocessing
validate-gamebook missing --csv
# Parse CSV to create reprocessing job list
```

---

## 📊 Key Metrics to Monitor

### Daily
- ✅ All scheduled games processed
- ✅ Average 30-35 players per game
- ✅ Resolution rate ≥98%

### Weekly
- ✅ Consistent player counts across days
- ✅ No pattern of missing games
- ✅ Resolution rate stable

### Monthly
- ✅ All teams have ~82 games (during regular season)
- ✅ Overall resolution rate ≥98.5%
- ✅ No systematic data quality issues

---

## 🔗 Related Documentation

- **Query Files:** `validation/queries/raw/nbac_gamebook/`
- **Validator Code:** `validation/validators/raw/nbac_gamebook_validator.py`
- **Config File:** `validation/configs/raw/nbac_gamebook.yaml`
- **Processor Reference:** (Your processor documentation)

---

## 📞 Quick Reference Card

```bash
# Daily
validate-gamebook yesterday          # Check yesterday

# Weekly
validate-gamebook week               # Last 7 days
validate-gamebook resolution         # Name resolution quality

# After Backfills
validate-gamebook completeness       # Full check
validate-gamebook missing            # Find gaps
validate-gamebook status             # Player status validation

# During Games
validate-gamebook today              # Processor health

# Save Results
validate-gamebook [command] --csv    # To CSV
validate-gamebook [command] --table  # To BigQuery

# Help
validate-gamebook help               # Full help
validate-gamebook list               # List queries
```

---

## 🎓 Understanding Name Resolution

The gamebook data includes **inactive players** (injury report) with only last names:
- **Input:** "James" (last name only)
- **Resolution System:** Looks up full name using injury database + Basketball Reference rosters
- **Output:** "LeBron James" (full name for cross-table joins)

**Target:** 98.92% resolution rate (industry-leading accuracy)

**Expected Failures:**
- G-League assignments (~0.3%)
- Trade-pending players (~0.2%)
- "Not With Team" status (~0.2%)
- Two-way contracts (~0.18%)

These are **legitimate exclusions** (cannot receive prop bets), so 98.92% is effectively 100% for business purposes.

---

**Last Updated:** October 12, 2025
**Version:** 1.0
**Target Resolution Rate:** 98.92%
