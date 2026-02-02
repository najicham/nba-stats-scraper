# Prediction Timing Improvement - Design Document

**Created**: February 2, 2026
**Session**: 73 (Design), 74 (Implementation)
**Status**: IMPLEMENTED ✅

---

## Problem Statement

**Current State:**
- Predictions triggered at 7:00 AM ET
- Vegas lines available at 2:00 AM ET (80%+ of players)
- Predictions run WITHOUT real lines - silently fall back to estimated lines (season averages)
- Result: Lower quality predictions that may need re-running

**User Requirement:**
- Run predictions as soon as quality data is available
- Don't run with estimated lines that need re-running
- Update predictions when more lines become available

---

## Line Availability Analysis

| Time (ET) | Players with Lines | Source |
|-----------|-------------------|--------|
| 2:00 AM | 80-85% (~144 players) | BettingPros morning scrape |
| 7:00 AM | 80-85% | No change (business hours just starting) |
| 10:00 AM | 85-90% | Midday updates |
| 3:00 PM | 90-95% | Pregame updates |

**Key Insight:** Most lines are available very early (2 AM). The 15-20% added later are typically:
- Role players
- Players on late injury reports
- Lines for late games (West Coast)

---

## Solution (IMPLEMENTED in Session 74)

### 1. REQUIRE_REAL_LINES Mode ✅

Added `require_real_lines` parameter to coordinator:

```python
# Request to /start endpoint
{
    "game_date": "TODAY",
    "require_real_lines": true,  # Only predict players WITH real lines
    "force": true
}
```

**Implementation:**
- `player_loader.create_prediction_requests()` - Added `require_real_lines` parameter
- `coordinator.py` /start endpoint - Accepts and passes parameter
- Players with `line_source='NO_PROP_LINE'` are filtered out when `require_real_lines=True`

### 2. Early Prediction Scheduler ✅

Created `predictions-early` scheduler:

| Job | Schedule | Mode | Expected |
|-----|----------|------|----------|
| `predictions-early` | 2:30 AM ET | REAL_LINES_ONLY | ~140 players |
| `overnight-predictions` | 7:00 AM ET | ALL_PLAYERS | ~200 players |
| `same-day-predictions` | 11:30 AM ET | ALL_PLAYERS | Catch stragglers |

**Setup Script:** `bin/orchestrators/setup_early_predictions_scheduler.sh`

### 3. Line Source Tracking ✅

Already implemented in schema:
- `line_source`: 'ACTUAL_PROP', 'NO_PROP_LINE', 'ESTIMATED_AVG'
- `line_source_api`: 'ODDS_API', 'BETTINGPROS', NULL
- `sportsbook`: 'DRAFTKINGS', 'FANDUEL', etc.

**Query to verify:**
```sql
SELECT line_source, line_source_api, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY 1, 2
```

---

## Files Modified (Session 74)

| File | Change |
|------|--------|
| `predictions/coordinator/player_loader.py` | Added `require_real_lines` parameter |
| `predictions/coordinator/coordinator.py` | Accept and pass `require_real_lines` |
| `bin/orchestrators/setup_early_predictions_scheduler.sh` | New scheduler script |

---

## Prediction Schedule (Updated)

| Job | Time (ET) | Mode | Purpose |
|-----|-----------|------|---------|
| `predictions-early` | 2:30 AM | REAL_LINES_ONLY | First batch with real lines |
| `overnight-predictions` | 7:00 AM | ALL_PLAYERS | Full run including NO_PROP_LINE |
| `same-day-predictions` | 11:30 AM | ALL_PLAYERS | Catch late additions |
| `same-day-predictions-tomorrow` | 6:00 PM | ALL_PLAYERS | Next day predictions |

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| Time to first prediction | 7:00 AM | 2:30 AM |
| % predictions with real lines (early) | N/A | 100% |
| Players predicted early | 0 | ~140 |

---

## Verification

```bash
# Check scheduler exists
gcloud scheduler jobs describe predictions-early --location=us-west2

# Check line availability for today
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT player_lookup) as players_with_lines
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL"

# Check predictions have real lines
bq query --use_legacy_sql=false "
SELECT line_source, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY line_source"
```

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| No predictions if lines never arrive | 7 AM fallback runs ALL_PLAYERS mode |
| Early predictions miss late-added players | 7 AM and 11:30 AM schedulers catch them |
| Scheduler fails silently | Existing prediction monitoring alerts |
