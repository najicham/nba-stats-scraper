# Backfill Progress Monitor - Usage Guide

**Created:** 2025-11-30
**Location:** `bin/infrastructure/monitoring/backfill_progress_monitor.py`
**Purpose:** Real-time monitoring for Phase 3 and Phase 4 backfill execution

---

## Quick Start

```bash
# Single check (run once, see current state)
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py

# Continuous monitoring (auto-refresh every 30 seconds)
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --continuous

# Detailed view (shows all tables)
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --detailed

# Show only failures
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --failures-only
```

---

## Features

### 1. Overall Progress Tracking

Shows completion percentage for Phase 3 and Phase 4 with visual progress bars:

```
📊 OVERALL PROGRESS
🔵 Phase 3 (Analytics): 348/675 dates (51.6%)
   [█████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░] 51.6%

🟣 Phase 4 (Precompute): 0/675 dates (0.0%)
   [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 0.0%
```

### 2. Table-Level Progress (--detailed)

Shows progress for each individual table:

```
📋 TABLE-LEVEL PROGRESS
🔵 Phase 3 Analytics:
   ⏳ player_game_summary                       348/675 ( 51.6%)
   ⏳ team_defense_game_summary                   0/675 (  0.0%)
   ⏳ team_offense_game_summary                   0/675 (  0.0%)
   ⏳ upcoming_player_game_context                5/675 (  0.7%)
   ⏳ upcoming_team_game_context                  0/675 (  0.0%)

🟣 Phase 4 Precompute:
   ⏳ player_composite_factors                    0/675 (  0.0%)
   ⏳ player_daily_cache                          0/675 (  0.0%)
   ⏳ player_shot_zone_analysis                   0/675 (  0.0%)
   ⏳ team_defense_zone_analysis                  0/675 (  0.0%)
```

**Status Icons:**
- ✅ = 100% complete (Phase 3) or ≥95% complete (Phase 4, due to bootstrap skip)
- ⏳ = In progress
- ❌ = Error

### 3. Season-by-Season Breakdown

Tracks progress across 4 NBA seasons:

```
🗓️  SEASON-BY-SEASON BREAKDOWN
Season         Expected      Phase 3      Phase 4     P3 %     P4 %
2021-22             215           75            0    34.9%     0.0%
2022-23             214          117            0    54.7%     0.0%
2023-24             209          119            0    56.9%     0.0%
2024-25              37           37            0   100.0%     0.0%
```

### 4. Processing Rate & ETA

Shows how fast backfill is running and estimates completion time:

```
⚡ PROCESSING RATE
🔵 Phase 3: 45 dates/hour (last 1 hour)
   Remaining: 327 dates
   ETA: 7.3 hours

🟣 Phase 4: 12 dates/hour (last 1 hour)
   Remaining: 675 dates
   ETA: 2.3 days
```

**Note:** Rate is based on recent activity (last 1 hour). Shows "0 dates/hour" when nothing is running.

### 5. Recent Failures Detection

Shows processor failures from the last 2 hours:

```
⚠️  RECENT FAILURES (last 2 hours, showing 5)
❌ PlayerGameSummaryProcessor
   Date: 2024-01-15
   Time: 2025-11-30 10:15:30
   Error: [{"error_message":"Missing required data...","error_type":"ValidationError"...
```

Shows "NO RECENT FAILURES" when backfill is running smoothly.

---

## Usage Patterns

### During Backfill Execution

**Recommended setup:**

```bash
# Terminal 1: Run backfill job
./bin/run_backfill.sh analytics/player_game_summary --start-date 2021-10-19 --end-date 2022-04-10

# Terminal 2: Monitor progress continuously
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --continuous --interval 60
```

### Quick Health Check

```bash
# Check current status (single snapshot)
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py
```

### Focus on Specific Season

```bash
# Monitor only 2023-24 season
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --season 2023-24 --detailed
```

### Troubleshooting Mode

```bash
# Show only failures to identify issues
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --failures-only
```

