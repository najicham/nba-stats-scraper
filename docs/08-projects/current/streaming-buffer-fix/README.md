# Streaming Buffer Duplicate Cleanup Fix

**Date:** 2026-01-30
**Session:** 28 Continuation
**Status:** Implemented, needs deployment and Cloud Scheduler setup

## Problem Summary

Duplicates accumulate in `player_prop_predictions` because the `_deactivate_older_predictions()` method runs immediately after MERGE consolidation, but the MERGE just inserted rows that are now in BigQuery's streaming buffer (locked for 30-90 minutes).

### Timeline of the Bug

```
07:41:28 UTC - Batch 1 runs MERGE → inserts predictions to main table
              ↓
              These rows enter streaming buffer (locked for 30-90 min)
              ↓
07:41:30 UTC - _deactivate_older_predictions() runs UPDATE
              ↓
              ERROR: Can't UPDATE rows in streaming buffer!
              ↓
              Duplicates remain active
              ↓
08:37:08 UTC - Batch 2 runs MERGE → inserts MORE predictions
              ↓
              Even more duplicates created
```

### Root Cause

The `_deactivate_older_predictions()` method in `predictions/shared/batch_staging_writer.py` runs immediately after MERGE consolidation. But the MERGE just inserted rows that are now in the streaming buffer, so the subsequent UPDATE cannot modify them.

### Impact

- **4,415+ duplicates** exist in the source table
- Grading already handles this via ROW_NUMBER dedup (working correctly)
- Source table is messy but functional
- Manual cleanup was blocked until streaming buffer cleared

## Solution Implemented

### Approach: Delayed Cleanup Job (Option A)

Added a new `/cleanup-duplicates` endpoint that can be called 2+ hours after predictions when the streaming buffer has cleared.

### Files Changed

| File | Change |
|------|--------|
| `predictions/shared/batch_staging_writer.py` | Added `cleanup_duplicate_predictions()` method to `BatchConsolidator` |
| `predictions/coordinator/coordinator.py` | Added `/cleanup-duplicates` endpoint |

### New Endpoint

```
POST /cleanup-duplicates
Authorization: X-API-Key or Bearer token

Request body:
{
    "game_date": "2026-01-30",  // Required
    "dry_run": false            // Optional - just count without deactivating
}

Response:
{
    "status": "success",
    "duplicates_found": 42,
    "duplicates_deactivated": 42,
    "dry_run": false,
    "game_date": "2026-01-30"
}
```

### How It Works

1. **Count duplicates** using ROW_NUMBER to identify non-newest predictions
2. **Deactivate** by setting `is_active = FALSE` on older predictions
3. **Return results** with counts for monitoring

## Deployment Steps

### 1. Deploy Updated Coordinator

```bash
./bin/deploy-service.sh prediction-coordinator
```

### 2. Verify Endpoint Works (Dry Run)

```bash
# Get the service URL
SERVICE_URL=$(gcloud run services describe prediction-coordinator --region=us-west2 --format='value(status.url)')

# Test with dry run
curl -X POST "${SERVICE_URL}/cleanup-duplicates" \
  -H "X-API-Key: ${COORDINATOR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-29", "dry_run": true}'
```

### 3. Run Actual Cleanup

```bash
# Clean up today's duplicates (only after 2 hours since predictions)
curl -X POST "${SERVICE_URL}/cleanup-duplicates" \
  -H "X-API-Key: ${COORDINATOR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-30", "dry_run": false}'
```

### 4. Set Up Cloud Scheduler (Optional)

For automatic cleanup, create a Cloud Scheduler job that runs 2 hours after predictions:

```bash
# If predictions run at 8:00 AM ET, schedule cleanup for 10:00 AM ET
gcloud scheduler jobs create http prediction-duplicate-cleanup \
  --schedule="0 10 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/cleanup-duplicates" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"game_date": "TODAY", "dry_run": false}' \
  --oidc-service-account-email="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --location=us-west2
```

**Note:** The `game_date: "TODAY"` value needs a small modification to the endpoint to support (currently requires explicit YYYY-MM-DD format). For now, you can use a Lambda or Cloud Function to call with the current date.

## Validation Commands

