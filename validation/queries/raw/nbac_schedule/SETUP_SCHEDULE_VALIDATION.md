# NBA.com Schedule Validation - Setup Guide

Quick setup instructions for the `validate-schedule` CLI tool.

---

## 📦 What's Included

### 1. **SQL Queries** (8 files)
- `season_completeness_check.sql` - Overall season validation
- `find_missing_regular_season_games.sql` - Regular season gaps
- `verify_playoff_completeness.sql` - Playoff structure
- `team_balance_check.sql` - Team game balance
- `team_schedule_gaps.sql` - Suspicious gaps (7+ days)
- `daily_freshness_check.sql` - Yesterday's games check
- `schedule_horizon_check.sql` - Future schedule horizon
- `enhanced_field_quality.sql` - 18 analytical fields quality

### 2. **CLI Tool**
- `validate-schedule` - Bash script for running queries

### 3. **Documentation**
- `VALIDATE_SCHEDULE_CLI.md` - Quick-start guide
- `README.md` - Query documentation
- `SETUP_SCHEDULE_VALIDATION.md` - This file

### 4. **Test Script**
- `test-validate-schedule.sh` - Verify installation

---

## 🚀 Quick Setup (5 minutes)

### Step 1: Create Queries Directory

```bash
cd ~/code/nba-stats-scraper
mkdir -p validation/queries/raw/nbac_schedule
```

### Step 2: Save Query Files

Save all 8 SQL query files to:
```
validation/queries/raw/nbac_schedule/
```

**Files to save:**
1. `season_completeness_check.sql`
2. `find_missing_regular_season_games.sql`
3. `verify_playoff_completeness.sql`
4. `team_balance_check.sql`
5. `team_schedule_gaps.sql`
6. `daily_freshness_check.sql`
7. `schedule_horizon_check.sql`
8. `enhanced_field_quality.sql`

Also save:
- `README.md` in the same directory

### Step 3: Save CLI Tool

Save `validate-schedule` to:
```
scripts/validate-schedule
```

Make it executable:
```bash
chmod +x scripts/validate-schedule
```

### Step 4: Save Documentation

Save to:
- `scripts/VALIDATE_SCHEDULE_CLI.md`
- `validation/queries/raw/nbac_schedule/README.md`

### Step 5: Save Test Script

Save `test-validate-schedule.sh` to:
```
scripts/test-validate-schedule.sh
```

Make it executable:
```bash
chmod +x scripts/test-validate-schedule.sh
```

---

## ✅ Verify Installation

### Run Test Script
```bash
./scripts/test-validate-schedule.sh
```

**Expected output:**
```
Test 1: Check script exists                    ✅
Test 2: Check script is executable             ✅
Test 3: Check queries directory exists          ✅
Test 4: List query files                        ✅ (8 files)
Test 5: Test help command                       ✅
Test 6: Test list command                       ✅
Test 7: Check BigQuery CLI (bq)                 ✅
Test 8: Verify all expected query files exist   ✅
```

### Test CLI Commands
```bash
# Show help
validate-schedule help

# List queries
validate-schedule list
```

---

## 🎯 First Run

### Test with Real Data

```bash
# 1. Check yesterday's games
validate-schedule yesterday

# 2. Check schedule horizon
validate-schedule horizon

# 3. Full season check (might take ~30 seconds)
validate-schedule completeness
```

**If queries fail:**
- Verify BigQuery authentication: `gcloud auth application-default login`
- Check project ID in queries (should be `nba-props-platform`)
- Verify table exists: `bq show nba_raw.nbac_schedule`

---

## 📁 File Structure (After Setup)

```
nba-stats-scraper/
├── scripts/
│   ├── validate-schedule                           # CLI tool
│   ├── VALIDATE_SCHEDULE_CLI.md                    # Quick-start guide
│   └── test-validate-schedule.sh                   # Test script
│
└── validation/
    └── queries/
        └── raw/
            └── nbac_schedule/
                ├── README.md                        # Query documentation
                ├── season_completeness_check.sql
                ├── find_missing_regular_season_games.sql
                ├── verify_playoff_completeness.sql
                ├── team_balance_check.sql
                ├── team_schedule_gaps.sql
                ├── daily_freshness_check.sql
                ├── schedule_horizon_check.sql
                └── enhanced_field_quality.sql
```

---

## 🎨 Create Shell Alias (Optional)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
# NBA Schedule Validation
alias validate-schedule='~/code/nba-stats-scraper/scripts/validate-schedule'
```

Reload shell:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

Test alias:
```bash
validate-schedule help
```

---

## 📅 Daily Use

### Morning Routine
```bash
# Run daily checks
validate-schedule yesterday
validate-schedule horizon
```

### Weekly Health Check
```bash
# Monday morning
validate-schedule completeness
validate-schedule balance
validate-schedule fields
```

---

## 🔄 Next Steps (Optional)

After CLI tool is working, you can create:

1. **YAML Config** (`validation/configs/raw/nbac_schedule.yaml`)
   - Expected coverage (6,706+ games)
   - 18 enhanced field definitions
   - Known gaps (All-Star breaks)
   - Validation thresholds

2. **Python Validator** (`validation/validators/raw/nbac_schedule_validator.py`)
   - Custom validation methods
   - Programmatic access to queries
   - Integration with validation framework

3. **Automated Monitoring**
   - Cron jobs for daily checks
   - Alerts for critical issues
   - Dashboard integration

---

## 🆘 Troubleshooting

### "Command not found"
```bash
# Use full path
~/code/nba-stats-scraper/scripts/validate-schedule help

# Or check if script is executable
chmod +x scripts/validate-schedule
```

### "Query file not found"
```bash
# Verify queries exist
ls -la validation/queries/raw/nbac_schedule/*.sql

# Should show 8 .sql files
```

### "Cannot query over table without filter"
This shouldn't happen with provided queries (all include partition filters). If it does, verify you're using the original query files without modifications.

### BigQuery authentication errors
```bash
# Re-authenticate
gcloud auth application-default login

# Set project
gcloud config set project nba-props-platform
```

---

## 📚 Documentation

- **CLI Quick-Start**: `scripts/VALIDATE_SCHEDULE_CLI.md`
- **Query Details**: `validation/queries/raw/nbac_schedule/README.md`
- **This Setup Guide**: You're reading it!

---

## 💡 Tips

1. **Start simple**: Begin with `yesterday` and `horizon` commands
2. **Save results**: Use `--csv` for important checks
3. **Review patterns**: Run `completeness` weekly to catch issues early
4. **Automate**: Set up cron jobs for daily checks

---

## ✨ Success!

You now have:
- ✅ 8 validation queries ready to run
- ✅ CLI tool for easy execution
- ✅ Complete documentation
- ✅ Test script for verification

**Try it out:**
```bash
validate-schedule yesterday
```

---

**Questions?** Check the documentation files or run `validate-schedule help`

**Last Updated:** October 12, 2025
