# Gamebook Validation Installation Guide

**Complete setup instructions for NBA.com Gamebook validation system**

---

## 📦 Files to Update/Create

### ✅ Files Requiring Updates (3)

1. **validation/queries/raw/nbac_gamebook/season_completeness_check.sql**
   - Status: REPLACE with fixed version
   - Issue Fixed: GROUP BY aggregation error

2. **scripts/validate-gamebook**
   - Status: REPLACE with updated version
   - New Feature: Added `problems` command

3. **scripts/VALIDATE_GAMEBOOK_CLI.md**
   - Status: UPDATE with new sections
   - New Feature: Problems command documentation

4. **validation/queries/raw/nbac_gamebook/README.md**
   - Status: UPDATE with new query
   - New Feature: Problem cases query documentation

### ⭐ New Files to Create (1)

5. **validation/queries/raw/nbac_gamebook/name_resolution_problem_cases.sql**
   - Status: CREATE new file
   - Purpose: Detailed problem case investigation

---

## 🚀 Quick Installation

### Step 1: Navigate to Project Directory

```bash
cd ~/code/nba-stats-scraper
```

---

### Step 2: Backup Existing Files

```bash
# Backup query file
cp validation/queries/raw/nbac_gamebook/season_completeness_check.sql \
   validation/queries/raw/nbac_gamebook/season_completeness_check.sql.bak

# Backup script
cp scripts/validate-gamebook scripts/validate-gamebook.bak
```

---

### Step 3: Copy Artifact Contents

#### File 1: season_completeness_check.sql (REPLACE)

```bash
cat > validation/queries/raw/nbac_gamebook/season_completeness_check.sql << 'EOF'
[Copy content from artifact: "season_completeness_check.sql (FIXED)"]
EOF
```

---

#### File 2: name_resolution_problem_cases.sql (CREATE NEW)

```bash
cat > validation/queries/raw/nbac_gamebook/name_resolution_problem_cases.sql << 'EOF'
[Copy content from artifact: "name_resolution_problem_cases.sql"]
EOF
```

---

#### File 3: validate-gamebook (REPLACE)

```bash
cat > scripts/validate-gamebook << 'EOF'
[Copy content from artifact: "validate-gamebook (COMPLETE)"]
EOF

# Make executable
chmod +x scripts/validate-gamebook
```

---

#### File 4: VALIDATE_GAMEBOOK_CLI.md (UPDATE)

```bash
# Option A: Replace entire file
cat > scripts/VALIDATE_GAMEBOOK_CLI.md << 'EOF'
[Copy updated content from artifact]
EOF

# Option B: Manual edit to add problems section
nano scripts/VALIDATE_GAMEBOOK_CLI.md
# Add problems command to tables and examples
```

---

#### File 5: README.md (UPDATE)

```bash
# Option A: Replace entire file
cat > validation/queries/raw/nbac_gamebook/README.md << 'EOF'
[Copy updated content from artifact]
EOF

# Option B: Manual edit
nano validation/queries/raw/nbac_gamebook/README.md
# Update query count from 7 to 8
# Add section 4 for name_resolution_problem_cases.sql
```

---

### Step 4: Verify Installation

```bash
# Test script is executable
./scripts/validate-gamebook help

# List all queries
./scripts/validate-gamebook list

# Should show:
#   1. season_completeness_check.sql          (alias: completeness)
#   2. find_missing_regular_season_games.sql  (alias: missing)
#   3. name_resolution_quality.sql            (alias: resolution)
#   4. name_resolution_problem_cases.sql      (alias: problems)  ← NEW
#   5. player_status_validation.sql           (alias: status)
#   6-8. Daily monitoring queries...
```

---

### Step 5: Test the Fixes

```bash
# Test the fixed completeness query
./scripts/validate-gamebook completeness

# Test the new problems command
./scripts/validate-gamebook problems

# Test resolution summary
./scripts/validate-gamebook resolution
```

---

## ✅ Expected Results

### After Installation

1. **completeness** query should run without errors ✅
2. **problems** command should be recognized ✅
3. **8 queries** should be listed (was 7 before) ✅

