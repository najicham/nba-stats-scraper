# Session 78: Cascade Contamination Deep Investigation

## Date: 2025-12-08 (continuing Session 77)

## Summary
Investigated and discovered the full cascade contamination chain for December 2021 data. Fixed a major timing bug but discovered the root cause is at Phase 2 level.

## Key Findings

### 1. Timing Bug Fixed
**Issue**: `time_markers` was a class variable shared between all processor instances, causing cumulative timing in backfills.

**Symptoms**:
- Dependencies validated in 0s → 30s → 60s → 111s → ...
- Times kept increasing with each date processed

**Fix**: Moved `time_markers` to instance variable in `__init__`
- File: `data_processors/precompute/precompute_base.py`
- Commit: `a475152`

### 2. Full Cascade Chain Discovered

```
Phase 2: player_game_summary
    └── paint_attempts = NULL    ← ROOT CAUSE

Phase 3: team_defense_game_summary
    └── opp_paint_attempts = OK (fixed in Session 77)

Phase 4: TDZA
    └── paint_defense_vs_league_avg = OK (98.2%)

Phase 4: PSZA
    └── paint_rate_last_10 = 0   ← Contaminated from Phase 2
    └── paint_pct_last_10 = NULL ← Contaminated from Phase 2

Phase 4: PCF
    └── opponent_strength_score = 0 ← Contaminated from PSZA
```

### 3. What Was Fixed
| Table | Status | Notes |
|-------|--------|-------|
| team_defense_game_summary | CLEAN | Shot zone data populated |
| team_defense_zone_analysis | CLEAN (98.2%) | 16 NULLs from early Dec teams |
| player_shot_zone_analysis | CONTAMINATED | Source data NULL |
| player_composite_factors | CONTAMINATED | Uses contaminated PSZA |

### 4. What Still Needs Fixing
**Root cause**: `player_game_summary.paint_attempts` is NULL for all December 2021.

This requires a **Phase 2 backfill** to populate shot zone data from play-by-play logs.

## Phase 3 Data Gaps (PCF Failures)
4 dates missing in `upcoming_player_game_context` (Phase 3):
- Dec 7, Dec 22, Dec 24, Dec 27

These caused expected PCF failures (3 of 30 dates).

## Performance Improvements Verified
With the timing fix, backfill performance is now correct:
- TDZA: ~20s per date (30 dates in ~10 min)
- PCF: ~30s per date (27 dates in ~14 min)

## Next Steps

1. **Phase 2 Backfill Required**
   - Run `player_game_summary` backfill with shot zone data
   - This requires play-by-play data as source

2. **Re-run After Phase 2 Fix**
   - PSZA backfill (will now have data)
   - PCF backfill (will calculate correctly)

3. **Phase 3 Data Gaps**
   - Dec 7, 22, 27 need `upcoming_player_game_context` populated
   - Dec 24 is an off-day (no action needed)

## Files Changed

| File | Change |
|------|--------|
| `data_processors/precompute/precompute_base.py` | Fixed time_markers class variable bug |

## Commands to Continue

```bash
# Check Phase 2 shot zone status
bq query 'SELECT game_date, COUNT(*), COUNT(paint_attempts) FROM player_game_summary WHERE game_date BETWEEN "2021-12-01" AND "2021-12-31" GROUP BY 1'

# After Phase 2 is fixed, re-run PSZA then PCF:
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py --start-date 2021-12-01 --end-date 2021-12-31 --skip-preflight
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py --start-date 2021-12-01 --end-date 2021-12-31 --skip-preflight

# Validate cascade
PYTHONPATH=. .venv/bin/python scripts/validate_cascade_contamination.py --start-date 2021-12-01 --end-date 2021-12-31 --quick
```

## Terminology Established
**Cascade Contamination**: When gaps in upstream data cause downstream processes to run with incomplete inputs, producing records that exist but contain invalid values (NULLs, zeros, or incorrect calculations).
