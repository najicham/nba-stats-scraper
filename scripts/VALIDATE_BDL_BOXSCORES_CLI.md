# validate-bdl-boxscores CLI Tool Guide

**Quick Reference for Ball Don't Lie Box Scores Validation**

---

## 🚀 Installation

```bash
cd ~/code/nba-stats-scraper

# Make the script executable
chmod +x scripts/validate-bdl-boxscores

# Optional: Create alias for easier access
echo "alias validate-bdl-boxscores='~/code/nba-stats-scraper/scripts/validate-bdl-boxscores'" >> ~/.bashrc
source ~/.bashrc
```

**Verify installation:**
```bash
validate-bdl-boxscores help
```

---

## 📖 Quick Start

### See What's Available
```bash
validate-bdl-boxscores help      # Show full help
validate-bdl-boxscores list      # List all queries
```

### Run Your First Check
```bash
# Check yesterday's games (daily morning routine)
validate-bdl-boxscores yesterday

# Full season completeness check
validate-bdl-boxscores completeness
```

---

## 🎯 Common Workflows

### Morning Routine (During Season)
```bash
# Check if yesterday's games were captured
validate-bdl-boxscores yesterday

# If issues found, check last week's trend
validate-bdl-boxscores week
```

**Expected Output:**
```
✅ Complete          - All games captured with proper player counts
⚪ No games          - Off day (All-Star break, etc.)
❌ CRITICAL          - No box score data (scraper failure)
⚠️ WARNING          - Missing games or low player counts
```

---

### After Running Backfills
```bash
# 1. Full completeness check
validate-bdl-boxscores completeness

# 2. Find any remaining gaps
validate-bdl-boxscores missing

# 3. Verify data quality vs NBA.com
validate-bdl-boxscores cross-validate

# 4. Check playoffs
validate-bdl-boxscores playoffs
```

---

### Weekly Health Check
```bash
# Run on Monday mornings
validate-bdl-boxscores week

# Cross-validate stats quality
validate-bdl-boxscores cross-validate

# If patterns emerge, investigate specific dates
validate-bdl-boxscores missing
```

---

### Game Day Monitoring
```bash
# Check scraper is running (run after games complete)
validate-bdl-boxscores today
```

---

## 📋 All Commands

### Historical Validation

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `completeness` | `complete`, `full` | Full season check (all teams/seasons) | After backfills, quarterly |
| `missing` | `gaps` | Find specific missing games | When completeness shows gaps |
| `cross-validate` | `xval`, `compare`, `gamebook` | Compare BDL vs NBA.com stats | Weekly data quality check |
| `playoffs` | `playoff` | Verify playoff completeness | After playoffs, during backfill |

### Daily Monitoring

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `yesterday` | `daily` | Check yesterday's games | Every morning 9 AM |
| `week` | `weekly`, `7days` | Last 7 days coverage | Weekly (Monday) |
| `today` | `now`, `realtime` | Real-time scraper health | After games complete |

---

## 💾 Saving Results

### Save to CSV
```bash
validate-bdl-boxscores completeness --csv
validate-bdl-boxscores cross-validate --csv
validate-bdl-boxscores yesterday --csv
```

**Output:** `validation_bdl_season_completeness_check_20251012_143022.csv`

### Save to BigQuery Table
```bash
validate-bdl-boxscores completeness --table
```

**Output:** `nba-props-platform:validation.bdl_season_completeness_check_20251012`

---

## 📊 Understanding Output

### Season Completeness Check

```
row_type    | season  | team | reg_games | playoff_games | unique_players | avg_players | min_players | max_players | notes
DIAGNOSTICS | 5278    | diag | 0         | 360           | 4918          | 165070      |             |             | Check: null counts should be 0
TEAM        | 2021-22 | BOS  | 82        | 24            | 67            | 32.5        | 28          | 38          |
TEAM        | 2021-22 | GSW  | 81        | 22            | 65            | 31.8        | 27          | 37          | ⚠️ Missing regular season games
```

**What to Look For:**
- ✅ **DIAGNOSTICS row**: All null counts should be 0 (no join failures)
- ✅ **reg_games**: Should be 82 for all teams
- ✅ **avg_players**: Should be ~30-35 (reasonable range)
- ✅ **min_players**: Should be >= 20 (sanity check)
- ⚠️ **Notes column**: Shows teams with missing games or data issues