### Test Output

```bash
$ ./scripts/validate-gamebook list

Available Validation Queries

Historical Validation:
  1. season_completeness_check.sql          (alias: completeness)
  2. find_missing_regular_season_games.sql  (alias: missing)
  3. name_resolution_quality.sql            (alias: resolution)
  4. name_resolution_problem_cases.sql      (alias: problems)
  5. player_status_validation.sql           (alias: status)

Daily Monitoring:
  6. daily_check_yesterday.sql              (alias: yesterday)
  7. weekly_check_last_7_days.sql           (alias: week)
  8. realtime_scraper_check.sql             (alias: today)
```

---

## 🎯 What Was Fixed

### Issue 1: season_completeness_check.sql
**Error:** `Unrecognized name: is_playoffs at [121:3]`

**Root Cause:** Final SELECT referenced `is_playoffs` outside of scope

**Fix:** Added proper GROUP BY aggregation with SUM() for playoff flag checks

---

### Issue 2: problems command missing
**Error:** `Unknown command: problems`

**Root Cause:** Command handler not updated in script

**Fix:** Added `problems|issues|failures)` case statement

---

### Enhancement: New problem cases query
**Purpose:** Detailed investigation tool for resolution failures

**Use Case:** Export specific problem cases for manual review and pattern analysis

---

## 🔧 Troubleshooting

### Script Not Executable

```bash
chmod +x scripts/validate-gamebook
```

---

### "Query file not found"

**Check files exist:**
```bash
ls -la validation/queries/raw/nbac_gamebook/

# Should show 7 SQL files:
# - season_completeness_check.sql
# - find_missing_regular_season_games.sql
# - name_resolution_quality.sql
# - name_resolution_problem_cases.sql  ← NEW
# - player_status_validation.sql
# - daily_check_yesterday.sql
# - weekly_check_last_7_days.sql
# - realtime_scraper_check.sql
```

---

### SQL Errors When Running Queries

**Verify you copied the ENTIRE artifact contents:**
- Check file starts with `-- =====...` header
- Check file ends properly (no truncation)
- Verify no extra characters added during copy/paste

---

## 📋 File Checklist

Before considering installation complete:

- [ ] `season_completeness_check.sql` - REPLACED with fixed version
- [ ] `name_resolution_problem_cases.sql` - CREATED (new file)
- [ ] `validate-gamebook` - REPLACED with updated version
- [ ] `validate-gamebook` - Made executable with `chmod +x`
- [ ] `VALIDATE_GAMEBOOK_CLI.md` - UPDATED with problems section
- [ ] `README.md` - UPDATED to show 8 queries
- [ ] Tested: `./scripts/validate-gamebook list` shows 8 queries
- [ ] Tested: `./scripts/validate-gamebook completeness` runs without errors
- [ ] Tested: `./scripts/validate-gamebook problems` works

---

## 🎓 Next Steps

### After Installation

1. **Test with real data:**
   ```bash
   ./scripts/validate-gamebook yesterday
   ./scripts/validate-gamebook completeness
   ./scripts/validate-gamebook resolution
   ./scripts/validate-gamebook problems --csv
   ```

2. **Set up daily automation:**
   ```bash
   crontab -e
   # Add: 0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-gamebook yesterday
   ```

3. **Create config file** (optional - for Python validator)
   - `validation/configs/raw/nbac_gamebook.yaml`

4. **Create validator class** (optional - for Python integration)
   - `validation/validators/raw/nbac_gamebook_validator.py`

---

## 📞 Support

**If you encounter issues:**

1. Verify all files copied correctly (no truncation)
2. Check file permissions (`chmod +x scripts/validate-gamebook`)
3. Ensure you're in correct directory (`cd ~/code/nba-stats-scraper`)
4. Test queries directly with `bq query --use_legacy_sql=false < [file]`

---

**Installation Date:** October 12, 2025  
**Files Updated:** 5 (3 updates, 1 new, 1 optional)  
**Validation System:** Complete and Ready