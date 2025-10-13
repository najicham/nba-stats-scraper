# validate-odds-props CLI Tool Guide

**Quick Reference for Odds API Player Props Data Validation**

---

## 🚀 Installation

```bash
cd ~/code/nba-stats-scraper

# Make the script executable
chmod +x scripts/validate-odds-props

# Optional: Create alias for easier access
echo "alias validate-odds-props='~/code/nba-stats-scraper/scripts/validate-odds-props'" >> ~/.bashrc
source ~/.bashrc
```

**Verify installation:**
```bash
validate-odds-props help
```

---

## 📖 Quick Start

### See What's Available
```bash
validate-odds-props help      # Show full help
validate-odds-props list      # List all queries
```

### Run Your First Check
```bash
# Full gap analysis (shows all 4 seasons)
validate-odds-props gaps

# Check yesterday's games (daily morning routine)
validate-odds-props yesterday
```

---

## 📊 Current Data Status

### Known Coverage (as of Oct 2025)

| Season  | Regular Season | Playoffs | Status |
|---------|---------------|----------|--------|
| 2021-22 | 0% (0 games) | 0% (0 games) | ❌ No Data |
| 2022-23 | 0% (0 games) | 34% (31 games) | ❌ Mostly Missing |
| 2023-24 | 70% (866 games) | 89% (78 games) | ✅ Good |
| 2024-25 | 74% (913 games) | 92% (82 games) | ✅ Good |

### Key Insights
- **2021-22 & 2022-23**: Historical scraper not active yet
- **2023-24**: First season with good coverage (started mid-season)
- **2024-25**: Current season with excellent coverage
- **Low coverage**: 336 games in 2023-24 have <6 players (acceptable)

---

## 🎯 Common Workflows

### Morning Routine (During Season)
```bash
# Check if yesterday's games have props
validate-odds-props yesterday

# If issues found, check last week's trend
validate-odds-props week
```

**Expected Output:**
```
✅ Complete              - All games have adequate props
⚪ No games scheduled    - Off day
❌ CRITICAL              - No props data (scraper failure)
🟡 WARNING               - Low player coverage (<6 players)
```

---

### After Running Backfills
```bash
# 1. Full gap analysis
validate-odds-props gaps

# 2. Find games with NO props
validate-odds-props missing

# 3. Find games with low coverage
validate-odds-props low-coverage

# 4. Verify playoffs
validate-odds-props playoffs
```

---

### Weekly Health Check
```bash
# Run on Monday mornings
validate-odds-props week

# If patterns emerge, dig deeper
validate-odds-props gaps
validate-odds-props missing
```

---

### Game Day Monitoring
```bash
# Check scraper is running (run hourly during games)
validate-odds-props today
```

---

## 📋 All Commands

### Historical Validation

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `gaps` | `gap-analysis`, `overview` | Complete 4-season analysis | First run, monthly review |
| `completeness` | `complete`, `teams` | Team-by-team stats | After backfills |
| `missing` | `no-props`, `critical` | Games with ZERO props | When gaps shows issues |
| `low-coverage` | `low`, `sparse` | Games with <6 players | Quality checks |
| `playoffs` | `playoff` | Verify playoff completeness | After playoffs |

### Daily Monitoring

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `yesterday` | `daily` | Check yesterday's games | Every morning 9 AM |
| `week` | `weekly`, `7days` | Last 7 days coverage | Weekly (Monday) |
| `today` | `now`, `realtime` | Real-time scraper health | Hourly during games |

---

## 💾 Saving Results

### Save to CSV
```bash
validate-odds-props gaps --csv
validate-odds-props missing --csv
```

**Output:** `validation_props_comprehensive_gap_analysis_20251012_143022.csv`

### Save to BigQuery Table
```bash
validate-odds-props gaps --table
```

**Output:** `nba-props-platform:validation.props_comprehensive_gap_analysis_20251012`

---

## 📊 Understanding Output

### Gap Analysis (Most Important!)

```
season  | game_type      | scheduled | with_props | missing | coverage_% | avg_players | status
2023-24 | Regular Season |    1234   |     866    |   368   |    70.2    |    10.9     | 🔴 Partial
2023-24 | Playoffs       |      88   |      78    |    10   |    88.6    |    14.0     | 🔴 Partial
2024-25 | Regular Season |    1236   |     913    |   323   |    73.9    |    12.2     | 🔴 Partial
2024-25 | Playoffs       |      89   |      82    |     7   |    92.1    |    14.8     | 🔴 Partial
```

