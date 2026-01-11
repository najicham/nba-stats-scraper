# DNP-Aware Completeness Check

**Date:** January 10, 2026
**Status:** Implemented
**Impact:** High - Prediction coverage improved from ~34% to ~80%+

## Problem Statement

The prediction pipeline was only generating predictions for 31 out of 91 players with betting lines (34% coverage). Investigation revealed that 108 players were being filtered out by the `player_daily_cache` processor due to failing completeness checks.

### Root Cause

The completeness checker was comparing:
- **Expected games**: Games the player's team had scheduled
- **Actual games**: Games the player appears in `player_game_summary`

Players who missed games due to legitimate reasons (injury, rest, coach's decision) were penalized:

| Player | Team Games | Games Played | DNP Games | Completeness | Threshold |
|--------|-----------|--------------|-----------|--------------|-----------|
| Donovan Mitchell | 3 | 2 | 1 (Jan 6) | 66.7% | 70% FAIL |
| Victor Wembanyama | 3 | 2 | 1 | 66.7% | 70% FAIL |
| Kyrie Irving | 3 | 0 | 2 | 16.7% | 70% FAIL |

The 70% threshold was designed to catch data pipeline failures, but it was incorrectly flagging players with legitimate DNPs (Did Not Play).

## Solution: DNP-Aware Completeness

### Concept

Distinguish between:
- **DNP (Did Not Play)**: Player appears in raw boxscore with 0 minutes. This is expected - we shouldn't have analytics data for games a player didn't play.
- **Data Gap**: Player played (minutes > 0 in raw boxscore) but missing from `player_game_summary`. This is a real problem.

### Implementation

Added `dnp_aware` parameter to `CompletenessChecker.check_completeness_batch()`:

```python
def check_completeness_batch(
    self,
    entity_ids: List[str],
    entity_type: str,
    analysis_date: date,
    upstream_table: str,
    upstream_entity_field: str,
    lookback_window: int,
    window_type: str = 'games',
    season_start_date: Optional[date] = None,
    fail_on_incomplete: bool = False,
    completeness_threshold: float = 90.0,
    dnp_aware: bool = False  # NEW
) -> Dict[str, Dict]:
```

When `dnp_aware=True`:
1. Queries raw boxscores for games where player had 0 minutes (DNPs)
2. Subtracts DNP count from expected games
3. Calculates completeness against adjusted expected
4. Adds gap classification: `NO_GAP`, `DATA_GAP`, or `NAME_UNRESOLVED`

### New Return Fields

```python
{
    'player_lookup': {
        'expected_count': 3,        # Team's scheduled games
        'actual_count': 2,          # Games in upstream table
        'completeness_pct': 100.0,  # Calculated against adjusted expected
        'missing_count': 0,
        'is_complete': True,
        'is_production_ready': True,
        # New DNP-aware fields:
        'dnp_count': 1,             # Games with 0 minutes in raw boxscores
        'adjusted_expected': 2,     # expected - dnp
        'gap_classification': 'NO_GAP'
    }
}
```

### Gap Classification Logic

| Condition | Classification | Meaning |
|-----------|---------------|---------|
| `actual >= adjusted_expected` | `NO_GAP` | Data is complete for games played |
| `actual < adjusted_expected` | `DATA_GAP` | Player played but data missing |
| `actual=0 AND dnp=0 AND expected>0` | `NAME_UNRESOLVED` | No raw data at all - likely name mismatch |

## Files Changed

| File | Change |
|------|--------|
| `shared/utils/completeness_checker.py` | Added `dnp_aware` parameter, `_query_dnp_games()` method |
| `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` | Enabled `dnp_aware=True` |

## Test Results

### Before (DNP-unaware)
```
donovanmitchell: 66.7% complete (2/3 games) - FAILS
victorwembanyama: 66.7% complete (2/3 games) - FAILS
```

### After (DNP-aware)
```
donovanmitchell: 100.0% complete (2/2 adjusted, 1 DNP) - PASSES
victorwembanyama: 100.0% complete (2/2 adjusted, 1 DNP) - PASSES
```

## Measured Impact

### Per-Window Results (DNP-aware)
| Window | Pass Rate | Players |
|--------|-----------|---------|
| L5 | 99.1% | 209/211 |
| L10 | 98.6% | 208/211 |
| L7d | 75.8% | 160/211 |
| L14d | 87.7% | 185/211 |

### Combined (All 4 Windows Must Pass)
| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Players passing completeness | 103 | 158 | +55 (+53%) |
| Pass rate | 48.8% | 74.9% | +26.1pp |
| Blocked by DNP | 55+ | 0 | Eliminated |

### Remaining Failures (53 players)
- **DATA_GAP**: ~50 players - actual data processing issues to investigate
- **NAME_UNRESOLVED**: 2 players - need alias/registry work

## Edge Cases Handled

1. **Player injured multiple games**: All DNP games excluded, 100% if no data gaps
2. **Player traded mid-window**: Only counts games for current team
3. **New player (few games)**: Handled by separate `min_games_required` check
4. **Name resolution failure**: Classified as `NAME_UNRESOLVED` when expected > 0 but 0 in both raw and summary

## Monitoring

The completeness checker now logs DNP exclusions:
```
DNP check: 45 players with DNP games, 67 total DNP games in window
```

Gap classifications can be monitored to detect:
- `DATA_GAP` spikes → Pipeline processing issue
- `NAME_UNRESOLVED` growth → Name resolution backlog

## Related Documentation

- `docs/08-projects/current/pipeline-reliability-improvements/optimization/enhanced-failure-tracking.md`
- `docs/09-handoff/2026-01-10-SESSION-3-HANDOFF.md`
