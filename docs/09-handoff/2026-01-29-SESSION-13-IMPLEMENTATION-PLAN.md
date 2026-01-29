# Session 13 Implementation Plan - January 29, 2026

## Quick Wins Completed ✅

1. **Deactivated 2,174 duplicate predictions** - Only `ensemble_v1_1` remains active for 2026-01-28
2. **Triggered API export** for 2026-01-28
3. **Updated Firestore** Phase 3 completion to 5/5 for 2026-01-29

---

## P1 Fix #1: Prediction Deduplication

### Problem
Multiple model versions (v1, v8, ensemble_v1, ensemble_v1_1) all have `is_active=TRUE` for the same player/game.

### Root Cause
- Worker always sets `is_active=True` (line 1416 in worker.py)
- MERGE doesn't deactivate older predictions
- No post-MERGE cleanup of older model versions

### Solution
Add a deactivation step after MERGE to mark older predictions as inactive.

### File: `predictions/shared/batch_staging_writer.py`

**Location**: After line 650 (after MERGE completes), before post-consolidation validation (line 670)

**Add new method**:

```python
def _deactivate_older_predictions(self, game_date: str) -> int:
    """
    Deactivate older predictions for the same player/game, keeping only the newest.

    This handles cases where multiple model versions or multiple batches created
    predictions for the same player/game combination.

    Args:
        game_date: Game date to process

    Returns:
        Number of predictions deactivated
    """
    main_table = f"{self.project_id}.{self.staging_dataset}.{MAIN_PREDICTIONS_TABLE}"

    # Deactivate all but the newest prediction per player/game
    # Uses ROW_NUMBER to identify the newest by created_at
    deactivation_query = f"""
    UPDATE `{main_table}` T
    SET is_active = FALSE,
        updated_at = CURRENT_TIMESTAMP()
    WHERE game_date = '{game_date}'
      AND is_active = TRUE
      AND prediction_id IN (
        SELECT prediction_id
        FROM (
          SELECT
            prediction_id,
            ROW_NUMBER() OVER (
              PARTITION BY game_id, player_lookup
              ORDER BY created_at DESC
            ) as row_num
          FROM `{main_table}`
          WHERE game_date = '{game_date}'
            AND is_active = TRUE
        )
        WHERE row_num > 1
      )
    """

    try:
        query_job = self.bq_client.query(deactivation_query)
        query_job.result(timeout=60)
        deactivated = query_job.num_dml_affected_rows or 0

        if deactivated > 0:
            logger.info(
                f"Deactivated {deactivated} older predictions for game_date={game_date}"
            )
        return deactivated

    except Exception as e:
        logger.error(f"Failed to deactivate older predictions: {e}", exc_info=True)
        return 0
```

**Modify `_consolidate_with_lock` method** (around line 650):

```python
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"MERGE complete: {rows_affected} rows affected in {elapsed_ms:.1f}ms (batch={batch_id})"
            )

            # NEW: Deactivate older predictions after MERGE
            # This ensures only the newest prediction per player/game is active
            logger.info(f"Deactivating older predictions for game_date={game_date}...")
            deactivated = self._deactivate_older_predictions(game_date)
            if deactivated > 0:
                logger.info(f"Deactivated {deactivated} older predictions")

            # CRITICAL: Check if MERGE actually wrote data
            # ... rest of existing code
```

---

## P1 Fix #2: DNP Flag Detection

### Problem
Players with `minutes_played=0` have `is_dnp=NULL` instead of `TRUE`.

### Root Causes
1. Extraction query filters `player_status = 'active'` only (line 608)
2. No DNP categorization logic in record building

### Solution
Modify extraction query and add DNP detection logic.

### File: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Change 1**: Modify extraction query (line 607-608)

```python
# BEFORE:
FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    AND player_status = 'active'

# AFTER:
FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    AND player_status IN ('active', 'dnp', 'inactive')
```

**Change 2**: Add DNP fields to SELECT (around line 599)

```python
# Add to SELECT clause:
player_status,
dnp_reason,
```

**Change 3**: Add helper method for DNP categorization (add as new method in class)

