# Odds API Props - Complete Backfill Workflow

<!--
File: docs/backfill/ODDS_API_PROPS_BACKFILL_WORKFLOW.md
-->

## 🎯 Quick Start

After fixing the LA Clippers team name bug, follow this workflow to backfill missing playoff data.

---

## Step 1: Identify Missing Data

Run the identification query to see exactly what's missing:

```bash
bq query --use_legacy_sql=false < identify_missing_playoff_games.sql
```

**Expected Output:**
- List of missing games by season and team
- Comma-separated date strings for backfill scripts

**Key Teams to Check:**
- ✅ **PHX** - Should show 4 missing games (2024 playoffs)
- ✅ **LAC** - Should show 5 missing games (2024 playoffs)  
- ✅ **DEN** - Should show 7 missing games (2025 playoffs)

---

## Step 2: Run the Backfill Script

### Option A: Backfill Everything (Recommended)

```bash
# Make script executable
chmod +x backfill_missing_props.sh

# Dry run first to verify
./backfill_missing_props.sh all --dry-run

# Run the backfill
./backfill_missing_props.sh all
```

### Option B: Backfill Specific Phases

```bash
# Just 2024-25 playoffs (7 games)
./backfill_missing_props.sh 2024-25

# Just 2023-24 playoffs (10 games)
./backfill_missing_props.sh 2023-24

# Test 2022-23 (older data, may not be available)
./backfill_missing_props.sh 2022-23 --dry-run
```

### Option C: Manual Commands (Maximum Control)

```bash
# Phase 1A: 2024-25 DEN vs LAC
./bin/run_backfill.sh scrapers/odds_api_props \
  --dates=2025-04-19,2025-04-21,2025-04-24,2025-04-26,2025-04-29,2025-05-01,2025-05-03

./bin/run_backfill.sh raw/odds_api_props \
  --dates=2025-04-19,2025-04-21,2025-04-24,2025-04-26,2025-04-29,2025-05-01,2025-05-03

# Phase 1B: 2023-24 PHX-MIN and LAC-DAL
./bin/run_backfill.sh scrapers/odds_api_props \
  --dates=2024-04-20,2024-04-21,2024-04-23,2024-04-26,2024-04-28,2024-05-01,2024-05-03

./bin/run_backfill.sh raw/odds_api_props \
  --dates=2024-04-20,2024-04-21,2024-04-23,2024-04-26,2024-04-28,2024-05-01,2024-05-03
```

---

## Step 3: Validate Results

### Quick Check: Verify Critical Teams

```bash
bq query --use_legacy_sql=false '
SELECT 
  game_date,
  home_team_abbr,
  away_team_abbr,
  COUNT(DISTINCT player_name) as players,
  COUNT(DISTINCT bookmaker) as bookmakers
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE (home_team_abbr IN ("PHX","LAC","DEN","DAL") 
   OR away_team_abbr IN ("PHX","LAC","DEN","DAL"))
  AND game_date >= "2024-04-20"
GROUP BY game_date, home_team_abbr, away_team_abbr
ORDER BY game_date'
```

**Expected Results:**
- **PHX games:** 4 rows with 12-15 players each
- **LAC games:** 6 rows with 12-15 players each
- **DEN games:** 7 rows (if 2025 season processed)

### Comprehensive Validation

```bash
# Run full validation suite
bq query --use_legacy_sql=false < validate_backfill_results.sql
```

**What to Look For:**
- ✅ **Coverage %** should be near 100% for 2023-24 and 2024-25 playoffs
- ✅ **Avg players** should be 12+ for playoff games
- ✅ **No duplicate records** found
- ✅ **PHX, LAC, DAL** show "Complete" status

### Verify Files in GCS

```bash
# Check that props files were created
gsutil ls gs://nba-scraped-data/odds-api/player-props-history/2024-04-20/
gsutil ls gs://nba-scraped-data/odds-api/player-props-history/2024-04-21/
gsutil ls gs://nba-scraped-data/odds-api/player-props-history/2025-04-19/

# Verify file contents (sample one)
gsutil cat gs://nba-scraped-data/odds-api/player-props-history/2024-04-21/*/snap-*.json | head -50
```

---

## Step 4: Update Documentation

After successful backfill:

1. **Update coverage stats** in your backfill plan document
2. **Mark phases as complete** ✅
3. **Document any API limitations** encountered
4. **Save validation results** for future reference

```bash
# Save validation results
bq query --use_legacy_sql=false < validate_backfill_results.sql > backfill_validation_$(date +%Y%m%d).txt
```

---

## 🚨 Troubleshooting

