# Session 29 Handoff - 2026-01-30

## Session Summary

Fixed the streaming buffer race condition that prevented duplicate cleanup in `player_prop_predictions`.

## Problem Fixed

The `_deactivate_older_predictions()` method ran immediately after MERGE consolidation, but those rows were in BigQuery's streaming buffer (locked for 30-90 min). This caused duplicates to accumulate because the UPDATE to deactivate older predictions failed silently.

## Solution Implemented

Added a **delayed cleanup endpoint** (`/cleanup-duplicates`) that can be called 2+ hours after predictions when the streaming buffer has cleared.

### Files Changed

| File | Change |
|------|--------|
| `predictions/shared/batch_staging_writer.py` | Added `cleanup_duplicate_predictions()` method to `BatchConsolidator` |
| `predictions/coordinator/coordinator.py` | Added `/cleanup-duplicates` endpoint |
| `docs/08-projects/current/streaming-buffer-fix/README.md` | Full project documentation |

### New Endpoint

```bash
POST /cleanup-duplicates
{
    "game_date": "2026-01-30",  # Required
    "dry_run": false            # Optional
}
```

## Testing Performed

1. **Syntax verification**: Both modified files pass Python syntax check
2. **Manual cleanup**: Successfully cleaned Jan 23 duplicates (2,477 → 0)
3. **Streaming buffer observation**: Confirmed rows from today's backfill cannot be cleaned (in buffer)

## Current Duplicate Status

| game_date  | total_active | duplicates | Status |
|------------|--------------|------------|--------|
| 2026-01-29 | 113 | 0 | Clean |
| 2026-01-28 | 1097 | 632 | In streaming buffer |
| 2026-01-27 | 1047 | 236 | In streaming buffer |
| 2026-01-26 | 1075 | 271 | In streaming buffer |
| 2026-01-25 | 1682 | 695 | In streaming buffer |
| 2026-01-24 | 441 | 125 | In streaming buffer |
| 2026-01-23 | 85 | 0 | **Cleaned this session** |
| 2026-01-22 | 369 | 1 | In streaming buffer |
| 2026-01-21 | 216 | 0 | Clean |
| 2026-01-20 | 809 | 252 | In streaming buffer |

Note: Dates with "In streaming buffer" had backfill rows created at 2026-01-30 08:37:XX UTC.

## Deployment Required

```bash
# Deploy the coordinator with new endpoint
./bin/deploy-service.sh prediction-coordinator
```

## Next Steps for Follow-up Session

### 1. Deploy and Test (Priority 1)

```bash
# Deploy
./bin/deploy-service.sh prediction-coordinator

# Test dry run
curl -X POST "${SERVICE_URL}/cleanup-duplicates" \
  -H "X-API-Key: ${COORDINATOR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-28", "dry_run": true}'
```

### 2. Clean Up Historical Duplicates (Priority 2)

After streaming buffer clears (~2 hours after last backfill):

```bash
for DATE in 2026-01-20 2026-01-22 2026-01-24 2026-01-25 2026-01-26 2026-01-27 2026-01-28; do
  curl -X POST "${SERVICE_URL}/cleanup-duplicates" \
    -H "X-API-Key: ${COORDINATOR_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"${DATE}\", \"dry_run\": false}"
done
```

### 3. Set Up Automated Cleanup (Priority 3)

Create Cloud Scheduler job for daily cleanup at 10:00 AM ET (2 hours after 8 AM predictions):

```bash
gcloud scheduler jobs create http prediction-duplicate-cleanup \
  --schedule="0 10 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/cleanup-duplicates" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"game_date": "TODAY"}' \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --location=us-west2
```

**Note:** The endpoint currently requires explicit YYYY-MM-DD format. Add support for "TODAY" keyword if automated scheduling is desired.

## Key Learnings

1. **BigQuery streaming buffer** locks rows for 30-90 minutes after DML operations (MERGE/INSERT)
2. **Backfills create new rows** that go into the streaming buffer, blocking cleanup even for historical dates
3. **Grading already handles duplicates** via ROW_NUMBER dedup, so duplicates don't affect graded results
4. **Delayed cleanup is the correct pattern** for BigQuery DML on recently-modified tables

## Commits

None yet - changes need to be committed and deployed.

## Related Documentation

- Project documentation: `docs/08-projects/current/streaming-buffer-fix/README.md`
- Previous handoff: `docs/09-handoff/2026-01-30-SESSION-28-CONTINUATION-HANDOFF.md`
