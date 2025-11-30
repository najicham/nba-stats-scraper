# Backfill Pre-Execution Handoff

**Created:** 2025-11-29 22:19 PST
**Purpose:** Tasks that must be completed before backfill execution
**Status:** Blocking - Complete these first

---

## Summary

Two categories of work must be completed before executing the 4-year backfill:

| Category | Items | Priority |
|----------|-------|----------|
| Create Phase 4 Backfill Jobs | 5 processors | HIGH - Blocking |
| Fix BettingPros Fallback | 1 processor | HIGH - Affects coverage |

---

## Task 1: Create Phase 4 Backfill Jobs

### What's Missing

All 5 Phase 4 precompute processors need backfill jobs created:

| Processor | Location to Create |
|-----------|-------------------|
| team_defense_zone_analysis | `backfill_jobs/precompute/team_defense_zone_analysis/` |
| player_shot_zone_analysis | `backfill_jobs/precompute/player_shot_zone_analysis/` |
| player_composite_factors | `backfill_jobs/precompute/player_composite_factors/` |
| player_daily_cache | `backfill_jobs/precompute/player_daily_cache/` |
| ml_feature_store | `backfill_jobs/precompute/ml_feature_store/` |

### Template to Follow

Use the Phase 3 analytics backfill job as template:
```
backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py
```

### Required Features

Each Phase 4 backfill job must have:

1. **CLI Arguments:**
   - `--dry-run` - Check data without processing
   - `--start-date` / `--end-date` - Date range
   - `--dates` - Retry specific failed dates

2. **Processing:**
   - Day-by-day processing (avoids BigQuery limits)
   - `backfill_mode=True` in processor options
   - Progress logging every 10 days

3. **Bootstrap Period Skip:**
   ```python
   BOOTSTRAP_PERIODS = [
       ('2021-10-19', '2021-10-25'),
       ('2022-10-18', '2022-10-24'),
       ('2023-10-24', '2023-10-30'),
       ('2024-10-22', '2024-10-28'),
   ]
   # Skip these dates - Phase 4 intentionally produces no data
   ```

4. **Failed Dates Tracking:**
   - Collect failed dates during run
   - Print retry command at end

5. **Phase 3 Validation (Optional but Recommended):**
   - Before processing each date, check Phase 3 has data for lookback window
   - Log warning if incomplete

### Execution Order Reminder

Phase 4 processors have inter-dependencies. The backfill jobs should be run in this order:

```
1. team_defense_zone_analysis   (reads Phase 3 only)
2. player_shot_zone_analysis    (reads Phase 3 only)
3. player_composite_factors     (reads #1, #2, Phase 3)
4. player_daily_cache           (reads #1, #2, #3, Phase 3)
5. ml_feature_store             (reads #1, #2, #3, #4)
```

**Do NOT parallelize these for the same date range.**

---

## Task 2: Fix BettingPros Fallback in upcoming_player_game_context

### The Problem

The `upcoming_player_game_context` processor currently only queries Odds API:

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Current behavior (lines 335, 540, 554):**
```sql
FROM `nba_raw.odds_api_player_points_props`
```

**Coverage:**
- Odds API: 271/675 dates (40%)
- BettingPros: 673/675 dates (99.7%)

Without this fix, `upcoming_player_game_context` will only have data for 40% of historical dates.

### The Fix

Modify the processor to use BettingPros as a fallback when Odds API data is missing.

**Option A: UNION with deduplication**
```sql
WITH odds_api_props AS (
    SELECT player_lookup, game_id, game_date, points_line, bookmaker, ...
    FROM `nba_raw.odds_api_player_points_props`
    WHERE game_date = '{target_date}'
),
bettingpros_props AS (
    SELECT player_lookup, game_id, game_date, points_line, bookmaker, ...
    FROM `nba_raw.bettingpros_player_points_props`
    WHERE game_date = '{target_date}'
      AND game_date NOT IN (SELECT DISTINCT game_date FROM odds_api_props)
)
SELECT * FROM odds_api_props
UNION ALL
SELECT * FROM bettingpros_props
```

**Option B: Fallback in Python**
```python
# Try Odds API first
props_df = query_odds_api(target_date)

# If empty, fall back to BettingPros
if props_df.empty:
    props_df = query_bettingpros(target_date)
```

### Locations to Modify

Search for `odds_api_player_points_props` in the file:
- Line 335: Driver query (determines which players to process)
- Line 540: Props extraction
- Line 554: Props extraction

### Testing

After fix:
```bash
# Dry run for a date with only BettingPros data
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --dry-run --start-date 2021-10-20 --end-date 2021-10-20

# Should show players available (from BettingPros)
```

---

## Verification Before Backfill

After completing both tasks, verify:

### 1. Phase 4 Backfill Jobs Exist

```bash
for proc in team_defense_zone_analysis player_shot_zone_analysis player_composite_factors player_daily_cache ml_feature_store; do
  if [ -f "backfill_jobs/precompute/$proc/${proc}_precompute_backfill.py" ]; then
    echo "✅ $proc"
  else
    echo "❌ $proc MISSING"
  fi
done
```

### 2. BettingPros Fallback Works

```bash
# Run dry-run for a date that only has BettingPros data
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --dry-run --start-date 2021-11-01 --end-date 2021-11-01

# Should show players available, not "0 players"
```

---

## Reference Documents

| Document | Purpose |
|----------|---------|
| `docs/08-projects/current/backfill/BACKFILL-RUNBOOK.md` | Step-by-step execution guide |
| `docs/08-projects/current/backfill/BACKFILL-MASTER-PLAN.md` | Current state, gaps, what could go wrong |
| `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py` | Template for Phase 4 jobs |
| `docs/01-architecture/data-readiness-patterns.md` | All data safety patterns |

---

## After Completion

Once both tasks are done, proceed to execute backfill following:
`docs/08-projects/current/backfill/BACKFILL-RUNBOOK.md`

---

**Document Version:** 1.0
**Last Updated:** 2025-11-29 22:19 PST