### Issue: "No event ID found for LAC@DAL"

**Cause:** Team name mismatch not fixed yet

**Solution:** Verify the fix in `odds_api_props_scraper_backfill.py`:
```python
'LAC': 'Los Angeles Clippers',  # ✅ Must be full name
```

### Issue: "No files found to process"

**Cause:** Scraper phase didn't create files

**Solution:**
1. Check scraper logs for API errors
2. Verify dates are after May 3, 2023 (PROPS_START_DATE)
3. Check Odds API subscription status

### Issue: "Validation errors for file"

**Cause:** Scraped file has unexpected format

**Solution:**
1. Check file contents: `gsutil cat gs://path/to/file.json`
2. Verify event_id matches between events and props files
3. Check processor validation logic

### Issue: Low player counts (<8 players)

**Cause:** Odds API had limited coverage for that game

**Solution:**
- This is expected for some older games
- Check multiple bookmakers were queried
- Consider acceptable for games >1 year old

---

## 📊 Expected Results Summary

### After Phase 1A (2024-25 Playoffs)
- **Coverage:** 99.7% → 100%
- **Games added:** 7 DEN vs LAC games
- **Players per game:** 15-18 (playoff games have more props)

### After Phase 1B (2023-24 Playoffs)
- **Coverage:** 99.5% → 100%
- **Games added:** 10 games (4 PHX-MIN + 6 LAC-DAL)
- **Players per game:** 12-16

### After Phase 2 (2022-23 Playoffs - Optional)
- **Coverage:** 93.1% → 98%+
- **Games added:** ~16 games (Play-in + Semifinals)
- **Players per game:** 10-14 (older data may have less)

---

## 💰 Cost Estimate

**Odds API Historical Requests:**
- Phase 1A: ~$0.14-0.70 (7 dates)
- Phase 1B: ~$0.12-0.60 (6 unique dates)
- Phase 2: ~$0.22-1.38 (11 dates)

**Total: $0.48-2.68** for high-priority backfill

---

## ⏱️ Time Estimate

**Per Phase:**
- Dry run: 2-5 minutes
- Scraper execution: 5-15 minutes
- Processor execution: 5-10 minutes
- Validation: 2-5 minutes

**Total: 20-45 minutes** for high-priority backfill (Phases 1A + 1B)

---

## 📝 Checklist

### Pre-Backfill
- [ ] Fixed team name mapping in scraper (`'LAC': 'Los Angeles Clippers'`)
- [ ] Ran identification queries to confirm missing data
- [ ] Checked Odds API subscription status
- [ ] Verified GCS bucket permissions
- [ ] Activated virtual environment (`source .venv/bin/activate`)

### During Backfill
- [ ] Dry run completed successfully
- [ ] Scraper phase executed without errors
- [ ] Verified files created in GCS
- [ ] Processor phase executed without errors
- [ ] No validation errors in logs

### Post-Backfill
- [ ] Ran validation queries
- [ ] Verified PHX, LAC, DEN/DAL games are complete
- [ ] Checked no duplicate records
- [ ] Player counts are reasonable (12+ for playoffs)
- [ ] Saved validation results
- [ ] Updated documentation

---

## 🔗 Related Files

- **Identification Query:** `identify_missing_playoff_games.sql`
- **Backfill Script:** `backfill_missing_props.sh`
- **Validation Query:** `validate_backfill_results.sql`
- **Scraper Job:** `backfill_jobs/scrapers/odds_api_props/`
- **Processor Job:** `backfill_jobs/raw/odds_api_props/`
- **Processor Code:** `data_processors/raw/oddsapi/odds_api_props_processor.py`

---

## 📞 Quick Commands Reference

```bash
# 1. Identify missing data
bq query --use_legacy_sql=false < identify_missing_playoff_games.sql

# 2. Run backfill (all phases)
./backfill_missing_props.sh all

# 3. Validate results
bq query --use_legacy_sql=false < validate_backfill_results.sql

# 4. Quick team check
bq query --use_legacy_sql=false \
  'SELECT game_date, home_team_abbr, away_team_abbr, COUNT(DISTINCT player_name) as players
   FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
   WHERE (home_team_abbr IN ("PHX","LAC") OR away_team_abbr IN ("PHX","LAC"))
     AND game_date >= "2024-04-20"
   GROUP BY 1,2,3 ORDER BY 1'

# 5. Check GCS files
gsutil ls gs://nba-scraped-data/odds-api/player-props-history/2024-04-21/
```

---

**Last Updated:** October 2025  
**Status:** Ready for execution after team name fix
