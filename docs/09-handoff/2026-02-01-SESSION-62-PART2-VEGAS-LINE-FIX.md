# Session 62 Part 2 - Vegas Line Feature Store Fix

**Date:** 2026-02-01
**Focus:** Root cause analysis and fix for vegas_line feature store coverage drop
**Previous:** Session 62 Part 1 (heartbeat deployment), Session 61 (discovery)

---

## Session Summary

Investigated and fixed the critical vegas_line feature coverage drop (99.4% → 43.4%) that caused V8 model hit rate to collapse. The root cause was an architectural mismatch between two well-intentioned changes made at different times.

---

## Root Cause (Detailed)

### The Problem

Two changes created an unintended incompatibility:

| Date | Change | Intent | Effect |
|------|--------|--------|--------|
| Dec 10, 2025 | `backfill_mode` added | Fix 35% roster coverage gap | Expanded player list to ALL players |
| Jan 31, 2026 | Vegas source → Phase 3 | Use cascade for scraper resilience | Phase 3 only has Vegas for expected players |

### Data Flow Before (Working)

```
upcoming_player_game_context (Phase 3)
├── Player list: 150-200 (players with props)
└── Vegas lines: 150-200 (same source)
Result: 99.4% coverage
```

### Data Flow After (Broken)

```
get_players_with_games(backfill_mode=True)
├── Source: player_game_summary
└── Returns: 500+ players (ALL who played)

_batch_extract_vegas_lines()
├── Source: upcoming_player_game_context (Phase 3)
└── Returns: 150-200 players (only those with props)

Result: 43.4% coverage (200/500 intersection)
```

---

## Fix Applied

### Code Changes

| File | Change |
|------|--------|
| `feature_extractor.py` | Added `backfill_mode` parameter to `batch_extract_all_data()` |
| `feature_extractor.py` | Added `backfill_mode` parameter to `_batch_extract_vegas_lines()` |
| `feature_extractor.py` | Backfill mode queries raw betting tables (odds_api, bettingpros) instead of Phase 3 |
| `ml_feature_store_processor.py` | Pass `self.is_backfill_mode` to `batch_extract_all_data()` |
| `validate-daily/SKILL.md` | Added Priority 2F: Vegas coverage check (alert if <80%) |
| `README.md` | Updated with prevention mechanisms |

### Query Logic (Backfill Mode)

```sql
WITH odds_api_lines AS (
    -- Primary: Odds API (DraftKings preferred)
    SELECT player_lookup, vegas_points_line, vegas_opening_line
    FROM odds_api_player_points_props
    WHERE game_date = @date
),
bettingpros_lines AS (
    -- Fallback: BettingPros (must filter market_type='points')
    SELECT player_lookup, vegas_points_line, vegas_opening_line
    FROM bettingpros_player_points_props
    WHERE game_date = @date AND market_type = 'points'
)
SELECT COALESCE(oa.player_lookup, bp.player_lookup),
       COALESCE(oa.vegas_points_line, bp.vegas_points_line), ...
FROM odds_api_lines oa
FULL OUTER JOIN bettingpros_lines bp USING (player_lookup)
```

---

## Prevention Mechanisms Added

### 1. Vegas Coverage Check in `/validate-daily`

Added Priority 2F check:

```sql
SELECT ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- ALERT if < 80%
```

### 2. Root Cause Documentation

Created comprehensive analysis document:
- `docs/08-projects/current/feature-quality-monitoring/2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md`

---

## What Still Needs to Be Done

### Immediate (Before Experiments)

1. **Re-run feature store backfill** for Nov 2025 - Feb 2026 with the fix:
   ```bash
   # Example - run backfill with new code
   PYTHONPATH="$PWD" python -c "
   from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
   from datetime import date, timedelta

   processor = MLFeatureStoreProcessor()
   start = date(2025, 11, 1)
   end = date(2026, 2, 1)

   current = start
   while current <= end:
       try:
           processor.process({'analysis_date': current.isoformat(), 'backfill_mode': True})
           print(f'Processed {current}')
       except Exception as e:
           print(f'Error {current}: {e}')
       current += timedelta(days=1)
   "
   ```

2. **Verify coverage improved**:
   ```sql
   SELECT FORMAT_DATE('%Y-%m', game_date) as month,
     ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date >= '2025-11-01' AND ARRAY_LENGTH(features) >= 33
   GROUP BY 1 ORDER BY 1
   -- Should be >95% after fix (was 43%)
   ```

### After Fix Verified

3. **Run ML experiments** from `docs/08-projects/current/ml-challenger-experiments/EXPERIMENT-PLAN.md`
   - Start with `exp_20260201_dk_only` (DraftKings-only training)
   - Compare to V8 baseline on Jan 2026 holdout

---

## Files Changed

```
M .claude/skills/validate-daily/SKILL.md (+38 lines)
M data_processors/precompute/ml_feature_store/feature_extractor.py (+99 lines)
M data_processors/precompute/ml_feature_store/ml_feature_store_processor.py (+5 lines)
M docs/08-projects/current/feature-quality-monitoring/README.md (+59 lines)
A docs/08-projects/current/feature-quality-monitoring/2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md (new)
A docs/09-handoff/2026-02-01-SESSION-62-PART2-VEGAS-LINE-FIX.md (this file)
```

---

## Key Learnings

1. **Architectural changes need cross-component testing** - The Dec 2025 and Jan 2026 changes were both correct individually but incompatible together

2. **Coverage monitoring is different from value monitoring** - Pre-write validation caught value errors but not coverage drops

3. **Backfill mode should be tested against production baseline** - If production has 99% coverage, backfill should too

4. **The fix is about data source, not filtering** - Don't filter to props-only players; instead, expand the Vegas data source for backfill

---

*Created: 2026-02-01 Session 62 Part 2*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
