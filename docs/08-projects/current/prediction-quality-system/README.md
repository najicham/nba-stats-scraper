# Prediction Quality System

**Created:** Session 94 (2026-02-03)
**Updated:** Session 95 (2026-02-03)
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

---

## Solution: "Predict Once, Never Replace"

### Core Principle

Instead of making predictions early with bad data and replacing them later, we **WAIT** until features are ready, then make ONE final prediction. This ensures:

1. **Stability**: Users never see predictions change
2. **Quality**: Predictions use best available data
3. **Trust**: "By 4 PM ET, all predictions are final"

### Quality Gate Logic

```python
def should_predict(player, already_has_prediction, mode, feature_quality):
    # Rule 1: Never replace existing predictions
    if already_has_prediction:
        return False

    # Rule 2: High quality (85%+)? Predict now
    if feature_quality >= 85:
        return True

    # Rule 3: Last call? Force prediction (but flag it)
    if mode == 'LAST_CALL':
        player.low_quality_flag = True
        player.forced_prediction = True
        return True

    # Rule 4: Final retry with medium quality (80%+)? Accept it
    if mode == 'FINAL_RETRY' and feature_quality >= 80:
        return True

    # Rule 5: Low quality, not last call? Wait for better data
    return False
```

---

## New Schedule (All Times ET)

### Data Pipeline (Upstream)

| Time ET | Job | Purpose |
|---------|-----|---------|
| 6:00 AM | overnight-phase4 | Phase 4 precompute (uses overnight data) |
| 7:00 AM | ml-feature-store-morning | Feature store refresh #1 |
| 10:00 AM | ml-feature-store-midday | Feature store refresh #2 |
| 1:00 PM | ml-feature-store-afternoon | Feature store refresh #3 |

### Predictions

| Time ET | Time PST | Mode | Quality Threshold | Behavior |
|---------|----------|------|-------------------|----------|
| 8:00 AM | 5:00 AM | FIRST | 85% | Only predict high-quality players |
| 9:00 AM | 6:00 AM | RETRY | 85% | Retry players still missing |
| 10:00 AM | 7:00 AM | RETRY | 85% | Retry after feature store refresh |
| 11:00 AM | 8:00 AM | RETRY | 85% | Continue retries |
| 12:00 PM | 9:00 AM | RETRY | 85% | Continue retries |
| 1:00 PM | 10:00 AM | FINAL_RETRY | 80% | Lower threshold for stragglers |
| 4:00 PM | 1:00 PM | LAST_CALL | 0% | Force all remaining predictions |

### Exports

| Time ET | Job | Notes |
|---------|-----|-------|
| 11:00 AM | phase6-tonight-picks-morning | First export |
| 1:00 PM | phase6-tonight-picks | Mid-day export |
| 5:00 PM | phase6-tonight-picks-pregame | Final pre-game export |

---

## Schema Changes

### New Fields in `player_prop_predictions`

| Field | Type | Description |
|-------|------|-------------|
| `feature_quality_score` | FLOAT64 | Quality score at prediction time (snapshot) |
| `low_quality_flag` | BOOLEAN | True if quality < 85% when predicted |
| `forced_prediction` | BOOLEAN | True if made at LAST_CALL despite low quality |
| `prediction_attempt` | STRING | Which run made it (FIRST, RETRY, FINAL_RETRY, LAST_CALL) |

---

## Alerting

### Slack Alerts (#nba-alerts)

| Alert | Trigger | Action |
|-------|---------|--------|
| LOW_QUALITY_FEATURES | >20% of players have quality < 85% | Check Phase 4 status |
| PHASE4_DATA_MISSING | 0 rows in player_composite_factors for today | Investigate Phase 4 pipeline |
| FORCED_PREDICTIONS | >10 players forced at LAST_CALL | Review data pipeline health |
| LOW_COVERAGE | <80% of expected players have predictions by 1 PM | Investigate blockers |

### Structured Logging

All prediction runs log:
- `prediction_quality_distribution`: Count by quality tier
- `players_skipped_low_quality`: Players waiting for better data
- `players_already_predicted`: Players skipped (already have prediction)
- `players_predicted_this_run`: New predictions made
- `forced_predictions_count`: Players forced at LAST_CALL

---

## Files Changed

| File | Change | Status |
|------|--------|--------|
| `all_subsets_picks_exporter.py` | Quality filter (85%) | Done (Session 94) |
| `execution_logger.py` | NULL fix | Done (Session 94) |
| `schemas/nba_predictions/player_prop_predictions.json` | Add quality fields | Session 95 |
| `predictions/coordinator/coordinator.py` | Quality gates, no-replace logic | Session 95 |
| `predictions/coordinator/player_loader.py` | Check existing predictions | Session 95 |
| Cloud Scheduler jobs | New timing schedule | Session 95 |

---

## Metrics to Monitor

1. **Quality Score Distribution**: Most predictions should be 85%+
2. **Prediction Timing**: First predictions by 8 AM ET
3. **Forced Prediction Rate**: Should be <5% of players
4. **Export Coverage**: 11 AM export should have picks

---

## Related Sessions

- Session 93: Alert investigation, overnight schedule fix
- Session 94: Quality filter, timing investigation, export schedules
- Session 95: Predict-once design, quality gates, alerting
