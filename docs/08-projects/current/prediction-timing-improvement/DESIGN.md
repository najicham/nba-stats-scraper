# Prediction Timing Improvement - Design Document

**Created**: February 2, 2026
**Session**: 73
**Status**: Design

---

## Problem Statement

**Current State:**
- Predictions triggered at 6:15 AM ET
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
| 2:00 AM | 80-85% | Morning line scrape |
| 7:00 AM | 80-85% | No change (business hours just starting) |
| 10:00 AM | 85-90% | Midday updates |
| 3:00 PM | 90-95% | Pregame updates |

**Key Insight:** Most lines are available very early (2 AM). The 15-20% added later are typically:
- Role players
- Players on late injury reports
- Lines for late games (West Coast)

---

## Proposed Solution

### Key Insight

Sportsbooks only offer lines for ~40-50% of players (starters + key rotation). Bench players rarely get lines. The quality gate should NOT block predictions because bench players lack lines.

**Actual line availability (Feb 1 example):**
- 2 AM ET: 144 players have lines (from BettingPros)
- Throughout day: Grows to 177 players by 7 PM
- Total players in context: 326
- Coverage: 44-54% (but these are the IMPORTANT players)

### 1. Line Quality Gate (IMPLEMENTED)

Added `validate_line_coverage()` to `DataFreshnessValidator`:
- Tracks real line coverage for visibility
- Logs coverage at startup (warning if low)
- Can be used to SKIP predictions entirely (optional)

```python
valid, reason, details = validator.validate_line_coverage(game_date, min_coverage_pct=70.0)
# details['line_coverage_pct'] = 44.0  # Example
```

### 2. Prediction Strategy: Real Lines Only Mode

**New approach:** Instead of blocking all predictions or using estimates:

1. **`REQUIRE_REAL_LINES = True`** (new coordinator config)
2. Only generate predictions for players WITH real lines
3. Skip players without lines (no estimated predictions)
4. Track `line_source` in predictions: `'real'` or `'estimated'`

**Benefits:**
- Quality predictions only (no estimates to re-run)
- Earlier predictions for players with lines (2 AM vs 6 AM)
- Clear visibility into which predictions have real data

### 3. New Prediction Schedule

| Job | Time (ET) | Purpose | Expected Players |
|-----|-----------|---------|-----------------|
| `predictions-early` | 2:30 AM | First batch with real lines | ~140 players |
| `predictions-morning` | 7:00 AM | Catch any new lines | ~5-10 new players |
| `predictions-midday` | 12:00 PM | Final refresh | ~10-20 new players |

### 4. Tracking Prediction Quality

Add to `player_prop_predictions` table:
- `line_source`: `'odds_api'`, `'bettingpros'`, `'estimated'`
- `prediction_batch`: `'early'`, `'morning'`, `'midday'`

Query to see prediction quality:
```sql
SELECT line_source, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY line_source
```

---

## Implementation Plan

### Phase 1: Quality Gate (This Session)

1. Add `validate_line_coverage()` to `DataFreshnessValidator`
2. Add `line_coverage_pct` to coordinator startup logging
3. Add `REQUIRE_REAL_LINES = True` flag (can disable for testing)

### Phase 2: Earlier Scheduling (Future)

1. Create `predictions-early` scheduler job at 2:30 AM ET
2. Modify coordinator to check line quality gate before proceeding
3. Add Slack notification when predictions skip due to low line coverage

### Phase 3: Refresh Predictions (Future)

1. Add `line_source` column to `player_prop_predictions` table
2. Create `predictions-refresh` job that only updates estimated→real
3. Track refresh metrics

---

## Files to Modify

| File | Change |
|------|--------|
| `predictions/coordinator/data_freshness_validator.py` | Add `validate_line_coverage()` |
| `predictions/coordinator/coordinator.py` | Call line validation at startup |
| `config/workflows.yaml` | Update prediction timing (Phase 2) |

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| % predictions with real lines | ~0% at 6:15 AM | 70%+ |
| Time to first prediction | 6:15 AM | 2:30 AM (if quality met) |
| Predictions needing refresh | Unknown | Tracked |

---

## Risks

| Risk | Mitigation |
|------|------------|
| No predictions if lines never arrive | 7 AM fallback with lower threshold |
| Refresh causing duplicates | Use MERGE with update logic |
| Over-complicated scheduling | Start simple, add complexity only if needed |
