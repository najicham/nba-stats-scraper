# Phase 4 Precompute Backfill Jobs

**Created:** 2025-11-30
**Last Updated:** 2025-11-30
**Purpose:** Documentation for Phase 4 backfill jobs and backfill mode pattern

---

## Overview

Phase 4 (Precompute) processors have backfill jobs for historical data processing. These jobs:
- Process data day-by-day to avoid BigQuery size limits
- Use `backfill_mode=True` to disable defensive checks
- Skip bootstrap periods (first 7 days of each season, dynamically from schedule)
- Support progress persistence with checkpoint files (auto-resume on restart)
- Do NOT trigger downstream processors (Phase 5)

---

## Backfill Jobs Location

All Phase 4 backfill jobs are in `backfill_jobs/precompute/`:

```
backfill_jobs/precompute/
├── team_defense_zone_analysis/
│   └── team_defense_zone_analysis_precompute_backfill.py
├── player_shot_zone_analysis/
│   └── player_shot_zone_analysis_precompute_backfill.py
├── player_composite_factors/
│   └── player_composite_factors_precompute_backfill.py
├── player_daily_cache/
│   └── player_daily_cache_precompute_backfill.py
└── ml_feature_store/
    └── ml_feature_store_precompute_backfill.py
```

---

## Execution Order (CRITICAL)

Phase 4 processors have inter-dependencies. **Run in this order:**

```
1. team_defense_zone_analysis   (reads Phase 3 only)
2. player_shot_zone_analysis    (reads Phase 3 only)
   ↑ These can run in PARALLEL

3. player_composite_factors     (reads #1, #2, Phase 3)
4. player_daily_cache           (reads #1, #2, #3, Phase 3)
5. ml_feature_store             (reads #1, #2, #3, #4)
   ↑ These must run SEQUENTIALLY
```

### Automated Orchestration

Use the orchestration script to run all processors in the correct order:

```bash
# Full 4-year backfill with parallelization
./bin/backfill/run_phase4_backfill.sh --start-date 2021-10-19 --end-date 2025-06-22

# Dry run to check readiness
./bin/backfill/run_phase4_backfill.sh --start-date 2024-01-01 --end-date 2024-03-31 --dry-run

# Resume from specific processor (if #1 and #2 already done)
./bin/backfill/run_phase4_backfill.sh --start-date 2024-01-01 --end-date 2024-03-31 --start-from 3
```

---

## Pre-Flight Check: Verify Phase 3 Readiness

Before running Phase 4, verify Phase 3 data is complete:

```bash
# Check if Phase 3 is ready for the date range
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 --end-date 2025-06-22

# Verbose output with missing dates
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 --end-date 2025-06-22 --verbose
```

The script checks all 5 Phase 3 tables and reports coverage percentages.

---

## Progress Persistence (Checkpoints)

All backfill jobs support **automatic checkpoint/resume**:

### How It Works

- Checkpoints saved to `/tmp/backfill_checkpoints/`
- Each job creates a unique checkpoint file based on date range
- Progress saved after each successful/failed/skipped date
- On restart, automatically resumes from last successful date

### CLI Flags

```bash
# Check checkpoint status
python backfill_jobs/precompute/.../..._precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22 --status

# Force restart (ignore checkpoint)
python backfill_jobs/precompute/.../..._precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22 --no-resume
```

### Checkpoint File Format

```json
{
  "job_name": "team_defense_zone_analysis",
  "start_date": "2021-10-19",
  "end_date": "2025-06-22",
  "last_successful_date": "2024-03-15",
  "successful_dates": ["2021-10-26", "2021-10-27", ...],
  "failed_dates": ["2024-01-05"],
  "skipped_dates": ["2021-10-19", "2021-10-20", ...],
  "stats": {"processed": 500, "successful": 495, "failed": 5, "skipped": 28}
}
```

---

## Backfill Mode Pattern

When running backfills, processors use these options:

```python
opts = {
    'analysis_date': analysis_date,
    'project_id': 'nba-props-platform',
    'backfill_mode': True,           # Disables defensive checks
    'skip_downstream_trigger': True,  # Don't trigger Phase 5
    'strict_mode': False              # Skip upstream status checks
}
```

### What `backfill_mode=True` Does

1. **Disables Historical Date Check**
   - Normally processors reject dates >90 days old
   - Backfill mode allows processing any historical date

2. **Suppresses Alerts**
   - No email/Slack notifications for warnings
   - Prevents alert fatigue during bulk processing

3. **Bypasses Defensive Checks**
   - Skips upstream processor status validation
   - Skips gap detection in lookback windows
   - (These checks assume real-time data flow, not backfills)