---

### Yesterday Check

```
check_date | scheduled_games | games_with_data | total_player_records | unique_players | avg_players_per_game | min_players_per_game | status
2025-10-11 | 12              | 12              | 385                  | 142            | 32.1                 | 28                   | ✅ Complete
```

**Status Values:**
- `✅ Complete` - All good, no action needed
- `⚪ No games scheduled` - Off day
- `❌ CRITICAL: No box score data` - **Scraper failed - investigate now**
- `⚠️ WARNING: X games missing` - **Check which games missing**
- `⚠️ WARNING: Suspiciously low player count` - **Data quality issue**

---

### Cross-Validation with Gamebook

```
game_date  | player_name      | team | presence_status | bdl_points | gamebook_points | point_diff | issue_severity
2025-10-11 | LeBron James     | LAL  | in_both        | 28         | 28              | 0          | ✅ Match
2025-10-11 | Stephen Curry    | GSW  | in_both        | 35         | 32              | 3          | 🔴 CRITICAL: Point discrepancy
2025-10-11 | Kevin Durant     | PHX  | missing_from_bdl|           | 27              |            | 🔴 CRITICAL: Missing from BDL
```

**Issue Severity:**
- `✅ Match` - Stats agree perfectly
- `🟡 WARNING: Stat discrepancy` - Assists/rebounds differ by >2
- `🔴 CRITICAL: Point discrepancy` - Points differ by >2 (affects prop settlement!)
- `🔴 CRITICAL: Missing from BDL` - Player in gamebook but not BDL
- `🟡 WARNING: Missing from Gamebook` - Player in BDL but not gamebook (less critical)

---

### Missing Games

```
game_date  | home_team  | away_team | matchup    | status                       | schedule_game_id
2024-11-30 | Suns       | Warriors  | GSW @ PHX  | MISSING FROM BDL BOX SCORES | 0022400217
2024-04-02 | 76ers      | Hornets   | CHA @ PHI  | MISSING FROM BDL BOX SCORES | 0022301182
```

**Action:** Create backfill dates file:
```bash
# Create dates file from output
cat > backfill_dates.txt << EOF
2024-11-30
2024-04-02
EOF

# Run scraper backfill
gcloud run jobs execute bdl-boxscores-processor-backfill \
  --args="--dates-file,backfill_dates.txt" \
  --region=us-west2
```

---

### Playoff Verification

```
team                  | expected_games | actual_games | total_player_records | avg_players_per_game | missing_games | status
Boston Celtics        | 24             | 24           | 778                  | 32.4                 | 0             | ✅ Complete
Golden State Warriors | 22             | 22           | 694                  | 31.5                 | 0             | ✅ Complete
```

**What to Look For:**
- All teams should show `✅ Complete`
- `missing_games` should be 0
- `avg_players_per_game` should be 30-35
- If incomplete, run `validate-bdl missing` to find specific games

---

### Real-time Scraper Check

```
matchup      | game_state  | game_status_text | total_players | teams_with_data | last_processed_at | status                           | recommendation
LAL vs BOS   | completed   | Final            | 32            | 2               | 2025-10-11 23:45 | ✅ Data captured                | No action needed
GSW vs PHX   | in_progress | Q3 - 8:45        | 0             | 0               |                  | ⚪ In progress (no data - normal)| No action needed
MIA vs DEN   | completed   | Final            | 0             | 0               |                  | ❌ CRITICAL: Missing data       | Run scraper immediately
```

**Status Indicators:**
- `✅ Data captured` - Completed games with full data (>= 20 players)
- `⚠️ Incomplete data` - Completed game but < 20 players (investigate)
- `❌ CRITICAL: Missing data` - Completed game with no data (scraper failed)
- `🔵 Live data available` - In-progress game with data (scraper working)
- `⚪ In progress (no data - normal)` - Game still in progress
- `⚪ Scheduled (no data - normal)` - Game hasn't started yet

---

## 🔧 Troubleshooting

### "Command not found: validate-bdl-boxscores"

**Problem:** Alias not set up or script not executable

**Solution:**
```bash
# Make executable
chmod +x ~/code/nba-stats-scraper/scripts/validate-bdl-boxscores

# Use full path
~/code/nba-stats-scraper/scripts/validate-bdl-boxscores help

# Or set up alias
echo "alias validate-bdl-boxscores='~/code/nba-stats-scraper/scripts/validate-bdl-boxscores'" >> ~/.bashrc
source ~/.bashrc
```