**What to Look For:**
- ✅ **coverage_%**: Higher is better (70%+ is good)
- ✅ **avg_players**: 10-12 regular season, 14-16 playoffs is excellent
- ⚠️ **missing games**: Number of games with no props at all

---

### Team Completeness Check

```
row_type | season  | team | info1 | info2 | info3 | info4 | notes
TEAM     | 2023-24 | BOS  | 67    | 10.3  | 19    | 14.7  |
TEAM     | 2023-24 | LAC  | 1     | 5.0   | 0     | 0     | 🟡 Low coverage
```

**Columns:**
- `info1`: Regular season games with props
- `info2`: Avg players per regular season game
- `info3`: Playoff games with props
- `info4`: Avg players per playoff game

**What to Look For:**
- Teams should have 60-70 regular season games (not all 82 is expected)
- Avg players should be 10+ for regular season, 14+ for playoffs
- 🟡 Low coverage flag = <6 players average

---

### Missing Games

```
game_date  | home_team | away_team | matchup    | game_type      | status
2023-10-24 | Warriors  | Suns      | PHX @ GSW  | REGULAR SEASON | 🔴 CRITICAL: NO PROPS DATA
2023-10-25 | Hornets   | Hawks     | ATL @ CHA  | REGULAR SEASON | 🔴 CRITICAL: NO PROPS DATA
```

**Action:** These are games where scraper completely failed or didn't run
- Document if early season (expected gap)
- Backfill if data available from The Odds API

---

### Low Coverage Games

```
game_date  | matchup    | game_type      | unique_players | coverage_level | sample_players
2023-11-15 | SAC @ LAL  | REGULAR SEASON | 4              | 🟡 VERY LOW   | LeBron James, Anthony Davis...
2023-12-03 | MEM @ LAC  | REGULAR SEASON | 5              | 🟡 LOW        | Kawhi Leonard, Paul George...
```

**What This Means:**
- Some games naturally have fewer props (less interesting matchups)
- 4-6 players = LOW but acceptable
- <4 players = VERY LOW (might indicate partial scraper failure)

---

### Yesterday Check

```
check_date | scheduled | with_props | total_players | avg_players | min_players | max_players | status
2025-10-11 | 12        | 12         | 142           | 11.8        | 8           | 15          | ✅ Complete
```

**Status Values:**
- `✅ Complete` - All games have 6+ players
- `🟡 WARNING: Low average coverage` - Games have <6 avg players
- `⚠️ WARNING: X games with <6 players` - Some games sparse
- `❌ CRITICAL: No props data` - **Scraper failed completely**
- `🔴 CRITICAL: X games missing props` - **Some games not captured**

---

### Playoff Verification

```
team | expected_games | actual_games | avg_players | min_players | max_players | status
BOS  | 24             | 19           | 14.7        | 9           | 18          | ⚠️ Incomplete (5 missing)
IND  | 17             | 17           | 14.2        | 11          | 16          | ✅ Complete
```

**What to Look For:**
- `✅ Complete` = All playoff games captured
- `⚠️ Incomplete` = Some playoff games missing
- `🟡 Low Player Coverage` = Games have <8 players (low for playoffs)

---

## 🔧 Troubleshooting

### "Command not found: validate-props"

**Solution:**
```bash
chmod +x ~/code/nba-stats-scraper/scripts/validate-props
```

Or use full path:
```bash
~/code/nba-stats-scraper/scripts/validate-props help
```

---

### "Query file not found"

**Solution:**
```bash
# Verify queries exist
ls -la ~/code/nba-stats-scraper/validation/queries/raw/odds_api_props/

# Should see 8 .sql files
validate-props list
```

---

### "No results" or "Empty table"

**Cause:** Date range outside your actual data coverage

**Solution:**
- Focus on 2023-24 and 2024-25 seasons
- Adjust date ranges in queries to match your coverage
- Check `gaps` command to see actual date range

---

## 📅 Recommended Schedule

### Daily (Automated via Cron)

```bash
# Add to crontab: crontab -e
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-odds-props yesterday
```

### Weekly (Manual or Automated)

```bash
# Monday mornings
validate-odds-props week
```

### Monthly (Manual)

```bash
# First Monday of month
validate-odds-props gaps           # Overview
validate-odds-props completeness   # Team details
```

### After Backfills (Manual)

```bash
# Run all validation
validate-odds-props gaps
validate-odds-props missing
validate-odds-props low-coverage
validate-odds-props playoffs
```

