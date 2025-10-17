# Complete Odds API Props Backfill Workflow

<!--
File: docs/backfill/COMPLETE_ODDS_API_PROPS_BACKFILL_WORKFLOW.md
-->

## 🎯 Overview

This guide walks you through the complete process of identifying, backfilling, and validating missing Odds API props data using your existing validation infrastructure.

---

## 📋 Prerequisites

1. ✅ **Fix Applied:** Team name mapping corrected in scraper
   ```python
   'LAC': 'Los Angeles Clippers',  # ✅ Fixed in odds_api_props_scraper_backfill.py
   ```

2. ✅ **Environment Ready:**
   ```bash
   source .venv/bin/activate
   gcloud auth application-default login
   ```

3. ✅ **Scripts Executable:**
   ```bash
   chmod +x scripts/validate-odds-props
   chmod +x backfill_missing_props.sh
   ```

---

## 🔍 Phase 1: Identify Missing Data

### Step 1.1: Run Comprehensive Gap Analysis

```bash
# See the big picture - coverage across all seasons
./scripts/validate-odds-props gaps
```

**What to Look For:**
- Overall coverage % by season
- Missing game counts
- Date ranges with gaps

**Expected Output:**
```
Season    Game Type        Scheduled  With Props  Missing  Coverage%
2024-25   Playoffs              89        82         7      92.1%
2023-24   Playoffs              87        77        10      88.5%
2023-24   Regular Season     1,236       868       368      70.2%
2022-23   Playoffs              90        31        59      34.4%
```

### Step 1.2: Identify Specific Missing Playoff Games

```bash
# Get the exact missing playoff games
./scripts/validate-odds-props missing --csv
```

**What This Does:**
- Finds games in schedule but not in props table
- Exports to CSV: `validation_props_find_missing_games_TIMESTAMP.csv`
- Shows specific dates and matchups

**Expected Critical Findings:**
- 🔴 PHX: 4 missing playoff games (2024)
- 🔴 LAC: 5-6 missing playoff games (2024)
- 🔴 DEN: 7 missing playoff games (2025)

### Step 1.3: Verify Playoff Completeness by Team

```bash
# See which teams are missing playoff data
./scripts/validate-odds-props playoffs
```

**Expected Output:**
```
Team   Expected  Actual  Missing  Avg Players  Status
PHX         4       0       4          0       ❌ All Missing
LAC         6       1       5         14       ⚠️ Incomplete
DAL        22      18       4         15       ⚠️ Incomplete
DEN         7       0       7          0       ❌ All Missing
```

---

## 🛠️ Phase 2: Run the Backfill

### Step 2.1: Test with Dry Run

```bash
# See what would be processed without actually running
./backfill_missing_props.sh 2023-24 --dry-run
```

**What This Shows:**
- Dates that will be scraped
- Expected API calls
- File locations

**Review the Output:**
- Verify dates match your missing games
- Check no duplicate dates
- Confirm dates are after May 3, 2023 (PROPS_START_DATE)

### Step 2.2: Backfill High Priority (2023-24 Playoffs)

```bash
# Run Phase 1B - backfill 2023-24 PHX and LAC playoff games
./backfill_missing_props.sh 2023-24
```

**What Happens:**
1. **Scraper phase:** Calls Odds API for historical data
   - Creates event files in GCS
   - Creates props files in GCS
   - ~10-15 minutes

2. **Processor phase:** Loads files to BigQuery
   - Reads files from GCS
   - Transforms and validates
   - Inserts into `nba_raw.odds_api_player_points_props`
   - ~5-10 minutes

**Monitor for Errors:**
```bash
# Watch for these success indicators:
✅ Step 1: Scraping props from Odds API...
   Phase 1B: 2023-24 Playoffs
   Series 1: PHX vs MIN (4 games)
   Series 2: LAC vs DAL (6 games)

✅ Step 2: Processing scraped files to BigQuery...
   Processing 2024-04-20 (X files)
   Batch complete: X/X successful
```

### Step 2.3: Backfill Current Season (2024-25) - Optional

```bash
# Run Phase 1A - backfill 2024-25 DEN vs LAC series
./backfill_missing_props.sh 2024-25
```

**Only Run If:**
- Current season playoffs have concluded
- Missing data confirmed in validation queries
- High priority for recent analysis

### Step 2.4: Manual Backfill (Maximum Control)

If you prefer step-by-step control:

```bash
# Step 1: Scrape specific dates
./bin/run_backfill.sh scrapers/odds_api_props \
  --dates=2024-04-20,2024-04-21,2024-04-23

# Step 2: Verify files created in GCS
gsutil ls gs://nba-scraped-data/odds-api/player-props-history/2024-04-20/
gsutil ls gs://nba-scraped-data/odds-api/player-props-history/2024-04-21/
gsutil ls gs://nba-scraped-data/odds-api/player-props-history/2024-04-23/

# Step 3: Process the files to BigQuery
./bin/run_backfill.sh raw/odds_api_props \
  --dates=2024-04-20,2024-04-21,2024-04-23
```

