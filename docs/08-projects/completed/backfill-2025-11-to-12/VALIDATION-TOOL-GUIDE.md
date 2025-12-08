# Backfill Validation & Planning Tool

**Tool:** `bin/backfill/validate_and_plan.py`  
**Purpose:** Check what data exists and get exact commands for what needs to run  
**Use Before:** Every backfill operation (single date, range, or full backfill)

---

## Quick Start

```bash
# Single date - see what's there
python3 bin/backfill/validate_and_plan.py 2024-01-15

# Date range - see status
python3 bin/backfill/validate_and_plan.py 2024-01-15 2024-01-28

# Date range with execution plan - get commands to run
python3 bin/backfill/validate_and_plan.py 2024-01-15 2024-01-28 --plan
```

---

## What It Checks

### Phase 2: Raw Data (Scrapers)
Shows what scraper data exists AND checks run history:
- **CRITICAL:** Player boxscores, team boxscores, player props
- **IMPORTANT:** Play-by-play (for shot zones)
- **FALLBACK:** BDL player boxscores

**Tells you:**
- If scrapers **never ran** (need to run them)
- If scrapers **ran but failed** (need to investigate/retry)
- If scrapers **ran but found no data** (use fallback or accept gap)

### Phase 3: Analytics
Shows which analytics tables have data:
- player_game_summary
- team_defense_game_summary
- team_offense_game_summary
- upcoming_player_game_context
- upcoming_team_game_context

**Tells you:** Which Phase 3 backfill jobs to run

### Phase 4: Precompute
Shows which precompute tables have data:
- team_defense_zone_analysis
- player_shot_zone_analysis
- player_composite_factors
- player_daily_cache

**Tells you:** Which Phase 4 backfill jobs to run (and in what order)

---

## Output Legend

**Phase 2/3/4 Status:**
- ✓ = Complete (100%)
- ⚠ = Mostly complete (90-99%)
- △ = Partial (1-89%)
- ○ = Empty (0%)
- ✗ = Error or missing

**Phase Summary:**
- `✓ Ready` = All critical data present
- `✓ Complete` = All tables at 100%
- `△ Need backfill` = Some data exists, need to complete
- `○ Need backfill` = No data, need to run
- `✗ Need scrapers` = Phase 2 data missing

---

## Usage Examples

### Example 1: Check Single Date Status
```bash
python3 bin/backfill/validate_and_plan.py 2024-01-15
```

**Use case:** Quick check if a specific date has been processed

**Output:** Shows status for each phase (no execution plan)

### Example 2: Check Date Range with Execution Plan
```bash
python3 bin/backfill/validate_and_plan.py 2024-01-15 2024-01-28 --plan
```

**Use case:** Before starting a backfill (recommended!)

**Output:** 
- Status for all phases
- Exact commands to run for missing data
- Correct execution order (Phase 3 parallel, Phase 4 sequential)

### Example 3: Validate After Backfill
```bash
# After Phase 3 backfill
python3 bin/backfill/validate_and_plan.py 2024-01-15 2024-01-28

# Should show Phase 3 complete, Phase 4 empty
```

**Use case:** Verify backfill completed successfully

### Example 4: Full Backfill Planning
```bash
# Check first 14 days of season
python3 bin/backfill/validate_and_plan.py 2021-10-15 2021-10-28 --plan

# Check specific season
python3 bin/backfill/validate_and_plan.py 2023-10-24 2024-04-14 --plan
```

**Use case:** Plan large-scale backfill operations

---

## Interpreting Results

### Scenario 1: Ready for Phase 3
```
Phase 2 (Raw):       ✓ Ready
Phase 3 (Analytics): ○ Need backfill
Phase 4 (Precompute): ○ Need backfill

Next Action: Run Phase 3 backfill
```

**What to do:** Copy/paste Phase 3 commands from execution plan

### Scenario 2: Ready for Phase 4
```
Phase 2 (Raw):       ✓ Ready
Phase 3 (Analytics): ✓ Complete
Phase 4 (Precompute): ○ Need backfill

Next Action: Run Phase 4 backfill (sequential)
```

**What to do:** Copy/paste Phase 4 commands, run ONE AT A TIME

### Scenario 3: Missing Scrapers
```
Phase 2 (Raw):       ✗ Need scrapers
Phase 3 (Analytics): ○ Need backfill
Phase 4 (Precompute): ○ Need backfill

Next Action: Run scrapers first, then Phase 3
```

**What to do:** Run scrapers for the date range first

