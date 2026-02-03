# Prediction Quality System

**Created:** Session 94 (2026-02-03)
**Status:** In Progress

## Problem Statement

On Feb 2, 2026, the top 3 high-edge picks all MISSED because they had incomplete ML features (missing BDB shot zone data). The model predicted conservatively, creating artificially high edges, and when players exceeded expectations, all bets lost.

### Evidence

| Player | Quality Score | Predicted | Line | Actual | Result |
|--------|---------------|-----------|------|--------|--------|
| Trey Murphy III | 82.73% | 11.1 | 22.5 | 27 | MISS |
| Jaren Jackson Jr | 82.73% | 13.8 | 22.5 | 30 | MISS |
| Jabari Smith Jr | 82.73% | 9.4 | 17.5 | 19 | MISS |
| Zion Williamson | **87.59%** | 21.0 | 23.5 | 14 | HIT |

**Root Cause:** Missing BDB shot zone data (`pct_paint`, `pct_mid_range`, `pct_three` = 0)

### Historical Performance by Quality Score

| Quality Tier | Hit Rate | Sample Size |
|--------------|----------|-------------|
| High (85%+) | **56.8%** | 1,208 |
| Medium (80-85%) | 51.9% | 270 |
| Low (<80%) | 48.1% | 108 |

## Secondary Issue: Prediction Timing

Predictions for Feb 2 were created at **4:38 PM ET** instead of **5:11 AM ET**. The 1 PM export ran with 0 picks because predictions didn't exist yet.

## Solutions Implemented

### 1. Feature Quality Filter in Exports (DONE)
- **File:** `data_processors/publishing/all_subsets_picks_exporter.py`
- **Change:** Added `MIN_FEATURE_QUALITY_SCORE = 85.0` threshold
- **Effect:** Players with missing BDB data (quality < 85%) won't be exported as "top picks"

### 2. Multiple Export Schedules (DONE)
- **11 AM ET:** `phase6-tonight-picks-morning`
- **1 PM ET:** `phase6-tonight-picks` (existing)
- **5 PM ET:** `phase6-tonight-picks-pregame`

### 3. Smart Prediction Retry System (TODO)
See: [SMART-RETRY-DESIGN.md](./SMART-RETRY-DESIGN.md)

## Critical Rule: Back-to-Back Players Need BDB Data

### Why This Matters

For players on a **back-to-back** (b2b_flag = 1), their previous game's performance is critical:
- Fatigue affects scoring
- Shot selection changes
- Minutes may be managed

If we don't have BDB play-by-play data from their previous game, we can't accurately assess:
- Shot zone tendencies
- Fatigue-adjusted shot selection
- Paint vs perimeter scoring patterns

### Rule Implementation

```
For back-to-back players:
  If previous game BDB data is missing:
    - Attempt 1-2: PAUSE prediction, alert, trigger BDB scraper
    - Attempt 3 (final): Proceed with low-quality flag, exclude from top picks
```

## Files Changed

| File | Change | Status |
|------|--------|--------|
| `all_subsets_picks_exporter.py` | Quality filter | Done |
| `execution_logger.py` | NULL fix | Done |
| Scheduler jobs | Added 11 AM, 5 PM exports | Done |
| `coordinator.py` | Smart retry logic | TODO |
| `player_loader.py` | B2B quality gate | TODO |

## Metrics to Monitor

1. **Quality Score Distribution:** Should see most predictions at 85%+
2. **Export Coverage:** 11 AM export should have picks (not empty)
3. **B2B Player Accuracy:** Track hit rate for b2b players separately

## Related Sessions

- Session 93: Alert investigation, overnight schedule fix
- Session 94: Quality filter, timing investigation, export schedules

## Next Steps

1. Implement smart retry logic in coordinator
2. Add B2B quality gate in player_loader
3. Add alerting when predictions are blocked due to missing data
4. Deploy changes to prediction-coordinator
