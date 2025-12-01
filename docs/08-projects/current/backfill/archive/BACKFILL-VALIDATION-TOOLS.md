# Backfill Validation Tools

**Created:** 2025-11-30
**Purpose:** Tools for checking data availability before/after backfill execution

---

## Overview

Two validation scripts support the backfill process:

| Tool | When to Use | Purpose |
|------|-------------|---------|
| `preflight_check.py` | BEFORE backfill | Check what data exists, identify gaps |
| `verify_backfill_range.py` | AFTER backfill | Verify backfill completed correctly |

---

## 1. Pre-Flight Check

**Location:** `bin/backfill/preflight_check.py`

Checks data availability across all phases for a date range or single date.

### Usage

```bash
# Check date range (verbose shows per-date details)
PYTHONPATH=/home/naji/code/nba-stats-scraper python bin/backfill/preflight_check.py \
  --start-date 2021-10-19 --end-date 2021-11-01 --verbose

# Check single date
PYTHONPATH=/home/naji/code/nba-stats-scraper python bin/backfill/preflight_check.py \
  --date 2021-10-25 --verbose

# Check only specific phase (faster)
PYTHONPATH=/home/naji/code/nba-stats-scraper python bin/backfill/preflight_check.py \
  --start-date 2021-10-19 --end-date 2021-11-01 --phase 2
```

### Options

| Option | Description |
|--------|-------------|
| `--start-date` | Start of date range (YYYY-MM-DD) |
| `--end-date` | End of date range (YYYY-MM-DD) |
| `--date` | Single date (shortcut for start=end) |
| `--phase` | Check only specific phase: 1=GCS, 2=Raw, 3=Analytics, 4=Precompute |
| `--verbose`, `-v` | Show per-date record counts and missing dates |

### What It Checks

**Phase 1 (GCS Scraped Files):**
- nbac_team_boxscore
- nbac_gamebook_player_stats
- nbac_play_by_play
- bdl_standings
- odds_api_player_props
- bettingpros_player_props

**Phase 2 (Raw BigQuery):**
- nbac_team_boxscore
- nbac_gamebook_player_stats
- nbac_play_by_play
- bdl_player_boxscores
- bdl_standings
- odds_api_player_points_props
- bettingpros_player_props
- nbac_schedule

**Phase 3 (Analytics BigQuery):**
- player_game_summary
- team_defense_game_summary
- team_offense_game_summary
- upcoming_player_game_context
- upcoming_team_game_context

**Phase 4 (Precompute BigQuery):**
- team_defense_zone_analysis
- player_shot_zone_analysis
- player_composite_factors
- player_daily_cache

### Output Interpretation

```
✅ = 99%+ coverage (ready)
⚠️ = 80-99% coverage (may have gaps)
❌ = <80% coverage or errors (needs attention)
```

### Example Output

```
======================================================================
  PHASE 2: Raw Data (BigQuery)
======================================================================

  ✅ nbac_team_boxscore
     Dates: 14/14 (100.0%)
     Records: 388
     Per date (first 5):
        2021-10-19: 8 records
        2021-10-20: 42 records
        ...

  ❌ odds_api_player_points_props
     Dates: 0/14 (0.0%)
     Records: 0
     Missing: ['2021-10-19', '2021-10-20', ...]
```

---

## 2. Verification Check

**Location:** `bin/backfill/verify_backfill_range.py`

Verifies that backfill completed correctly, including bootstrap period handling.

### Usage

```bash
# Verify backfill for date range
PYTHONPATH=/home/naji/code/nba-stats-scraper python bin/backfill/verify_backfill_range.py \
  --start-date 2021-10-19 --end-date 2021-11-01 --verbose
```

### Options

| Option | Description |
|--------|-------------|
| `--start-date` | Start of date range (YYYY-MM-DD) |
| `--end-date` | End of date range (YYYY-MM-DD) |
| `--verbose`, `-v` | Show detailed output |

### What It Checks

1. **Expected game dates** - From schedule
2. **Phase 3 completeness** - All 5 tables should have all dates
3. **Phase 4 completeness** - Should have non-bootstrap dates only
4. **Bootstrap handling** - Verifies bootstrap dates are correctly skipped
5. **Processor run history** - Checks for failures
6. **Data quality spot check** - Reasonable averages

### Bootstrap Period Awareness

The verification script knows about bootstrap periods (first 7 days of each season):
- 2021-22: Oct 19-25
- 2022-23: Oct 18-24
- 2023-24: Oct 24-30
- 2024-25: Oct 22-28

Phase 4 tables are expected to be empty for bootstrap dates.

### Example Output

```
======================================================================
BACKFILL VERIFICATION: 2021-10-19 to 2021-11-01
======================================================================

1. EXPECTED GAME DATES
--------------------------------------------------
   Total game dates: 14
   Bootstrap dates (Phase 4 skips): 7
   Non-bootstrap dates: 7

2. PHASE 3 ANALYTICS COMPLETENESS
--------------------------------------------------
   ✅ player_game_summary: 14/14
   ✅ team_defense_game_summary: 14/14
   ...

3. PHASE 4 PRECOMPUTE COMPLETENESS
--------------------------------------------------
   Note: Bootstrap dates (7) should be skipped

   ✅ team_defense_zone_analysis: 7/7
   ✅ player_shot_zone_analysis: 7/7
   ...

======================================================================
✅ VERIFICATION PASSED - All checks successful!
======================================================================
```

---

## Workflow

### Before Backfill

```bash
# 1. Check current state
python bin/backfill/preflight_check.py --start-date X --end-date Y --verbose

# 2. Verify Phase 2 is ready (should be ~100%)
python bin/backfill/preflight_check.py --start-date X --end-date Y --phase 2

# 3. If Phase 2 ready, proceed with Phase 3 backfill
```

### During Backfill

```bash
# Check progress on Phase 3
python bin/backfill/preflight_check.py --start-date X --end-date Y --phase 3
```

### After Backfill

```bash
# Full verification
python bin/backfill/verify_backfill_range.py --start-date X --end-date Y --verbose
```

---

## Recommended Test Run

Before full 4-year backfill, test with first 14 days of 2021-22 season:

```bash
# Date range: 2021-10-19 to 2021-11-01
# Bootstrap: Oct 19-25 (7 days) - Phase 4 skips
# Full processing: Oct 26 - Nov 1 (7 days) - Phase 4 processes

# 1. Pre-flight
python bin/backfill/preflight_check.py --start-date 2021-10-19 --end-date 2021-11-01 --verbose

# 2. Run Phase 3 backfill (see BACKFILL-RUNBOOK.md)

# 3. Mid-check
python bin/backfill/preflight_check.py --start-date 2021-10-19 --end-date 2021-11-01 --phase 3

# 4. Run Phase 4 backfill (see BACKFILL-RUNBOOK.md)

# 5. Final verification
python bin/backfill/verify_backfill_range.py --start-date 2021-10-19 --end-date 2021-11-01 --verbose
```

**Expected results:**
- Phase 3: 14/14 dates for all 5 tables
- Phase 4: 7/7 dates (bootstrap correctly skipped)

---

## Related Documents

| Document | Purpose |
|----------|---------|
| `BACKFILL-RUNBOOK.md` | Step-by-step backfill execution |
| `BACKFILL-MASTER-PLAN.md` | Strategy and troubleshooting |
| `BACKFILL-GAP-ANALYSIS.md` | SQL queries for detailed analysis |
| `BACKFILL-MONITOR-USAGE.md` | Real-time progress monitoring |

---

**Document Version:** 1.0
**Last Updated:** 2025-11-30
