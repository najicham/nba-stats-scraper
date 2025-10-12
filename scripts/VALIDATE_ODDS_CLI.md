# validate-odds CLI Tool Guide

**Quick Reference for NBA Odds Data Validation**

---

## 🚀 Installation

```bash
cd ~/code/nba-stats-scraper

# Make the script executable
chmod +x scripts/validate-odds

# Optional: Create alias for easier access
echo "alias validate-odds='~/code/nba-stats-scraper/scripts/validate-odds'" >> ~/.bashrc
source ~/.bashrc
```

**Verify installation:**
```bash
validate-odds help
```

---

## 📖 Quick Start

### See What's Available
```bash
validate-odds help      # Show full help
validate-odds list      # List all queries
```

### Run Your First Check
```bash
# Check yesterday's games (daily morning routine)
validate-odds yesterday

# Full season completeness check
validate-odds completeness
```

---

## 🎯 Common Workflows

### Morning Routine (During Season)
```bash
# Check if yesterday's games were captured
validate-odds yesterday

# If issues found, check last week's trend
validate-odds week
```

**Expected Output:**
```
✅ Complete          - All games captured
⚪ No games          - Off day (All-Star break, etc.)
❌ CRITICAL          - Scraper failure (investigate immediately)
⚠️ WARNING          - Some games missing
```

---

### After Running Backfills
```bash
# 1. Full completeness check
validate-odds completeness

# 2. Find any remaining gaps
validate-odds missing

# 3. Verify playoffs
validate-odds playoffs
```

---

### Weekly Health Check
```bash
# Run on Monday mornings
validate-odds week

# If patterns emerge, investigate specific dates
validate-odds missing
```

---

### Game Day Monitoring
```bash
# Check scraper is running (run hourly during games)
validate-odds today
```

---

## 📋 All Commands

### Historical Validation

| Command | Alias | Purpose | When to Run |
|---------|-------|---------|-------------|
| `completeness` | `complete`, `full` | Full season check (4 seasons) | After backfills, quarterly |
| `missing` | `gaps` | Find specific missing games | When completeness shows gaps |
| `markets` | `discrepancies` | Find spreads vs totals issues | Monthly, investigating quality |
| `playoffs` | `playoff` | Verify playoff completeness | After playoffs, during backfill |

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
validate-odds completeness --csv
validate-odds yesterday --csv
```

**Output:** `validation_season_completeness_check_20251012_143022.csv`

### Save to BigQuery Table
```bash
validate-odds completeness --table
```

**Output:** `nba-props-platform:validation.odds_season_completeness_check_20251012`

---

## 📊 Understanding Output

### Season Completeness Check

```
row_type    | season  | team              | reg_spreads | reg_totals | playoff_spreads | playoff_totals | total | notes
DIAGNOSTICS | 5278    | null_playoff_flag | 0           | 0          | 0               | 360            | 4918  | Check: all should be 0
TEAM        | 2021-22 | Boston Celtics    | 82          | 82         | 24              | 24             | 106   |
TEAM        | 2021-22 | Warriors          | 81          | 81         | 22              | 22             | 103   | ⚠️ Missing games
```

**What to Look For:**
- ✅ **DIAGNOSTICS row**: All values should be 0 (no join failures)
- ✅ **reg_spreads/totals**: Should be 82 for all teams
- ⚠️ **Notes column**: Shows teams with missing games

---

### Yesterday Check

```
check_date | scheduled_games | odds_games | games_with_spreads | games_with_totals | status
2025-10-11 | 12              | 12         | 12                 | 12                | ✅ Complete
```

**Status Values:**
- `✅ Complete` - All good, no action needed
- `⚪ No games scheduled` - Off day
- `❌ CRITICAL: No odds data` - **Scraper failed - investigate now**
- `⚠️ WARNING: X games missing` - **Check which games missing**

---

### Missing Games

```
game_date  | home_team | away_team | matchup    | status
2021-11-30 | Suns      | Warriors  | GSW @ PHX  | MISSING FROM ODDS DATA
2022-04-02 | 76ers     | Hornets   | CHA @ PHI  | MISSING FROM ODDS DATA
```

**Action:** Create backfill dates file:
```bash
# Create dates file from output
cat > backfill_dates.txt << EOF
2021-11-30
2022-04-02
EOF

# Run scraper backfill
python -m backfill_jobs.scrapers.odds_api_lines.odds_api_lines_backfill_job \
  --dates-file backfill_dates.txt --force
