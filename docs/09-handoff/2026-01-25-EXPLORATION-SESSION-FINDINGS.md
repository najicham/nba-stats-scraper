# Exploration Session Findings: 2026-01-25

**Session:** System exploration following EXPLORATION-HANDOFF.md
**Focus:** Scraper resilience, data processor edge cases, prediction duplicates, data quality
**Status:** Investigation complete, findings documented

---

## Executive Summary

This session discovered **9 new issues** in addition to confirming existing problems:

| Priority | Issue | Impact |
|----------|-------|--------|
| **P0** | Prediction duplicates: 6,473 extra rows | Data integrity, storage costs |
| **P0** | nbac_player_boxscore scraper failing | Missing 2026-01-24 data |
| **P1** | 618 orphaned analytics records | Data consistency |
| **P1** | Scraper resilience gaps (8 issues) | API failures cascade |
| **P1** | Processor silent record skipping | Data loss undetected |
| **P2** | No phase transitions in 48 hours | Potential orchestration issue |
| **P2** | Three uncoordinated retry systems | Inconsistent resilience |
| **P2** | Streaming buffer row loss | Rows skipped without retry |
| **P3** | Batch size hardcoding | Memory pressure risk |

---

## Issue #1: Prediction Duplicates (P0 - CRITICAL)

### Evidence

```sql
-- 1,692 duplicate business keys with 6,473 extra rows
SELECT COUNT(*) as duplicate_key_combinations, SUM(cnt - 1) as extra_rows
FROM (
  SELECT game_id, player_lookup, system_id,
         CAST(COALESCE(current_points_line, -1) AS INT64) as line,
         COUNT(*) as cnt
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= '2026-01-15'
  GROUP BY 1, 2, 3, 4
  HAVING COUNT(*) > 1
)
-- Result: 1,692 combinations, 6,473 extra rows
```

### Root Cause Analysis

1. **Multiple prediction batches** run at different times (13:28:50, 15:06:07, 22:00:02)
2. **NULL current_points_line** records are duplicated despite COALESCE(-1) fix
3. Example: dariusgarland on 2026-01-19 has **10 NULL duplicates** per system_id
4. Each batch consolidates separately, finding "NOT MATCHED" when it should find "MATCHED"

### Affected Code

- **File:** `predictions/shared/batch_staging_writer.py:330-347`
- **Issue:** MERGE with COALESCE(-1) isn't preventing NULL duplicates across batches
- **Root cause:** Distributed lock is per-game_date but multiple batch_ids can run for same game_date

### Recommended Fix

```sql
-- Option 1: Add UNIQUE constraint on business key
ALTER TABLE nba_predictions.player_prop_predictions
ADD CONSTRAINT unique_prediction_key
UNIQUE (game_id, player_lookup, system_id, current_points_line);

-- Option 2: Cleanup query
DELETE FROM nba_predictions.player_prop_predictions
WHERE prediction_id NOT IN (
  SELECT MIN(prediction_id)
  FROM nba_predictions.player_prop_predictions
  GROUP BY game_id, player_lookup, system_id,
           CAST(COALESCE(current_points_line, -1) AS INT64)
);
```

---

## Issue #2: nbac_player_boxscore Scraper Failing (P0)

### Evidence

```
Error: Max decode/download retries reached: 8
URL: https://stats.nba.com/stats/leaguegamelog?Counter=1000&DateFrom=2026-01-24&...
Exception: NoHttpStatusCodeException: No status_code on download response.
```

### Impact

- 2026-01-24 data only 85.7% complete (6/7 games)
- Grading at 42.9% for 2026-01-24
- 1 pending processor in failed_processor_queue

### Root Cause

NBA.com API returning no HTTP status code (possible rate limiting or blocking)

### Location

- **File:** `scrapers/scraper_base.py:2476` - `check_download_status()` raises NoHttpStatusCodeException

---

## Issue #3: Scraper Resilience Gaps (P1)

### Finding 3.1: BDL Pagination Partial Data Loss

**File:** `scrapers/balldontlie/bdl_player_box_scores.py:306-324`

When pagination fails mid-request:
- Partial data from successful pages is **lost**
- No fallback to return collected data
- Error notification logs `rows_so_far` but doesn't save them

### Finding 3.2: Three Uncoordinated Retry Systems

| System | File | Threshold | Cooldown |
|--------|------|-----------|----------|
| ProxyCircuitBreaker | proxy_utils.py | 3 failures | 5 min |
| ProxyManager | proxy_manager.py | Score < 20 | 60s × 2^n |
| RateLimitHandler | rate_limit_handler.py | 5 retries | 2-120s |

**Problem:** No coordination between systems, inconsistent behavior

### Finding 3.3: HTTP Timeout May Be Insufficient

**File:** `scrapers/scraper_base.py:222`

```python
timeout_http = 20  # 20 seconds default
```

Large dataset responses may exceed 20s, especially BDL pagination

### Finding 3.4: Circuit Breaker Opens Too Aggressively

**File:** `scrapers/utils/proxy_utils.py:46`

```python
failure_threshold: int = 3  # Opens after just 3 failures
```

Temporary rate limits trigger circuit breaker, blocking proxies unnecessarily

---

## Issue #4: Processor Silent Record Skipping (P1)

### Finding 4.1: Records Filtered Without Tracking

**File:** `data_processors/raw/balldontlie/bdl_player_box_scores_processor.py:175-327`

```python
for stat in stats:
    if not game or not team or not player:
        skipped_count += 1
        continue  # Silent skip - no per-record details
```

