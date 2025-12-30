# Investigation Report: Prediction Coverage Loss

**Date:** December 29, 2025
**Investigator:** Claude Code
**Severity:** CRITICAL

---

## Executive Summary

A deep investigation revealed that the prediction pipeline is experiencing **silent data loss** due to BigQuery's concurrent DML operation limits. While the system reports 100% success, 57% of predictions are being dropped.

---

## Timeline of Discovery

| Time (ET) | Event |
|-----------|-------|
| 2:45 PM | Coordinator started batch for Dec 29 |
| 2:47 PM | 158 prediction requests published to Pub/Sub |
| 2:47:51 | First DML rate limit errors appear in logs |
| 2:49 PM | Coordinator reports 158/158 complete (100% success) |
| 9:30 PM | Investigation reveals only 68 players in BigQuery |

---

## Issue #1: BigQuery DML Concurrency Limit (CRITICAL)

### The Problem

BigQuery enforces a hard limit of **20 concurrent DML operations per table**. Our prediction worker architecture violates this limit.

### Evidence from Logs

```
2025-12-29 19:47:58 - worker - ERROR - Error writing to BigQuery:
400 Resources exceeded during query execution: Too many DML statements
outstanding against table nba-props-platform:nba_predictions.player_prop_predictions,
limit is 20.
```

**Count of errors:** 90 (exactly matching 90 missing players)

### Current Architecture (Broken)

```
                    ┌─────────────────────────────────────┐
                    │      Prediction Coordinator         │
                    │    (publishes 158 messages)         │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │           Pub/Sub Topic             │
                    │      (prediction-request-prod)      │
                    └─────────────────┬───────────────────┘
                                      │
        ┌────────────┬────────────────┼────────────────┬────────────┐
        ▼            ▼                ▼                ▼            ▼
   ┌─────────┐  ┌─────────┐     ┌─────────┐     ┌─────────┐  ┌─────────┐
   │Worker 1 │  │Worker 2 │ ... │Worker 20│ ... │Worker 99│  │Worker100│
   │(5 thrd) │  │(5 thrd) │     │(5 thrd) │     │(5 thrd) │  │(5 thrd) │
   └────┬────┘  └────┬────┘     └────┬────┘     └────┬────┘  └────┬────┘
        │            │               │               │            │
        ▼            ▼               ▼               ▼            ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                    BigQuery MERGE Operations                     │
   │                                                                  │
   │   ✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓    ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ...    │
   │   └──── 20 succeed ────┘  └───────── 80+ fail (rate limited) ──┘ │
   │                                                                  │
   │                    LIMIT: 20 concurrent DML                      │
   └─────────────────────────────────────────────────────────────────┘
```

### Why This Wasn't Caught

1. **Worker returns 204 (success) even on write failure**
   - Code at `worker.py:1110`: `# Don't raise - log and continue (graceful degradation)`

2. **Coordinator tracks Pub/Sub completions, not BigQuery writes**
   - Progress tracker counts completion events, not actual database rows

3. **No monitoring for prediction count vs expected**
   - Dashboard shows "success" based on coordinator status

### Quantified Impact

| Metric | Expected | Actual | Loss |
|--------|----------|--------|------|
| Players with predictions | 158 | 68 | 90 (57%) |
| Total prediction rows | 3,950 | 1,700 | 2,250 (57%) |
| Systems per player | 5 | 5 | 0 |
| Lines per player | 5 | 5 | 0 |

---

## Issue #2: Player Lookup Normalization (HIGH)

### The Problem

15 players have betting lines (odds data) but no ML features because their `player_lookup` format differs between data sources.

### Affected Players

| Props Table Format | Issue |
|-------------------|-------|
| `garytrentjr` | Jr. suffix concatenated |
| `jabarismithjr` | Jr. suffix concatenated |
| `jaimejaquezjr` | Jr. suffix concatenated |
| `kevinporterjr` | Jr. suffix concatenated |
| `marvinbagleyiii` | III suffix concatenated |
| `michaelporterjr` | Jr. suffix concatenated |
| `timhardawayjr` | Jr. suffix concatenated |
| `treymurphyiii` | III suffix concatenated |
| `wendellcarterjr` | Jr. suffix concatenated |
| `alexsarr` | Unknown format issue |
| `boneshyland` | Unknown format issue |
| `carltoncarrington` | Unknown format issue |
| `herbjones` | Unknown format issue |
| `nicolasclaxton` | Unknown format issue |
| `robertwilliams` | Unknown format issue |

### Root Cause

The Odds API returns player names with suffixes concatenated (`garytrentjr`), while the feature store may use different formats or these players may not be in the roster data at all.

---

## Issue #3: Silent Failure Pattern (HIGH)

### The Problem

The system is designed for "graceful degradation" but this masks critical failures.

### Code Analysis

**Worker write failure handling (`worker.py:1108-1110`):**
```python
except Exception as e:
    logger.error(f"Error writing to BigQuery: {e}")
    # Don't raise - log and continue (graceful degradation)
```

**Worker HTTP response (`worker.py:318-319`):**
```python
logger.warning(f"No predictions generated for {player_lookup}")
return ('', 204)  # Still return success (graceful degradation)
```

### Impact

- Pub/Sub sees 204 = success, won't retry
- Coordinator counts completion = success
- User sees 100% success rate
- **57% of data is silently lost**

---

## Data Quality Analysis

### Feature Store Status

All 352 players in feature store have identical quality metrics:

| Metric | Value |
|--------|-------|
| feature_quality_score | 62.8 |
| is_production_ready | FALSE |
| completeness_percentage | 100.0 |
| backfill_bootstrap_mode | FALSE |

**Note:** Despite `is_production_ready=FALSE`, predictions are generated because `quality_score >= 50` passes the validation threshold.

### Context vs Feature Store Discrepancy

| Table | is_production_ready |
|-------|---------------------|
| upcoming_player_game_context | TRUE (all 352) |
| ml_feature_store_v2 | FALSE (all 352) |

This discrepancy should be investigated but is **not causing the prediction loss**.

---

## Verification Queries Used

### Count predictions by status
```sql
SELECT
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-12-29' AND is_active = TRUE;
-- Result: 1700 predictions, 68 players
```

### Find missing players
```sql
WITH context_players AS (
  SELECT player_lookup
  FROM nba_analytics.upcoming_player_game_context
  WHERE game_date = '2025-12-29'
    AND avg_minutes_per_game_last_7 >= 15
    AND is_production_ready = TRUE
),
predicted AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = '2025-12-29' AND is_active = TRUE
)
SELECT c.player_lookup
FROM context_players c
WHERE NOT EXISTS (SELECT 1 FROM predicted p WHERE p.player_lookup = c.player_lookup);
-- Result: 90 players missing
```

### Count BigQuery errors in logs
```bash
gcloud logging read 'textPayload=~"Too many DML statements"' --format="value(textPayload)" | wc -l
# Result: 90 errors
```

---

## Conclusions

1. **Primary Issue:** Architecture violates BigQuery's 20 concurrent DML limit
2. **Secondary Issue:** Silent failures mask data loss from monitoring
3. **Tertiary Issue:** Player lookup normalization gaps

The system is fundamentally broken for high-concurrency scenarios. A redesign of the write pattern is required.

---

## Next Steps

See [SOLUTION-OPTIONS.md](./SOLUTION-OPTIONS.md) for proposed fixes.
