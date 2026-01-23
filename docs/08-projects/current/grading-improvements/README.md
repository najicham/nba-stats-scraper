# Grading Improvements Project

**Status:** COMPLETE
**Started:** 2026-01-23
**Completed:** 2026-01-23

---

## Overview

This project addresses follow-up improvements after the ESTIMATED_AVG cleanup:
1. MAE-only grading for NO_PROP_LINE predictions
2. Enhanced monitoring and alerting
3. Historical data documentation

## Background

The ESTIMATED_AVG line source issue was resolved on 2026-01-23:
- 105,438 fake betting lines eliminated
- All predictions now use real lines (ACTUAL_PROP, VEGAS_BACKFILL) or correctly marked NO_PROP_LINE
- Clean 77.1% win rate on ACTUAL_PROP predictions with CatBoost v8

## Tasks

### Phase 1: Analysis (Complete)
- [x] Analyze historical seasons (2021-2024) line source distribution
- [x] Verify ESTIMATED_AVG = 0 across all data

### Phase 2: MAE Analytics
- [x] Create MAE-only analytics view for NO_PROP_LINE predictions (2 views created)
- [x] Add MAE metrics to daily grading report (updated grading_alert v2.0)

### Phase 3: Monitoring
- [x] Add ESTIMATED_AVG reappearance monitoring alert (CRITICAL alert if count > 0)
- [x] Add NO_PROP_LINE percentage monitoring (WARNING if > 40%)
- [x] Deploy grading-delay-alert v2.0 (revision 00003-peh)

### Phase 4: Documentation
- [x] Document historical data state and line source semantics (LINE-SOURCE-REFERENCE.md)

---

## Historical Analysis Results (2026-01-23)

### Line Source Distribution by Season

| Season | Total | ACTUAL_PROP | VEGAS_BACKFILL | NO_PROP_LINE | NO_VEGAS_DATA | % Gradable |
|--------|-------|-------------|----------------|--------------|---------------|------------|
| 2021-22 | 116,734 | 13,775 | 46,277 | 15,635 | 41,047 | 51.4% |
| 2022-23 | 108,137 | 13,605 | 44,573 | 11,954 | 38,005 | 53.8% |
| 2023-24 | 109,035 | 14,751 | 49,323 | 11,172 | 33,789 | 58.8% |
| 2024-25 | 158,985 | 44,567 | 62,804 | 23,250 | 28,364 | 67.1% |

**Key observations:**
- Gradable percentage improving over time (51% → 67%)
- 2024-25 has highest volume and best line coverage
- NO_PROP_LINE represents legitimate scenarios (role players without props)

### ESTIMATED_AVG Verification

```
ESTIMATED_AVG active predictions: 0 ✓
Total active predictions: 492,891
```

### Grading Table Analysis (CatBoost v8, 2024-25)

| Line Source | Graded | Win Rate | MAE |
|-------------|--------|----------|-----|
| ACTUAL_PROP | 20,052 | 77.1% | 5.03 |
| VEGAS_BACKFILL | 30 | 90.0% | 3.69 |

**Note:** Win rate calculated excluding NULL prediction_correct (PASS/HOLD recommendations).

### Recommendation Distribution (2024-25)

| Line Source | OVER | UNDER | PASS | NO_LINE |
|-------------|------|-------|------|---------|
| ACTUAL_PROP | 9,963 | 34,810 | 11,421 | - |
| VEGAS_BACKFILL | 4,899 | 17,860 | 34,290 | - |
| NO_VEGAS_DATA | - | - | - | 25,423 |

---

## Line Source Semantics

| Source | Meaning | Gradable | Has Real Line |
|--------|---------|----------|---------------|
| ACTUAL_PROP | Live betting line from OddsAPI or BettingPros | ✓ | ✓ |
| VEGAS_BACKFILL | Historical line from BettingPros (pre-game snapshot) | ✓ | ✓ |
| NO_PROP_LINE | No betting line available (role player) | MAE only | ✗ |
| NO_VEGAS_DATA | No Vegas data available | MAE only | ✗ |

### Column Meanings

| Column | Description |
|--------|-------------|
| `current_points_line` | Real Vegas line (NULL if none) |
| `estimated_line_value` | Player's L5 average (always populated) |
| `has_prop_line` | TRUE only for real lines |
| `line_source` | Category as above |
| `recommendation` | OVER/UNDER/PASS/HOLD/NO_LINE |
| `prediction_correct` | TRUE/FALSE/NULL (NULL for PASS/HOLD/NO_LINE) |

---

## Implementation Details

### MAE-Only Grading for NO_PROP_LINE

**Current state:** NO_PROP_LINE predictions are filtered out of grading entirely.

**Proposed change:** Include NO_PROP_LINE in grading but:
- Set `prediction_correct = NULL` (cannot evaluate betting accuracy)
- Compute `absolute_error` and `signed_error` normally
- Track MAE separately for analytics

**Benefits:**
- Measure point prediction accuracy for all players
- Compare MAE between players with/without props
- Identify if model performs better/worse on role players

### Monitoring Alerts

**ESTIMATED_AVG reappearance:**
- Query: `SELECT COUNT(*) FROM predictions WHERE line_source = 'ESTIMATED_AVG' AND is_active = TRUE`
- Alert threshold: count > 0
- Channel: #nba-alerts

**NO_PROP_LINE percentage:**
- Query: Daily percentage of predictions with NO_PROP_LINE
- Alert threshold: > 40% (indicates OddsAPI/BettingPros issues)
- Channel: #nba-alerts

---

## BigQuery Views Created

### nba_predictions.mae_by_line_source

Comprehensive view joining predictions with actuals for MAE calculation.

**Key columns:**
- `game_date`, `player_lookup`, `system_id`
- `predicted_points`, `actual_points`
- `absolute_error`, `signed_error`
- `line_source`, `has_real_line`

**Sample query:**
```sql
SELECT
  line_source,
  has_real_line,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae
FROM nba_predictions.mae_by_line_source
WHERE system_id = 'catboost_v8'
  AND game_date >= '2024-10-01'
GROUP BY 1, 2
```

### nba_predictions.daily_mae_summary

Pre-aggregated daily summary for monitoring dashboards.

**Key columns:**
- `game_date`, `system_id`
- `total_predictions`, `overall_mae`
- `with_line_count`, `with_line_mae`
- `no_line_count`, `no_line_mae`
- `pct_with_line`, `overall_bias`

---

## Key Finding: NO_PROP_LINE Has Lower MAE

Counterintuitively, predictions for players WITHOUT betting lines have **lower MAE** than those with lines:

| Line Source | MAE (2024-25) | Explanation |
|-------------|---------------|-------------|
| NO_PROP_LINE | 3.29 | Role players with consistent, low-variance scoring |
| ACTUAL_PROP | 4.25 | Stars with high-variance, harder to predict |

This makes sense: role players typically score 0-10 points consistently, while stars have more variable games (10-40+ range).

**Bias:** NO_PROP_LINE predictions show slight positive bias (+0.82) - model over-predicts role player points slightly.

---

## Related Documents

- [Line Source Reference Guide](./LINE-SOURCE-REFERENCE.md) - Definitive reference for line sources
- [ESTIMATED_AVG Design Flaw](../../09-handoff/2026-01-23-ESTIMATED-LINE-DESIGN-FLAW.md)
- [Cleanup Complete Handoff](../../09-handoff/2026-01-23-CLEANUP-COMPLETE-HANDOFF.md)
- [Historical Line Source Handoff](../../09-handoff/2026-01-23-HISTORICAL-LINE-SOURCE-HANDOFF.md)