```python
def _categorize_dnp_reason(self, reason_text: Optional[str]) -> Optional[str]:
    """
    Categorize DNP reason into standard categories.

    Args:
        reason_text: Raw reason from gamebook

    Returns:
        Category: 'injury', 'rest', 'coach_decision', 'personal', or 'other'
    """
    if not reason_text:
        return None

    reason_lower = str(reason_text).lower()

    # Injury patterns
    if any(word in reason_lower for word in [
        'injury', 'injured', 'illness', 'sprain', 'strain',
        'sore', 'pain', 'surgery', 'concussion', 'knee',
        'ankle', 'back', 'hamstring', 'shoulder'
    ]):
        return 'injury'

    # Rest patterns
    if any(word in reason_lower for word in [
        'rest', 'load management', 'recovery', 'maintenance'
    ]):
        return 'rest'

    # Personal patterns
    if any(word in reason_lower for word in [
        'personal', 'family', 'birth', 'funeral'
    ]):
        return 'personal'

    # Coach decision patterns
    if any(word in reason_lower for word in [
        'coach', 'decision', 'not with team', 'suspension'
    ]):
        return 'coach_decision'

    return 'other'
```

**Change 4**: Modify record building in `_process_record` (around line 1523-1525)

```python
# BEFORE:
'is_active': bool(row['player_status'] == 'active'),
'player_status': row['player_status'],

# AFTER:
'is_active': bool(row['player_status'] == 'active'),
'player_status': row['player_status'],
'is_dnp': row['player_status'] in ('dnp', 'inactive') or (
    row.get('minutes_decimal', 0) == 0 and row['player_status'] == 'active'
),
'dnp_reason': row.get('dnp_reason') if row['player_status'] != 'active' else None,
'dnp_reason_category': self._categorize_dnp_reason(row.get('dnp_reason')) if row['player_status'] != 'active' else None,
```

---

## P3 Fix: Morning Health Check False Alarm

### Problem
Morning health check flags 65% minutes coverage as CRITICAL, but 112 players are legitimate DNPs.

### File: `bin/monitoring/morning_health_check.sh`

**Modify the coverage calculation** to exclude DNPs:

```sql
-- BEFORE:
ROUND(100.0 * COUNTIF(minutes_played > 0) / COUNT(*), 1) as minutes_pct

-- AFTER:
ROUND(100.0 * COUNTIF(minutes_played > 0) / NULLIF(COUNTIF(is_dnp = FALSE OR is_dnp IS NULL), 0), 1) as minutes_pct
```

**Add DNP count to output**:
```sql
COUNTIF(is_dnp = TRUE) as dnp_count,
```

---

## Testing Plan

### For Fix #1 (Prediction Deduplication)
```bash
# 1. Run prediction worker for a test game
# 2. Verify only one active prediction per player/game:
bq query "
SELECT player_lookup, game_id, COUNT(*) as active_count
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-01-29')
  AND is_active = TRUE
GROUP BY 1, 2
HAVING COUNT(*) > 1"
# Should return 0 rows
```

### For Fix #2 (DNP Detection)
```bash
# 1. Reprocess a game with known DNPs:
python -c "
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
p = PlayerGameSummaryProcessor()
p.run({'start_date': '2026-01-28', 'end_date': '2026-01-28'})
"

# 2. Verify DNP flags set:
bq query "
SELECT player_lookup, is_dnp, dnp_reason, dnp_reason_category, minutes_played
FROM nba_analytics.player_game_summary
WHERE game_date = DATE('2026-01-28')
  AND minutes_played = 0
LIMIT 10"
# Should show is_dnp=TRUE for all
```

---

## Deployment Order

1. **Fix #2 first** (DNP Detection) - no dependencies, safe to deploy
2. **Fix #3** (Morning Health Check) - depends on Fix #2 being deployed
3. **Fix #1 last** (Prediction Dedup) - most complex, test thoroughly

---

## Rollback Plan

### Fix #1 Rollback
```sql
-- If deactivation query causes issues, re-activate all predictions
UPDATE nba_predictions.player_prop_predictions
SET is_active = TRUE
WHERE game_date = DATE('2026-01-29')
  AND is_active = FALSE
  AND updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
```

### Fix #2 Rollback
- Revert extraction query to `player_status = 'active'`
- DNP records will stop appearing but won't break anything

---

## Estimated Impact

| Fix | Records Affected | Risk Level |
|-----|-----------------|------------|
| Prediction Dedup | ~1,500/day | Medium |
| DNP Detection | ~100-150/day | Low |
| Health Check | N/A (display only) | Very Low |

---

*Created: 2026-01-29 09:50 AM PT*
*Author: Claude Opus 4.5*
