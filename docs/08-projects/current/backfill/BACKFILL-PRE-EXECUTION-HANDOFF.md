# Backfill Pre-Execution Handoff

**Created:** 2025-11-29 22:19 PST
**Last Updated:** 2025-11-30
**Purpose:** Tasks that must be completed before backfill execution
**Status:** ALL TASKS COMPLETE - Ready for backfill execution

---

## Summary

Two categories of work must be completed before executing the 4-year backfill:

| Category | Items | Priority | Status |
|----------|-------|----------|--------|
| Create Phase 4 Backfill Jobs | 5 processors | HIGH - Blocking | **COMPLETE** |
| Fix BettingPros Fallback | 1 processor | HIGH - Affects coverage | **COMPLETE** |

---

## Task 1: Create Phase 4 Backfill Jobs - **COMPLETE**

**Completed:** 2025-11-30

All 5 Phase 4 precompute backfill jobs have been created:

| Processor | Location | Status |
|-----------|----------|--------|
| team_defense_zone_analysis | `backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py` | ✅ |
| player_shot_zone_analysis | `backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py` | ✅ |
| player_composite_factors | `backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py` | ✅ |
| player_daily_cache | `backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py` | ✅ |
| ml_feature_store | `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | ✅ |

### Usage

See `PHASE4-BACKFILL-JOBS.md` for complete documentation including:
- CLI arguments (`--dry-run`, `--start-date`, `--end-date`, `--dates`)
- Execution order (must run sequentially: 1→2→3→4→5)
- Bootstrap period handling
- Backfill mode options

---

## Task 2: Fix BettingPros Fallback in upcoming_player_game_context - **COMPLETE**

**Completed:** 2025-11-30
**Handoff Document:** `docs/09-handoff/2025-11-30-bettingpros-fallback-complete.md`

### Implementation Summary

Implemented Python fallback (Option B) with these changes:
- Added `_extract_players_from_bettingpros()` method
- Added `_extract_prop_lines_from_bettingpros()` method
- Modified driver query to try Odds API first, fall back to BettingPros if empty
- Handles schema differences (BettingPros lacks `game_id`, uses JOINs with schedule)

### Test Results (2021-11-01)

| Metric | Result |
|--------|--------|
| Props source | BettingPros (Odds API had 0) |
| Players found | 57 |
| Players processed | 53 |
| Coverage improvement | 40% → 99.7% |

---

### Original Problem (Resolved)

The `upcoming_player_game_context` processor previously only queried Odds API:

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