### Scenario 4: All Complete
```
Phase 2 (Raw):       ✓ Ready
Phase 3 (Analytics): ✓ Complete
Phase 4 (Precompute): ✓ Complete

Status: ✓ COMPLETE - All data exists
```

**What to do:** Nothing! Data already exists.

---

## Execution Plan Output

With `--plan` flag, the tool gives you copy/paste commands:

```bash
STEP 2: Run Phase 3 Analytics Backfill
──────────────────────────────────────────────
# Can run all 5 in parallel

# player_game_summary - missing 14 dates
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2024-01-15 --end-date 2024-01-28

# (repeat for other 4 processors)

STEP 3: Run Phase 4 Precompute Backfill (SEQUENTIAL!)
──────────────────────────────────────────────
# MUST run one at a time, wait for each to complete

# 1. team_defense_zone_analysis - missing 14 dates
PYTHONPATH=$(pwd) python3 backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2024-01-15 --end-date 2024-01-28
# Wait for completion before proceeding

# (repeat for other processors in order)
```

---

## Bootstrap Dates

The tool automatically accounts for bootstrap periods (first 7 days of each season):

**2021-22:** Oct 15-21, 2021  
**2022-23:** Oct 18-24, 2022  
**2023-24:** Oct 24-30, 2023  
**2024-25:** Oct 22-28, 2024  

**Phase 4 skips these dates** - this is intentional and expected.

Example output:
```
Phase 4: 7/14 complete
Note: 7 bootstrap dates (Phase 4 skips these)
```

This means 7 dates were skipped (bootstrap) + 7 dates complete = 14 total accounted for.

---

## Recommended Workflow

### Before Any Backfill:

```bash
# 1. Validate what exists
python3 bin/backfill/validate_and_plan.py START END --plan

# 2. Copy/paste suggested commands

# 3. Run Phase 3 (parallel OK)

# 4. Validate Phase 3 complete
python3 bin/backfill/validate_and_plan.py START END

# 5. Run Phase 4 (sequential only!)

# 6. Validate Phase 4 complete  
python3 bin/backfill/validate_and_plan.py START END
```

### During Large Backfills:

```bash
# Check progress periodically
python3 bin/backfill/validate_and_plan.py 2021-10-15 2024-11-29

# If issues found, narrow down to specific date
python3 bin/backfill/validate_and_plan.py 2023-11-15 --plan
```

---

## Integration with Other Tools

### Use with Progress Monitor
```bash
# Terminal 1: Run backfill
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/...

# Terminal 2: Monitor progress
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --continuous

# Terminal 3: Validate when complete
python3 bin/backfill/validate_and_plan.py START END
```

### Use with Pre-Flight Verification
```bash
# Before starting
./bin/backfill/preflight_verification.sh --quick

# Validate specific range
python3 bin/backfill/validate_and_plan.py START END --plan

# Execute backfill
# (run suggested commands)

# Validate completion
python3 bin/backfill/validate_and_plan.py START END
```

---

## Troubleshooting

### "Table not found" errors
**Cause:** Dataset or table doesn't exist  
**Fix:** Check that processors have been deployed

### Unexpected percentages
**Cause:** Real-time processing may have added some dates  
**Action:** This is OK - just backfill the missing dates

### Phase 4 shows less than expected
**Cause:** Bootstrap dates are being skipped (intentional)  
**Check:** Look for "Note: X bootstrap dates" message

### All zeros despite running backfill
**Cause:** Backfill may have failed silently  
**Action:** Check Cloud Run logs for the specific job

---

## Technical Details

**Project:** nba-props-platform  
**Datasets Checked:**
- nba_raw (Phase 2)
- nba_analytics (Phase 3)
- nba_precompute (Phase 4)

**Date Fields:**
- Most tables: `game_date`
- player_shot_zone_analysis: `analysis_date`
- team_defense_zone_analysis: `analysis_date`
- player_daily_cache: `cache_date`

**Dependencies:** google-cloud-bigquery (already installed)

---

## See Also

- [00-START-HERE.md](./00-START-HERE.md) - Main backfill guide
- [BACKFILL-RUNBOOK.md](./BACKFILL-RUNBOOK.md) - Step-by-step execution
- [BACKFILL-MONITOR-USAGE.md](./BACKFILL-MONITOR-USAGE.md) - Progress monitoring
- [TEST-RUN-EXECUTION-PLAN.md](./TEST-RUN-EXECUTION-PLAN.md) - 14-day test plan