---

## ✅ Phase 3: Validate Results

### Step 3.1: Quick Team Check

```bash
# Verify critical teams now have data
bq query --use_legacy_sql=false '
SELECT 
  game_date,
  CONCAT(away_team_abbr, " @ ", home_team_abbr) as matchup,
  COUNT(DISTINCT player_name) as players,
  COUNT(DISTINCT bookmaker) as bookmakers,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date BETWEEN "2024-04-20" AND "2024-05-03"
  AND (home_team_abbr IN ("PHX","LAC","DAL") 
   OR away_team_abbr IN ("PHX","LAC","DAL"))
GROUP BY game_date, matchup
ORDER BY game_date'
```

**Success Criteria:**
- ✅ PHX games: 4 rows with 12-15 players each
- ✅ LAC games: 6 rows with 12-15 players each
- ✅ Each game has 2+ bookmakers
- ✅ Total records = players × bookmakers × props

### Step 3.2: Re-run Playoff Verification

```bash
# Should now show improved coverage
./scripts/validate-odds-props playoffs
```

**Before Backfill:**
```
Team   Expected  Actual  Missing  Status
PHX         4       0       4     ❌ All Missing
LAC         6       1       5     ⚠️ Incomplete
```

**After Backfill:**
```
Team   Expected  Actual  Missing  Avg Players  Status
PHX         4       4       0         14       ✅ Complete
LAC         6       6       0         15       ✅ Complete
DAL        22      22       0         15       ✅ Complete
```

### Step 3.3: Run Comprehensive Validation

```bash
# Full validation suite
bq query --use_legacy_sql=false < validate_backfill_results.sql > backfill_results_$(date +%Y%m%d).txt
```

**What This Checks:**
1. Coverage by season (should be 100% for 2023-24 playoffs)
2. Critical teams (PHX, LAC, DAL) - all complete
3. Specific backfilled dates - quality scores
4. Player coverage quality - no low counts
5. No duplicate records created
6. Before/after comparison

### Step 3.4: Verify Files in GCS

```bash
# Spot check that files exist and have content
gsutil cat gs://nba-scraped-data/odds-api/player-props-history/2024-04-21/7aa3ab404262a55d4c5473372324c52a-LACDAL/20*.json | head -100

# Verify multiple snapshots exist
gsutil ls -l gs://nba-scraped-data/odds-api/player-props-history/2024-04-21/*/
```

**Look For:**
- Multiple snapshot files per game (snap-XXXX.json)
- JSON contains player props with over/under prices
- Team names match: "Los Angeles Clippers" not "LA Clippers"

### Step 3.5: Check for Data Quality Issues

```bash
# Find any games with low player counts
./scripts/validate-odds-props low-coverage
```

**Acceptable Low Coverage:**
- Regular season: 6-10 players (some games)
- Playoffs: Should always have 12+ players
- If playoff games show <10 players → investigate

---

## 📊 Phase 4: Monitor Going Forward

### Daily Monitoring (Add to Cron)

```bash
# Run every morning at 9 AM
0 9 * * * /path/to/scripts/validate-odds-props yesterday
```

**Alert Conditions:**
- Status: ❌ CRITICAL (no data for completed games)
- Status: ⚠️ WARNING (missing games or low counts)
- Any email with "CRITICAL" → immediate investigation

### Weekly Review

```bash
# Monday morning routine
./scripts/validate-odds-props week          # Coverage trends
./scripts/validate-odds-props low-coverage  # Quality check
```

### Monthly Completeness Check

```bash
# First Monday of each month
./scripts/validate-odds-props completeness --csv
./scripts/validate-odds-props gaps
```

---

## 🚨 Troubleshooting

### Issue: "No event ID found for LAC@DAL"

**Cause:** Team name fix not applied or not deployed

**Solution:**
```bash
# 1. Verify fix in code
grep "Los Angeles Clippers" backfill_jobs/scrapers/odds_api_props/odds_api_props_scraper_backfill.py

# Should show:
'LAC': 'Los Angeles Clippers',  # ✅ Correct

# 2. If wrong, fix and re-run backfill
```

### Issue: Scraper runs but no files created

**Cause:** Odds API returns no events for date

**Solution:**
```bash
# 1. Check events file exists
gsutil ls gs://nba-scraped-data/odds-api/events-history/2024-04-21/

# 2. Check events content
gsutil cat gs://nba-scraped-data/odds-api/events-history/2024-04-21/*.json

# 3. Verify date is after May 3, 2023
# 4. Check Odds API subscription status
```

