# Session 195 Handoff: ml-feature-store Scheduler Date Bug

**Date:** 2026-02-11 (Wednesday morning)
**Status:** CRITICAL BUG - Needs immediate fix
**Impact:** Feature store processes yesterday instead of today → 84% prediction coverage loss

## Quick Summary

The `ml-feature-store-7am-et` Cloud Scheduler job has a date resolution bug. It's configured with `"analysis_date": "TODAY"` but actually processes **yesterday's date** instead of today.

**Impact this morning:**
- Expected: ~113 predictions for healthy players
- Actual: 18 predictions (84% coverage loss)
- Feature store still using stale data from last night

## What Happened This Morning (Timeline)

```
Feb 11, 12:00 UTC (7:00 AM ET) - ml-feature-store-7am-et scheduler fires
  ↓
Payload sent: {"processors": ["MLFeatureStoreProcessor"], "analysis_date": "TODAY", ...}
  ↓
Phase 4 service receives and resolves "TODAY" → Feb 10 (WRONG!)
  ↓
Logs show: "Found 139 players with games on 2026-02-10 [BACKFILL MODE]"
  ↓
Writes 137 records for Feb 10 (yesterday) - NOT Feb 11 (today)
  ↓
Feature store for Feb 11 remains stale (192 records from last night at 10:30 PM)
  ↓
8:00 AM ET - Prediction run uses stale Feb 11 feature store
  ↓
Result: Only 7 players have predictions (insufficient fresh data)
  ↓
8:50 AM PT - Manual coordinator trigger adds 11 more players → 18 total
  ↓
Final: 18 players with predictions (vs ~113 expected)
```

## Evidence

### 1. Scheduler Configuration

```bash
$ gcloud scheduler jobs describe ml-feature-store-7am-et --location=us-west2 --format=json | jq -r '.httpTarget.body' | base64 -d | jq '.'
{
  "processors": [
    "MLFeatureStoreProcessor"
  ],
  "analysis_date": "TODAY",  # ← Configured correctly
  "strict_mode": false,
  "skip_dependency_check": true
}
```

### 2. Actual Processing Logs (7:01 AM ET)

```
2026-02-11T12:01:58 - Found 139 players with games on 2026-02-10 [BACKFILL MODE]
                                                        ^^^^^^^^^^^
                                                        SHOULD BE 2026-02-11!

2026-02-11T12:02:16 - Write complete: 137/137 rows (for 2026-02-10)
2026-02-11T12:02:17 - POST_WRITE_VALIDATION [2026-02-10]: 137 records
```

### 3. Feature Store Status (8:00 AM PT)

```sql
SELECT game_date, COUNT(*) as total, MAX(created_at) as last_created
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-11'
GROUP BY 1;

-- Result:
-- game_date: 2026-02-11
-- total: 192
-- last_created: 2026-02-10 22:30:47  ← Still from LAST NIGHT!
```

### 4. Prediction Coverage Impact

```sql
SELECT
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-11' AND system_id = 'catboost_v9';

-- Before manual trigger (8 AM ET): 7 players
-- After manual trigger (8:50 AM PT): 18 players
-- Expected (if scheduler worked): ~113 players
```

## Root Cause Hypothesis

**The "TODAY" string is being resolved server-side at the wrong timezone or using wrong date logic.**

Possible causes:
1. **Timezone mismatch:** Service runs in UTC, interprets "TODAY" as UTC today (which was still Feb 10 at 7 AM ET on Feb 11)
2. **Date resolution timing:** "TODAY" resolved when message was created/scheduled, not when processed
3. **Backfill mode detection:** Service sees "TODAY" and incorrectly switches to backfill mode
4. **Code bug:** Date parsing logic in Phase 4 service has off-by-one error

## Investigation Steps

### Step 1: Check Phase 4 Date Resolution Logic

```bash
# Read the main service entry point
cat data_processors/precompute/main_precompute_service.py | grep -A 20 "TODAY"

# Check how analysis_date is parsed
grep -r "analysis_date.*TODAY" data_processors/precompute/
```

**Look for:**
- Where "TODAY" string gets converted to actual date
- Timezone handling (UTC vs ET)
- Any date arithmetic (today - 1, etc.)

### Step 2: Test Date Resolution

```bash
# Manually publish with "TODAY" and check logs
gcloud pubsub topics publish nba-phase4-trigger \
  --message='{"processors": ["MLFeatureStoreProcessor"], "analysis_date": "TODAY", "strict_mode": false}'

# Check what date it actually processes
gcloud logging read 'resource.labels.service_name=nba-phase4-precompute-processors
  AND timestamp>="$(date -u +%Y-%m-%dT%H:%M:%S)Z"
  AND jsonPayload.processor_name="ml_feature_store"' \
  --limit=10 --format=json | jq -r '.[] | .jsonPayload.message' | grep "Found.*players"
```

### Step 3: Check Other Schedulers

```bash
# List all schedulers using "TODAY"
gcloud scheduler jobs list --location=us-west2 --format=json | \
  jq -r '.[] | select(.httpTarget.body | @base64d | contains("TODAY")) | .name'

# Check if they have the same bug
```

### Step 4: Verify Timezone Configuration

```bash
# Check Cloud Run service timezone
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="TZ")'

# Check Cloud Scheduler timezone
gcloud scheduler jobs describe ml-feature-store-7am-et \
  --location=us-west2 --format=json | jq -r '.timeZone'
```

