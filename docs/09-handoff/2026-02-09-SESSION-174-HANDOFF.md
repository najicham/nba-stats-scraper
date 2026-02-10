# Session 174 Handoff

**Date:** 2026-02-09
**Previous:** Session 173 consolidated handoff (Sessions 170-172)

## What Was Done

### P1: Feb 9 Regeneration (Fixed UNDER bias in pre-fix predictions)

The Feb 9 FIRST-run predictions had avg_pvl = -3.84 (extreme UNDER bias) because they were generated before the Session 170-171 fixes were deployed. We regenerated them:

1. Used `/regenerate-with-supersede` endpoint to supersede old predictions and generate new ones
2. **Manual consolidation required** — see "Known Issues" below
3. Result: 82 active OVERNIGHT predictions with avg_pvl = +0.15 (healthy)

| Metric | Before (FIRST) | After (OVERNIGHT) |
|--------|---------------|-------------------|
| avg_pvl | -3.84 | **+0.15** |
| OVER % | 0% | **24.4%** |
| Active preds | 42 | **82** |

### P2: Session 172 Worker Fixes — Already Deployed

Both fixes (line_values type-check at line 1142, recovery_median log level at line 1152) were already in the codebase at commit `9795ea60`. No action needed.

### P3: OddsAPI Line Matching — Investigated

Line source breakdown shows highly variable OddsAPI matching:

| Date | Mode | OddsAPI | BettingPros | OddsAPI % |
|------|------|---------|-------------|-----------|
| Feb 7 | BACKFILL | 5 | 132 | 4% |
| Feb 8 | BACKFILL | 44 | 9 | 83% |
| Feb 9 | FIRST | 10 | 32 | 24% |

Root cause still unclear. Not correlated with run mode. Needs deeper investigation of `player_loader.py:_query_actual_betting_line()` and OddsAPI data timing.

### P5: Logging Verification

- Both services deployed at correct commit `9795ea60`
- Signal calculator: Working (Feb 5 errors were pre-deploy, now fixed)
- STALE_MESSAGE, PUBLISH_METRICS, CONSOLIDATION_METRICS all functional

---

## Known Issues Found This Session

### Issue 1: Regeneration Doesn't Auto-Consolidate (CRITICAL for future sessions)

**Problem:** The `/regenerate-with-supersede` endpoint publishes Pub/Sub messages to workers, who write to staging tables. But when the Firestore batch tracker is reset (via `/reset`), consolidation never triggers automatically. The staging tables sit orphaned.

**Root Cause:** The batch completion handler (which triggers consolidation) only runs when Firestore transitions a batch from incomplete→complete. If the batch is reset/force-completed via `/reset`, the in-memory tracker is cleared without running consolidation.

**Fix Required (for future sessions):** After any `/regenerate-with-supersede` + `/reset`, manually consolidate:

```python
PYTHONPATH=. python3 -c "
from google.cloud import bigquery
from predictions.shared.batch_staging_writer import BatchConsolidator

client = bigquery.Client(project='nba-props-platform')
consolidator = BatchConsolidator(client, 'nba-props-platform')

batch_id = 'YOUR_BATCH_ID_HERE'
tables = consolidator._find_staging_tables(batch_id)
print(f'Found {len(tables)} staging tables')

if tables:
    result = consolidator.consolidate_batch(batch_id=batch_id, game_date='YYYY-MM-DD', cleanup=True)
    print(f'Consolidated: {result.rows_affected} rows, success={result.success}')
"
```

**Better fix (code change):** Add auto-consolidation to the `/reset` endpoint, or add a standalone `/consolidate` endpoint. See coordinator.py line 2838.

### Issue 2: Workers Don't Report Completion for Quality-Blocked Players

**Problem:** When `/regenerate-with-supersede` publishes all 95 players to Pub/Sub (no quality gate at coordinator level), 13 workers that hit quality blocks (zero tolerance for defaults) ACK the Pub/Sub message (204) but never report completion back to the coordinator. The batch stalls at 82/95.

**Root Cause:** The quality gate is at the coordinator level for `/start` (pre-filters players before publishing), but `/regenerate-with-supersede` uses `_generate_predictions_for_date()` which bypasses the quality gate and publishes ALL players. Workers that skip quality-blocked players return 204 without calling `/completion`.

**Workaround:** After waiting 5-10 min, use `/check-stalled` to see progress. If stuck below 95%, use `/reset` + manual consolidation (Issue 1).

**Better fix (code change):** Either:
1. Add quality gate to `_generate_predictions_for_date()`, OR
2. Make workers report completion even for quality-skipped players

### Issue 3: Stale Batches Block New Runs

**Problem:** A stale batch from Feb 5 (`batch_2026-02-05_1770680838`) was blocking new `/start` requests. Required manual `/reset` to clear.

**Lesson:** Always check `/status` before triggering new runs. If a stale batch exists, `/reset` it first.