4. **Disables Downstream Triggers**
   - Does NOT publish to Pub/Sub topics
   - Phase 5 will NOT auto-trigger
   - (You must run Phase 5 backfills separately after Phase 4)

---

## Bootstrap Periods

Bootstrap detection uses the shared config (`shared/config/nba_season_dates.py`):

```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def is_bootstrap_date(check_date: date) -> bool:
    """Check if date falls within bootstrap period (first 7 days of season)."""
    season_year = get_season_year_from_date(check_date)
    return is_early_season(check_date, season_year, days_threshold=7)
```

**Why skip bootstrap?** Phase 4 processors require lookback windows (e.g., 15 games per team). In the first week of the season, there isn't enough data to compute meaningful metrics.

---

## CLI Usage

All backfill jobs support the same CLI interface:

### Dry Run (Check Data Availability)
```bash
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --dry-run --start-date 2024-01-01 --end-date 2024-01-07
```

### Process Date Range (Auto-Resumes if Interrupted)
```bash
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22
```

### Check Checkpoint Status
```bash
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22 --status
```

### Force Restart (Ignore Checkpoint)
```bash
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22 --no-resume
```

### Retry Specific Failed Dates
```bash
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --dates 2024-01-05,2024-01-12,2024-01-18
```

---

## Full 4-Year Backfill

### Option 1: Use Orchestration Script (Recommended)

```bash
# Full backfill with parallelization
./bin/backfill/run_phase4_backfill.sh --start-date 2021-10-19 --end-date 2025-06-22
```

### Option 2: Run Manually

```bash
export PYTHONPATH=/home/naji/code/nba-stats-scraper

# 1. Team Defense Zone Analysis (runs first)
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22

# 2. Player Shot Zone Analysis (can run parallel with #1)
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22

# 3. Player Composite Factors (after #1 and #2)
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22

# 4. Player Daily Cache (after #1, #2, #3)
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22

# 5. ML Feature Store (after ALL above)
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22
```

---

## Output Tables

| Backfill Job | Output Table |
|--------------|--------------|
| team_defense_zone_analysis | `nba_precompute.team_defense_zone_analysis` |
| player_shot_zone_analysis | `nba_precompute.player_shot_zone_analysis` |
| player_composite_factors | `nba_precompute.player_composite_factors` |
| player_daily_cache | `nba_precompute.player_daily_cache` |
| ml_feature_store | `nba_predictions.ml_feature_store_v2` |

---

## Monitoring Progress

### During Execution
- Progress logged every 10 days
- Success/failure counts shown

### Check Checkpoint Status
```bash
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2025-06-22 --status
```

Example output:
```
============================================================
CHECKPOINT STATUS: team_defense_zone_analysis
============================================================
  Date range: 2021-10-19 to 2025-06-22
  Total days: 675
  Processed:  500
    - Successful: 470
    - Failed:     2
    - Skipped:    28
  Last success: 2024-03-15
  Resume from: 2024-03-16 (175 days remaining)
  Checkpoint file: /tmp/backfill_checkpoints/team_defense_zone_analysis_2021-10-19_2025-06-22.json
============================================================
```

---

## Troubleshooting

### "Missing critical dependencies"
The processor depends on upstream Phase 4 tables that haven't been backfilled yet. Run processors in order.

### "No data for date X"
Check if Phase 3 analytics has data for that date using:
```bash
python bin/backfill/verify_phase3_for_phase4.py --start-date X --end-date X --verbose
```

### "Bootstrap period skipped"
Expected behavior for first 7 days of each season. No action needed.

### Resuming After Crash
Just re-run the same command - it will automatically resume from the checkpoint.

### Retrying Failed Dates
Each backfill prints a retry command at the end:
```bash
python ... --dates 2024-01-05,2024-01-12,2024-01-18
```

---

## Utilities

| Script | Purpose |
|--------|---------|
| `bin/backfill/run_phase4_backfill.sh` | Orchestrates all 5 processors with parallelization |
| `bin/backfill/verify_phase3_for_phase4.py` | Verifies Phase 3 data is ready |
| `shared/backfill/checkpoint.py` | Checkpoint manager for progress persistence |

---

## Related Documents

| Document | Purpose |
|----------|---------|
| `BACKFILL-RUNBOOK.md` | Step-by-step execution guide |
| `BACKFILL-MASTER-PLAN.md` | Current state, gaps, what could go wrong |
| `BACKFILL-PRE-EXECUTION-HANDOFF.md` | Pre-execution tasks checklist |

---

**Document Version:** 2.0
**Last Updated:** 2025-11-30
