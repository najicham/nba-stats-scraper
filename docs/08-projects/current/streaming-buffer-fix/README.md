# Streaming Buffer Duplicate Cleanup Fix

**Date:** 2026-01-30
**Session:** 29 (continuation of 28)
**Status:** COMPLETE - Deployed, tested, and automated

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

## Solution Implemented

### Approach: Delayed Cleanup Job (Option A)

Added a new `/cleanup-duplicates` endpoint that can be called 2+ hours after predictions when the streaming buffer has cleared.

### Files Changed

| File | Change |
|------|--------|
| `predictions/shared/batch_staging_writer.py` | Added `cleanup_duplicate_predictions()` method to `BatchConsolidator` |
| `predictions/coordinator/coordinator.py` | Added `/cleanup-duplicates` endpoint with TODAY/YESTERDAY support |
| `bin/deploy-service.sh` | Fixed to include `GCP_PROJECT_ID` env var |

### New Endpoint

```
POST /cleanup-duplicates
Authorization: X-API-Key or Bearer token

Request body:
{
    "game_date": "2026-01-30",  // YYYY-MM-DD, "TODAY", or "YESTERDAY"
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

1. **Supports date keywords**: "TODAY", "YESTERDAY", or explicit YYYY-MM-DD
2. **Count duplicates** using ROW_NUMBER to identify non-newest predictions
3. **Deactivate** by setting `is_active = FALSE` on older predictions
4. **Return results** with counts for monitoring

## Deployment Complete

### Service Deployed

- **Service**: prediction-coordinator
- **Revision**: prediction-coordinator-00108-24j
- **Endpoint**: `/cleanup-duplicates` (working)

### Cloud Scheduler Job Created

```
Name:     prediction-duplicate-cleanup
Schedule: 30 15 * * * (UTC) = 10:30 AM ET
Payload:  {"game_date": "YESTERDAY", "dry_run": false}
Status:   ENABLED
```

The job runs at 10:30 AM ET daily (2.5 hours after morning predictions at 8 AM ET), cleaning up the previous day's duplicates.

## Cleanup Results (2026-01-30)

### All Historical Duplicates Cleaned

| Date | Duplicates Found | Deactivated | Status |
|------|------------------|-------------|--------|
| 2026-01-20 | 252 | 589 | **CLEANED** |
| 2026-01-22 | 1 | 286 | **CLEANED** |
| 2026-01-23 | 2,477 | 2,807 | **CLEANED** |
| 2026-01-24 | 125 | 360 | **CLEANED** |
| 2026-01-25 | 695 | 1,400 | **CLEANED** |
| 2026-01-26 | 271 | 836 | **CLEANED** |
| 2026-01-27 | 236 | 811 | **CLEANED** |
| 2026-01-28 | 632 | 776 | **CLEANED** |
| **TOTAL** | **4,689** | **7,865** | |

### Verification

```
+------------+--------------+----------------+
| game_date  | total_active | est_duplicates |
+------------+--------------+----------------+
| 2026-01-29 |          113 |              0 |
| 2026-01-28 |          321 |              0 |
| 2026-01-27 |          236 |              0 |
| 2026-01-26 |          239 |              0 |
| 2026-01-25 |          282 |              0 |
| 2026-01-24 |           81 |              0 |
| 2026-01-23 |           85 |              0 |
| 2026-01-22 |           83 |              0 |
| 2026-01-21 |          216 |              0 |
| 2026-01-20 |          220 |              0 |
+------------+--------------+----------------+
```

**All dates now show 0 duplicates.**

## Usage

### Manual Cleanup

```bash
SERVICE_URL="https://prediction-coordinator-756957797294.us-west2.run.app"
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)

# Dry run (count only)
curl -X POST "${SERVICE_URL}/cleanup-duplicates" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "YESTERDAY", "dry_run": true}'

# Actual cleanup
curl -X POST "${SERVICE_URL}/cleanup-duplicates" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "YESTERDAY", "dry_run": false}'
```

### Validation Commands

```bash
# Check current duplicates
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total_active,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '_', system_id)) as duplicates
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
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

## Key Learnings

1. **BigQuery streaming buffer** locks rows for 30-90 minutes after DML operations (MERGE/INSERT)
2. **Backfills create new rows** that go into the streaming buffer, blocking cleanup even for historical dates
3. **Grading already handles duplicates** via ROW_NUMBER dedup, so duplicates don't affect graded results
4. **Delayed cleanup is the correct pattern** for BigQuery DML on recently-modified tables
5. **Deploy scripts should preserve env vars** - use `--update-env-vars` not `--set-env-vars`

## Related Documentation

- Session 28 Handoff: `docs/09-handoff/2026-01-30-SESSION-28-CONTINUATION-HANDOFF.md`
- Session 29 Handoff: `docs/09-handoff/2026-01-30-SESSION-29-HANDOFF.md`
- Session 92: Distributed lock fix for race conditions
- Session 13: Deactivation logic for cross-batch duplicates