### Issue 4: Signal Calculator Includes Superseded Predictions

**Problem:** The signal calculator query (`signal_calculator.py` line 122-126) doesn't filter on `is_active = TRUE`. It counts ALL predictions including superseded ones, which inflates totals and skews over/under percentages.

**Impact:** Feb 9 signal showed 188 total picks (should be 82 active), 6.9% OVER (should be 24.4%).

**Fix:** Add `AND is_active = TRUE` to the signal calculator query.

---

## Pending Work

### P0: Verify Feb 10 FIRST-run (~6 AM ET tomorrow)

This is the first FIRST-run with all fixes deployed. The true validation moment.

```sql
SELECT prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1;
```

**Targets:** avg_pvl within +/-1.5, OVER% > 25%, no massive UNDER skew.

### P3 (continued): OddsAPI Line Matching Root Cause

Need to add diagnostic logging to `player_loader.py:_query_actual_betting_line()` to distinguish:
- "No OddsAPI data in BigQuery for this player" vs
- "Query timeout" vs
- "Player name format mismatch"

### P4: Hit Rate Investigation

Now that we have clean BACKFILL predictions for Feb 9, re-evaluate hit rate after games complete:

```sql
SELECT DATE_TRUNC(pa.game_date, WEEK) as week,
  COUNT(*) as graded, COUNTIF(pa.prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.player_prop_predictions p
  ON pa.player_lookup = p.player_lookup AND pa.game_date = p.game_date AND pa.system_id = p.system_id
WHERE pa.system_id = 'catboost_v9' AND pa.game_date >= '2026-01-12'
  AND pa.actual_points IS NOT NULL AND pa.line_value IS NOT NULL
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND p.is_active = TRUE AND p.prediction_run_mode = 'BACKFILL'
GROUP BY 1 ORDER BY 1;
```

### Fix Regeneration Auto-Consolidation (Medium — still pending)

Options:
1. Add `/consolidate` endpoint to coordinator
2. Have `/reset` trigger consolidation before clearing tracker
3. Have `_generate_predictions_for_date()` use the quality gate

---

## Code Changes Made This Session

### 1. Signal Calculator: Filter on `is_active = TRUE` (signal_calculator.py:125)

Added `AND is_active = TRUE` to the signal query so it only counts active predictions, not superseded ones. Without this, signals were inflated (188 total picks instead of 82 active).

### 2. Worker: Report completion for skipped players (worker.py:850-858, 868-873)

Added `publish_completion_event()` calls in two early-return paths:
- **Permanent skip reasons** (quality_too_low, invalid_features): line 854-858
- **Stale messages** (past-date transient failures): line 869-873

This fixes the root cause of regeneration batches stalling at <100% completion. Previously, quality-blocked workers ACK'd Pub/Sub but never told the coordinator they were done, causing the batch to wait forever for the missing 13 workers.

### Files Modified

| File | Change | Lines |
|------|--------|-------|
| `predictions/coordinator/signal_calculator.py` | Add `is_active = TRUE` filter | 125 |
| `predictions/worker/worker.py` | Report completion for permanent skips | 850-858 |
| `predictions/worker/worker.py` | Report completion for stale messages | 868-873 |

---

## Quick Reference: Regeneration Procedure

For future sessions that need to regenerate predictions:

```bash
# 1. Reset any stale batch
curl -X POST "$COORD_URL/reset" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{"game_date":"YYYY-MM-DD"}'

# 2. Regenerate with supersede
curl -X POST "$COORD_URL/regenerate-with-supersede" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{"game_date":"YYYY-MM-DD","reason":"description"}'

# 3. Wait 5-10 min, check progress
curl -X POST "$COORD_URL/check-stalled" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{}'

# 4. When progress stalls (quality-blocked workers), reset the batch
curl -X POST "$COORD_URL/reset" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{"batch_id":"BATCH_ID_FROM_STEP_2"}'

# 5. CRITICAL: Manually consolidate staging tables
PYTHONPATH=. python3 -c "
from google.cloud import bigquery
from predictions.shared.batch_staging_writer import BatchConsolidator
client = bigquery.Client(project='nba-props-platform')
consolidator = BatchConsolidator(client, 'nba-props-platform')
batch_id = 'BATCH_ID_FROM_STEP_2'
tables = consolidator._find_staging_tables(batch_id)
print(f'Found {len(tables)} staging tables')
if tables:
    result = consolidator.consolidate_batch(batch_id=batch_id, game_date='YYYY-MM-DD', cleanup=True)
    print(f'Consolidated: {result.rows_affected} rows, success={result.success}')
"

# 6. Verify results
bq query "SELECT prediction_run_mode, is_active, COUNT(*), ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl FROM nba_predictions.player_prop_predictions WHERE system_id='catboost_v9' AND game_date='YYYY-MM-DD' GROUP BY 1,2"
```