---

## 🎯 Real-World Examples

### Example 1: Morning Check Shows Low Coverage

```bash
$ validate-odds-props yesterday

check_date | scheduled | with_props | avg_players | low_coverage_games | status
2025-10-11 | 12        | 12         | 5.2         | 8                  | 🟡 WARNING: Low average coverage
```

**Actions:**
1. Check which specific games have low coverage: `validate-odds-props low-coverage`
2. Investigate if pattern (specific teams, back-to-backs, etc.)
3. May be normal for less interesting matchups

---

### Example 2: Finding All Missing Games for 2023-24

```bash
# Generate CSV of all missing games
$ validate-odds-props missing --csv

# Opens in Excel/Numbers to analyze patterns
# Group by month to see when coverage started
```

**Finding:** Coverage started December 2023, Oct-Nov missing = expected gap

---

### Example 3: Weekly Trend Analysis

```bash
$ validate-odds-props week

game_date  | day_of_week | scheduled | with_props | avg_players | status
2025-10-11 | Friday      | 12        | 12         | 11.8        | ✅ Complete
2025-10-10 | Thursday    | 11        | 11         | 12.3        | ✅ Complete
2025-10-09 | Wednesday   | 0         | 0          | 0           | ⚪ No games
2025-10-08 | Tuesday     | 10        | 9          | 10.5        | 🔴 Incomplete (1 missing)
```

**Pattern Found:** Tuesday had missing game - check that specific date

---

## 💡 Pro Tips

### 1. Focus on Recent Seasons
```bash
# Your best data is 2023-24 and 2024-25
# Don't waste time on 2021-22 and 2022-23 unless you can backfill
```

### 2. Low Coverage is Often Normal
```bash
# Not every game has props for 15 players
# 6-8 players for non-primetime games is acceptable
# Only worry if avg drops below 6
```

### 3. Quick Health Check
```bash
# One-liner to verify system health
validate-odds-props yesterday && validate-odds-props today
```

### 4. Generate Weekly Reports
```bash
# Create automated weekly report
{
  echo "=== Weekly Props Validation Report ==="
  echo "Generated: $(date)"
  echo ""
  validate-odds-props week
  echo ""
  validate-odds-props low-coverage
} > props_weekly_$(date +%Y%m%d).txt
```

### 5. Compare with Odds Game Lines
```bash
# Props should exist for any game that has game lines
# Missing props but has game lines = scraper issue
validate-odds yesterday
validate-odds-props yesterday
```

---

## 🔗 Related Documentation

- **Query Files:** `validation/queries/raw/odds_api_props/`
- **Validator Code:** `validation/validators/raw/odds_api_props_validator.py`
- **Data Gaps Doc:** `validation/docs/odds_api_props_data_coverage.md`

---

## 📞 Quick Reference Card

```bash
# Most Important Command
validate-odds-props gaps                  # See everything at once

# Daily
validate-odds-props yesterday             # Check yesterday

# Weekly  
validate-odds-props week                  # Last 7 days

# Quality Checks
validate-odds-props missing               # Find CRITICAL issues
validate-odds-props low-coverage          # Find WARNING issues

# After Backfills
validate-odds-props completeness          # Team-by-team
validate-odds-props playoffs              # Verify playoffs

# During Games
validate-odds-props today                 # Scraper health

# Save Results
validate-odds-props [command] --csv       # To CSV
validate-odds-props [command] --table     # To BigQuery

# Help
validate-odds-props help                  # Full help
validate-odds-props list                  # List queries
```

---

## 🎯 Understanding Your Data Status

### What You Have (Good!)
- ✅ **2023-24**: 866/1234 regular season games (70%)
- ✅ **2023-24**: 78/88 playoff games (89%)
- ✅ **2024-25**: 913/1236 regular season games (74%)
- ✅ **2024-25**: 82/89 playoff games (92%)

### What's Missing (Expected)
- ❌ **2021-22**: Complete season (scraper not built yet)
- ❌ **2022-23**: Regular season (scraper not built yet)
- 🟡 **Oct-Nov 2023**: Early season games (scraper startup period)

### Focus Areas
1. **Daily monitoring**: Ensure new games get captured
2. **Low coverage tracking**: Identify games with <6 players
3. **Playoff verification**: Ensure high-stakes games complete

---

**Last Updated:** October 12, 2025  
**Version:** 1.0  
**Data Coverage:** May 2023 - Present
