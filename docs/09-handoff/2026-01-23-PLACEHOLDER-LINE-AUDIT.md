# Placeholder Line (20.0) Audit Report

**Generated:** 2026-01-23 07:35 AM ET
**Author:** Claude Code Session

---

## Executive Summary

Found **919 predictions** across **6 dates** using the 20.0 placeholder line value:

| Date | Predictions | Players | Issue Type |
|------|-------------|---------|------------|
| 2026-01-21 | 869 | 156 | **CRITICAL**: odds_api failure, no bettingpros fallback |
| 2025-12-18 | 17 | 3 | ESTIMATED_AVG rounded to 20.0 |
| 2025-12-05 | 18 | 3 | ESTIMATED_AVG rounded to 20.0 |
| 2025-11-24 | 10 | 2 | ESTIMATED_AVG rounded to 20.0 |
| 2025-11-22 | 5 | 1 | ESTIMATED_AVG rounded to 20.0 |

---

## Critical Issue: Jan 21, 2026 (869 predictions)

### Root Cause
- `odds_api_player_points_props` table stopped receiving data after Jan 18
- No bettingpros fallback existed in the coordinator
- All 156 players received predictions with NULL line_source and 20.0 line

### Status
- **Fixed**: Bettingpros fallback added to player_loader.py
- **Regenerated**: New predictions generated with real lines
- **Deployment**: Coordinator with fix deployed (revision 00081-v8h)

---

## Historical 20.0 Lines (2025 Season)

These are legitimate cases where player averages rounded to exactly 20.0:

### Players Affected
| Player | Game Date | Actual Season Avg | Why 20.0? |
|--------|-----------|-------------------|-----------|
| giannisantetokounmpo | Nov 22, 24; Dec 5 | 22.1 PPG | L5 avg was ~20 at time |
| dariusgarland | Nov 24; Dec 5 | 21.0 PPG | L5 avg was ~20 at time |
| lukadoncic | Dec 5, 18 | 28.5 PPG | L5 avg was lower early season |
| deniavdija | Dec 18 | 24.8 PPG | L5 avg was ~20 at time |
| keyontegeorge | Dec 18 | 26.0 PPG | L5 avg was ~20 at time |

### Characteristics
- All have `line_source = ESTIMATED_AVG`
- All have `has_prop_line = false` (no betting line available)
- All have `estimation_method = points_avg_last_5`
- These are valid predictions for players without betting lines

---

## Fixes Implemented

### 1. Bettingpros Fallback (v3.8)
```python
# Now in _query_actual_betting_line():
# 1. Try odds_api first
# 2. Fallback to bettingpros if odds_api unavailable
```

### 2. 20.0 Avoidance (v3.9)
```python
# In _estimate_betting_line_with_method():
if estimated == 20.0:
    estimated = 20.5 if avg >= 20.0 else 19.5
```

### 3. Monitoring (v3.9)
- Added line source tracking (`_track_line_source`)
- Added batch summary logging (`get_line_source_stats`)
- Logs WARNING when bettingpros > odds_api
- Logs ERROR when no line available from either source

---

## Grading Impact

### Affected Predictions
- Jan 21, 2026: 869 predictions are UNGRADEABLE (line_source = NULL)
- These are filtered out by grading query:
  ```sql
  AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  ```

### Resolution
- Regenerate Jan 21 predictions with real bettingpros lines (COMPLETED)
- These will have `line_source = ACTUAL_PROP` or `BETTINGPROS`
- Grading can then proceed normally

---

## Recommendations

1. **Monitor odds_api health** - Investigate HTTP 400 errors in workflow executor
2. **Alert on fallback usage** - New logging will warn when bettingpros > odds_api
3. **Consider deprecating odds_api** - Bettingpros has 28K+ lines/day vs ~100 for odds_api
4. **Backfill grading** - Run grading for Jan 17-22 once predictions regenerated

---

## Query to Find Future Issues

```sql
-- Alert query: Find predictions with placeholder lines
SELECT game_date, COUNT(*) as placeholder_count
FROM `nba_predictions.player_prop_predictions`
WHERE current_points_line = 20.0
  AND is_active = TRUE
GROUP BY 1
ORDER BY 1 DESC
```
