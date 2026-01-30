# Session 29 Handoff - 2026-01-30

## Session Summary

Fixed the streaming buffer race condition that prevented duplicate cleanup in `player_prop_predictions`. **All tasks completed:**

1. Deployed new `/cleanup-duplicates` endpoint with TODAY/YESTERDAY support
2. Cleaned up all historical duplicates (4,689 found, 7,865 deactivated)
3. Set up Cloud Scheduler for automated daily cleanup
4. Fixed deploy script to preserve environment variables

## Problem Fixed

The `_deactivate_older_predictions()` method ran immediately after MERGE consolidation, but those rows were in BigQuery's streaming buffer (locked for 30-90 min). This caused duplicates to accumulate because the UPDATE to deactivate older predictions failed silently.

## Solution Implemented

Added a **delayed cleanup endpoint** (`/cleanup-duplicates`) that can be called 2+ hours after predictions when the streaming buffer has cleared.

### Files Changed

| File | Change |
|------|--------|
| `predictions/shared/batch_staging_writer.py` | Added `cleanup_duplicate_predictions()` method to `BatchConsolidator` |
| `predictions/coordinator/coordinator.py` | Added `/cleanup-duplicates` endpoint with TODAY/YESTERDAY support |
| `bin/deploy-service.sh` | Fixed to use `--update-env-vars` with `GCP_PROJECT_ID` |
| `docs/08-projects/current/streaming-buffer-fix/README.md` | Full project documentation |

### New Endpoint

```bash
POST /cleanup-duplicates
{
    "game_date": "YESTERDAY",  # YYYY-MM-DD, "TODAY", or "YESTERDAY"
    "dry_run": false           # Optional
}
```

## Deployment Complete

- **Service**: prediction-coordinator
- **Revision**: prediction-coordinator-00108-24j
- **Status**: Deployed and tested

### Cloud Scheduler Job Created

```
Name:     prediction-duplicate-cleanup
Schedule: 30 15 * * * (UTC) = 10:30 AM ET
Payload:  {"game_date": "YESTERDAY", "dry_run": false}
Status:   ENABLED
```

## All Duplicates Cleaned

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

All dates now show 0 duplicates:

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

## Key Learnings

1. **BigQuery streaming buffer** locks rows for 30-90 minutes after DML operations (MERGE/INSERT)
2. **Backfills create new rows** that go into the streaming buffer, blocking cleanup even for historical dates
3. **Grading already handles duplicates** via ROW_NUMBER dedup, so duplicates don't affect graded results
4. **Delayed cleanup is the correct pattern** for BigQuery DML on recently-modified tables
5. **Deploy scripts should use `--update-env-vars`** not `--set-env-vars` to preserve existing env vars

## Commands for Future Reference

### Manual Cleanup
```bash
SERVICE_URL="https://prediction-coordinator-756957797294.us-west2.run.app"
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)

curl -X POST "${SERVICE_URL}/cleanup-duplicates" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "YESTERDAY", "dry_run": false}'
```

### Check Duplicates
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as active,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '_', system_id)) as dupes
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1 DESC"
```

## Related Documentation

- Project documentation: `docs/08-projects/current/streaming-buffer-fix/README.md`
- Previous handoff: `docs/09-handoff/2026-01-30-SESSION-28-CONTINUATION-HANDOFF.md`