---

### "Query file not found"

**Problem:** Running from wrong directory or queries not created

**Solution:**
```bash
# Verify queries exist
ls -la ~/code/nba-stats-scraper/validation/queries/raw/bdl_boxscores/

# Should see:
# season_completeness_check.sql
# find_missing_games.sql
# cross_validate_with_gamebook.sql
# verify_playoff_completeness.sql
# daily_check_yesterday.sql
# weekly_check_last_7_days.sql
# realtime_scraper_check.sql

# Run list command to verify
validate-bdl-boxscores list
```

---

### "Permission denied"

**Problem:** Script not executable

**Solution:**
```bash
chmod +x ~/code/nba-stats-scraper/scripts/validate-bdl-boxscores
```

---

### Cross-validation shows many discrepancies

**Problem:** BDL stats don't match NBA.com gamebook

**Solutions:**
1. Check if BDL API changed (endpoint structure)
2. Verify processor is parsing fields correctly
3. Run on recent games only (test with `--last-days 1`)
4. Compare raw JSON from both sources manually

**Example:**
```bash
# Test on just yesterday
validate-bdl-boxscores cross-validate

# If issues, save for investigation
validate-bdl-boxscores cross-validate --csv
```

---

## 📅 Recommended Schedule

### Daily (Automated via Cron)

```bash
# Add to crontab: crontab -e
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-bdl-boxscores yesterday
```

### Weekly (Manual or Automated)

```bash
# Monday mornings
validate-bdl-boxscores week
validate-bdl-boxscores cross-validate
```

### Monthly (Manual)

```bash
# First Monday of month - full health check
validate-bdl-boxscores completeness
validate-bdl-boxscores cross-validate --csv
```

### After Backfills (Manual)

```bash
# Run all four
validate-bdl-boxscores completeness
validate-bdl-boxscores missing
validate-bdl-boxscores playoffs
validate-bdl-boxscores cross-validate
```

---

## 🎯 Real-World Examples

### Example 1: Morning Check Shows Low Player Count

```bash
$ validate-bdl-boxscores yesterday

check_date | scheduled_games | games_with_data | min_players_per_game | status
2025-10-11 | 12              | 12              | 18                   | ⚠️ WARNING: Suspiciously low player count
```

**Actions:**
1. Check which game had only 18 players
2. Run cross-validation to compare with gamebook
3. Investigate scraper logs for that specific game
4. Re-run scraper if needed

---

### Example 2: Cross-Validation Finds Point Discrepancies

```bash
$ validate-bdl-boxscores cross-validate

game_date  | player_name   | bdl_points | gamebook_points | point_diff | issue_severity
2025-10-11 | Luka Doncic   | 35         | 32              | 3          | 🔴 CRITICAL: Point discrepancy
```

**Actions:**
1. This affects prop settlement - investigate immediately
2. Check raw JSON from both BDL API and NBA.com
3. Determine which source is correct (NBA.com is authoritative)
4. If BDL is wrong, document and possibly use gamebook instead
5. Re-scrape if temporary API issue

---

### Example 3: Backfill Verification

```bash
# After running backfill for 2023-24 season
$ validate-bdl-boxscores completeness

# Shows Boston Celtics with 81/82 regular season games
$ validate-bdl-boxscores missing

game_date  | matchup    | status
2024-01-15 | BOS @ LAL  | MISSING FROM BDL BOX SCORES

# Create targeted backfill
$ gcloud run jobs execute bdl-boxscores-processor-backfill \
  --args="--start-date,2024-01-15,--end-date,2024-01-15" \
  --region=us-west2

# Verify fix
$ validate-bdl-boxscores completeness
# Now shows 82/82 ✅
```

---

### Example 4: Weekly Health Check Pattern Detection

```bash
$ validate-bdl-boxscores week

game_date  | day_of_week | scheduled_games | games_with_data | min_players_per_game | status
2025-10-11 | Friday      | 12              | 12              | 28                   | ✅ Complete
2025-10-10 | Thursday    | 11              | 11              | 30                   | ✅ Complete
2025-10-09 | Wednesday   | 0               | 0               | 0                    | ⚪ No games
2025-10-08 | Tuesday     | 10              | 9               | 0                    | ⚠️ Incomplete
2025-10-07 | Monday      | 8               | 8               | 19                   | ⚠️ Low player count
```

