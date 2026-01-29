# Grading Deep Dive Investigation - 2026-01-29

## Status: RESOLVED

Investigation into why grading coverage was incomplete for some dates. Found two key issues:
1. **Duplicate predictions** with different line values for the same player/system/game (INTENTIONAL - line sensitivity)
2. **Production write failures** during grading that don't occur locally (FIXED - manual backfill completed)

## Resolution Summary

- **Fixed**: NAType handling bug in `get_actuals_for_date()` - now uses `pd.notna()` instead of `is not None`
- **Backfilled**: Jan 23-25 grading via local execution
- **Documented**: Line sensitivity feature and its impact on grading

### Final Grading Coverage

| Date       | Graded | Active | Voided |
|------------|--------|--------|--------|
| 2026-01-28 | 2,582  | 2,479  | 103    |
| 2026-01-27 | 612    | 571    | 41     |
| 2026-01-26 | 723    | 670    | 53     |
| 2026-01-25 | 685    | 665    | 20     |
| 2026-01-24 | 124    | 124    | 0      |
| 2026-01-23 | 1,294  | 1,289  | 5      |

## Executive Summary (Original)

## Issue 1: Duplicate Predictions

### Discovery

For Jan 23, we found:
- 1294 total ACTUAL_PROP predictions
- 392 unique business keys (player_lookup + system_id + game_id)
- **902 duplicates (70%)**

### Example: aaronnesmith on 2026-01-23

```
player_lookup | system_id    | game_id          | line_value | created_at
--------------+--------------+------------------+------------+---------------------
aaronnesmith  | catboost_v8  | 20260123_IND_OKC | 13.5       | 2026-01-23 22:00:02
aaronnesmith  | catboost_v8  | 20260123_IND_OKC | 12.5       | 2026-01-23 22:00:02
aaronnesmith  | catboost_v8  | 20260123_IND_OKC | 10.5       | 2026-01-23 22:00:02
aaronnesmith  | catboost_v8  | 20260123_IND_OKC | 9.5        | 2026-01-23 22:00:02
aaronnesmith  | catboost_v8  | 20260123_IND_OKC | 11.5       | 2026-01-23 15:05:59
```

**5 predictions for the same player/system/game** with different line values (9.5, 10.5, 11.5, 12.5, 13.5).

### Duplicate Count by Date

| Date       | Total | Unique Keys | Duplicates | Dup % |
|------------|-------|-------------|------------|-------|
| 2026-01-28 | 447   | 136         | 311        | 70%   |
| 2026-01-27 | 612   | 612         | 0          | 0%    |
| 2026-01-26 | 723   | 683         | 40         | 6%    |
| 2026-01-25 | 858   | 737         | 121        | 14%   |
| 2026-01-24 | 154   | 149         | 5          | 3%    |
| 2026-01-23 | 1294  | 392         | 902        | 70%   |

### Root Cause Analysis

The prediction system intentionally generates predictions at **multiple line levels** to show:
- What the recommendation would be at line=9.5
- What the recommendation would be at line=10.5
- etc.

This is a **feature**, not a bug - it allows evaluation of predictions across different betting scenarios.

However, for **grading purposes**, we need to decide:
1. Which line to grade against (the actual prop line that was available?)
2. How to handle multiple predictions per business key

### Proposed Solution

**Option A: Grade only the "primary" prediction**
- Add a `is_primary_line` flag to predictions
- Only grade predictions where is_primary_line = TRUE
- The primary line would be the actual market line at game time

**Option B: Grade all line variants separately**
- Include line_value in the business key
- Grade each prediction independently
- This provides more granular accuracy analysis

**Option C: Deduplicate at grading time**
- In the grading processor, pick the most recent prediction per business key
- Or pick the prediction closest to the actual market line

## Issue 2: Production Write Failures

### Symptom

Grading runs in production but only writes partial results:
- Jan 23: Should write 1294 records, only 21 written
- All 4 graded players are from one game (HOU_DET)

### Local Test Results

Running grading locally works perfectly:
```
Loading predictions... Found 1294 predictions (67 unique players)
Loading actuals... Found 281 player actuals
Grading... Total graded: 1294 (all successful)
Sanitization... All 1294 records sanitized successfully
```

### Cloud Function Logs

```
2026-01-29 23:38:41 Low actuals coverage for 2026-01-23: 7.2% (281 actuals / 3891 predictions)
```

The function runs but something fails during the BigQuery write.

### Possible Causes

1. **Timeout**: 60-second timeout may not be enough for 1294 records
2. **Unique constraint violation**: If prediction_accuracy table has constraints
3. **Race condition**: Multiple grading runs interfering
4. **Memory limit**: Cloud Function memory exhaustion

### Investigation Needed

1. Check prediction_accuracy table for unique constraints
2. Check Cloud Function memory and timeout settings
3. Review BigQuery load job logs for errors
4. Test with smaller batch sizes

## Action Items

### Immediate (P1)

- [ ] Understand why Jan 23 grading only partially completed
- [ ] Check Cloud Function configuration (memory, timeout)
- [ ] Review BigQuery table constraints

### Short-term (P2)

- [ ] Decide on grading strategy for duplicate predictions
- [ ] Implement deduplication in grading processor
- [ ] Add better error logging for write failures

### Long-term (P3)

- [ ] Review prediction generation to prevent excessive duplicates
- [ ] Add prediction deduplication at write time
- [ ] Improve grading monitoring and alerting

## Validation Queries

### Check Line Source Distribution
```sql
SELECT game_date, line_source, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-01-23' AND is_active = TRUE
GROUP BY 1, 2 ORDER BY 1 DESC, predictions DESC
```

### Check Grading Coverage by Line Source
```sql
WITH predictions AS (
  SELECT game_date, line_source, player_lookup, system_id
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= '2026-01-23' AND is_active = TRUE
),
graded AS (
  SELECT DISTINCT game_date, player_lookup, system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= '2026-01-23'
)
SELECT
  p.game_date, p.line_source,
  COUNT(*) as total,
  COUNTIF(g.player_lookup IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(g.player_lookup IS NOT NULL) / COUNT(*), 1) as graded_pct
FROM predictions p
LEFT JOIN graded g ON p.game_date = g.game_date
  AND p.player_lookup = g.player_lookup AND p.system_id = g.system_id
GROUP BY 1, 2 ORDER BY 1 DESC, total DESC
```

### Find Business Key Duplicates
```sql
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT CONCAT(player_lookup, '|', system_id, '|', game_id)) as unique_keys,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '|', system_id, '|', game_id)) as duplicates
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-01-23' AND is_active = TRUE AND line_source = 'ACTUAL_PROP'
GROUP BY 1 ORDER BY 1 DESC
```

---

*Created: 2026-01-29*
*Author: Claude Opus 4.5*
