# Session 109: Spot Check Investigation Findings

**Date:** 2026-02-03
**Session:** 109
**Issue:** Spot check validation failures for usage_rate calculation

## Executive Summary

Spot check validation found 2/5 samples failing usage_rate validation with 5-9% mismatches. Investigation revealed **no calculation bug** in usage_rate, but a **data quality bug** where `minutes_played` is rounded to integers, causing validation mismatches.

## Root Cause

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
**Lines:** 1842, 2468

```python
# BUG: Rounding loses precision
minutes_int = int(round(minutes_decimal)) if minutes_decimal is not None else None
```

The processor:
1. Correctly parses "03:18" → 3.3 minutes
2. Correctly calculates usage_rate with 3.3 minutes
3. **Incorrectly rounds to 3 before storing** (loses 0.3 minutes)

## Failed Samples

### 1. rasheerfleming (PHX) on 2026-02-01

**Raw data:** 03:18 = 3.3 minutes
**Stored:** minutes_played = 3 (rounded)
**Stored usage_rate:** 27.7% (calculated with 3.3 min)
**Spot check recalc:** 30.5% (uses 3 min from database)
**Mismatch:** 9.18%

**Verification:**
- Correct: 100 × 2.0 × 48 / (3.3 × 104.92) = 27.7% ✓
- Spot check: 100 × 2.0 × 48 / (3.0 × 104.92) = 30.5% (uses rounded)

### 2. buddyhield (GSW) on 2026-01-11

**Raw data:** 07:20 = 7.33 minutes
**Stored:** minutes_played = 7 (rounded)
**Stored usage_rate:** 5.7% (calculated with 7.33 min)
**Spot check recalc:** 6.0% (uses 7 min from database)
**Mismatch:** 5.04%

**Verification:**
- Correct: 100 × 1.0 × 48 / (7.33 × 114.24) = 5.7% ✓
- Spot check: 100 × 1.0 × 48 / (7.0 × 114.24) = 6.0% (uses rounded)

## Schema Analysis

**Table:** `nba_analytics.player_game_summary`
**Field:** `minutes_played NUMERIC(5,1)`

The schema **supports 1 decimal place** (e.g., 3.3, 7.33), but the processor rounds to integers before writing.

## Impact Assessment

| Severity | High |
|----------|------|
| **Scope** | All players with non-whole minute totals (~60-70% of records) |
| **Calculation Accuracy** | usage_rate calculations are CORRECT (use decimal minutes during processing) |
| **Data Quality** | minutes_played values are WRONG (rounded, losing precision) |
| **ML Features** | Features using minutes_played have reduced precision |
| **Spot Checks** | Will continue to fail until fixed |

## Fix Required

### Code Change

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Lines 1842, 2468:**
```python
# OLD (loses precision)
minutes_int = int(round(minutes_decimal)) if minutes_decimal is not None else None

# NEW (preserve decimal)
minutes_played = round(minutes_decimal, 1) if minutes_decimal is not None else None
```

Also update all references from `minutes_int` to `minutes_played` in the record-building code.

### Deployment Steps

1. Apply code fix to player_game_summary_processor.py
2. Deploy nba-phase3-analytics-processors service
3. Regenerate data for current season (2025-11-01 to present)
4. Re-run spot checks to verify fix

### Expected Outcomes

- minutes_played will store decimal values (3.3, 7.33)
- Spot check validation will pass (usage_rate matches recalculation)
- ML features using minutes_played will be more precise

## Additional Finding: Duplicate Records

**Issue:** Some players appear twice in player_game_summary for the same game
**Example:** graysonallen, kobebrown, jordanmiller all duplicated for 20260201_LAC_PHX
**Impact:** Low (duplicates have identical values)
**Note:** Separate issue from minutes rounding, should be investigated independently

## Recommendations

1. **P0:** Fix minutes rounding bug (lines 1842, 2468)
2. **P0:** Redeploy Phase 3 processor
3. **P1:** Regenerate current season data
4. **P2:** Investigate duplicate records issue
5. **P2:** Add pre-commit validation to prevent integer rounding of NUMERIC fields

## Session Agent Work

**Agent ID:** a50e2c4
**Agent Type:** general-purpose
**Task:** Investigated JOIN logic and found no bugs, identified minutes precision as root cause

## Related Files

- `/home/naji/code/nba-stats-scraper/data_processors/analytics/player_game_summary/player_game_summary_processor.py` (lines 1842, 2468)
- `/home/naji/code/nba-stats-scraper/scripts/spot_check_data_accuracy.py` (validation script)
- `/home/naji/code/nba-stats-scraper/schemas/nba_analytics/player_game_summary.json` (schema definition)

## Next Steps for Session 110

1. Review this document
2. Decide whether to fix immediately or defer
3. If fixing: Apply code change, deploy, regenerate data
4. Run spot checks again to verify
5. Continue with hit-rate-analysis after tonight's games (per Session 108 request)