```

---

### Playoff Verification

```
team                 | expected_games | actual_games | actual_spreads | actual_totals | missing_games | status
Boston Celtics       | 24             | 24           | 24             | 24            | 0             | ✅ Complete
Golden State Warriors| 22             | 22           | 22             | 22            | 0             | ✅ Complete
```

**What to Look For:**
- All teams should show `✅ Complete`
- `missing_games` should be 0
- If incomplete, run `validate-odds missing` to find specific games

---

## 🔧 Troubleshooting

### "Command not found: validate-odds"

**Problem:** Alias not set up or script not executable

**Solution:**
```bash
# Make executable
chmod +x ~/code/nba-stats-scraper/scripts/validate-odds

# Use full path
~/code/nba-stats-scraper/scripts/validate-odds help

# Or set up alias
echo "alias validate-odds='~/code/nba-stats-scraper/scripts/validate-odds'" >> ~/.bashrc
source ~/.bashrc
```

---

### "Query file not found"

**Problem:** Running from wrong directory or queries not created

**Solution:**
```bash
# Verify queries exist
ls -la ~/code/nba-stats-scraper/validation/queries/raw/odds_game_lines/

# Should see:
# season_completeness_check.sql
# find_missing_regular_season_games.sql
# etc.

# Run list command to verify
validate-odds list
```

---

### "Permission denied"

**Problem:** Script not executable

**Solution:**
```bash
chmod +x ~/code/nba-stats-scraper/scripts/validate-odds
```

---

## 📅 Recommended Schedule

### Daily (Automated via Cron)

```bash
# Add to crontab: crontab -e
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-odds yesterday
```

### Weekly (Manual or Automated)

```bash
# Monday mornings
validate-odds week
```

### Monthly (Manual)

```bash
# First Monday of month - full health check
validate-odds completeness
validate-odds markets
```

### After Backfills (Manual)

```bash
# Run all three
validate-odds completeness
validate-odds missing
validate-odds playoffs
```

---

## 🎯 Real-World Examples

### Example 1: Morning Check Shows Issues

```bash
$ validate-odds yesterday

check_date | scheduled_games | odds_games | status
2025-10-11 | 12              | 10         | ⚠️ WARNING: 2 games missing
```

**Actions:**
1. Check which games are missing
2. Investigate scraper logs
3. Re-run scraper for that date

---

### Example 2: Backfill Verification

```bash
# After running backfill
$ validate-odds completeness

# Look for teams with <82 regular season games
# If found:
$ validate-odds missing --csv

# Create backfill list from CSV
# Re-run backfill
# Verify again
$ validate-odds completeness
```

---

### Example 3: Weekly Health Check

```bash
$ validate-odds week

game_date  | day_of_week | scheduled_games | odds_games | status
2025-10-11 | Friday      | 12              | 12         | ✅ Complete
2025-10-10 | Thursday    | 11              | 11         | ✅ Complete
2025-10-09 | Wednesday   | 0               | 0          | ⚪ No games
2025-10-08 | Tuesday     | 10              | 9          | ⚠️ Incomplete
```

**Pattern Found:** Tuesday had incomplete data - investigate that specific date

---

## 💡 Pro Tips

### 1. Chain Commands for Reports
```bash
# Generate complete validation report
{
  echo "=== Season Completeness ==="
  validate-odds completeness
  echo ""
  echo "=== Missing Games ==="
  validate-odds missing
  echo ""
  echo "=== Last Week ==="
  validate-odds week
} > validation_report_$(date +%Y%m%d).txt
```

### 2. Quick Status Check
```bash
# One-liner to check everything is healthy
validate-odds yesterday && echo "✅ All systems operational"
```

### 3. Alert on Failures
```bash
# Add to cron job
validate-odds yesterday || echo "❌ Validation failed!" | mail -s "Odds Validation Alert" you@example.com
```

### 4. Save Historical Results
```bash
# Keep monthly snapshots
validate-odds completeness --table  # Saves with timestamp in table name
```

---

## 🔗 Related Documentation

- **Full Validation Guide:** `validation/docs/odds_game_lines_validation_guide.md`
- **Query Files:** `validation/queries/raw/odds_game_lines/`
- **Validator Code:** `validation/validators/raw/odds_game_lines_validator.py`

---

## 📞 Quick Reference Card

```bash
# Daily
validate-odds yesterday              # Check yesterday

# Weekly  
validate-odds week                   # Last 7 days

# After Backfills
validate-odds completeness           # Full check
validate-odds missing                # Find gaps
validate-odds playoffs               # Verify playoffs

# During Games
validate-odds today                  # Scraper health

# Save Results
validate-odds [command] --csv        # To CSV
validate-odds [command] --table      # To BigQuery

# Help
validate-odds help                   # Full help
validate-odds list                   # List queries
```

---

**Last Updated:** October 12, 2025  
**Version:** 1.0