## Proposed Fixes

### Option 1: Use Explicit Date in Scheduler (Recommended)

Update scheduler payload to calculate date in scheduler, not service:

```json
{
  "processors": ["MLFeatureStoreProcessor"],
  "analysis_date": "{{ .CloudSchedulerExecutionTime | date \"2006-01-02\" }}",
  "strict_mode": false,
  "skip_dependency_check": true
}
```

**Pros:** Clear, unambiguous, scheduler controls the date
**Cons:** Requires scheduler reconfiguration

### Option 2: Fix Service Date Resolution

Update `data_processors/precompute/main_precompute_service.py`:

```python
# Before (buggy):
if analysis_date == "TODAY":
    analysis_date = datetime.now().date()  # Uses server UTC!

# After (fixed):
if analysis_date == "TODAY":
    from zoneinfo import ZoneInfo
    analysis_date = datetime.now(ZoneInfo('America/New_York')).date()
```

**Pros:** Fixes root cause, works for all schedulers
**Cons:** Need to deploy service

### Option 3: Use UTC+1 or Explicit Tomorrow

Hack the scheduler to use "TOMORROW" or add 1 day:

```json
{
  "processors": ["MLFeatureStoreProcessor"],
  "analysis_date": "TOMORROW",  // Will resolve to correct date in ET
  "strict_mode": false
}
```

**Pros:** Quick workaround
**Cons:** Fragile, confusing, not a real fix

## Testing the Fix

```bash
# 1. Deploy fix (if Option 2)
./bin/deploy-service.sh nba-phase4-precompute-processors

# 2. Update scheduler (if Option 1)
gcloud scheduler jobs update http ml-feature-store-7am-et \
  --location=us-west2 \
  --message-body='{"processors":["MLFeatureStoreProcessor"],"analysis_date":"2026-02-12",...}'

# 3. Test manually at 11 AM ET (4 PM UTC) same day
gcloud scheduler jobs run ml-feature-store-7am-et --location=us-west2

# 4. Check logs - should process TODAY (Feb 11), not yesterday
gcloud logging read 'resource.labels.service_name=nba-phase4-precompute-processors
  AND jsonPayload.processor_name="ml_feature_store"' \
  --limit=5 --format=json | jq -r '.[] | .jsonPayload.message' | grep "Found.*players"

# 5. Verify feature store was updated
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*), MAX(created_at)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
GROUP BY 1"

# Should show created_at within last hour
```

## Workaround for Tomorrow Morning

If fix isn't ready by tonight, manually trigger at 7 AM ET:

```bash
# Explicit date (no "TODAY" ambiguity)
gcloud pubsub topics publish nba-phase4-trigger \
  --message="{\"processors\": [\"MLFeatureStoreProcessor\"], \"analysis_date\": \"2026-02-12\", \"strict_mode\": false, \"skip_dependency_check\": true}"

# Or use coordinator with force regenerate
curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "game_date": "2026-02-12",
    "prediction_run_mode": "REAL_LINES_ONLY",
    "force_regenerate_feature_store": true
  }'
```

## Related Issues

### Yesterday's Investigation (Session 195)

We discovered that 79/192 players were "blocked" from predictions on Feb 11. Investigation revealed:

1. **28 players are inactive/injured** (Tatum, Lillard, etc.) - WORKING AS INTENDED ✅
2. **DNP filter from Session 2026-02-04** correctly excludes non-playing players ✅
3. **Zero-tolerance policy** correctly prevents predictions for injured players ✅

**See:** `docs/09-handoff/2026-02-11-SESSION-195-RESOLUTION.md`

This is SEPARATE from today's scheduler bug. The 28 inactive players should remain filtered.

### Expected Coverage After Fix

With scheduler working correctly:
- 192 players in upcoming_player_game_context
- ~28 inactive/injured filtered by DNP filter ✅
- ~50 missing shot zone data (acceptable)
- **~113 quality-ready players** should get predictions

Today we only got 18 because feature store wasn't refreshed.

## Files to Check

```
data_processors/precompute/main_precompute_service.py  # Date resolution logic
data_processors/precompute/ml_feature_store/ml_feature_store_processor.py  # Processing
shared/utils/date_utils.py  # Date helper functions (if exists)
orchestration/cloud_functions/phase3_to_phase4/main.py  # Orchestrator date handling
```

## Success Criteria

✅ **Fix is successful when:**
1. Scheduler runs at 7 AM ET on Feb 12
2. Logs show: "Found X players with games on 2026-02-12" (TODAY, not yesterday!)
3. Feature store updated: MAX(created_at) is within 1 hour
4. Predictions at 8 AM ET use fresh feature store
5. ~113 players get predictions (not just 18)

## Open Questions

1. **How long has this bug existed?** Check historical logs
2. **Do other schedulers have the same bug?** (overnight-phase4-7am-et, etc.)
3. **Why didn't we notice before?** Does backfill mode mask the issue?
4. **Is there monitoring for stale feature stores?** Should add canary

## Additional Context

**Current time:** Wednesday Feb 11, 8:00 AM PST / 11:00 AM ET
**Games today:** 14 games scheduled for Feb 11 evening
**Production impact:** Low (18 predictions is acceptable for launch, post-game will work)
**Urgency:** High (must fix before tomorrow morning)

---

**Next session start here:** Investigate date resolution in `main_precompute_service.py`, implement Option 2 fix, test, and deploy before tonight.