---

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--continuous` | False | Run continuously with auto-refresh |
| `--interval N` | 30 | Refresh interval in seconds (use with --continuous) |
| `--detailed` | False | Show table-level progress breakdown |
| `--failures-only` | False | Show only recent failures |
| `--season YYYY-YY` | All | Filter by season (e.g., 2023-24) |

---

## Understanding the Output

### Phase 3 vs Phase 4 Progress

**Phase 3 (Analytics):**
- Target: 675/675 dates (100%)
- All 5 processors must reach 100%
- Processors can run in parallel

**Phase 4 (Precompute):**
- Target: ~647/675 dates (96%)
- Bootstrap periods (first 7 days of each season) are intentionally skipped
- Processors must run sequentially (strict dependency order)

### What's Normal

✅ **Phase 3:**
- 100% completion expected
- All tables should have same date count

✅ **Phase 4:**
- 95-96% completion expected (due to bootstrap skip)
- Tables may have slightly different counts during execution
- Should converge to same count when complete

### What's a Problem

⚠️ **Warning Signs:**
- Phase 3 stuck at <100% after backfill completes
- Processing rate = 0 for >1 hour during active backfill
- Many failures (>20 in last 2 hours)
- Phase 4 tables have very different date counts

---

## Integration with Backfill Runbook

This monitor complements the backfill execution runbook:

**Pre-Flight Check:**
```bash
# Verify starting state (Stage 0)
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --detailed
```

**During Phase 3 Backfill:**
```bash
# Monitor progress every 60 seconds (Stage 1)
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --continuous --interval 60
```

**Phase 3 Quality Gate:**
```bash
# Verify 675/675 dates before moving to Phase 4
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py
```

**During Phase 4 Backfill:**
```bash
# Monitor sequential processor execution (Stage 2)
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --continuous --detailed
```

**Phase 4 Quality Gate:**
```bash
# Verify ~647/675 dates (96%+ acceptable)
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py
```

---

## Data Sources

The monitor queries these BigQuery tables:

**For progress tracking:**
- `nba_raw.nbac_schedule` - Expected game dates (ground truth)
- `nba_analytics.*` - Phase 3 table completion
- `nba_precompute.*` - Phase 4 table completion

**For failure detection:**
- `nba_reference.processor_run_history` - All processor execution logs

**Query performance:**
- Typical run time: 20-30 seconds (queries 10+ tables)
- Uses `COUNT(DISTINCT date)` for accurate progress
- Partitioned tables for efficient queries

---

## Troubleshooting

### Monitor Shows Errors

**"Error: 400 Unrecognized name: analysis_date"**
- Means Phase 4 table doesn't exist yet (expected before backfill)
- Will resolve once backfill creates the table

**Monitor is slow (>1 minute)**
- Normal for first run (BigQuery cold start)
- Subsequent runs should be faster (<30 seconds)

### Progress Not Updating

**Processing rate shows 0 dates/hour:**
- Check if backfill job is actually running
- Look at "Recent Failures" section for issues
- Verify backfill job logs

**Progress stuck:**
- Check for failures in processor_run_history:
  ```sql
  SELECT data_date, processor_name, status, errors
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE status = 'failed'
  ORDER BY started_at DESC
  LIMIT 20
  ```

---

## Tips & Best Practices

### 1. Use Continuous Mode During Active Backfill

```bash
# Let it auto-refresh while backfill runs
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --continuous --interval 60
```

Press `Ctrl+C` to stop.

### 2. Start with --detailed to Understand State

```bash
# See exactly which tables need backfill
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --detailed
```

### 3. Check Failures After Each Season

```bash
# After completing 2021-22 season
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --season 2021-22 --failures-only
```

### 4. Log Progress for Documentation

```bash
# Save snapshot to file
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --detailed > backfill_progress_$(date +%Y%m%d_%H%M).txt
```

### 5. Monitor Phase 4 Carefully

Phase 4 processors must run sequentially. Use `--detailed` to verify:

```bash
# Watch tables fill in order: team_defense_zone_analysis → player_shot_zone_analysis → ...
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --continuous --detailed
```

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [BACKFILL-RUNBOOK.md](BACKFILL-RUNBOOK.md) | Step-by-step execution guide |
| [BACKFILL-MASTER-PLAN.md](BACKFILL-MASTER-PLAN.md) | Strategy and current state |
| [BACKFILL-GAP-ANALYSIS.md](BACKFILL-GAP-ANALYSIS.md) | Detailed SQL queries for analysis |
| [BACKFILL-FAILURE-RECOVERY.md](BACKFILL-FAILURE-RECOVERY.md) | Recovery procedures |

---

## Example Session

```bash
$ python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --detailed

================================================================================
🔍 NBA BACKFILL PROGRESS MONITOR
📅 Target: 2021-10-01 to 2024-11-29
⏰ Checked: 2025-11-30 14:30:00
================================================================================

📊 OVERALL PROGRESS
🔵 Phase 3 (Analytics): 675/675 dates (100.0%) ✅
   [██████████████████████████████████████████████████] 100.0%

🟣 Phase 4 (Precompute): 647/675 dates (95.9%) ✅
   [████████████████████████████████████████████████░░] 95.9%
   Note: Bootstrap periods (first 7 days) are intentionally skipped

📋 TABLE-LEVEL PROGRESS
🔵 Phase 3 Analytics:
   ✅ player_game_summary                       675/675 (100.0%)
   ✅ team_defense_game_summary                 675/675 (100.0%)
   ✅ team_offense_game_summary                 675/675 (100.0%)
   ✅ upcoming_player_game_context              675/675 (100.0%)
   ✅ upcoming_team_game_context                675/675 (100.0%)

🟣 Phase 4 Precompute:
   ✅ player_composite_factors                  647/675 ( 95.9%)
   ✅ player_daily_cache                        647/675 ( 95.9%)
   ✅ player_shot_zone_analysis                 647/675 ( 95.9%)
   ✅ team_defense_zone_analysis                647/675 ( 95.9%)

🗓️  SEASON-BY-SEASON BREAKDOWN
Season         Expected      Phase 3      Phase 4     P3 %     P4 %
2021-22             215          215          208   100.0%    96.7%
2022-23             214          214          207   100.0%    96.7%
2023-24             209          209          202   100.0%    96.7%
2024-25              37           37           30   100.0%    81.1%

⚡ PROCESSING RATE
🔵 Phase 3: 0 dates/hour (last 1 hour)
🟣 Phase 4: 0 dates/hour (last 1 hour)

✅ NO RECENT FAILURES (last 2 hours)

================================================================================

🎉 Backfill complete! All quality gates passed.
```

---

**Created:** 2025-11-30
**Version:** 1.0
**Maintainer:** Infrastructure Team