### Check Current Duplicates

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as duplicates
FROM nba_predictions.player_prop_predictions AS t
WHERE EXISTS (
  SELECT 1 FROM nba_predictions.player_prop_predictions AS d
  WHERE d.player_lookup = t.player_lookup
    AND d.game_date = t.game_date
    AND d.system_id = t.system_id
    AND d.is_active = TRUE
    AND d.created_at > t.created_at
)
AND t.game_date >= '2026-01-09'
AND t.is_active = TRUE"
```

### Verify Streaming Buffer Cleared

```bash
# If this succeeds (0 rows affected), buffer is clear for that date
bq query --use_legacy_sql=false "
UPDATE nba_predictions.player_prop_predictions
SET is_active = FALSE
WHERE FALSE"
```

### Check Duplicates Per Day

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total_active,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, system_id)) as duplicates
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE
  AND game_date >= '2026-01-20'
GROUP BY 1
ORDER BY 1 DESC"
```

## Why Not Other Options?

### Option B: Batch Loading Instead of UPDATE
- More complex MERGE logic
- Potential performance impact
- Risk of data loss if not implemented carefully

### Option C: Accept Duplicates in Source
- Simplest but source table grows indefinitely
- Queries always need dedup logic
- Storage costs increase over time

### Option D: Pre-MERGE Deduplication
- Only handles within-batch duplicates
- Cross-batch duplicates still accumulate
- Doesn't address the root cause

## Existing Mitigation

The grading processor already handles duplicates via ROW_NUMBER deduplication (v5.0 fix):

```sql
-- prediction_accuracy_processor.py uses this pattern
WITH deduped AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY player_lookup, game_date, system_id
    ORDER BY created_at DESC
  ) as rn
  FROM player_prop_predictions
  WHERE is_active = TRUE
)
SELECT * FROM deduped WHERE rn = 1
```

This means **grading works correctly** even with duplicates in the source table.

## Testing Results (2026-01-30)

### Manual Cleanup Test

Successfully cleaned up Jan 23 duplicates:
- Before: 2,477 duplicates
- After: 0 duplicates
- Rows affected: 2,807

### Streaming Buffer Observation

Many game dates (Jan 20-28) have rows created TODAY (2026-01-30 08:37:XX) from a backfill job. These rows are in the streaming buffer and cannot be cleaned immediately.

```
| game_date  | newest_created       | duplicates |
|------------|----------------------|------------|
| 2026-01-28 | 2026-01-30 08:37:35  | 632        | <- In buffer
| 2026-01-27 | 2026-01-30 08:37:33  | 236        | <- In buffer
| 2026-01-26 | 2026-01-30 08:37:32  | 271        | <- In buffer
| 2026-01-25 | 2026-01-30 08:37:29  | 695        | <- In buffer
| 2026-01-24 | 2026-01-30 08:37:27  | 125        | <- In buffer
| 2026-01-23 | 2026-01-23 22:01:12  | 0          | <- Cleaned!
```

### Next Steps

Wait 2 hours after the backfill completed (08:37 UTC + 2h = 10:37 UTC), then run:

```bash
# After 10:37 UTC today (2026-01-30)
for DATE in 2026-01-20 2026-01-22 2026-01-24 2026-01-25 2026-01-26 2026-01-27 2026-01-28; do
  curl -X POST "${SERVICE_URL}/cleanup-duplicates" \
    -H "X-API-Key: ${COORDINATOR_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"${DATE}\", \"dry_run\": false}"
done
```

## Future Improvements

1. **Automatic cleanup**: Add Cloud Scheduler job for daily cleanup
2. **Metrics**: Track duplicate counts in monitoring dashboard
3. **Alerting**: Alert if duplicates exceed threshold after cleanup window
4. **Backfill cleanup**: Run cleanup for historical dates with accumulated duplicates

## Testing

### Unit Test (Local)

```python
# test_batch_staging_writer.py
def test_cleanup_duplicate_predictions_dry_run():
    consolidator = BatchConsolidator(bq_client, project_id)
    result = consolidator.cleanup_duplicate_predictions('2026-01-29', dry_run=True)
    assert 'duplicates_found' in result
    assert result['dry_run'] == True
    assert result['duplicates_deactivated'] == 0
```

### Integration Test

```bash
# Clean up a known date with duplicates
curl -X POST "http://localhost:8080/cleanup-duplicates" \
  -H "X-API-Key: ${COORDINATOR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-29", "dry_run": false}'
```

## Related Issues

- Session 28 Continuation Handoff: `docs/09-handoff/2026-01-30-SESSION-28-CONTINUATION-HANDOFF.md`
- Session 92 distributed lock fix for race conditions
- Session 13 deactivation logic for cross-batch duplicates
