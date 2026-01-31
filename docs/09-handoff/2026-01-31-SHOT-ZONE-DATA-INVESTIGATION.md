# Shot Zone Data Investigation Handoff

**Date:** 2026-01-31
**Session:** Context continuation from daily validation
**Status:** ROOT CAUSE IDENTIFIED - FIX NEEDED

## Executive Summary

Shot zone data (paint_attempts, mid_range_attempts, three_pt_attempts) is showing invalid rates:
- Avg paint rate: 25.9% (should be 30-45%)
- Avg three rate: 61% (should be 20-50%)

**Root Cause:** Data source mismatch - paint/mid come from play-by-play (incomplete), three_pt comes from box score (complete).

## Problem Details

### Symptoms
1. Validation warning: "avg paint rate 25.9% lower than expected"
2. Validation warning: "avg three rate 61% > 50% (CRITICAL: likely data corruption)"
3. Shot zone rates don't sum to 100% for some players

### Data Evidence

```sql
-- Shot zone data coverage gap
SELECT game_date, has_paint, has_three
FROM player_game_summary
WHERE game_date >= '2026-01-20';

-- Results show:
-- Jan 21: 19 records with paint, 165 with three (12% coverage)
-- Jan 30: 177 records with paint, 200 with three (88% coverage)
```

### Root Cause

**The three fields come from DIFFERENT sources:**

| Field | Source | Coverage |
|-------|--------|----------|
| `paint_attempts` | Play-by-play (BDB/NBAC) | ~50-88% |
| `mid_range_attempts` | Play-by-play (BDB/NBAC) | ~50-88% |
| `three_pt_attempts` | **Box score** | 100% |

When play-by-play is missing for a player:
- `paint_attempts = NULL` or 0
- `three_pt_attempts = actual value` (from box score)
- Rate calculation: paint gets 0%, three gets inflated share

### BigDataBall Coverage Gap

```
Date        | Scheduled | BDB Games | Missing
2026-01-17  | 9         | 0         | 9 (100%)
2026-01-21  | 7         | 1         | 6 (86%)
2026-01-24  | 7         | 2         | 5 (71%)
2026-01-30  | 9         | 9         | 0 (0%)
```

Coverage improved after Jan 25, but earlier dates have significant gaps.

## Affected Components

### Files

1. **Shot Zone Analyzer** (primary)
   - Path: `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py`
   - Lines 175-290: BigDataBall extraction
   - Lines 328-412: NBAC fallback

2. **Player Game Summary Processor**
   - Path: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
   - Lines 1665, 2233: `three_pt_attempts` from box score

3. **Shot Zone Analysis (Precompute)**
   - Path: `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
   - Lines 99-180: Rate calculation with safeguard (only catches NULL, not zeros)

### Tables

| Table | Purpose |
|-------|---------|
| `nba_raw.bigdataball_play_by_play` | Primary shot zone source |
| `nba_raw.nbac_play_by_play` | Fallback shot zone source |
| `nba_analytics.player_game_summary` | Merged player stats with zones |
| `nba_precompute.player_shot_zone_analysis` | Rate calculations |
| `nba_orchestration.pending_bdb_games` | Tracking missing BDB (currently empty) |

## Fix Options

### Option 1: Same-Source Zone Data (Recommended)

Ensure all zone data comes from the same source:

```python
# In player_game_summary_processor.py
# Instead of using box score for three_pt_attempts:

if shot_zones_available:
    three_pt_attempts = shot_zone_data.get('three_attempts_pbp')  # From PBP
else:
    three_pt_attempts = None  # Mark as unavailable, don't use box score
```

### Option 2: Zone Data Completeness Flag

Add a flag to indicate zone data completeness:

```python
# New field in player_game_summary
'zone_data_complete': bool(paint_attempts and mid_range_attempts and three_pt_attempts),
'zone_data_source': 'bigdataball' | 'nbac' | 'box_score_only' | 'mixed'
```

### Option 3: Enhanced Safeguard in Rate Calculation

Update `player_shot_zone_analysis_processor.py`:

```python
# Current safeguard (insufficient):
three_has_data = games_df['three_pt_attempts'].notna().any()

# Better safeguard:
all_zones_from_pbp = (
    games_df['paint_attempts'].notna().any() and
    games_df['mid_range_attempts'].notna().any() and
    games_df['three_attempts_pbp'].notna().any()  # Use PBP field
)
if not all_zones_from_pbp:
    return None  # Don't calculate rates with mixed sources
```

## Immediate Actions

1. **Track Missing BDB Games**
   - The `pending_bdb_games` table is empty but should have entries
   - Verify `persist_pending_bdb_games()` is being called
   - Check if BDB failures are being detected

2. **Backfill BDB Data**
   - Run BDB backfill for dates with missing data (Jan 17-24)
   - Games may now have BDB data available

3. **Regenerate Shot Zone Analysis**
   - After fixing, regenerate `player_shot_zone_analysis` for affected dates

## Monitoring Additions Needed

1. **Daily Zone Completeness Check**
   ```sql
   -- Add to validation
   SELECT game_date,
     COUNTIF(paint_attempts IS NOT NULL) as has_paint,
     COUNTIF(three_pt_attempts IS NOT NULL) as has_three,
     has_paint / has_three as coverage_ratio
   FROM player_game_summary
   WHERE game_date = CURRENT_DATE() - 1
   ```

2. **BDB Coverage Alert**
   ```sql
   -- Alert if BDB coverage < 80% for yesterday
   SELECT
     (SELECT COUNT(DISTINCT game_id) FROM nba_raw.bigdataball_play_by_play WHERE game_date = YESTERDAY) /
     (SELECT COUNT(*) FROM nba_reference.nba_schedule WHERE game_date = YESTERDAY AND game_status = 3)
   ```

## Impact Assessment

### Model Impact
- Shot zone features (`pct_paint`, `pct_mid_range`, `pct_three`) are corrupted
- These feed into CatBoost V8 predictions
- May contribute to model drift (separate issue)

### Prediction Impact
- Players with incomplete zone data get skewed predictions
- Feature `shot_zone_mismatch_score` uses incorrect rates

## Related Issues

- CatBoost V8 model drift (separate handoff doc)
- BDB was disabled as backup source Jan 28 (data quality issues)
- The `has_shot_zone_data` flag was added Jan 25 but may not be used correctly

## Testing Verification

After fix, verify:

1. Zone rates sum to 100% (±2%)
2. Paint rate between 30-45%
3. Three rate between 20-50%
4. Coverage ratio > 95% for games with BDB data

## Key Files to Modify

| Priority | File | Change |
|----------|------|--------|
| P1 | `player_game_summary_processor.py` | Use PBP three_pt, not box score |
| P1 | `shot_zone_analyzer.py` | Enhance fallback tracking |
| P2 | `player_shot_zone_analysis_processor.py` | Add source validation |
| P2 | `validate_tonight_data.py` | Add zone completeness check |