Individual failures hidden, only total logged

### Finding 4.2: Smart Idempotency Hides Data Gaps

**File:** `data_processors/raw/smart_idempotency_mixin.py:288-420`

When hash matches existing data, write skipped entirely:
- No validation if data is complete
- Partial upstream failures not detected on re-run

### Finding 4.3: Streaming Buffer Rows Lost

**File:** `data_processors/raw/processor_base.py:1296-1323`

```python
if "streaming buffer" in str(load_e).lower():
    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
    self.stats["rows_skipped"] = len(rows)
    return  # Rows NOT retried in this run
```

---

## Issue #5: 618 Orphaned Analytics Records (P1)

### Evidence

```sql
SELECT COUNT(*) as orphaned
FROM nba_analytics.player_game_summary a
LEFT JOIN nba_raw.bdl_player_boxscores b
  ON a.game_id = b.game_id
  AND a.player_lookup = b.player_lookup
  AND b.game_date >= '2026-01-01'
WHERE b.player_lookup IS NULL AND a.game_date >= '2026-01-01'
-- Result: 618 orphaned records
```

Analytics records exist without matching raw boxscores

---

## Issue #6: No Phase Transitions in 48 Hours (P2)

### Evidence

From workflow_health.py:
```
🟠 phase_transitions: No phase transitions in last 48 hours
```

### Potential Causes

1. Orchestration stopped/paused
2. No games in window (unlikely - schedule shows 7 games on 2026-01-24)
3. Phase transition logging broken

---

## Issue #7: Processor Completion Issues (P2)

### Evidence

```
🟡 processor_completions: 2 processors with low completion rate
- nbac_player_boxscore: 1 start, 0 completions, 1 error
- bdl_player_box_scores_scraper: 1 start, 0 completions, 0 errors
```

---

## Issue #8: Batch Size Hardcoding (P3)

### Finding 8.1: Fixed 1000-record batches

**File:** `data_processors/reference/base/database_strategies.py:70`

```python
batch_size = 1000  # No adjustment for record size or memory
```

### Finding 8.2: ML Feature Store uses smaller batches

**File:** `data_processors/precompute/ml_feature_store/batch_writer.py:460`

```python
BATCH_SIZE = 100  # Hardcoded, no configuration
```

---

## Current System Health Summary

### Data Completeness (Last 3 Days)

| Date | Expected | BDL | Analytics | Grading |
|------|----------|-----|-----------|---------|
| 2026-01-24 | 7 | 85.7% | 85.7% | 42.9% |
| 2026-01-23 | 8 | 100% | 100% | 87.5% |
| 2026-01-22 | 8 | 100% | 100% | 87.5% |

### Phase Transitions (Last 3 Days)

| Date | Status | Bottleneck |
|------|--------|------------|
| 2026-01-24 | PARTIAL | schedule → boxscores (85.7%) |
| 2026-01-23 | OK | - |
| 2026-01-22 | PARTIAL | features → predictions (45.8%) |

### Failed Processor Queue

| Game Date | Processor | Status | Retries | Error |
|-----------|-----------|--------|---------|-------|
| 2026-01-24 | nbac_player_boxscore | pending | 0 | Max decode/download retries reached: 8 |

---

## Recommended Immediate Actions

### 1. Fix Prediction Duplicates (P0)

```sql
-- Run cleanup query to remove 6,473 extra rows
DELETE FROM nba_predictions.player_prop_predictions
WHERE prediction_id NOT IN (
  SELECT MIN(prediction_id)
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= '2026-01-15'
  GROUP BY game_id, player_lookup, system_id,
           CAST(COALESCE(current_points_line, -1) AS INT64)
);
```

### 2. Retry nbac_player_boxscore (P0)

```bash
# Manual retry with longer timeout
python -c "
from scrapers.nbacom.nbac_player_boxscore import NbacPlayerBoxscoreScraper
scraper = NbacPlayerBoxscoreScraper()
scraper.timeout_http = 60  # Increase timeout
scraper.run(game_date='2026-01-24')
"
```

### 3. Investigate Phase Transitions (P2)

```sql
-- Check if phase transitions are being logged
SELECT * FROM nba_orchestration.phase_transitions
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR)
ORDER BY timestamp DESC
LIMIT 20;
```

---

## Files Changed/Reviewed

| File | Lines | Finding |
|------|-------|---------|
| predictions/shared/batch_staging_writer.py | 1-822 | Duplicate root cause |
| scrapers/scraper_base.py | 2476 | NoHttpStatusCodeException |
| scrapers/balldontlie/bdl_player_box_scores.py | 306-324 | Partial data loss |
| scrapers/utils/proxy_utils.py | 46 | Circuit breaker threshold |
| data_processors/raw/processor_base.py | 1296-1323 | Streaming buffer skip |
| data_processors/raw/smart_idempotency_mixin.py | 288-420 | Hash skip issue |

---

## Next Steps

1. **Immediate:** Clean up prediction duplicates (6,473 rows)
2. **Immediate:** Manually retry nbac_player_boxscore for 2026-01-24
3. **Short-term:** Fix batch_staging_writer to prevent future duplicates
4. **Short-term:** Add per-record tracking to processors
5. **Medium-term:** Coordinate retry/circuit breaker systems
6. **Medium-term:** Add streaming buffer retry logic

---

*Created: 2026-01-25*
*Session Duration: ~1 hour*
*Issues Found: 9 (2 P0, 4 P1, 2 P2, 1 P3)*