### Issue: Files exist but processor shows validation errors

**Cause:** File format unexpected or corrupt

**Solution:**
```bash
# 1. Download and inspect file
gsutil cat gs://nba-scraped-data/odds-api/player-props-history/YYYY-MM-DD/*/snap-*.json | jq .

# 2. Check for required fields
jq '.data.bookmakers[].markets[] | select(.key=="player_points")' file.json

# 3. If format is correct, check processor validation logic
# 4. Re-scrape the date if file is corrupt
```

### Issue: Low player counts in validation

**Cause:** Odds API had limited coverage for that game

**Solution:**
```bash
# Acceptable for:
# - Games >1 year old (historical API limits)
# - Regular season games (less betting interest)
# - Eliminated teams late in season

# Not acceptable for:
# - Recent playoff games (<6 months old)
# - Should have 12+ players

# Action: Check multiple bookmakers were queried
```

### Issue: Duplicate records after backfill

**Cause:** Processor ran multiple times on same files

**Solution:**
```sql
-- Find duplicates
SELECT 
  game_date, player_name, bookmaker, snapshot_timestamp,
  COUNT(*) as count
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date BETWEEN '2024-04-20' AND '2024-05-03'
GROUP BY 1,2,3,4
HAVING COUNT(*) > 1;

-- Delete duplicates (keep one copy)
-- Use DML with QUALIFY to remove duplicates
```

---

## 📈 Expected Results Summary

### After Phase 1A (2024-25 Playoffs)
```
Coverage: 92.1% → 100.0%
Games Added: 7 (DEN vs LAC series)
Players per Game: 15-18
Bookmakers per Game: 2-3
Cost: ~$0.14-0.70
Time: 15-20 minutes
```

### After Phase 1B (2023-24 Playoffs)
```
Coverage: 88.5% → 100.0%
Games Added: 10 (PHX-MIN + LAC-DAL)
Players per Game: 12-16
Bookmakers per Game: 2-3
Cost: ~$0.20-1.00
Time: 20-30 minutes
```

### After Phase 2 (2022-23 Playoffs - Optional)
```
Coverage: 34.4% → 98%+
Games Added: ~16 (Play-in + Semifinals)
Players per Game: 10-14
Bookmakers per Game: 1-2 (older data)
Cost: ~$0.34-2.43
Time: 30-45 minutes
```

---

## 📝 Checklist

### Pre-Backfill
- [ ] Team name fix verified (`'LAC': 'Los Angeles Clippers'`)
- [ ] Ran `./scripts/validate-odds-props gaps` (baseline)
- [ ] Ran `./scripts/validate-odds-props playoffs` (specific targets)
- [ ] Ran `./scripts/validate-odds-props missing --csv` (export list)
- [ ] Virtual environment activated
- [ ] GCS permissions verified

### During Backfill
- [ ] Dry run completed successfully
- [ ] Scraper phase: files created in GCS
- [ ] Processor phase: no validation errors
- [ ] Logs reviewed for warnings

### Post-Backfill
- [ ] Quick team check shows data
- [ ] `./scripts/validate-odds-props playoffs` shows complete
- [ ] `validate_backfill_results.sql` shows improvement
- [ ] No duplicate records found
- [ ] Player counts reasonable (12+ for playoffs)
- [ ] Saved validation results to file
- [ ] Updated documentation

---

## 🔗 Quick Command Reference

```bash
# === IDENTIFY ===
./scripts/validate-odds-props gaps              # Overview
./scripts/validate-odds-props playoffs          # Team completeness
./scripts/validate-odds-props missing --csv     # Specific games

# === BACKFILL ===
./backfill_missing_props.sh 2023-24 --dry-run  # Test
./backfill_missing_props.sh 2023-24            # Execute

# === VALIDATE ===
./scripts/validate-odds-props playoffs          # Quick check
bq query --use_legacy_sql=false < validate_backfill_results.sql

# === MONITOR ===
./scripts/validate-odds-props yesterday         # Daily
./scripts/validate-odds-props week              # Weekly
./scripts/validate-odds-props completeness      # Monthly
```

---

## 📞 Support Resources

- **Validation Queries:** `validation/queries/raw/odds_api_props/`
- **CLI Tool:** `scripts/validate-odds-props --help`
- **Backfill Scripts:** `backfill_missing_props.sh`
- **Scraper Job:** `backfill_jobs/scrapers/odds_api_props/`
- **Processor Job:** `backfill_jobs/raw/odds_api_props/`
- **Documentation:** This file + `BACKFILL_WORKFLOW.md`

---

**Last Updated:** October 2025  
**Status:** Ready for execution  
**Estimated Total Time:** 1-2 hours for high-priority backfill  
**Estimated Total Cost:** $0.50-2.00