**Pattern Found:** 
- Tuesday missing 1 game - investigate that specific date
- Monday had suspiciously low player count - possible data quality issue
- Rest of week looks healthy

---

## 💡 Pro Tips

### 1. Chain Commands for Complete Reports
```bash
# Generate comprehensive validation report
{
  echo "=== BDL Box Scores Validation Report ==="
  echo "Generated: $(date)"
  echo ""
  echo "=== Season Completeness ==="
  validate-bdl-boxscores completeness
  echo ""
  echo "=== Missing Games ==="
  validate-bdl-boxscores missing
  echo ""
  echo "=== Data Quality (vs Gamebook) ==="
  validate-bdl-boxscores cross-validate
  echo ""
  echo "=== Last Week Coverage ==="
  validate-bdl-boxscores week
} > bdl_validation_report_$(date +%Y%m%d).txt
```

### 2. Quick Status Check
```bash
# One-liner to check everything is healthy
validate-bdl-boxscores yesterday && validate-bdl-boxscores cross-validate && echo "✅ All systems operational"
```

### 3. Alert on Failures
```bash
# Add to cron job
validate-bdl-boxscores yesterday || echo "❌ BDL Validation failed!" | mail -s "BDL Box Score Alert" you@example.com
```

### 4. Compare Multiple Days
```bash
# Save last 7 days for trending analysis
validate-bdl-boxscores week --csv

# Look at the CSV to spot patterns
cat validation_bdl_weekly_check_last_7_days_*.csv
```

### 5. Focus on Critical Stats
```bash
# Cross-validation focuses on points (critical for props)
# Run this weekly to ensure prop settlement accuracy
validate-bdl-boxscores cross-validate --csv

# Filter CSV for only critical issues
grep "CRITICAL" validation_bdl_cross_validate_*.csv
```

---

## 🔗 Related Documentation

- **Full Query README:** `validation/queries/raw/bdl_boxscores/README.md`
- **Validator Config:** `validation/configs/raw/bdl_boxscores.yaml`
- **Schema:** `schemas/bigquery/bdl_tables.sql`
- **Processor Reference:** NBA Processors Reference Documentation (section 7)

---

## 📞 Quick Reference Card

```bash
# Daily
validate-bdl-boxscores yesterday              # Check yesterday

# Weekly  
validate-bdl-boxscores week                   # Last 7 days
validate-bdl-boxscores cross-validate         # Data quality check

# After Backfills
validate-bdl-boxscores completeness           # Full check
validate-bdl-boxscores missing                # Find gaps
validate-bdl-boxscores playoffs               # Verify playoffs
validate-bdl-boxscores cross-validate         # Quality check

# During Games
validate-bdl-boxscores today                  # Scraper health

# Save Results
validate-bdl-boxscores [command] --csv        # To CSV
validate-bdl-boxscores [command] --table      # To BigQuery

# Help
validate-bdl-boxscores help                   # Full help
validate-bdl-boxscores list                   # List queries
```

---

## 🎓 Understanding BDL-Specific Nuances

### Player Count Flexibility
Unlike odds data (which has exactly 8 rows per game), player counts vary:
- **Normal range:** 30-35 total players per game
- **Close games:** 25-28 players (shorter rotation)
- **Blowouts:** 35-40 players (deep bench usage)
- **Minimum threshold:** 20 players (below this = investigate)

### Active Players Only
BDL only includes players who actually played:
- ✅ Players with >0 minutes
- ❌ DNP (Did Not Play)
- ❌ Inactive players
- ❌ Injured players

This is **normal** and different from NBA.com gamebooks which list everyone.

### Cross-Validation is Critical
Because BDL is a third-party API, always verify against NBA.com:
- **Points:** CRITICAL (affects prop settlement) - must match within 2 points
- **Assists/Rebounds:** HIGH (future props) - should match within 2
- **Other stats:** MEDIUM (consistency checks)

---

**Last Updated:** October 12, 2025  
**Version:** 1.0  
**Script Name:** `validate-bdl-boxscores`
**Data Source:** Ball Don't Lie API player box scores
