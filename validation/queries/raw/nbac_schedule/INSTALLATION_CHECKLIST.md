# NBA Schedule Validation - Installation Checklist

Quick checklist for setting up the validate-schedule CLI tool.

---

## ✅ Pre-Installation

- [ ] Working directory: `~/code/nba-stats-scraper`
- [ ] BigQuery access configured (`gcloud auth application-default login`)
- [ ] `bq` CLI tool installed and working (`bq version`)
- [ ] Table exists: `nba-props-platform.nba_raw.nbac_schedule`

---

## 📂 Create Directory Structure

```bash
cd ~/code/nba-stats-scraper
mkdir -p validation/queries/raw/nbac_schedule
mkdir -p scripts
```

- [ ] Directory created: `validation/queries/raw/nbac_schedule/`
- [ ] Directory exists: `scripts/`

---

## 📝 Save Query Files

Save to `validation/queries/raw/nbac_schedule/`:

- [ ] `season_completeness_check.sql`
- [ ] `find_missing_regular_season_games.sql`
- [ ] `verify_playoff_completeness.sql`
- [ ] `team_balance_check.sql`
- [ ] `team_schedule_gaps.sql`
- [ ] `daily_freshness_check.sql`
- [ ] `schedule_horizon_check.sql`
- [ ] `enhanced_field_quality.sql`
- [ ] `README.md`

**Total: 8 SQL files + 1 README**

---

## 🔧 Save CLI Tool

- [ ] Save `validate-schedule` to `scripts/validate-schedule`
- [ ] Make executable: `chmod +x scripts/validate-schedule`

---

## 📖 Save Documentation

- [ ] Save `VALIDATE_SCHEDULE_CLI.md` to `scripts/VALIDATE_SCHEDULE_CLI.md`
- [ ] Save `SETUP_SCHEDULE_VALIDATION.md` to `scripts/SETUP_SCHEDULE_VALIDATION.md`

---

## 🧪 Save Test Script

- [ ] Save `test-validate-schedule.sh` to `scripts/test-validate-schedule.sh`
- [ ] Make executable: `chmod +x scripts/test-validate-schedule.sh`

---

## ✅ Verify Installation

### Run Test Script
```bash
./scripts/test-validate-schedule.sh
```

Expected results:
- [ ] ✅ Test 1: Script exists
- [ ] ✅ Test 2: Script is executable
- [ ] ✅ Test 3: Queries directory exists
- [ ] ✅ Test 4: All 8 query files listed
- [ ] ✅ Test 5: Help command works
- [ ] ✅ Test 6: List command works
- [ ] ✅ Test 7: bq command available
- [ ] ✅ Test 8: All query files present

### Test CLI Commands
```bash
validate-schedule help
validate-schedule list
```

- [ ] Help displays correctly
- [ ] List shows 8 queries

---

## 🎯 First Real Query

Run your first validation query:

```bash
validate-schedule yesterday
```

Expected output:
- [ ] Query executes without errors
- [ ] Results display in terminal
- [ ] Status indicator shows (✅, 🟡, or 🔴)

---

## 🎨 Optional: Create Alias

```bash
echo "alias validate-schedule='~/code/nba-stats-scraper/scripts/validate-schedule'" >> ~/.bashrc
source ~/.bashrc
```

- [ ] Alias created
- [ ] Alias works: `validate-schedule help`

---

## 📊 Test All Query Types

Try each category:

```bash
# Daily monitoring
validate-schedule yesterday        # ✅
validate-schedule horizon          # ✅

# Historical validation
validate-schedule completeness     # ✅ (might take 30 seconds)
validate-schedule balance          # ✅
validate-schedule gaps             # ✅

# Data quality
validate-schedule fields           # ✅

# Playoffs (if applicable)
validate-schedule playoffs         # ✅
```

- [ ] All queries execute successfully
- [ ] Results make sense (no obvious errors)
- [ ] Status indicators display correctly

---

## 🔄 Optional: Test Output Formats

```bash
# Save to CSV
validate-schedule yesterday --csv

# Save to BigQuery table
validate-schedule yesterday --table
```

- [ ] CSV file created in current directory
- [ ] BigQuery table created in `validation` dataset

---

## 📋 Final Checklist

### Files (Total: 13)

**Queries (9 files):**
- [ ] 8 SQL query files
- [ ] 1 README.md

**Scripts (3 files):**
- [ ] validate-schedule CLI tool
- [ ] test-validate-schedule.sh
- [ ] (validate-odds if you have it)

**Documentation (3 files):**
- [ ] VALIDATE_SCHEDULE_CLI.md
- [ ] SETUP_SCHEDULE_VALIDATION.md
- [ ] INSTALLATION_CHECKLIST.md (this file)

### Functionality
- [ ] All queries execute without errors
- [ ] Help and list commands work
- [ ] Output is readable and colored
- [ ] Status indicators display correctly
- [ ] CSV export works (optional)
- [ ] BigQuery table export works (optional)

---

## 🎉 Success Criteria

You're done when:
1. ✅ Test script passes all checks
2. ✅ `validate-schedule yesterday` runs successfully
3. ✅ `validate-schedule completeness` shows results
4. ✅ No "file not found" or "permission denied" errors

---

## 🆘 Common Issues

### Issue: "Command not found"
**Fix:** Use full path or create alias
```bash
~/code/nba-stats-scraper/scripts/validate-schedule help
```

### Issue: "Query file not found"
**Fix:** Verify all 8 SQL files are in correct directory
```bash
ls -la validation/queries/raw/nbac_schedule/*.sql
```

### Issue: "Cannot query over table without filter"
**Fix:** You're using modified queries - use the original query files

### Issue: BigQuery authentication errors
**Fix:** Re-authenticate
```bash
gcloud auth application-default login
gcloud config set project nba-props-platform
```

---

## 📞 Next Steps After Installation

1. **Daily use**: Add to morning routine
   ```bash
   validate-schedule yesterday
   validate-schedule horizon
   ```

2. **Weekly health check**: Monday mornings
   ```bash
   validate-schedule completeness
   validate-schedule balance
   validate-schedule fields
   ```

3. **Automate**: Set up cron jobs (optional)
   ```bash
   crontab -e
   # Add: 0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-schedule yesterday
   ```

4. **Create config** (advanced - optional):
   - Create `validation/configs/raw/nbac_schedule.yaml`
   - Create `validation/validators/raw/nbac_schedule_validator.py`

---

## ✨ You're All Set!

**Quick test:**
```bash
validate-schedule help
validate-schedule yesterday
```

If both work, you're ready to go! 🚀

---

**Last Updated:** October 12, 2025
